"""OpenAI-backed LLM provider (F5, D5/D33).

Selected with LLM_PROVIDER=openai. The key comes from OPENAI_API_KEY in the
environment (.env locally, the hosting platform's env settings when deployed)
and never reaches the client or the repository.

The contract matches the mock exactly: bounded history in (assembled by
app/context.py, F4), plain-text replies out, and insight proposals that cite
source_message_ids so memories stay traceable (D11/D12). The server validates
everything through memories.normalise_proposals before persisting.
"""

import json

from openai import BadRequestError, OpenAI

from ..config import settings
from .base import ChatContext, LLMProvider

_SYSTEM_BASE = (
    "You are a warm, attentive film-reflection companion inside a movie "
    "journal app. You help the user put into words what a film meant to them "
    "and, over time, notice the themes, tastes and reactions they return to.\n"
    "How to converse:\n"
    "- Respond to what the user actually said, in 2-5 sentences. Be natural and "
    "conversational, not an interviewer. A thoughtful observation is often a "
    "better reply than another question; you may ask one genuine question when "
    "it deepens the reflection, but do not end every reply with one and never "
    "repeat a question you already asked.\n"
    "- Use the film knowledge in the context (director, cast, themes, synopsis) "
    "when it illuminates what the user is saying, as a companion rather than an "
    "encyclopaedia. Never invent plot details, quotes, scenes or endings.\n"
    "- If the user mentions another film, engage with the connection genuinely; "
    "avoid spoilers for films they have not said they watched.\n"
    "- Only draw on the confirmed memories listed in the context; never claim to "
    "remember something that is not there, and never say \"you told me\" unless "
    "it is actually in the context.\n"
    "- Let the user disagree with your reading; never assume a film's themes "
    "describe the user's own life.\n"
    "Safety:\n"
    "- Never diagnose the user or make clinical or psychological claims.\n"
    "- Never turn a passing mood into a personality trait.\n"
    "- Respect hesitation or refusal; do not press for personal disclosure.\n"
    "Be gentle, specific and concise."
)

# Film Assistant conversations are recommender turns, not reflection turns
# (F10): decisive picks from the server-provided candidate pool, grounded in
# the user's taste — never a reflective interview, never the user's library.
_SYSTEM_DISCOVERY = (
    "You are the Film Assistant inside a movie-journal app: a decisive, "
    "knowledgeable film recommender - not a reflective interviewer.\n"
    "Rules:\n"
    "- Recommend three concrete films chosen ONLY from the candidate list in "
    "the context, copying each tmdb_id exactly — aim for three distinct picks; "
    "fall back to fewer only if the list cannot support three. Never name a film that "
    "is not on the list, and never invent films, directors, or plot details.\n"
    "- Never recommend a film already in the user's library; the list is "
    "already filtered for you.\n"
    "- Honour the current request over general taste: if the user asks for "
    "something comfortable, do not fall back to their usual genres instead.\n"
    "- Give each pick one specific reason tied to what the user is asking for "
    "or the confirmed memories in the context - never a generic compliment.\n"
    "- Lead with the picks; keep the reply under 120 words, warm and direct; "
    "no spoilers, no lectures.\n"
    "- If the candidate list is empty, ask one short clarifying question "
    "instead of recommending. Never fabricate a film to fill the gap."
)

_KIND_DEFINITIONS = (
    '- "theme": a recurring idea or motif in the films they discuss.\n'
    '- "preference": something they explicitly liked or disliked.\n'
    '- "insight": an observation connecting a film to their own experience or values.\n'
    '- "aesthetic": cinematography, atmosphere, sound, or visual style they respond to.\n'
    '- "narrative": storytelling structure, pacing, characters, or endings they care about.\n'
    '- "emotional_response": their felt reaction to a film (sadness, delight, catharsis).\n'
    '- "viewing_intention": what they seek from a viewing experience (comfort, novelty, etc.).'
)


def _context_block(context: ChatContext) -> str:
    lines = []
    if context.display_name:
        lines.append(f"The user's name is {context.display_name}.")
    if context.conversation_type == "discovery":
        lines.append(
            "This is a Film Assistant discovery conversation: the user wants "
            "help finding their next film. Recommend decisively from the "
            "candidate list below."
        )
        if context.request:
            lines.append(
                "Explicit request to honour: " + context.request + " "
                "Recommend only films that satisfy it."
            )
        if context.intent:
            lines.append(
                context.intent + " Prefer films that fit this intention, but "
                "candidate quality and fit still matter."
            )
        if context.library_titles:
            lines.append(
                "Films already in the user's library — NEVER recommend any "
                "of these:"
            )
            lines.append(", ".join(context.library_titles[:60]))
        if context.suggestions:
            lines.append(
                "Candidate films — recommend ONLY from this list "
                "(tmdb_id must be copied exactly into the JSON):"
            )
            for film in context.suggestions:
                genres = ", ".join(film.get("genres") or [])
                lines.append(
                    f"- {film['title']}"
                    + (f" ({film['year']})" if film.get("year") else "")
                    + f" [tmdb_id {film['tmdb_id']}]"
                    + (f" — {genres}" if genres else "")
                    + (f" — fits because: {film['why']}" if film.get("why") else "")
                )
        else:
            lines.append(
                "No candidate list is available for this turn: name 1-3 "
                "well-known real films that fit the mood instead."
            )
    film = context.film or {}
    if film:
        genres = ", ".join(film.get("genres") or [])
        lines.append(
            f"Film: {film.get('title')}"
            + (f" ({film['year']})" if film.get("year") else "")
            + (f" — genres: {genres}" if genres else "")
        )
        if film.get("overview"):
            lines.append(f"Synopsis: {film['overview']}")
        if context.watch_type == "planning":
            lines.append("The user is PLANNING to watch this film.")
        else:
            lines.append("The user has SEEN this film and is reflecting on it.")
    elif context.title:
        lines.append(f"Free reflection titled \"{context.title}\".")
    if context.memories_detail:
        lines.append(
            "Confirmed memories (shown as: content [kind, evidence]; use them "
            "naturally, never quote, and never claim to remember anything not "
            "listed here):"
        )
        for m in context.memories_detail:
            kind = str(m.get("kind") or "memory")
            evidence = str(m.get("evidence_type") or "inferred")
            scope = str(m.get("scope") or "stable")
            tag = f"{kind}, {evidence}"
            if scope != "stable":
                tag += f", {scope}"
            lines.append(f"- {m['content']} [{tag}]")
    elif context.memories:
        lines.append("Confirmed memories about the user (use naturally, never quote):")
        lines.extend(f"- {memory}" for memory in context.memories)

    if context.mentioned_films:
        lines.append(
            "Other films the user just mentioned (discuss the connection; "
            "avoid spoilers for films they have not said they watched):"
        )
        for film in context.mentioned_films:
            name = film.get("title") or ""
            if name:
                lines.append(
                    f"- {name}"
                    + (f" ({film.get('year')})" if film.get("year") else "")
                )

    if context.discussed_films:
        titles = [f.get("title") for f in context.discussed_films if f.get("title")]
        if titles:
            lines.append("Films the user has recently reflected on: " + ", ".join(titles[:12]))

    if context.recurring_themes:
        lines.append("Themes that recur across the user's reflections:")
        for theme in context.recurring_themes:
            lines.append(f"- {theme['theme']} (in {', '.join(theme['films'])})")

    if context.recently_recommended:
        names = [r.get("title") for r in context.recently_recommended if r.get("title")]
        if names:
            lines.append("The user was recently recommended: " + ", ".join(names[:10]))

    if context.viewing_history:
        watched = [f.get("title") for f in context.viewing_history.get("watched") or []]
        watchlist = [f.get("title") for f in context.viewing_history.get("watchlist") or []]
        if watched:
            lines.append("Films the user has watched: " + ", ".join(watched[:15]))
        if watchlist:
            lines.append("Films on the user's watchlist (not yet watched): " + ", ".join(watchlist[:10]))

    if context.film_context:
        fc = context.film_context
        if fc.get("tmdb_id"):
            lines.append(f"Film TMDB id: {fc['tmdb_id']} (use as source_film_tmdb_id).")
        notes = []
        if fc.get("director"):
            notes.append(f"directed by {fc['director']}")
        if fc.get("cast"):
            notes.append("featuring " + ", ".join(fc["cast"]))
        if fc.get("themes"):
            notes.append("themes: " + ", ".join(fc["themes"]))
        if fc.get("runtime"):
            notes.append(f"{fc['runtime']} min")
        if notes:
            lines.append("Film notes: " + "; ".join(notes) + ".")
        if fc.get("synopsis"):
            lines.append("Synopsis: " + fc["synopsis"])
    return "\n".join(lines)


def _transcript(messages: list[dict]) -> str:
    return "\n".join(
        f"[{m.get('id', '?')}] {m.get('role', '?')}: {m.get('content', '')}"
        for m in messages
    )


class OpenAIProvider(LLMProvider):
    def __init__(self, client: OpenAI | None = None, model: str | None = None):
        if client is None and not settings.openai_api_key:
            raise RuntimeError(
                "LLM_PROVIDER=openai needs OPENAI_API_KEY in the environment"
            )
        self._client = client or OpenAI(api_key=settings.openai_api_key)
        self._model = model or settings.openai_model

    def _complete(self, messages: list[dict], json_mode: bool = False) -> str:
        kwargs: dict = {"model": self._model, "messages": messages}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            response = self._client.chat.completions.create(**kwargs)
        except BadRequestError:
            # Reasoning models sometimes reject `response_format json_object`;
            # fall back to the prompt's own "respond with JSON only" instruction.
            if not json_mode:
                raise
            kwargs.pop("response_format", None)
            response = self._client.chat.completions.create(**kwargs)
        return (response.choices[0].message.content or "").strip()


    def opening(self, context: ChatContext) -> str:
        film = context.film or {}
        if film and context.watch_type == "planning":
            task = (
                f"Open a planning conversation about \"{film.get('title')}\". "
                "Welcome the user briefly and ask what draws them to it."
            )
        elif film:
            task = (
                f"Open a reflection on \"{film.get('title')}\". Welcome the "
                "user briefly and invite them to recall a moment or feeling "
                "that stayed with them."
            )
        elif context.conversation_type == "discovery":
            task = (
                "Open a Film Assistant conversation. Welcome the user briefly "
                "and ask what they are in the mood to watch — mention they "
                "can just ask you to surprise them."
            )
        else:
            task = (
                "Open a free reflection"
                + (f" titled \"{context.title}\"" if context.title else "")
                + ". Welcome the user briefly and ask an inviting first question."
            )
        return self._complete(
            [
                {"role": "system", "content": _SYSTEM_BASE + "\n" + _context_block(context)},
                {"role": "user", "content": task},
            ]
        )

    def chat(self, messages: list[dict], context: ChatContext) -> str:
        return self._complete(
            [
                {"role": "system", "content": _SYSTEM_BASE + "\n" + _context_block(context)},
                *messages,
            ]
        )

    def chat_discovery(self, messages: list[dict], context: ChatContext) -> dict:
        """Recommender turn: a decisive reply plus 1-3 named films (JSON)."""
        raw = self._complete(
            [
                {
                    "role": "system",
                    "content": _SYSTEM_DISCOVERY + "\n" + _context_block(context),
                },
                *messages,
                {
                    "role": "user",
                    "content": (
                        "Reply now. Respond with JSON only: "
                        '{"reply": str, "films": [{"tmdb_id": int | null, '
                        '"title": str, "year": int | null, "themes": [str]}]}. '
                        "`reply` is what the user reads (max 120 words, at "
                        "most one follow-up question); `films` lists the three "
                        "candidate films you recommend in it — copy each "
                        "film's tmdb_id from the candidate list exactly — "
                        "each with 2-4 short mood/theme tags."
                    ),
                },
            ],
            json_mode=True,
        )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"OpenAI returned unparseable discovery JSON: {raw[:200]}"
            ) from exc
        if not isinstance(data, dict) or not isinstance(data.get("reply"), str):
            raise RuntimeError(
                f"OpenAI discovery reply missing 'reply': {raw[:200]}"
            )
        films = data.get("films")
        if not isinstance(films, list):
            films = []
        cleaned: list[dict] = []
        for film in films[:3]:
            if not isinstance(film, dict):
                continue
            title = str(film.get("title") or "").strip()
            if not title:
                continue
            year = film.get("year")
            tmdb_id = film.get("tmdb_id")
            themes = [
                str(t).strip()
                for t in (film.get("themes") or [])
                if str(t).strip()
            ][:4]
            cleaned.append(
                {
                    "title": title,
                    "year": year if isinstance(year, int) else None,
                    "tmdb_id": tmdb_id if isinstance(tmdb_id, int) and tmdb_id > 0 else None,
                    "themes": themes,
                }
            )
        return {"reply": data["reply"].strip(), "films": cleaned}

    def extract_insights(
        self, messages: list[dict], context: ChatContext
    ) -> list[dict]:
        prompt = (
            "Read this reflection transcript and propose up to 5 memories worth "
            "keeping about the user's film taste and responses.\n"
            + _KIND_DEFINITIONS
            + "\nFor each proposal also give:\n"
            "- `evidence_type`: \"explicit\" if the user literally stated it, "
            "\"inferred\" if it is your interpretation of what they said.\n"
            "- `scope`: \"stable\" for a lasting trait, \"film_specific\" for a "
            "reaction to THIS film, \"session\" for a one-off mood. Never turn "
            "a temporary mood into a stable trait.\n"
            "- `confidence`: a coarse number from 0 to 1 reflecting how well "
            "grounded it is; inferred readings should score lower than explicit "
            "statements.\n"
            "- `source_film_tmdb_id`: the film being reflected on, when the "
            "context gives a TMDB id.\n\n"
            "Mix two kinds of proposals: faithful observations (what they "
            "revealed, in fresh words) and one or two bolder interpretive reads "
            "they could reasonably push back on. When the context lists themes "
            "recurring across their films, propose that pattern if the "
            "transcript supports it - but only as an interpretation, never as a "
            "fact about their private life.\n"
            "Every proposal must be anchored in something they actually said. "
            "Do not simply restate what they already know; add something they "
            "could not have written themselves.\n"
            "Never invent biography, never diagnose the user, and never infer "
            "their emotional state from a film preference.\n\n"
            "Rules: phrase `content` to the user in second person (\"You ...\"), "
            "max 500 characters; `explanation` briefly states which of their "
            "messages ground it; `source_message_ids` must only contain ids from "
            "the transcript below; skip anything already in the confirmed "
            "memories.\n\n"
            "Respond with JSON only: "
            '{"insights": [{"content", "kind", "explanation", '
            '"source_message_ids", "evidence_type", "scope", "confidence", '
            '"source_film_tmdb_id"}]}.\n\n'
            "Transcript:\n" + _transcript(messages)
        )
        raw = self._complete(
            [
                {"role": "system", "content": _context_block(context)},
                {"role": "user", "content": prompt},
            ],
            json_mode=True,
        )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            # The router maps this to 502 and keeps the conversation active so
            # the user can retry instead of ending with no proposals.
            raise RuntimeError(f"OpenAI returned unparseable insights: {raw[:200]}") from exc
        if isinstance(data, dict):
            data = data.get("insights", [])
        if not isinstance(data, list):
            raise RuntimeError(f"OpenAI returned unexpected insights shape: {raw[:200]}")
        return data
