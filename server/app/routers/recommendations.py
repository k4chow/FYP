"""Recommendation endpoints (Phase 6: F8, F9, F11).

GET /recommendations returns ranked, self-explaining cards from the
deterministic engine in app/recommendations.py (D35). Feedback posts
steer future runs: "more_like_this" becomes a seed, "not_for_me" a hard
exclusion. Both invalidate the per-user result cache immediately.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import recommendations as rec_svc
from ..deps import get_current_user
from ..supabase_client import supabase

router = APIRouter()

_SIGNALS = ("more_like_this", "not_for_me")


class FeedbackBody(BaseModel):
    tmdb_id: int = Field(..., gt=0)
    signal: str = Field(..., pattern="^(more_like_this|not_for_me)$")
    title: str = Field(default="", max_length=300)


@router.get("")
def list_recommendations(
    limit: int = Query(default=12, ge=1, le=24),
    refresh: bool = Query(default=False),
    exclude_tmdb_ids: list[int] | None = Query(default=None),
    current: dict = Depends(get_current_user),
) -> dict:
    cards = rec_svc.get_recommendations(
        current["id"],
        limit=limit,
        refresh=refresh,
        # Already-shown films this session (rotation): treated like library films,
        # so a refresh genuinely surfaces fresh picks even across restarts.
        exclude_ids=set(exclude_tmdb_ids or []),
    )
    return {"recommendations": cards}


@router.post("/feedback")
def send_feedback(
    body: FeedbackBody, current: dict = Depends(get_current_user)
) -> dict:
    user_id = current["id"]
    supabase.table("recommendation_feedback").upsert(
        {
            "user_id": user_id,
            "tmdb_id": body.tmdb_id,
            "title": body.title.strip(),
            "signal": body.signal,
        },
        on_conflict="user_id,tmdb_id",
    ).execute()
    rec_svc.invalidate(user_id)
    return {"tmdb_id": body.tmdb_id, "signal": body.signal}


@router.delete("/feedback/{tmdb_id}")
def clear_feedback(tmdb_id: int, current: dict = Depends(get_current_user)) -> dict:
    """Undo previous feedback on a card (thumb toggle off)."""
    user_id = current["id"]
    supabase.table("recommendation_feedback").delete().eq(
        "user_id", user_id
    ).eq("tmdb_id", tmdb_id).execute()
    rec_svc.invalidate(user_id)
    return {"tmdb_id": tmdb_id, "signal": None}
