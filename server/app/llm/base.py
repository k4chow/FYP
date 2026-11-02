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
    def extract_insights(
        self, messages: list[dict], context: ChatContext
    ) -> list[dict]:
        """Propose memories from a finished conversation (Phase 4, D12).
        Returns [] until Phase 4 implements extraction."""
