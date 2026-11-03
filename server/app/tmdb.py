"""TMDB API client (F7).

All TMDB access is server-side so the API key never reaches the client;
the `films` table acts as our local cache of catalogue metadata.
"""

import random
import time

import httpx
from fastapi import HTTPException

from .config import settings

BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p"


def poster_url(path: str | None, size: str = "w342") -> str | None:
    return f"{IMAGE_BASE}/{size}{path}" if path else None


MAX_ATTEMPTS = 4


def _backoff(attempt: int) -> float:
    """Bounded exponential backoff with jitter (attempt is zero-based)."""
    return min(8.0, float(2**attempt)) + random.uniform(0, 0.5)


def _get(path: str, params: dict) -> dict | None:
    if not settings.tmdb_api_key:
        raise HTTPException(status_code=500, detail="TMDB API key not configured")
    params = {**params, "api_key": settings.tmdb_api_key}
    for attempt in range(MAX_ATTEMPTS):
        try:
            res = httpx.get(f"{BASE}{path}", params=params, timeout=15)
        except httpx.HTTPError as exc:
            if attempt == MAX_ATTEMPTS - 1:
                raise HTTPException(
                    status_code=502, detail=f"TMDB request failed: {exc}"
                )
            time.sleep(_backoff(attempt))
            continue
        if res.status_code == 404:
            return None
        # Rate limits and upstream failures are transient: back off, but never
        # loop indefinitely. Other HTTP errors (401/403/422) are not retried.
        if res.status_code == 429 or res.status_code >= 500:
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(_backoff(attempt))
                continue
            detail = (
                "TMDB rate limited after retries"
                if res.status_code == 429
                else f"TMDB error {res.status_code} after retries"
            )
            raise HTTPException(status_code=502, detail=detail)
        if res.status_code != 200:
            raise HTTPException(status_code=502, detail=f"TMDB error {res.status_code}")
        return res.json()
    raise HTTPException(status_code=502, detail="TMDB request failed after retries")


def search_movies(query: str, year: int | None = None) -> list[dict]:
    params: dict = {"query": query, "include_adult": "false"}
    if year:
        params["year"] = str(year)
    data = _get("/search/movie", params) or {}
    return data.get("results", [])


def movie_details(tmdb_id: int) -> dict | None:
    return _get(f"/movie/{tmdb_id}", {})


def _year_from_release(release: str | None) -> int | None:
    release = release or ""
    return int(release[:4]) if release[:4].isdigit() else None


def simplify_search_result(r: dict) -> dict:
    return {
        "tmdb_id": r["id"],
        "title": r.get("title"),
        "year": _year_from_release(r.get("release_date")),
        "poster_url": poster_url(r.get("poster_path")),
        "overview": r.get("overview") or "",
    }


def film_row_from_details(d: dict) -> dict:
    """Map a TMDB movie-details payload to a `films` table row."""
    return {
        "tmdb_id": d["id"],
        "title": d.get("title") or "Untitled",
        "year": _year_from_release(d.get("release_date")),
        "genres": [g["name"] for g in d.get("genres", [])],
        "poster_path": d.get("poster_path"),
        "metadata": {
            "overview": d.get("overview") or "",
            "runtime": d.get("runtime"),
            "vote_average": d.get("vote_average"),
            "original_language": d.get("original_language"),
        },
    }
