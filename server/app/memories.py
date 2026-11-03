"""Memory lifecycle and traceability helpers (F3, D11, D12).

Proposals live in the existing `memories` table. Conversation linkage is
derived from validated `source_message_ids`, so review edits never rewrite or
disconnect the append-only messages an insight came from.
"""

from datetime import datetime, timezone
from uuid import UUID

from .supabase_client import supabase

MAX_PROPOSALS = 5
_KINDS = {"theme", "preference", "insight"}
_SOURCE_SELECT = "id,conversation_id,role,content,created_at"


def _uuid_text(value: object) -> str | None:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _excerpt(text: object, limit: int = 120) -> str:
    clean = " ".join(str(text).split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def normalise_proposals(raw: object, source_messages: list[dict]) -> list[dict]:
    """Validate provider output; malformed entries are dropped, never stored."""
    if not isinstance(raw, list):
        return []
    allowed = {
        message_id: message
        for message in source_messages
        if (message_id := _uuid_text(message.get("id")))
    }
    proposals: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        kind = str(item.get("kind", "")).strip().lower()
        explanation = " ".join(str(item.get("explanation", "")).split())
        raw_ids = item.get("source_message_ids")
        if (
            not 1 <= len(content) <= 500
            or kind not in _KINDS
            or not 1 <= len(explanation) <= 500
            or not isinstance(raw_ids, list)
        ):
            continue
        ids: list[str] = []
        for value in raw_ids:
            message_id = _uuid_text(value)
            if message_id and message_id in allowed and message_id not in ids:
                ids.append(message_id)
        key = content.casefold()
        if ids and key not in seen:
            seen.add(key)
            proposals.append(
                {
                    "content": content,
                    "kind": kind,
                    "explanation": explanation,
                    "source_message_ids": ids,
                }
            )
        if len(proposals) == MAX_PROPOSALS:
            break
    return proposals


def insert_proposals(user_id: str, proposals: list[dict]) -> list[dict]:
    if not proposals:
        return []
    rows = [
        {
            "user_id": user_id,
            "content": item["content"],
            "kind": item["kind"],
            "status": "proposed",
            "source_message_ids": item["source_message_ids"],
        }
        for item in proposals
    ]
    return supabase.table("memories").insert(rows).execute().data


def _row_source_ids(row: dict) -> list[str]:
    raw = row.get("source_message_ids") or []
    if not isinstance(raw, list):
        return []
    ids: list[str] = []
    for value in raw:
        if (message_id := _uuid_text(value)) and message_id not in ids:
            ids.append(message_id)
    return ids


def _source_map(user_id: str, rows: list[dict]) -> dict[str, dict]:
    ids = sorted({source_id for row in rows for source_id in _row_source_ids(row)})
    if not ids:
        return {}
    messages = (
        supabase.table("messages").select(_SOURCE_SELECT).in_("id", ids).execute().data
    )
    conversation_ids = sorted({m["conversation_id"] for m in messages})
    if not conversation_ids:
        return {}
    conversations = (
        supabase.table("conversations")
        .select("id")
        .eq("user_id", user_id)
        .in_("id", conversation_ids)
        .execute()
        .data
    )
    own_conversations = {row["id"] for row in conversations}
    return {
        row["id"]: row
        for row in messages
        if row.get("conversation_id") in own_conversations
    }


def _fallback_explanation(sources: list[dict]) -> str:
    source = next((row for row in sources if row.get("role") == "user"), None)
    if source:
        return f"Based on what you wrote: “{_excerpt(source.get('content', ''))}”."
    if sources:
        return (
            "Based on this part of the reflection: "
            f"“{_excerpt(sources[0].get('content', ''))}”."
        )
    return "This insight was proposed from your reflection."


def serialise_rows(
    rows: list[dict],
    user_id: str,
    message_map: dict[str, dict] | None = None,
    explanations: dict[str, str] | None = None,
) -> list[dict]:
    """Return owner-safe payloads with only the cited source messages."""
    if message_map is None:
        message_map = _source_map(user_id, rows)
    payloads: list[dict] = []
    for row in rows:
        ids = _row_source_ids(row)
        sources = sorted(
            (message_map[source_id] for source_id in ids if source_id in message_map),
            key=lambda message: message.get("created_at", ""),
        )
        conversation_ids = {message.get("conversation_id") for message in sources}
        payloads.append(
            {
                "id": row["id"],
                "conversation_id": next(iter(conversation_ids))
                if len(conversation_ids) == 1
                else None,
                "content": row["content"],
                "kind": row["kind"],
                "status": row["status"],
                "explanation": (explanations or {}).get(row["id"])
                or _fallback_explanation(sources),
                "source_message_ids": ids,
                "source_messages": [
                    {
                        "id": message["id"],
                        "role": message["role"],
                        "content": message["content"],
                        "created_at": message["created_at"],
                    }
                    for message in sources
                ],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return payloads


def for_conversation(conversation_id: str, user_id: str) -> list[dict]:
    messages = (
        supabase.table("messages")
        .select(_SOURCE_SELECT)
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .execute()
        .data
    )
    message_map = {row["id"]: row for row in messages}
    if not message_map:
        return []
    rows = (
        supabase.table("memories")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at")
        .execute()
        .data
    )
    linked = [
        row
        for row in rows
        if any(source_id in message_map for source_id in _row_source_ids(row))
    ]
    return serialise_rows(linked, user_id, message_map)


def list_for_user(user_id: str, status: str | None = None) -> list[dict]:
    query = (
        supabase.table("memories")
        .select("*")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
    )
    if status:
        query = query.eq("status", status)
    return serialise_rows(query.execute().data, user_id)


def get_owned(memory_id: str, user_id: str) -> dict | None:
    rows = (
        supabase.table("memories")
        .select("*")
        .eq("id", memory_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def review(memory_id: str, status: str, content: str | None = None) -> dict:
    update = {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}
    if content is not None:
        update["content"] = content
    return supabase.table("memories").update(update).eq("id", memory_id).execute().data[0]

