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
            "help finding their next film. Explore their taste and current mood "
            "through questions; suggesting films conversationally is welcome here."
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

    def extract_insights(
        self, messages: list[dict], context: ChatContext
    ) -> list[dict]:
        prompt = (
            "Read this reflection transcript and propose up to 5 insights "
            "worth remembering about the user. Each proposal must be grounded "
            "in the user's own words.\n"
            + _KIND_DEFINITIONS
            + "\nRules: phrase `content` to the user in second person "
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
