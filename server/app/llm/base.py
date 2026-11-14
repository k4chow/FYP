"""Provider interface (F5, D5) — mirrors docs/02-architecture "Provider seam"."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ChatContext:
    """Bounded, server-assembled context for one turn (F4).

    Never contains the full conversation history and never proposed/rejected
    memories — assembly lives in app/context.py.
    """

    conversation_type: str = "reflection"  # 'reflection' | 'discovery'
    title: str | None = None  # conversation title (e.g. a free-reflection prompt)
    film: dict | None = None  # films row: title, year, genres, metadata, ...
    watch_type: str | None = None  # 'seen' | 'planning'
    memories: list[str] = field(default_factory=list)  # confirmed only
    display_name: str | None = None
    turn: int = 0  # how many user messages so far (deterministic selector)
    # Discovery-only context: titles already in the user's library (never
    # recommended again) and the personalised candidate pool to pick from.
    library_titles: list[str] = field(default_factory=list)
    suggestions: list[dict] = field(default_factory=list)
    # Phase 7: a restatement of an explicit constraint the user stated (e.g.
    # "only Paul Thomas Anderson films") so providers answer in scope rather
    # than falling back to the generic taste profile.
    request: str | None = None
    # Soft viewing intention (Part D): a rendered restatement of the current
    # mood / desired experience / exclusions, kept separate from the hard
    # `request` constraint above.
    intent: str | None = None
    # Personalisation (Part A-B). film_context is the compact truth dossier for
    # the linked film (director/cast/themes); memories_detail keeps kind,
    # evidence_type and scope so prompts can distinguish explicit preferences
    # from inferred ones; mentioned_films are other films named in the current
    # message; viewing_history / discussed_films / recently_recommended make the
    # shared user model visible to both assistants.
    film_context: dict | None = None
    memories_detail: list[dict] = field(default_factory=list)
    mentioned_films: list[dict] = field(default_factory=list)
    viewing_history: dict = field(default_factory=dict)
    discussed_films: list[dict] = field(default_factory=list)
    recently_recommended: list[dict] = field(default_factory=list)
    recurring_themes: list[dict] = field(default_factory=list)


class LLMProvider(ABC):
    """The seam every provider implements. `messages` arguments are always
    bounded lists of {"role", "content"} dicts, oldest first."""

    @abstractmethod
    def opening(self, context: ChatContext) -> str:
        """The assistant's first message for a new conversation."""

    @abstractmethod
    def chat(self, messages: list[dict], context: ChatContext) -> str:
        """Reply to the latest user message in `messages`."""

    @abstractmethod
    def chat_discovery(self, messages: list[dict], context: ChatContext) -> dict:
        """Recommender turn for discovery (Film Assistant) conversations.

        Returns {"reply": str, "films": [{"title", "year", "themes": [...]}]}.
        The router grounds each named film against TMDB before persisting, so
        titles may be resolved or dropped — providers must still name real,
        well-known films only.
        """

    @abstractmethod
    def extract_insights(
        self, messages: list[dict], context: ChatContext
    ) -> list[dict]:
        """Propose memories from a finished conversation (D12).

        `messages` is the same bounded window used for chat, with message ids
        included so each proposal can name its sources. Each item should use
        content, kind, explanation, and source_message_ids; the server still
        validates every field before persisting anything.
        """
