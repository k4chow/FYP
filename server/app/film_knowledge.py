"""Film knowledge retrieval for reflection and discovery (Part B).

Two jobs, both deterministic and cached so a conversation never re-hits TMDB
for something it already knows:

1. ``film_context()`` builds a compact, truthful film dossier (title, year,
   director, leading cast, genres, curated themes, synopsis, runtime) from a
   cached ``films`` row. Everything is grounded in TMDB data we have already
   stored; nothing is invented.

2. ``resolve_film_mentions()`` recognises when a message references *another*
   film and resolves each mention to a TMDB id. Detection is deterministic
   (quoted titles, "like / similar to / reminded me of" lead-ins, and titles
   already in the local catalogue) — no extra LLM round-trip. Resolutions are
   cached so the same film is looked up at most once per process.

``enrich_metadata()`` backfills director / cast / keywords onto a film's
metadata dict using TMDB; the caller (routers.films._ensure_film) owns the
database write so the catalogue's single cache path stays in one place.
"""

import re
import threading
import time

from . import themes as theme_svc
from . import tmdb
from .supabase_client import supabase

# How long a mention resolution / catalogue snapshot is kept.
_CACHE_TTL_SECONDS = 900.0
_cache: dict[str, tuple[float, dict]] = {}
_titles_snapshot: tuple[float, list[str]] = (0.0, [])
_lock = threading.Lock()

_QUOTED = re.compile(r"[“\"'‘]([^“”\"'‘’]{2,60})[”\"'’]")
_LEAD_IN = re.compile(
    r"\b(?:like|similar\s+to|reminded\s+me\b[^.!?]{0,20}?\bof|"
    r"reminds\s+me\b[^.!?]{0,20}?\bof|in\s+the\s+style\s+of|"
    r"compared\s+to|versus|vs\.?)\s+"
    r"([A-Z0-9][A-Za-z0-9'.&+:!?\- ]{1,60})",
    re.IGNORECASE,
)

_FILLER = {
    "a", "an", "and", "anything", "for", "in", "is", "it", "its", "me",
    "more", "my", "of", "on", "or", "the", "that", "this", "to", "too",
    "very", "was", "we", "with", "you", "your",
}


def _clean_span(raw: str) -> str:
    text = re.sub(r"[\s.,;:!?()]+$", "", (raw or "").strip())
    words = [w for w in text.split() if w.lower() not in _FILLER]
    return " ".join(words).strip(" ,.;:!?()") if words else ""


def _cache_get(key: str) -> dict | None:
    with _lock:
        entry = _cache.get(key)
        if entry and entry[0] > time.monotonic():
            return entry[1]
        if entry:
            _cache.pop(key, None)
    return None


def _cache_put(key: str, value: dict) -> None:
    with _lock:
        _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, value)


def enrich_metadata(tmdb_id: int, meta: dict | None) -> dict:
    """Backfill keywords / director / cast onto a metadata dict (best effort).

    TMDB is only asked for the pieces that are missing, and failures degrade to
    the input metadata — enrichment must never break a reflection turn.
    """
    meta = dict(meta or {})
    if not meta.get("keywords"):
        try:
            keywords = tmdb.movie_keywords(tmdb_id)
        except Exception:  # noqa: BLE001
            keywords = None
        if keywords:
            meta["keywords"] = keywords
    if not meta.get("director") or not meta.get("cast"):
        try:
            credits = tmdb.movie_credits(tmdb_id)
        except Exception:  # noqa: BLE001
            credits = None
        if credits:
            if not meta.get("director"):
                meta["director"] = credits.get("director")
            if not meta.get("cast"):
                meta["cast"] = credits.get("cast") or []
    return meta


def film_context(film: dict | None) -> dict | None:
    """Compact dossier from a cached films row (never a network call)."""
    if not film:
        return None
    meta = film.get("metadata") or {}
    keywords = meta.get("keywords") or []
    director = meta.get("director")
    cast = meta.get("cast") or []
    return {
        "tmdb_id": film.get("tmdb_id"),
        "title": film.get("title"),
        "year": film.get("year"),
        "genres": film.get("genres") or [],
        "director": director if isinstance(director, str) and director else None,
        "cast": [str(c) for c in cast][:6],
        "synopsis": (meta.get("overview") or "")[:500],
        "runtime": meta.get("runtime"),
        "themes": theme_svc.filter_keywords(keywords),
    }


def themes_from_overview(text: str) -> list[str]:
    """Deterministic theme tags from free text (network-free fallback).

    Used when a candidate has no cached keywords yet; matches only the curated
    theme vocabulary, so it never invents tags the film does not carry.
    """
    if not text:
        return []
    tokens = re.findall(r"[a-z']+", (text or "").casefold())
    grams: list[str] = list(tokens)
    for n in (2, 3):
        grams += [" ".join(tokens[i : i + n]) for i in range(max(0, len(tokens) - n + 1))]
    return theme_svc.filter_keywords(grams)


def _catalogue_titles() -> list[str]:
    with _lock:
        until, titles = _titles_snapshot
        if until > time.monotonic():
            return titles
    try:
        rows = supabase.table("films").select("title").limit(500).execute().data or []
    except Exception:  # noqa: BLE001 - mentions still resolve via search
        return []
    titles = [str(r.get("title") or "") for r in rows if r.get("title")]
    with _lock:
        _titles_snapshot = (time.monotonic() + _CACHE_TTL_SECONDS, titles)
    return titles


def _resolve_title(span: str) -> dict | None:
    key = span.casefold()
    cached = _cache_get(key)
    if cached:
        return cached
    try:
        hits = tmdb.search_movies(span)
    except Exception:  # noqa: BLE001 - a lookup failure must not break reflection
        return None
    if not hits:
        return None
    first = hits[0]
    title = str(first.get("title") or "")
    # Same guard as constraints.py: the result must share the span's leading
    # word, so a whole sentence is never mistaken for a film title.
    if not title or not span.split() or title.split()[0].casefold() != span.split()[0].casefold():
        return None
    year = None
    release = str(first.get("release_date") or "")
    if release[:4].isdigit():
        year = int(release[:4])
    film = {
        "tmdb_id": first.get("id"),
        "title": title,
        "year": year,
        "genres": [],  # filled by the caller once the film row is cached
    }
    _cache_put(key, film)
    return film


def resolve_film_mentions(message: str, limit: int = 3) -> list[dict]:
    """Return compact dicts for *other* films mentioned in a message.

    Spans come from quotes, "like / similar to / reminded me of" lead-ins and
    titles already in the local catalogue. A phrase only becomes a film once
    TMDB agrees; anything ambiguous is skipped and the caller may ask the user
    to clarify. Nothing here is an LLM call.
    """
    text = message or ""
    if not text.strip():
        return []

    spans: list[str] = []
    for match in _QUOTED.finditer(text):
        spans.append(_clean_span(match.group(1)))
    for match in _LEAD_IN.finditer(text):
        spans.append(_clean_span(match.group(1)))
    for title in _catalogue_titles():
        if title.casefold() in text.casefold():
            spans.append(title)

    resolved: list[dict] = []
    seen: set[str] = set()
    for span in spans:
        if len(resolved) >= limit:
            break
        if not span or len(span.split()) > 8:
            continue
        key = span.casefold()
        if key in seen:
            continue
        seen.add(key)
        film = _resolve_title(span)
        if film:
            resolved.append(film)
    return resolved