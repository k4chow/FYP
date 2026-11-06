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

from openai import OpenAI

from ..config import settings
from .base import ChatContext, LLMProvider

_SYSTEM_BASE = (
    "You are a warm, attentive film-reflection companion inside a movie "
    "journal app. You help the user put into words what a film meant to them.\n"
    "Rules:\n"
    "- Reply in 2-4 sentences and ask exactly one follow-up question.\n"
    "- Respond to what the user actually said; do not give reviews, trivia, "
    "or recommendations unless asked.\n"
    "- Never diagnose the user or make clinical claims.\n"
    "- Never invent plot details; if unsure, ask the user."
)

# Film Assistant conversations are recommender turns, not reflection turns
# (F10): decisive picks from the server-provided candidate pool, grounded in
# the user's taste — never a reflective interview, never the user's library.
_SYSTEM_DISCOVERY = (
    "You are the Film Assistant inside a movie-journal app: a decisive, "
    "knowledgeable film recommender — not a reflective interviewer.\n"
    "Rules:\n"
    "- Every reply must recommend one to three concrete films chosen FROM the "
    "candidate list in the context. Never recommend anything else.\n"
    "- Never recommend any film listed as being in the user's library.\n"
    "- Give each pick a one-line reason tied to what the user told you: "
    "their mood, taste, or the confirmed memories in the context.\n"
    "- Be decisive: lead with the picks. Ask at most one short follow-up "
    "question, and only if the candidate list is empty.\n"
    "- Keep replies under 120 words, warm and direct; no lectures, no "
    "spoilers.\n"
    "- Never invent films, directors, or plot details."
)

_KIND_DEFINITIONS = (
    '- "theme": an idea or motif the user kept returning to.\n'
    '- "preference": something the user explicitly liked or disliked.\n'
    '- "insight": an observation connecting the film to the user\'s own '
    "experience or values."
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
    if context.memories:
        lines.append("Confirmed memories about the user (use naturally, never quote):")
        lines.extend(f"- {memory}" for memory in context.memories)
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
                        "most one follow-up question); `films` lists the "
                        "1-3 candidate films you recommend in it — copy each "
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
            "Read this reflection transcript and propose up to 5 insights "
            "worth remembering about the user.\n"
            + _KIND_DEFINITIONS
            + "\nMix two kinds of proposals:\n"
            "- Faithful observations: what the user revealed, phrased in "
            "fresh words — some rephrasing is welcome.\n"
            "- Bolder interpretive reads: go one step beyond the transcript — "
            "a pattern across their films or reactions, a hypothesis about "
            "their taste or values, or a sharp interpretation they could "
            "reasonably push back on. These must still be anchored in "
            "something the user actually said.\n"
            "Do not simply repeat or rephrase what the user already knows "
            "they said — every proposal should add something they could not "
            "have written themselves, and at least one proposal should offer "
            "an interpretation the user might disagree with and argue "
            "against.\n"
            "Never invent biography and never diagnose the user.\n"
            "Rules: phrase `content` to the user in second person "
            "(\"You ...\"), max 500 characters; `explanation` briefly states "
            "which of their messages ground it; `source_message_ids` must "
            "only contain ids from the transcript below; skip anything "
            "already in the confirmed memories.\n\n"
            "Respond with JSON only: "
            '{"insights": [{"content", "kind", "explanation", '
            '"source_message_ids"}]}.\n\n'
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
