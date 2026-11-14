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


# TMDB genre ids are stable catalogue constants; name -> id for /discover/movie.
GENRE_IDS = {
    "Action": 28,
    "Adventure": 12,
    "Animation": 16,
    "Comedy": 35,
    "Crime": 80,
    "Documentary": 99,
    "Drama": 18,
    "Family": 10751,
    "Fantasy": 14,
    "History": 36,
    "Horror": 27,
    "Music": 10402,
    "Mystery": 9648,
    "Romance": 10749,
    "Science Fiction": 878,
    "TV Movie": 10770,
    "Thriller": 53,
    "War": 10752,
    "Western": 37,
}
GENRE_NAMES = {genre_id: name for name, genre_id in GENRE_IDS.items()}


def movie_recommendations(tmdb_id: int, page: int = 1) -> list[dict]:
    """TMDB's own recommendations for a film (Phase 6 candidate source)."""
    data = (
        _get(f"/movie/{tmdb_id}/recommendations", {"language": "en-US", "page": page})
        or {}
    )
    return data.get("results", [])


def movie_keywords(tmdb_id: int) -> list[str]:
    """TMDB keywords for a film (used for emotional-theme tags, D36).

    Returns the keyword *names* only; zero OpenAI credits are involved.
    """
    data = _get(f"/movie/{tmdb_id}/keywords", {}) or {}
    return [kw.get("name") for kw in data.get("keywords", []) if kw.get("name")]


def discover_movies(
    genre_ids: list[int] | None = None,
    sort_by: str = "popularity.desc",
    page: int = 1,
    year: int | None = None,
    person_id: int | None = None,
    min_votes: int = 200,
) -> list[dict]:
    """TMDB discovery listing, optionally matching ANY of the given genres.

    `person_id` restricts results to films that person has credit on
    (`with_crew`), which is how a director-scoped request such as "only Paul
    Thomas Anderson films" is served. `min_votes` is relaxed for those
    narrower queries so a single filmography is not filtered away.
    """
    params: dict = {
        "language": "en-US",
        "sort_by": sort_by,
        "include_adult": "false",
        "vote_count.gte": str(min_votes),
        "page": str(max(1, page)),
    }
    if genre_ids:
        params["with_genres"] = "|".join(str(g) for g in genre_ids)
    if year:
        params["primary_release_year"] = str(year)
    if person_id:
        params["with_crew"] = str(person_id)
    data = _get("/discover/movie", params) or {}
    return data.get("results", [])


def search_person(query: str) -> dict | None:
    """Resolve a person (typically a director) to their TMDB record."""
    text = (query or "").strip()
    if not text:
        return None
    data = _get("/search/person", {"query": text, "include_adult": "false"}) or {}
    results = data.get("results") or []
    if not results:
        return None
    folded = text.casefold()
    return next(
        (r for r in results if str(r.get("name") or "").casefold() == folded),
        results[0],
    )


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


def simplify_list_result(r: dict) -> dict:
    """Map a TMDB list result (recommendations/discover) to a candidate dict."""
    return {
        "tmdb_id": r["id"],
        "title": r.get("title") or "Untitled",
        "year": _year_from_release(r.get("release_date")),
        "poster_url": poster_url(r.get("poster_path")),
        "overview": r.get("overview") or "",
        "genres": [
            GENRE_NAMES.get(g) for g in r.get("genre_ids", []) if g in GENRE_NAMES
        ],
        "popularity": float(r.get("popularity") or 0.0),
        "vote_average": float(r.get("vote_average") or 0.0),
        "vote_count": int(r.get("vote_count") or 0),
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
