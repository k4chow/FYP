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

from .. import constraints as constraint_svc
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
    # Film Assistant turns pass the tmdb_ids already shown this session so the
    # recommender drops them and widens its pool (rotation on Regenerate/new msgs).
    exclude_tmdb_ids: list[int] = Field(default_factory=list)

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


def _candidate_pool(
    user_id: str,
    limit: int = 8,
    asked: dict | None = None,
    exclude_tmdb_ids: list[int] | None = None,
) -> list[dict]:
    """Personalised candidates for the Film Assistant to pick from.

    The recommendation engine already excludes library films and every
    "not for me" card, so anything the provider names from this pool is safe
    to show. When the user stated a constraint (`asked`), the pool is built
    from that request instead of the taste profile. Best-effort: an engine
    failure must never break the chat.
    """
    try:
        cards = rec_svc.get_recommendations(
            user_id,
            limit=limit,
            genres=(asked or {}).get("genres") or None,
            person_id=(asked or {}).get("person_id"),
            exclude_ids=set(exclude_tmdb_ids or []),
            # Excluding already-shown films must widen the pool, otherwise a
            # new turn or a Regenerate would just reshuffle the same top picks.
            refresh=bool(exclude_tmdb_ids),
            # Chatting must not consume Discover's "don't repeat these" state.
            track_served=False,
        )
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


def _library_ids(user_id: str) -> set[int]:
    return {
        row["films"]["tmdb_id"]
        for row in (
            supabase.table("user_films")
            .select("films(tmdb_id)")
            .eq("user_id", user_id)
            .execute()
            .data
            or []
        )
        if row.get("films") and row["films"].get("tmdb_id")
    }


def _last_user_text(history: list[dict]) -> str:
    return next(
        (str(m.get("content") or "") for m in reversed(history) if m.get("role") == "user"),
        "",
    )


def _requested_title_cards(
    title: str, tmdb_id: int | None, user_id: str
) -> tuple[list[dict], str | None]:
    """Cards for a film the user named explicitly (Phase 7).

    Returns ``(cards, note)``. When the film is already in the library, the
    cards are TMDB's own recommendations instead and `note` says so — so the
    assistant acknowledges the film instead of refusing to discuss it.
    """
    if not tmdb_id:
        try:
            hits = tmdb.search_movies(title)
        except Exception:  # noqa: BLE001
            return [], None
        if not hits:
            return [], None
        tmdb_id = hits[0].get("id")

    details = tmdb.movie_details(tmdb_id)
    if not details:
        return [], None

    library_ids = _library_ids(user_id)

    def card_from(r: dict) -> dict:
        return {
            "tmdb_id": r["id"],
            "title": r.get("title") or "Untitled",
            "year": _tmdb_year(r.get("release_date")),
            "genres": [
                tmdb.GENRE_NAMES[g] for g in r.get("genre_ids", []) if g in tmdb.GENRE_NAMES
            ],
            "runtime": None,
            "overview": r.get("overview") or "",
            "poster_url": poster_url(r.get("poster_path")),
            "vote_average": r.get("vote_average") or 0.0,
            "themes": [],
        }

    if details["id"] in library_ids:
        recs = tmdb.movie_recommendations(details["id"])[:4]
        cards = [
            card_from(r)
            for r in recs
            if r.get("id") and r["id"] not in library_ids
        ][:3]
        note = (
            f"“{details.get('title') or title}” is already in your library — "
            "here are films close to it instead."
        )
        return cards, note

    card = {
        "tmdb_id": details["id"],
        "title": details.get("title") or title,
        "year": _tmdb_year(details.get("release_date")),
        "genres": [g.get("name") for g in details.get("genres", [])],
        "runtime": details.get("runtime"),
        "overview": details.get("overview") or "",
        "poster_url": poster_url(details.get("poster_path")),
        "vote_average": details.get("vote_average") or 0.0,
        "themes": [],
    }
    try:
        neighbours = [
            r
            for r in tmdb.movie_recommendations(details["id"])[:3]
            if r.get("id") and r.get("id") not in library_ids and r.get("id") != details["id"]
        ]
    except Exception:  # noqa: BLE001
        neighbours = []
    return [card] + [card_from(r) for r in neighbours][:2], None


def _fallback_reply(cards: list[dict], note: str | None = None) -> str:
    if not cards:
        return "I couldn't pull together a solid pick that fits that — want to try a different mood?"
    titles = " and ".join(card["title"] for card in cards[:2])
    lead = (cards[0].get("genres") or ["worth a look"])[0].lower()
    text = (
        f"Going with {titles}. {cards[0]['title']} — {lead}. "
        "Which one grabs you, or shall I pull something different?"
    )
    return f"{text}\n\n{note}" if note else text


def _discovery_reply(
    history: list[dict],
    ctx: ChatContext,
    user_id: str,
    exclude_tmdb_ids: list[int] | None = None,
) -> tuple[str, dict]:
    """One Film Assistant turn: recommender reply + verified film cards.

    The provider picks from the personalised candidate pool (which already
    excludes the user's library and every "not for me" card), so every turn
    recommends films the user has not logged. Any provider or TMDB failure
    degrades to the top of that pool — discovery chat stays a recommender —
    and only a fully empty pool degrades to a plain chat reply.
    """
    llm = get_llm()
    asked = constraint_svc.parse_constraints(_last_user_text(history))
    pool = _candidate_pool(
        user_id,
        asked=asked if constraint_svc.has_constraint(asked) else None,
        exclude_tmdb_ids=exclude_tmdb_ids,
    )
    if pool:
        ctx = replace(ctx, suggestions=pool)
    hint = constraint_svc.describe(asked)
    if hint:
        ctx = replace(ctx, request=hint)
    try:
        turn = llm.chat_discovery(history, ctx)
        reply, specs = turn["reply"], turn.get("films") or []
    except Exception:  # noqa: BLE001 - a model/API error must never break chat
        specs, reply = [], None
    try:
        cards = _resolve_suggestions(specs, user_id)
    except Exception:  # noqa: BLE001 - grounding is best-effort
        cards = []
    if exclude_tmdb_ids:
        # Drop anything the user has already seen this session (the provider may
        # re-name an old title from the transcript; the candidate pool already
        # excludes it, but grounding by title can bring it back).
        shown = set(exclude_tmdb_ids)
        cards = [c for c in cards if c["tmdb_id"] not in shown]
    # A named film is answered directly — and if it is already logged, the
    # assistant acknowledges it with close alternatives instead of refusing.
    named_cards: list[dict] = []
    named_note: str | None = None
    if asked.get("title"):
        try:
            named_cards, named_note = _requested_title_cards(
                asked["title"], asked.get("tmdb_id"), user_id
            )
        except Exception:  # noqa: BLE001 - grounding is best-effort
            named_cards, named_note = [], None
    if named_cards:
        seen = {c["tmdb_id"] for c in named_cards}
        cards = named_cards + [c for c in cards if c["tmdb_id"] not in seen]
        cards = cards[:3]
    if not cards and pool:
        # The provider named nothing groundable — fall back to the top of the
        # personalised pool so every assistant turn still recommends films.
        cards = [_pool_card(film) for film in pool[:2]]
    if reply is None:
        # The provider failed: without any candidate pool to fall back on, the
        # turn degrades to a plain chat reply rather than an empty recommender.
        if not cards:
            return llm.chat(history, ctx), {}
        reply = _fallback_reply(cards, named_note)
    elif not reply:
        reply = _fallback_reply(cards, named_note)
    elif named_note:
        reply = f"{reply}\n\n{named_note}"
    return reply, {"kind": "suggestions", "recommendations": cards}


def discovery_opening(user_id: str) -> str:
    """The Film Assistant's first message, with no conversation row (Phase 7)."""
    ctx = ChatContext(
        conversation_type="discovery",
        memories=context_svc.confirmed_memories(user_id),
        display_name=_display_name(user_id),
        turn=0,
    )
    return get_llm().opening(ctx)


def discovery_turn(
    user_id: str, history: list[dict], exclude_tmdb_ids: list[int] | None = None
) -> dict:
    """One Film Assistant turn with no persistence (Phase 7).

    The client owns the transcript (sessionStorage) and sends the bounded
    window here; nothing is written to the database, so ending the chat is
    just the client discarding that transcript.
    """
    ctx = ChatContext(
        conversation_type="discovery",
        memories=context_svc.confirmed_memories(user_id),
        display_name=_display_name(user_id),
        turn=sum(1 for m in history if m.get("role") == "user"),
        library_titles=_library_titles(user_id),
    )
    reply, metadata = _discovery_reply(history, ctx, user_id, exclude_tmdb_ids)
    return {"reply": reply, "recommendations": metadata.get("recommendations", [])}


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


@router.delete("/{conversation_id}", status_code=200)
def delete_conversation(
    conversation_id: UUID, current: dict = Depends(get_current_user)
) -> dict:
    """Delete a reflection (or any own conversation) plus its derived insights.

    Order matters: memories are removed first (they reference message ids),
    then the messages, then the conversation row. The recommendation cache is
    invalidated because its ranking is built from confirmed memories.
    """
    conversation_id_text = str(conversation_id)
    _get_own(conversation_id_text, current["id"])
    rows = (
        supabase.table("messages")
        .select("id")
        .eq("conversation_id", conversation_id_text)
        .execute()
        .data
        or []
    )
    message_ids = [row["id"] for row in rows]
    memory_svc.delete_for_messages(current["id"], message_ids)
    if message_ids:
        supabase.table("messages").delete().eq(
            "conversation_id", conversation_id_text
        ).execute()
    supabase.table("conversations").delete().eq(
        "id", conversation_id_text
    ).execute()
    rec_svc.invalidate(current["id"])
    return {"deleted": True}


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
        reply, metadata = _discovery_reply(
            history, ctx, current["id"], body.exclude_tmdb_ids
        )
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
