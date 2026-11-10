"""Film catalogue + user library routes (F7).

`films` is a shared catalogue (written via service role only); `user_films`
is the per-user library. Every query is explicitly scoped to the caller.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import tmdb
from ..deps import get_current_user
from ..supabase_client import supabase

router = APIRouter()

MINE_SELECT = (
    "id,status,source,rating,watched_on,added_at,"
    "films(id,tmdb_id,title,year,genres,poster_path,metadata)"
)


def _flatten(row: dict) -> dict:
    film = row.pop("films") or {}
    meta = film.get("metadata") or {}
    return {
        **row,
        "film_id": film.get("id"),
        "tmdb_id": film.get("tmdb_id"),
        "title": film.get("title"),
        "year": film.get("year"),
        "genres": film.get("genres") or [],
        "runtime": meta.get("runtime"),
        "poster_url": tmdb.poster_url(film.get("poster_path")),
    }


def _ensure_film(tmdb_id: int) -> dict:
    """Return the `films` row for a TMDB id, fetching + caching it if new.

    Keywords are backfilled lazily for films cached before the theme tags
    feature existed, so the profile's emotional-theme counts stay current.
    """
    existing = (
        supabase.table("films").select("*").eq("tmdb_id", tmdb_id).limit(1).execute()
    )
    if existing.data:
        row = existing.data[0]
        if not ((row.get("metadata") or {}).get("keywords")):
            keywords = tmdb.movie_keywords(tmdb_id)
            if keywords:
                meta = dict(row.get("metadata") or {})
                meta["keywords"] = keywords
                updated = (
                    supabase.table("films")
                    .update({"metadata": meta})
                    .eq("id", row["id"])
                    .execute()
                    .data
                )
                row = (updated or [row])[0]
        return row
    details = tmdb.movie_details(tmdb_id)
    if details is None:
        raise HTTPException(status_code=404, detail="Film not found on TMDB")
    row = tmdb.film_row_from_details(details)
    keywords = tmdb.movie_keywords(tmdb_id)
    if keywords:
        row["metadata"] = {**(row.get("metadata") or {}), "keywords": keywords}
    res = supabase.table("films").upsert(row, on_conflict="tmdb_id").execute()
    return res.data[0]


class AddFilmBody(BaseModel):
    tmdb_id: int
    status: str = Field(pattern="^(watched|watchlist)$")
    rating: float | None = Field(default=None, ge=0, le=5)
    watched_on: date | None = None


class UpdateFilmBody(BaseModel):
    status: str | None = Field(default=None, pattern="^(watched|watchlist)$")
    rating: float | None = Field(default=None, ge=0, le=5)
    watched_on: date | None = None


@router.get("/search")
def search(
    q: str = Query(min_length=1), current: dict = Depends(get_current_user)
) -> dict:
    results = tmdb.search_movies(q)[:8]
    return {"results": [tmdb.simplify_search_result(r) for r in results]}


@router.get("/tmdb/{tmdb_id}")
def tmdb_detail(tmdb_id: int, current: dict = Depends(get_current_user)) -> dict:
    details = tmdb.movie_details(tmdb_id)
    if details is None:
        raise HTTPException(status_code=404, detail="Film not found on TMDB")
    row = tmdb.film_row_from_details(details)
    in_library = None
    film = (
        supabase.table("films").select("id").eq("tmdb_id", tmdb_id).limit(1).execute()
    )
    if film.data:
        uf = (
            supabase.table("user_films")
            .select("id,status,rating")
            .eq("user_id", current["id"])
            .eq("film_id", film.data[0]["id"])
            .limit(1)
            .execute()
        )
        in_library = uf.data[0] if uf.data else None
    return {
        "tmdb_id": row["tmdb_id"],
        "title": row["title"],
        "year": row["year"],
        "genres": row["genres"],
        "runtime": row["metadata"]["runtime"],
        "overview": row["metadata"]["overview"],
        "poster_url": tmdb.poster_url(row["poster_path"]),
        "in_library": in_library,
    }


@router.get("/mine")
def my_films(
    status: str | None = None,
    limit: int = Query(default=250, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current: dict = Depends(get_current_user),
) -> dict:
    query = (
        supabase.table("user_films")
        .select(MINE_SELECT, count="exact")
        .eq("user_id", current["id"])
        .order("added_at", desc=True)
    )
    if status in ("watched", "watchlist"):
        query = query.eq("status", status)
    res = query.range(offset, offset + limit - 1).execute()

    # Per-status totals for the filter pills — always for the whole library,
    # regardless of the active filter/pagination.
    def status_count(value: str | None) -> int:
        q = (
            supabase.table("user_films")
            .select("id", count="exact")
            .eq("user_id", current["id"])
            .limit(1)
        )
        if value:
            q = q.eq("status", value)
        return q.execute().count or 0

    counts = {
        "all": status_count(None),
        "watched": status_count("watched"),
        "watchlist": status_count("watchlist"),
    }
    return {
        "films": [_flatten(r) for r in res.data],
        "total": res.count or 0,
        "limit": limit,
        "offset": offset,
        "counts": counts,
    }


def _response_row(user_film: dict, film: dict) -> dict:
    film_meta = film.get("metadata") or {}
    return {
        **user_film,
        "tmdb_id": film.get("tmdb_id"),
        "title": film.get("title"),
        "year": film.get("year"),
        "genres": film.get("genres") or [],
        "runtime": film_meta.get("runtime"),
        "poster_url": tmdb.poster_url(film.get("poster_path")),
    }


@router.post("/mine", status_code=201)
def add_film(body: AddFilmBody, current: dict = Depends(get_current_user)) -> dict:
    film = _ensure_film(body.tmdb_id)
    existing = (
        supabase.table("user_films")
        .select("*")
        .eq("user_id", current["id"])
        .eq("film_id", film["id"])
        .limit(1)
        .execute()
        .data
    )
    # Watched always wins (D28): adding an already-watched film to the
    # watchlist must not downgrade its status — return it unchanged.
    if existing and existing[0]["status"] == "watched" and body.status == "watchlist":
        return _response_row(existing[0], film)
    row = {
        "user_id": current["id"],
        "film_id": film["id"],
        "status": body.status,
        "source": "manual",
        "rating": body.rating,
        "watched_on": body.watched_on.isoformat() if body.watched_on else None,
    }
    res = (
        supabase.table("user_films")
        .upsert(row, on_conflict="user_id,film_id")
        .execute()
    )
    return _response_row(res.data[0], film)


@router.patch("/mine/{user_film_id}")
def update_film(
    user_film_id: str,
    body: UpdateFilmBody,
    current: dict = Depends(get_current_user),
) -> dict:
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "watched_on" in updates:
        updates["watched_on"] = updates["watched_on"].isoformat()
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = (
        supabase.table("user_films")
        .update(updates)
        .eq("id", user_film_id)
        .eq("user_id", current["id"])
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Film not in your library")
    return {"ok": True}


@router.delete("/mine/{user_film_id}")
def remove_film(user_film_id: str, current: dict = Depends(get_current_user)) -> dict:
    res = (
        supabase.table("user_films")
        .delete()
        .eq("id", user_film_id)
        .eq("user_id", current["id"])
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Film not in your library")
    return {"ok": True}
