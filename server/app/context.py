"""Bounded LLM context assembly (F4).

The LLM only ever sees the last `llm_context_messages` messages of the
current conversation plus the user's `llm_context_memories` most recently
updated *confirmed* memories. Full history and proposed/rejected memories
are never included (docs/02 "LLM context assembly", D11/D12).
"""

from .config import settings
from .supabase_client import supabase


def recent_messages(conversation_id: str, limit: int | None = None) -> list[dict]:
    """Last N messages of a conversation, oldest first, as {role, content}."""
    limit = limit or settings.llm_context_messages
    res = (
        supabase.table("messages")
        .select("role,content")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(reversed(res.data))


def confirmed_memories(user_id: str, limit: int | None = None) -> list[str]:
    """Most recently updated confirmed memories — the only ones the LLM sees."""
    limit = limit or settings.llm_context_memories
    res = (
        supabase.table("memories")
        .select("content")
        .eq("user_id", user_id)
        .eq("status", "confirmed")
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [row["content"] for row in res.data]
