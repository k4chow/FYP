"""Reflective profile endpoints (F2).

GET /profile/summary builds a human-readable profile ONLY from confirmed
memories (D12: proposed/rejected memories never surface here) plus basic
library statistics. The summary text is generated deterministically — no LLM
call — so the profile works with the mock provider and stays reproducible.
"""

from collections import Counter

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import memories as memory_svc
from .. import recommendations as rec_svc
from ..deps import get_current_user
from ..supabase_client import supabase

router = APIRouter()

_PAGE = 1000
_TOP_GENRES = 3
_TOP_KIND_CONTENT = 3


def _count(table: str, user_id: str, **filters: str) -> int:
    query = (
        supabase.table(table)
        .select("id", count="exact")
        .eq("user_id", user_id)
    )
    for field, value in filters.items():
        query = query.eq(field, value)
    return query.limit(1).execute().count or 0


def _genre_counts(user_id: str, limit: int | None = _TOP_GENRES) -> list[dict]:
    """Genre frequency across the user's watched films, most common first.

    limit=None returns every genre (the profile page's Genres tab); the
    default keeps just the top few for the summary sentence.
    """
    counts: Counter[str] = Counter()
    offset = 0
    while True:
        page = (
            supabase.table("user_films")
            .select("films(genres)")
            .eq("user_id", user_id)
            .eq("status", "watched")
            .range(offset, offset + _PAGE - 1)
            .execute()
            .data
        )
        for row in page:
            for genre in (row.get("films") or {}).get("genres") or []:
                counts[genre] += 1
        if len(page) < _PAGE:
            break
        offset += _PAGE
    return [
        {"genre": genre, "count": count}
        for genre, count in counts.most_common(limit)
    ]


def _oxford(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _summary_text(
    memories: list[dict],
    stats: dict,
    display_name: str | None,
) -> str | None:
    """A short generated profile paragraph from confirmed insights only."""
    if not memories:
        return None
    who = f"{display_name}'s" if display_name else "Your"
    sentences = [
        f"{who} reflective profile draws on "
        f"{stats['confirmed_insights']} confirmed insight"
        f"{'s' if stats['confirmed_insights'] != 1 else ''} from "
        f"{stats['reflections_completed']} completed reflection"
        f"{'s' if stats['reflections_completed'] != 1 else ''}."
    ]
    if stats["films_watched"]:
        genres = [g["genre"] for g in stats["top_genres"]]
        watched = f"Across {stats['films_watched']} watched films"
        if genres:
            watched += f", {_oxford(genres)} lead the way"
        sentences.append(watched + ".")
    by_kind: dict[str, list[str]] = {"theme": [], "preference": [], "insight": []}
    for memory in memories:
        by_kind.setdefault(memory["kind"], []).append(memory["content"])
    if by_kind["theme"]:
        sentences.append("Recurring themes: " + _oxford(by_kind["theme"][:_TOP_KIND_CONTENT]))
    if by_kind["preference"]:
        sentences.append(_oxford(by_kind["preference"][:_TOP_KIND_CONTENT]))
    if by_kind["insight"]:
        sentences.append(_oxford(by_kind["insight"][:_TOP_KIND_CONTENT]))
    return "\n\n".join(sentences)


@router.get("/summary")
def profile_summary(current: dict = Depends(get_current_user)) -> dict:
    user_id = current["id"]
    display_name = (
        supabase.table("users")
        .select("display_name")
        .eq("id", user_id)
        .limit(1)
        .execute()
        .data
        or [{}]
    )[0].get("display_name")

    stats = {
        "films_watched": _count("user_films", user_id, status="watched"),
        "watchlist": _count("user_films", user_id, status="watchlist"),
        "confirmed_insights": _count("memories", user_id, status="confirmed"),
        "proposed_awaiting_review": _count("memories", user_id, status="proposed"),
        "reflections_completed": _count(
            "conversations", user_id, type="reflection", status="completed"
        ),
        "top_genres": _genre_counts(user_id),
        "genre_counts": _genre_counts(user_id, limit=None),
    }
    memories = memory_svc.list_for_user(user_id, "confirmed")
    groups = {
        kind: [m for m in memories if m["kind"] == kind]
        for kind in ("theme", "preference", "insight")
    }
    return {
        "display_name": display_name,
        "stats": stats,
        "summary": _summary_text(memories, stats, display_name),
        "groups": groups,
    }


# --- Recommendation preferences (N6, Phase 6) --------------------------------

_DEFAULT_STYLE = 30  # matches users.recommendation_style default


class PreferencesBody(BaseModel):
    recommendation_style: int = Field(
        ..., ge=0, le=100, description="0 = more like what I love, 100 = surprise me"
    )


@router.get("/preferences")
def get_preferences(current: dict = Depends(get_current_user)) -> dict:
    row = (
        supabase.table("users")
        .select("recommendation_style")
        .eq("id", current["id"])
        .limit(1)
        .execute()
        .data
        or [{}]
    )[0]
    value = row.get("recommendation_style")
    return {"recommendation_style": value if isinstance(value, int) else _DEFAULT_STYLE}


@router.patch("/preferences")
def update_preferences(
    body: PreferencesBody, current: dict = Depends(get_current_user)
) -> dict:
    supabase.table("users").update(
        {"recommendation_style": body.recommendation_style}
    ).eq("id", current["id"]).execute()
    # Weights change immediately; drop any cached Discover grid.
    rec_svc.invalidate(current["id"])
    return {"recommendation_style": body.recommendation_style}


# --- Onboarding questionnaire (D38) -------------------------------------------

_MAX_ANSWERS = 8


class QuestionnaireAnswer(BaseModel):
    question: str = Field(..., min_length=1, max_length=200)
    answer: str = Field(..., max_length=500)


class QuestionnaireBody(BaseModel):
    answers: list[QuestionnaireAnswer] = Field(default_factory=list, max_length=_MAX_ANSWERS)


@router.post("/questionnaire", status_code=201)
def save_questionnaire(
    body: QuestionnaireBody, current: dict = Depends(get_current_user)
) -> dict:
    """Save the onboarding about-you answers into the reflective profile.

    The answers are the user's own words, written about themselves, so they
    enter the profile directly as confirmed preferences — D12's review step
    exists for system-proposed insights, not user-authored data.
    """
    rows = [
        {
            "user_id": current["id"],
            "content": content,
            "kind": "preference",
            "status": "confirmed",
            "source_message_ids": [],
        }
        for item in body.answers
        if (content := item.answer.strip())
    ]
    if rows:
        supabase.table("memories").insert(rows).execute()
        # Profile content changed; drop any cached Discover grid.
        rec_svc.invalidate(current["id"])
    return {"saved": len(rows)}

