"""Reflection & discovery conversations (F1, F4, F5).

- F1/D11: every message (user and assistant) is persisted verbatim and
  append-only — including the assistant's opening message, so chat state
  has a single source of truth.
- F4: LLM context is assembled server-side and bounded — recent N messages
  + K confirmed memories (app/context.py), never the full history.
- F5/D5: replies come from the swappable provider seam (app/llm).
"""

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from .. import context as context_svc
from .. import memories as memory_svc
from .. import recommendations as rec_svc
from .. import tmdb
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


def _library_titles(user_id: str, limit: int = 80) -> list[str]:
    """Titles already logged by the user — the assistant must not re-recommend
    them (the recommendation engine excludes them too, but the LLM needs the
    list spelled out so it cannot name watched films in its reply text)."""
    res = (
        supabase.table("user_films")
        .select("films(title)")
        .eq("user_id", user_id)
        .limit(limit)
        .execute()
    )
    return [
        row["films"]["title"]
        for row in (res.data or [])
        if row.get("films") and row["films"].get("title")
    ]


def _chat_context(conv: dict, user_id: str, turn: int) -> ChatContext:
    return ChatContext(
        conversation_type=conv["type"],
        title=conv.get("title"),
        film=conv.get("films") or None,
        watch_type=conv.get("watch_type"),
        memories=context_svc.confirmed_memories(user_id),
        display_name=_display_name(user_id),
        turn=turn,
        library_titles=(
            _library_titles(user_id) if conv["type"] == "discovery" else []
        ),
    )


def _candidate_pool(user_id: str, limit: int = 8) -> list[dict]:
    """Personalised candidates for the Film Assistant to pick from.

    The recommendation engine already excludes library films and every
    "not for me" card, so anything the provider names from this pool is safe
    to show. Best-effort: an engine failure must never break the chat.
    """
    try:
        cards = rec_svc.get_recommendations(user_id, limit=limit)
    except Exception:  # noqa: BLE001 - discovery chat must never fail here
        return []
    return [
        {
            "tmdb_id": card["tmdb_id"],
            "title": card["title"],
            "year": card.get("year"),
            "genres": card.get("genres") or [],
            "overview": (card.get("overview") or "")[:220],
            "why": card.get("why") or "",
            "poster_url": card.get("poster_url"),
            "vote_average": card.get("vote_average", 0.0),
        }
        for card in cards
    ]


def _tmdb_year(release: object) -> int | None:
    """Release dates come back as 'YYYY-MM-DD' or None."""
    text = str(release or "")
    return int(text[:4]) if text[:4].isdigit() else None


def _resolve_suggestions(specs: list[dict], user_id: str) -> list[dict]:
    """Ground LLM-named films against TMDB, skipping films already in the
    library. Unresolvable titles are dropped; library films are skipped so
    the Film Assistant never recommends something the user has logged."""
    if not specs:
        return []
    library_ids = {
        row["films"]["tmdb_id"]
        for row in (
            supabase.table("user_films")
            .select("films(tmdb_id)")
            .eq("user_id", user_id)
            .execute()
            .data
            or []
        )
        if row.get("films")
    }
    cards: list[dict] = []
    for spec in specs[:3]:
        title = str(spec.get("title") or "").strip()
        if not title:
            continue
        year = spec.get("year")
        tmdb_id = spec.get("tmdb_id")
        if isinstance(tmdb_id, int) and tmdb_id > 0:
            # Providers grounded in the engine's candidate pool pass the TMDB
            # id through directly — no search needed, no wrong-title risk.
            if tmdb_id in library_ids:
                continue
            details = tmdb.movie_details(tmdb_id)
            if details is None:
                continue
        else:
            try:
                hits = tmdb.search_movies(
                    title, year if isinstance(year, int) else None
                )
            except Exception:  # noqa: BLE001 - grounding is best-effort per title
                continue
            match = next(
                (
                    hit
                    for hit in hits
                    if str(hit.get("title") or "").casefold() == title.casefold()
                ),
                hits[0] if hits else None,
            )
            if match is None or match.get("id") in library_ids:
                continue
            details = tmdb.movie_details(match["id"])
            if details is None:
                continue
        cards.append(
            {
                "tmdb_id": details["id"],
                "title": details.get("title") or title,
                "year": _tmdb_year(details.get("release_date")),
                "genres": [g.get("name") for g in details.get("genres", [])],
                "runtime": details.get("runtime"),
                "overview": details.get("overview") or "",
                "poster_url": poster_url(details.get("poster_path")),
                "vote_average": details.get("vote_average"),
                "themes": spec.get("themes") or [],
            }
        )
    return cards


def _pool_card(film: dict) -> dict:
    """Shape an engine candidate into an assistant card (runtime unknown)."""
    return {
        "tmdb_id": film["tmdb_id"],
        "title": film["title"],
        "year": film.get("year"),
        "genres": film.get("genres") or [],
        "runtime": None,
        "overview": film.get("overview") or "",
        "poster_url": film.get("poster_url"),
        "vote_average": film.get("vote_average", 0.0),
        "themes": [],
    }


def _discovery_reply(
    history: list[dict], ctx: ChatContext, user_id: str
) -> tuple[str, dict]:
    """One Film Assistant turn: recommender reply + verified film cards.

    The provider picks from the personalised candidate pool (which already
    excludes the user's library and every "not for me" card), so every turn
    recommends films the user has not logged. Any provider or TMDB failure
    degrades to the top of that pool — discovery chat stays a recommender —
    and only a fully empty pool degrades to a plain chat reply.
    """
    llm = get_llm()
    pool = _candidate_pool(user_id)
    if pool:
        ctx = replace(ctx, suggestions=pool)
    try:
        turn = llm.chat_discovery(history, ctx)
        reply, specs = turn["reply"], turn.get("films") or []
    except (RuntimeError, AttributeError, KeyError, TypeError):
        specs, reply = [], None
    try:
        cards = _resolve_suggestions(specs, user_id)
    except Exception:  # noqa: BLE001 - grounding is best-effort
        cards = []
    if not cards and pool:
        # The provider named nothing groundable — fall back to the top of the
        # personalised pool so every assistant turn still recommends films.
        cards = [_pool_card(film) for film in pool[:2]]
        titles = " and ".join(card["title"] for card in cards)
        lead = cards[0]["genres"][0] if cards[0]["genres"] else "worth a look"
        reply = (
            f"Going with {titles}. {cards[0]['title']} — {lead.lower()}. "
            "Which one grabs you, or shall I pull something different?"
        )
    if reply is None:
        return llm.chat(history, ctx), {}
    return reply, {"kind": "suggestions", "recommendations": cards}


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
    metadata: dict = {}
    if conv["type"] == "discovery":
        reply, metadata = _discovery_reply(history, ctx, current["id"])
    assistant_message = (
        supabase.table("messages")
        .insert(
            {
                "conversation_id": conversation_id_text,
                "role": "assistant",
                "content": reply,
                "metadata": metadata,
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
