"""Explicit request parsing for Film Assistant turns (Phase 7).

The recommendation engine describes *taste*; it cannot answer *"only Paul
Thomas Anderson films"*. This module reads the constraint the user actually
stated — a director, a specific title, or a genre — so the candidate pool can
be rebuilt around that request instead of the generic profile.

Parsing is deterministic (no extra LLM round-trip) and every extracted name is
validated against TMDB, which keeps false positives out: a phrase is only
accepted as a person once TMDB resolves it *and* that resolved name really is
present in the user's message.
"""

import re

from . import tmdb

# "only X films", "films by X", "directed by X", "everything X has made" ...
_DIRECTOR_PATTERNS = (
    re.compile(r"only\s+(?P<who>.+?)\s+(?:films?|movies?|stuff|ones)\b", re.IGNORECASE),
    re.compile(
        r"(?:films?|movies?)\s+(?:by|from|directed\s+by)\s+(?P<who>.+)$",
        re.IGNORECASE,
    ),
    re.compile(r"\bdirected\s+by\s+(?P<who>.+)$", re.IGNORECASE),
    re.compile(r"(?:anything|something|everything)\s+by\s+(?P<who>.+)$", re.IGNORECASE),
    re.compile(r"(?P<who>.+?)'s\s+(?:films?|movies?)\b", re.IGNORECASE),
)

# "recommend me X", "something like X", "similar to X"
_TITLE_PATTERNS = (
    re.compile(r"(?:recommend|suggest)(?:\s+me|\s+us)?\s+(?P<what>.+)$", re.IGNORECASE),
    re.compile(r"(?:something|anything)\s+like\s+(?P<what>.+)$", re.IGNORECASE),
    re.compile(r"similar\s+to\s+(?P<what>.+)$", re.IGNORECASE),
)

# Words that lead into a name but are never part of it.
_FILLER = {
    "a", "an", "and", "any", "anything", "be", "everything", "for", "get", "i",
    "just", "like", "me", "more", "movie", "movies", "only", "please", "put",
    "recommend", "recommended", "see", "show", "so", "some", "something",
    "suggest", "that", "the", "to", "us", "want", "wanna", "watch", "with",
    "would", "you",
}

_TRAILING = re.compile(r"[\s.,;:!?]+$")


def _clean_phrase(raw: str) -> str:
    """Trim a captured span down to the bare name/title words."""
    text = _TRAILING.sub("", (raw or "").strip())
    words = text.split()
    while words and words[0].lower().strip(",.;:!?") in _FILLER:
        words.pop(0)
    while words and words[-1].lower().strip(",.;:!?") in _FILLER:
        words.pop()
    return " ".join(words).strip(" ,.;:!?\"'“”")


def _resolve_director(text: str) -> tuple[str, int] | None:
    """First director phrase that TMDB confirms really appears in the text."""
    folded = text.casefold()
    for pattern in _DIRECTOR_PATTERNS:
        for match in pattern.finditer(text):
            phrase = _clean_phrase(match.group("who"))
            if not phrase or len(phrase.split()) > 4:
                continue
            person = tmdb.search_person(phrase)
            if not person or not person.get("id"):
                continue
            name = str(person.get("name") or "")
            if not name or name.casefold() not in folded:
                continue
            return name, int(person["id"])
    return None


def _resolve_title(text: str) -> tuple[str, int | None] | None:
    """A named film, confirmed by TMDB search rather than assumed."""
    for pattern in _TITLE_PATTERNS:
        for match in pattern.finditer(text):
            phrase = _clean_phrase(match.group("what"))
            if not phrase or len(phrase.split()) > 8:
                continue
            try:
                hits = tmdb.search_movies(phrase)
            except Exception:  # noqa: BLE001 - parsing must never break a turn
                continue
            if not hits:
                continue
            first = hits[0]
            title = str(first.get("title") or "")
            # Guard against sentences ("something comforting") being read as
            # titles: the search result must share the leading word.
            if not title or not phrase:
                continue
            if title.split()[0].casefold() != phrase.split()[0].casefold():
                continue
            return title, first.get("id")
    return None


def _resolve_genres(text: str) -> list[str]:
    lowered = text.lower()
    hits = [
        name
        for name in tmdb.GENRE_IDS
        if re.search(rf"\b{re.escape(name.lower())}\b", lowered)
    ]
    return hits[:2]


def parse_constraints(text: str) -> dict:
    """Extract {director, person_id, title, tmdb_id, genres} from a message."""
    message = (text or "").strip()
    empty = {
        "director": None,
        "person_id": None,
        "title": None,
        "tmdb_id": None,
        "genres": [],
    }
    if not message:
        return empty

    constraints = dict(empty)
    director = _resolve_director(message)
    if director:
        constraints["director"], constraints["person_id"] = director
        return constraints

    title = _resolve_title(message)
    if title:
        constraints["title"], constraints["tmdb_id"] = title
        return constraints

    constraints["genres"] = _resolve_genres(message)
    return constraints


def has_constraint(constraints: dict) -> bool:
    return bool(
        constraints.get("person_id")
        or constraints.get("title")
        or constraints.get("genres")
    )


def describe(constraints: dict) -> str:
    """One-line restatement used in the prompt so the model knows the ask."""
    if constraints.get("director"):
        return f'The user asked for films by {constraints["director"]} specifically.'
    if constraints.get("title"):
        return f'The user asked about the film "{constraints["title"]}".'
    genres = constraints.get("genres") or []
    if genres:
        return f"The user asked for {' / '.join(genres)} films specifically."
    return ""
