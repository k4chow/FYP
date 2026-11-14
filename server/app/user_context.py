"""Shared personalisation layer (Part A).

Reflection and discovery both read the same structured understanding of the
user here rather than each assembling their own ad-hoc queries:

- stable tastes / reflective memories (confirmed, relevance-ranked)
- dynamic viewing context (parsed from the *current* request only)
- viewing history (watched vs watchlist, clearly separated)
- recently discussed films and recently served recommendations

Everything is bounded and read-only; the LLM context assembler caps what each
conversation actually passes to the model. Temporary mood is never persisted as
a permanent trait — it lives only in the current request.
"""

import re

from .config import settings
from .supabase_client import supabase

_WORD_RE = re.compile(r"[a-z']+")

_STOPWORDS = {
    "about", "after", "again", "because", "before", "being", "between",
    "could", "every", "feels", "films", "going", "just", "maybe", "might",
    "movie", "movies", "much", "never", "really", "should", "still", "that",
    "their", "there", "these", "thing", "think", "this", "those", "through",
    "watch", "watched", "watching", "where", "which", "while", "with",
    "would", "you're", "you've", "your", "yours",
}

_PAGE = 1000


def _words(text: str) -> set[str]:
    return {
        w
        for w in _WORD_RE.findall((text or "").lower())
        if len(w) >= 3 and w not in _STOPWORDS
    }


def confirmed_memories_rich(user_id: str, limit: int | None = None) -> list[dict]:
    """Confirmed memories with kind/evidence/scope, newest updated first.

    Tolerant of the pre-migration schema: if the personalisation columns do
    not exist yet the query falls back to the core columns and the richer
    fields simply read as ``None`` downstream (``.get`` access everywhere).
    """
    limit = limit or (settings.llm_context_memories * 4)
    query = (
        supabase.table("memories")
        .select("id,content,kind,status,evidence_type,scope,confidence,updated_at")
        .eq("user_id", user_id)
        .eq("status", "confirmed")
        .order("updated_at", desc=True)
        .limit(limit)
    )
    try:
        res = query.execute()
    except Exception:  # noqa: BLE001 - older schema without the new columns
        res = (
            supabase.table("memories")
            .select("id,content,kind,status,updated_at")
            .eq("user_id", user_id)
            .eq("status", "confirmed")
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )
    return res.data or []


def relevant_memories(
    user_id: str, query: str | None, limit: int | None = None
) -> list[dict]:
    """Confirmed memories ranked for the current request.

    Relevance is lexical overlap with the query; explicit preferences are
    preferred over inferred readings, and recency breaks ties (the pool is
    already newest-first and the sort below is stable).
    """
    limit = limit or settings.llm_context_memories
    pool = confirmed_memories_rich(user_id, limit=limit * 4)
    if not pool:
        return []
    query_words = _words(query or "")
    if not query_words:
        return pool[:limit]
    scored: list[tuple[int, int, dict]] = []
    for row in pool:
        content_words = _WORD_RE.findall(str(row.get("content") or "").lower())
        overlap = len(query_words & set(content_words))
        explicit = 1 if row.get("evidence_type") == "explicit" else 0
        scored.append((overlap, explicit, row))
    scored.sort(key=lambda item: (-item[0], -item[1]))
    return [row for _, _, row in scored][:limit]


def viewing_history(user_id: str) -> dict:
    """Watched / watchlist split with ratings, bounded for the prompt."""
    watched: list[dict] = []
    watchlist: list[dict] = []
    offset = 0
    while True:
        page = (
            supabase.table("user_films")
            .select("status,rating,films(tmdb_id,title,year,genres)")
            .eq("user_id", user_id)
            .range(offset, offset + _PAGE - 1)
            .execute()
            .data
            or []
        )
        for row in page:
            film = row.get("films") or {}
            if not film.get("tmdb_id"):
                continue
            entry = {
                "tmdb_id": film["tmdb_id"],
                "title": film.get("title"),
                "year": film.get("year"),
                "genres": film.get("genres") or [],
                "rating": row.get("rating"),
            }
            if row.get("status") == "watchlist":
                watchlist.append(entry)
            else:
                watched.append(entry)
        if len(page) < _PAGE:
            break
        offset += _PAGE
    return {
        "watched": watched[: settings.llm_context_watched],
        "watchlist": watchlist[: settings.llm_context_watchlist],
    }


def discussed_films(user_id: str, limit: int = 20) -> list[dict]:
    """Titles from recent reflections, most recent first (cross-film memory)."""
    try:
        rows = (
            supabase.table("conversations")
            .select("films(title,year,tmdb_id),created_at")
            .eq("user_id", user_id)
            .eq("type", "reflection")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception:  # noqa: BLE001 - non-critical context
        return []
    out: list[dict] = []
    seen: set[int] = set()
    for row in rows:
        film = row.get("films") or {}
        tmdb_id = film.get("tmdb_id")
        if not tmdb_id or tmdb_id in seen:
            continue
        seen.add(tmdb_id)
        out.append(
            {"tmdb_id": tmdb_id, "title": film.get("title"), "year": film.get("year")}
        )
    return out


def recent_recommendations(user_id: str, limit: int = 10) -> list[dict]:
    """Recently served recommendations, for discovery -> reflection linkage."""
    try:
        rows = (
            supabase.table("recommendation_events")
            .select("tmdb_id,title,reason,novelty_category,watched_at,created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception:  # noqa: BLE001 - table may not exist yet (pre-migration)
        return []
    return rows