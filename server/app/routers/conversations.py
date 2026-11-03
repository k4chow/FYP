"""Reflection & discovery conversations (F1, F4, F5).

- F1/D11: every message (user and assistant) is persisted verbatim and
  append-only — including the assistant's opening message, so chat state
  has a single source of truth.
- F4: LLM context is assembled server-side and bounded — recent N messages
  + K confirmed memories (app/context.py), never the full history.
- F5/D5: replies come from the swappable provider seam (app/llm).
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from .. import context as context_svc
from .. import memories as memory_svc
from ..deps import get_current_user
from ..llm import ChatContext, get_llm
from ..supabase_client import supabase
from ..tmdb import poster_url
from .films import _ensure_film

router = APIRouter()

CONV_SELECT = (
    "id,type,title,status,watch_type,created_at,updated_at,ended_at,"
    "films(id,tmdb_id,title,year,genres,poster_path,metadata)"
)


class CreateConversationBody(BaseModel):
    type: str = Field(default="reflection", pattern="^(reflection|discovery)$")
    film_id: str | None = None
    tmdb_id: int | None = None
    watch_type: str | None = Field(default=None, pattern="^(seen|planning)$")
    title: str | None = Field(default=None, max_length=200)


class MessageBody(BaseModel):
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message content cannot be blank")
        return value  # D11: preserve the user's content verbatim.


def _serialise(row: dict) -> dict:
    row = dict(row)
    film = row.pop("films", None)
    if film:
        meta = film.get("metadata") or {}
        film = {
            "id": film.get("id"),
            "tmdb_id": film.get("tmdb_id"),
            "title": film.get("title"),
            "year": film.get("year"),
            "genres": film.get("genres") or [],
            "runtime": meta.get("runtime"),
            "overview": meta.get("overview") or "",
            "poster_url": poster_url(film.get("poster_path")),
        }
    return {**row, "film": film}


def _get_own(conversation_id: str, user_id: str) -> dict:
    res = (
        supabase.table("conversations")
        .select(CONV_SELECT)
        .eq("id", conversation_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return res.data[0]


def _display_name(user_id: str) -> str | None:
    res = (
        supabase.table("users")
        .select("display_name")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    return (res.data[0].get("display_name") if res.data else None) or None


def _chat_context(conv: dict, user_id: str, turn: int) -> ChatContext:
    return ChatContext(
        conversation_type=conv["type"],
        title=conv.get("title"),
        film=conv.get("films") or None,
        watch_type=conv.get("watch_type"),
        memories=context_svc.confirmed_memories(user_id),
        display_name=_display_name(user_id),
        turn=turn,
    )


def _user_turn_count(conversation_id: str) -> int:
    res = (
        supabase.table("messages")
        .select("id", count="exact")
        .eq("conversation_id", conversation_id)
        .eq("role", "user")
        .limit(1)
        .execute()
    )
    return res.count or 0


@router.post("", status_code=201)
def create_conversation(
    body: CreateConversationBody, current: dict = Depends(get_current_user)
) -> dict:
    film = None
    if body.film_id:
        found = (
            supabase.table("films")
            .select("*")
            .eq("id", body.film_id)
            .limit(1)
            .execute()
        )
        if not found.data:
            raise HTTPException(status_code=404, detail="Film not found")
        film = found.data[0]
    elif body.tmdb_id is not None:
        film = _ensure_film(body.tmdb_id)
    if body.watch_type and film is None:
        raise HTTPException(status_code=400, detail="watch_type requires a film")

    title = body.title or (f"Reflection on {film['title']}" if film else None)
    conv = (
        supabase.table("conversations")
        .insert(
            {
                "user_id": current["id"],
                "type": body.type,
                "film_id": film["id"] if film else None,
                "watch_type": body.watch_type,
                "title": title,
            }
        )
        .execute()
        .data[0]
    )

    # The assistant opens every conversation; persisted like any message (D11).
    ctx = _chat_context({**conv, "films": film}, current["id"], turn=0)
    opening = get_llm().opening(ctx)
    message = (
        supabase.table("messages")
        .insert(
            {
                "conversation_id": conv["id"],
                "role": "assistant",
                "content": opening,
                "metadata": {"kind": "opening"},
            }
        )
        .execute()
        .data[0]
    )
    return {
        "conversation": _serialise({**conv, "films": film}),
        "messages": [message],
    }


@router.get("")
def list_conversations(
    status: str | None = None,
    conv_type: str | None = Query(default=None, alias="type"),
    current: dict = Depends(get_current_user),
) -> dict:
    query = (
        supabase.table("conversations")
        .select(CONV_SELECT)
        .eq("user_id", current["id"])
        .order("updated_at", desc=True)
    )
    if status in ("active", "completed"):
        query = query.eq("status", status)
    if conv_type in ("reflection", "discovery"):
        query = query.eq("type", conv_type)
    res = query.execute()
    return {"conversations": [_serialise(r) for r in res.data]}


@router.get("/{conversation_id}/memories")
def get_conversation_memories(
    conversation_id: UUID, current: dict = Depends(get_current_user)
) -> dict:
    """Return every review item linked to one owned reflection, all statuses."""
    conversation_id_text = str(conversation_id)
    _get_own(conversation_id_text, current["id"])
    return {"memories": memory_svc.for_conversation(conversation_id_text, current["id"])}


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: UUID, current: dict = Depends(get_current_user)
) -> dict:
    conversation_id_text = str(conversation_id)
    conv = _get_own(conversation_id_text, current["id"])
    # Full history for display — F4 bounds only the LLM context, not the UI.
    res = (
        supabase.table("messages")
        .select("id,role,content,metadata,created_at")
        .eq("conversation_id", conversation_id_text)
        .order("created_at")
        .execute()
    )
    return {"conversation": _serialise(conv), "messages": res.data}


@router.post("/{conversation_id}/messages", status_code=201)
def post_message(
    conversation_id: UUID,
    body: MessageBody,
    current: dict = Depends(get_current_user),
) -> dict:
    conversation_id_text = str(conversation_id)
    conv = _get_own(conversation_id_text, current["id"])
    if conv["status"] != "active":
        raise HTTPException(status_code=409, detail="This conversation has ended")

    # D11: the user message is stored verbatim before any processing.
    user_message = (
        supabase.table("messages")
        .insert(
            {
                "conversation_id": conversation_id_text,
                "role": "user",
                "content": body.content,
            }
        )
        .execute()
        .data[0]
    )

    # F4: bounded context — recent N messages + confirmed memories only.
    history = context_svc.recent_messages(conversation_id_text)
    ctx = _chat_context(
        conv, current["id"], turn=_user_turn_count(conversation_id_text)
    )
    reply = get_llm().chat(history, ctx)
    assistant_message = (
        supabase.table("messages")
        .insert(
            {
                "conversation_id": conversation_id_text,
                "role": "assistant",
                "content": reply,
            }
        )
        .execute()
        .data[0]
    )

    supabase.table("conversations").update(
        {"updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", conversation_id_text).execute()

    return {"user_message": user_message, "assistant_message": assistant_message}


@router.post("/{conversation_id}/end")
def end_conversation(
    conversation_id: UUID, current: dict = Depends(get_current_user)
) -> dict:
    """End an owned reflection and create user-reviewable proposed memories.

    The message history is read through the same bounded window as chat (F4)
    and is never updated (D11). Repeat calls return the memories already linked
    to the completed reflection without extracting again.
    """
    conversation_id_text = str(conversation_id)
    conv = _get_own(conversation_id_text, current["id"])
    review_memories = memory_svc.for_conversation(conversation_id_text, current["id"])

    if conv["status"] != "completed":
        created_rows: list[dict] = []
        explanations: dict[str, str] = {}
        if conv["type"] == "reflection" and not review_memories:
            # Bounded records include ids solely so extraction can cite sources.
            records = context_svc.recent_message_records(conversation_id_text)
            ctx = _chat_context(
                conv, current["id"], turn=_user_turn_count(conversation_id_text)
            )
            try:
                raw = get_llm().extract_insights(records, ctx)
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail="Insight extraction failed; the reflection was not ended",
                ) from exc
            proposals = memory_svc.normalise_proposals(raw, records)
            created_rows = memory_svc.insert_proposals(current["id"], proposals)
            explanations = {
                row["id"]: proposal["explanation"]
                for row, proposal in zip(created_rows, proposals, strict=False)
            }

        now = datetime.now(timezone.utc).isoformat()
        supabase.table("conversations").update(
            {"status": "completed", "ended_at": now, "updated_at": now}
        ).eq("id", conversation_id_text).eq("status", "active").execute()
        conv = _get_own(conversation_id_text, current["id"])
        if created_rows:
            review_memories = memory_svc.serialise_rows(
                created_rows, current["id"], explanations=explanations
            )

    return {"conversation": _serialise(conv), "proposed_memories": review_memories}
