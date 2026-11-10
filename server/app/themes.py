"""Emotional-theme vocabulary: short "theme" tags from TMDB keywords (D36).

TMDB's per-film `keywords` are a noisy folksonomy ("based on novel", "voice
over narration", ...). We only surface the keywords that name a recurring
*human* theme, so Home and Profile read as grief / loneliness / memory rather
than catalogue trivia. `THEME_KEYWORDS` is the curated surface; `_ALIASES`
folds common variants onto one canonical tag ("grieving" -> "grief").

The filter is applied to a film's `metadata.keywords` (cached by routers.films
from TMDB /movie/{id}/keywords), so it costs no LLM calls or credits.
"""

# Canonical single-/two-word theme tags, lowercase.
THEME_KEYWORDS = {
    "abandonment", "addiction", "aging", "ambition", "anxiety", "belonging",
    "betrayal", "childhood", "coming of age", "connection", "death",
    "depression", "family", "faith", "fatherhood", "fear", "forgiveness",
    "freedom", "friendship", "grief", "guilt", "hope", "identity",
    "infidelity", "isolation", "jealousy", "justice", "loneliness", "loss",
    "love", "marriage", "memory", "mental illness", "mortality", "motherhood",
    "nostalgia", "obsession", "redemption", "regret", "religion", "revenge",
    "sacrifice", "sadness", "self discovery", "suicide", "survival", "trauma",
    "war",
}

# Variant -> canonical tag, so "grieving" still credits "grief".
_ALIASES = {
    "grieving": "grief",
    "grievance": "grief",
    "mourning": "grief",
    "bereavement": "grief",
    "lonely": "loneliness",
    "lonesome": "loneliness",
    "depressed": "depression",
    "anxious": "anxiety",
    "remembering": "memory",
    "memories": "memory",
    "obsessive": "obsession",
    "redemptive": "redemption",
    "nostalgic": "nostalgia",
    "ambitious": "ambition",
}


def tag_of(keyword: object) -> str | None:
    """Map one raw TMDB keyword to a canonical theme tag, or ``None``."""
    text = " ".join(str(keyword or "").strip().lower().split())
    if not text:
        return None
    if text in THEME_KEYWORDS:
        return text
    alias = _ALIASES.get(text)
    if alias:
        return alias
    # Containment fold: "grief of losing a parent" -> "grief".
    for theme in THEME_KEYWORDS:
        if theme in text or text in theme:
            return theme
    return None


def filter_keywords(keywords) -> list[str]:
    """Return the deduplicated, canonical theme tags present in a keyword list."""
    found: set[str] = set()
    seen: list[str] = []
    for keyword in keywords or []:
        tag = tag_of(keyword)
        if tag and tag not in found:
            found.add(tag)
            seen.append(tag)
    return seen