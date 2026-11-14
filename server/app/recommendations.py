"""Recommendation engine (Phase 6: F8, F9, F11, N6) — D35.

Deterministic, explainable ranking over the user's library, confirmed
memories, and explicit card feedback. No embeddings and no LLM calls
(D8: pgvector is deferred until plain SQL retrieval proves insufficient),
so results are reproducible and every card can explain itself.

Pipeline:
1. Load signals: library rows (status/rating joined to films), confirmed
   memories, recommendation_feedback rows, and users.recommendation_style.
2. Seeds: "more_like_this" feedback films plus highly rated / watchlisted
   library films; each seed pulls TMDB /movie/{id}/recommendations.
3. Genre pool: /discover/movie restricted to the user's top library genres.
4. Exclusions: anything already in the library and every "not_for_me"
   film is removed from the candidate set (F11).
5. Scoring: seed similarity from rated/watchlisted/feedback films, confirmed-
   memory keyword affinity (F8), a popularity term weighted by the style
   slider (0 = niche, 100 = mainstream, N6), and a TMDB quality prior.
6. Explanations: every card carries a human-readable `why` plus the
   `source_memories` that influenced it, for "Why am I seeing this?" (F9).
"""

import random
import re
import time
from collections import Counter

from . import tmdb
from .memories import list_for_user
from .supabase_client import supabase

# --- Tunable constants (D35) ------------------------------------------------
_SEED_LIMIT = 6  # seeds that each pull a TMDB recommendations page
_SEED_REC_LIMIT = 8  # candidates taken per seed, rank-weighted
_SEED_REFRESH_EXTRA = 8  # extra seed recs pulled on refresh for fresh material
_DISCOVER_LIMIT = 20  # raw discover rows considered per genre-pool page
# Two deterministic pool pages by default (popularity + best-rated); a refresh
# run adds a random year/page on top so it can surface different candidates.
_DISCOVER_VOTE_SORT = "vote_average.desc"
_QUALITY_WEIGHT = 0.5  # TMDB rating prior, confidence-scaled by vote_count
_REFRESH_POOL_FACTOR = 6  # refresh samples from a wide window: factor x limit
_FEEDBACK_SEED_WEIGHT = 1.2  # explicit "more like this" beats implicit seeds
_RATING_SEED_DIVISOR = 5.0  # a 5-star film seeds at weight 1.0
_WATCHLIST_SEED_WEIGHT = 0.6
_WATCHED_SEED_WEIGHT = 0.25  # watched but unrated
_MEMORY_KEYWORD_BONUS = 0.45  # per matched confirmed memory
_MEMORY_BONUS_CAP = 1.35  # at most three memories influence one card
_SEED_SIMILARITY_FACTOR = 1.2  # seed "more like what I love" weighting (fixed)
_POPULARITY_WEIGHT = 0.6  # full popularity swing at the slider extremes
_MAINSTREAM_VOTES = 20000.0  # vote_count at which a film counts as mainstream
_DISCOVER_BASE = 0.5  # genre-pool candidates start here
_TOP_GENRES = 3
_DEFAULT_STYLE = 30  # 0 = niche, 100 = mainstream (users.recommendation_style)
_CACHE_TTL_SECONDS = 300

_WORD_RE = re.compile(r"[a-z']+")

# Words that should never count as memory keyword evidence.
_STOPWORDS = {
    "about", "after", "again", "because", "before", "being", "between",
    "could", "every", "feels", "films", "going", "maybe", "might",
    "movie", "movies", "never", "really", "should", "still", "that",
    "their", "there", "these", "thing", "think", "this", "those",
    "through", "watch", "watched", "watching", "where", "which", "while",
    "would", "you're", "you've", "your", "yours",
}

# Aliases so a memory saying "sci-fi" still matches Science Fiction films.
_GENRE_ALIASES = {"sci-fi": "Science Fiction", "scifi": "Science Fiction"}

# Per-user result cache so repeated Discover loads do not hammer TMDB;
# feedback or style changes invalidate it explicitly.
_cache: dict[str, tuple[float, list[dict]]] = {}
# Films shown in the user's most recent run. A refresh excludes them so the
# grid genuinely changes instead of reordering the same picks.
_last_served: dict[str, set[int]] = {}


def invalidate(user_id: str) -> None:
    _cache.pop(user_id, None)


# --- Signal loading ----------------------------------------------------------


def _library_rows(user_id: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    page_size = 1000
    while True:
        page = (
            supabase.table("user_films")
            .select("status, rating, films(tmdb_id, title, year, genres)")
            .eq("user_id", user_id)
            .range(offset, offset + page_size - 1)
            .execute()
            .data
            or []
        )
        rows.extend(row for row in page if row.get("films"))
        if len(page) < page_size:
            return rows
        offset += page_size


def _feedback_rows(user_id: str) -> list[dict]:
    return (
        supabase.table("recommendation_feedback")
        .select("tmdb_id, title, signal")
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )


def _style(user_id: str) -> int:
    row = (
        supabase.table("users")
        .select("recommendation_style")
        .eq("id", user_id)
        .limit(1)
        .execute()
        .data
        or [{}]
    )[0]
    value = row.get("recommendation_style")
    return value if isinstance(value, int) else _DEFAULT_STYLE


def _keywords(text: str) -> set[str]:
    """Content words (len >= 5) that can act as evidence for a match."""
    return {
        word
        for word in _WORD_RE.findall(text.lower())
        if len(word) >= 5 and word not in _STOPWORDS
    }


def _memory_genres(content: str) -> set[str]:
    """Genre names explicitly named in a memory (incl. the sci-fi alias)."""
    lowered = content.lower()
    hits = {genre for alias, genre in _GENRE_ALIASES.items() if alias in lowered}
    hits.update(name for name in tmdb.GENRE_IDS if name.lower() in lowered)
    return hits


# --- Scoring -----------------------------------------------------------------


def _seed_weight(row: dict) -> float:
    """How strongly a library row should steer recommendations."""
    rating = row.get("rating")
    if isinstance(rating, (int, float)) and rating >= 4:
        return float(rating) / _RATING_SEED_DIVISOR
    if row.get("status") == "watchlist":
        return _WATCHLIST_SEED_WEIGHT
    if row.get("status") == "watched":
        return _WATCHED_SEED_WEIGHT
    return 0.0


def _build_seeds(library: list[dict], more_like_this: list[dict]) -> list[dict]:
    """Ordered seed list: explicit feedback first, then strongest library rows."""
    seeds = [
        {
            "tmdb_id": row["tmdb_id"],
            "title": row.get("title") or "that film",
            "weight": _FEEDBACK_SEED_WEIGHT,
            "reason": "feedback",
            "rating": None,
        }
        for row in more_like_this
    ]
    library_seeds = sorted(
        (
            {
                "tmdb_id": row["films"]["tmdb_id"],
                "title": row["films"]["title"],
                "weight": _seed_weight(row),
                "reason": "watchlist" if row.get("status") == "watchlist" else "rated",
                "rating": row.get("rating"),
            }
            for row in library
            if row["films"].get("tmdb_id") and _seed_weight(row) > 0
        ),
        key=lambda seed: (-seed["weight"], seed["tmdb_id"]),
    )
    seen = {seed["tmdb_id"] for seed in seeds}
    seeds.extend(seed for seed in library_seeds if seed["tmdb_id"] not in seen)
    return seeds[:_SEED_LIMIT]


def _why(
    best_seed: dict | None,
    matched_memories: list[dict],
    top_genres: list[str],
) -> str:
    """Human-readable explanation citing the strongest signals (F9)."""
    parts: list[str] = []
    if best_seed and best_seed["reason"] == "feedback":
        parts.append(f'Because you asked for more like "{best_seed["title"]}"')
    elif best_seed and best_seed["reason"] == "rated" and best_seed.get("rating"):
        parts.append(f'Because you rated "{best_seed["title"]}" {best_seed["rating"]:g}★')
    elif best_seed and best_seed["reason"] == "watchlist":
        parts.append(f'Because "{best_seed["title"]}" is on your watchlist')
    elif top_genres:
        parts.append(f"Because {top_genres[0]} films lead your library")
    if matched_memories:
        parts.append(f'it connects with your insight "{matched_memories[0]["content"]}"')
    if not parts:
        return "Popular on TMDB right now — a starting point while your profile grows."
    return " — and ".join(parts) + "."


def _diverse(cards: list[dict], limit: int, cap: int = 2) -> list[dict]:
    """Final grid selection with a genre spread: at most `cap` cards per
    primary genre while candidates last, then backfill from the rest."""
    chosen: list[dict] = []
    genre_counts: Counter[str] = Counter()
    skipped: list[dict] = []
    for card in cards:
        if len(chosen) >= limit:
            break
        primary = (card.get("genres") or [""])[0]
        if genre_counts[primary] < cap:
            chosen.append(card)
            genre_counts[primary] += 1
        else:
            skipped.append(card)
    while len(chosen) < limit and skipped:
        chosen.append(skipped.pop(0))
    return chosen


def get_recommendations(
    user_id: str,
    limit: int = 12,
    refresh: bool = False,
    *,
    genres: list[str] | None = None,
    person_id: int | None = None,
    exclude_ids: set[int] | None = None,
    track_served: bool = True,
) -> list[dict]:
    """Ranked, explained recommendation cards for the Discover grid.

    `refresh=True` skips the cache and, when the pool is large enough, samples
    a varied subset from the top slice instead of always showing the same
    highest-scored cards — so an explicit refresh shows new films rather than
    the same list reordered.

    `genres` / `person_id` (Phase 7) serve an *explicitly stated* constraint
    instead of the taste profile — the Film Assistant passes them when the user
    asks for something like "only Paul Thomas Anderson films". Constrained runs
    bypass the cache and never record `_last_served`, so chatting cannot change
    what Discover shows. `track_served=False` lets the Assistant use the normal
    profile pool without disturbing Discover's refresh state either.

    `exclude_ids` drops specific tmdb_ids (the Assistant's already-shown films)
    from the candidate set; pass `refresh=True` alongside it so the pool widens
    enough to replace them with fresh picks.
    """
    constrained = bool(genres or person_id)
    cached = _cache.get(user_id)
    if not constrained and not refresh and cached and cached[0] > time.monotonic():
        return cached[1][:limit]

    library = _library_rows(user_id)
    feedback = _feedback_rows(user_id)
    memories = list_for_user(user_id, "confirmed")
    style = _style(user_id)

    library_ids = {
        row["films"]["tmdb_id"] for row in library if row["films"].get("tmdb_id")
    }
    not_for_me = {row["tmdb_id"] for row in feedback if row["signal"] == "not_for_me"}
    more_like_this = [row for row in feedback if row["signal"] == "more_like_this"]
    excluded = library_ids | not_for_me
    if exclude_ids:
        # Films already shown this session (the Film Assistant rotates its
        # side panel) are treated like library films: never repeated.
        excluded |= {i for i in exclude_ids if isinstance(i, int)}
    if refresh:
        # A refresh must surface films the user has not just seen.
        excluded |= _last_served.get(user_id, set())

    genre_counts: Counter[str] = Counter()
    for row in library:
        genre_counts.update(row["films"].get("genres") or [])
    top_genres = [genre for genre, _ in genre_counts.most_common(_TOP_GENRES)]

    seeds = _build_seeds(library, more_like_this)

    # candidate tmdb_id -> accumulating record
    candidates: dict[int, dict] = {}

    def candidate_for(raw: dict) -> dict:
        info = tmdb.simplify_list_result(raw)
        return candidates.setdefault(
            info["tmdb_id"],
            {
                **info,
                "score": 0.0,
                "seed_score": 0.0,
                "best_seed": None,
                "matched_memories": {},
            },
        )

    # 1) Seed-driven candidates: TMDB's own recommendations per seed film.
    for seed in seeds:
        take = _SEED_REC_LIMIT + (_SEED_REFRESH_EXTRA if refresh else 0)
        recs = tmdb.movie_recommendations(seed["tmdb_id"])[:take]
        for rank, raw in enumerate(recs):
            if raw.get("id") in excluded:
                continue
            cand = candidate_for(raw)
            contribution = seed["weight"] / (1 + rank)
            cand["seed_score"] += contribution
            if cand["best_seed"] is None or contribution > cand["best_seed"][1]:
                cand["best_seed"] = (seed, contribution)
        if refresh:
            # A second page of this seed's recommendations adds genuinely new
            # films; the first page is stable, so a refresh would re-see it.
            for rank, raw in enumerate(
                tmdb.movie_recommendations(seed["tmdb_id"], page=2)[:_SEED_REFRESH_EXTRA]
            ):
                if raw.get("id") in excluded:
                    continue
                cand = candidate_for(raw)
                contribution = seed["weight"] / (4 + rank)
                cand["seed_score"] += contribution
                if cand["best_seed"] is None or contribution > cand["best_seed"][1]:
                    cand["best_seed"] = (seed, contribution)

    # 2) Genre pool: two deterministic discover pages (popularity + TMDB
    #    best-rated) within the user's top genres, or plain popular when the
    #    library is empty (the cold-start path). Refresh runs add a random
    #    year/page so they can surface candidates the default pages never show.
    if constrained:
        # A stated constraint outranks the taste profile: build the pool from
        # the requested director/genres so the assistant can actually answer,
        # then rank those films with the same scoring as any other pool.
        genre_ids = [tmdb.GENRE_IDS[g] for g in (genres or []) if g in tmdb.GENRE_IDS]
        pool_pages = [
            tmdb.discover_movies(genre_ids or None, person_id=person_id, min_votes=40),
            tmdb.discover_movies(
                genre_ids or None,
                sort_by=_DISCOVER_VOTE_SORT,
                person_id=person_id,
                min_votes=40,
            ),
            tmdb.discover_movies(
                genre_ids or None,
                sort_by="vote_count.desc",
                page=2,
                person_id=person_id,
                min_votes=40,
            ),
        ]
    else:
        genre_ids = [tmdb.GENRE_IDS[g] for g in top_genres if g in tmdb.GENRE_IDS]
        pool_pages = [
            tmdb.discover_movies(genre_ids or None),
            tmdb.discover_movies(genre_ids or None, sort_by=_DISCOVER_VOTE_SORT),
        ]
        if refresh:
            # A refresh broadens the pool with randomised discover pages (varied
            # sort, page and year) — including genre-blind ones — so the next
            # grid genuinely changes instead of reshuffling the same candidates.
            for sort_by in (
                "popularity.desc",
                _DISCOVER_VOTE_SORT,
                "vote_count.desc",
                "revenue.desc",
                "popularity.desc",
            ):
                pool_pages.append(
                    tmdb.discover_movies(
                        genre_ids or None,
                        sort_by=sort_by,
                        page=random.randint(1, 8),
                        year=random.randint(1960, 2025),
                    )
                )
            # Genre-blind pages surface films far outside the usual profile,
            # which is where genuinely "fresh" picks come from.
            pool_pages.append(
                tmdb.discover_movies(
                    None, sort_by="popularity.desc", page=random.randint(2, 10)
                )
            )
            pool_pages.append(
                tmdb.discover_movies(
                    None, sort_by=_DISCOVER_VOTE_SORT, page=random.randint(1, 6)
                )
            )
    for page_index, raw_rows in enumerate(pool_pages):
        page_weight = 1.0 if page_index == 0 else 0.7
        for raw in raw_rows[:_DISCOVER_LIMIT]:
            if raw.get("id") in excluded:
                continue
            candidate_for(raw)["score"] += _DISCOVER_BASE * page_weight

    memory_rows = [
        {
            "id": m["id"],
            "content": m["content"],
            "keywords": _keywords(m["content"]),
            "genres": _memory_genres(m["content"]),
        }
        for m in memories
    ]

    for cand in candidates.values():
        text = f"{cand['title']} {cand['overview']}".lower()
        cand_genres = set(cand["genres"])
        for memory in memory_rows:
            if memory["genres"] & cand_genres or any(
                kw in text for kw in memory["keywords"]
            ):
                cand["matched_memories"][memory["id"]] = memory

        quality_bonus = (
            (cand.get("vote_average", 0.0) / 10.0)
            * _QUALITY_WEIGHT
            * min(1.0, cand.get("vote_count", 0) / 2000.0)
        )
        memory_bonus = min(
            len(cand["matched_memories"]) * _MEMORY_KEYWORD_BONUS,
            _MEMORY_BONUS_CAP,
        )
        popularity_bonus = (
            _POPULARITY_WEIGHT
            * ((style / 100.0) * 2.0 - 1.0)
            * min(1.0, cand.get("vote_count", 0) / _MAINSTREAM_VOTES)
        )
        best = cand["best_seed"][0] if cand["best_seed"] else None
        cand["score"] += (
            cand["seed_score"] * _SEED_SIMILARITY_FACTOR
            + memory_bonus
            + popularity_bonus
            + quality_bonus
        )
        matched = sorted(cand["matched_memories"].values(), key=lambda m: m["id"])
        cand["why"] = _why(best, matched, top_genres)
        cand["source_memories"] = [
            {"id": m["id"], "content": m["content"]} for m in matched
        ]

    ranked = sorted(
        candidates.values(),
        key=lambda c: (-c["score"], -c["popularity"], c["tmdb_id"]),
    )
    if refresh and len(ranked) > limit:
        # Re-roll the grid so a refresh visibly changes it: keep just the top
        # couple of quality picks, then sample the rest from a wide window (the
        # deeper seed recs + broader randomised discover pages feed genuinely
        # fresh material into that window).
        keep = ranked[:2]
        window = ranked[2 : max(limit * _REFRESH_POOL_FACTOR, len(ranked))]
        chosen = keep + random.sample(window, k=min(limit - len(keep), len(window)))
        ranked = sorted(chosen, key=lambda c: -c["score"])
    cards = [
        {
            "tmdb_id": c["tmdb_id"],
            "title": c["title"],
            "year": c["year"],
            "genres": c["genres"],
            "poster_url": c["poster_url"],
            "overview": c["overview"],
            "vote_average": round(c.get("vote_average", 0.0), 1),
            "score": round(c["score"], 3),
            "why": c["why"],
            "source_memories": c["source_memories"],
        }
        for c in ranked
    ]
    if not constrained:
        _cache[user_id] = (time.monotonic() + _CACHE_TTL_SECONDS, cards)
    # A constrained pool is already narrow; the per-genre diversity cap would
    # silently drop half of a director's filmography.
    served = cards[:limit] if constrained else _diverse(cards, limit)
    if track_served and not constrained:
        _last_served[user_id] = {card["tmdb_id"] for card in served}
    return served

