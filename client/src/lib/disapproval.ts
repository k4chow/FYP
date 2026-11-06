import dataset from './cherie_disapproves.json'

// Cherie's Disapproval™ — a purely cosmetic annotation layer for film
// recommendations. It flags films Cherie has rated poorly (below 2.5 stars),
// exactly 2.5 stars, or exactly 3 stars (except Grand Theft Hamlet), plus the
// listed directed works of Paul Thomas Anderson and Taika Waititi. It NEVER
// affects ranking, scoring, or whether a film is shown.

interface FlaggedFilm {
  title: string
  year: number | null
  letterboxd_rating: number | null
  director: string | null
  format: string
  flag_reasons: string[]
  warning: string
}

interface DisapprovalDataset {
  rules?: { warning_text?: string }
  flagged_films: FlaggedFilm[]
}

export interface DisapprovalMatch {
  warning: string
  reasons: string[]
}

const data = dataset as DisapprovalDataset

const DEFAULT_WARNING = 'Cherie does not like this film.'

// Lowercase and strip punctuation/whitespace so minor title formatting
// differences (apostrophes, colons, dashes, commas, etc.) don't break matching.
function normalizeTitle(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

// Index flagged films by normalized title. A single title can map to several
// entries across different years (remakes, sequels carried under the same
// short name); the year disambiguates those.
const byTitle = new Map<string, FlaggedFilm[]>()
for (const film of data.flagged_films) {
  const key = normalizeTitle(film.title)
  if (!key) continue
  const existing = byTitle.get(key)
  if (existing) existing.push(film)
  else byTitle.set(key, [film])
}

// Returns the disapproval match for a film, or null when nothing applies.
// Matching prefers an exact title + release-year pair; a same-named film from
// a different year is deliberately NOT flagged. When the year is unavailable,
// a title only flags if it is unambiguous (a single flagged entry).
export function getDisapproval(
  title: string,
  year: number | null,
): DisapprovalMatch | null {
  const key = normalizeTitle(title)
  if (!key) return null

  const candidates = byTitle.get(key)
  if (!candidates || candidates.length === 0) return null

  if (year != null) {
    const exact = candidates.find((film) => film.year === year)
    if (!exact) return null
    return { warning: exact.warning || DEFAULT_WARNING, reasons: exact.flag_reasons }
  }

  if (candidates.length === 1) {
    const film = candidates[0]
    return { warning: film.warning || DEFAULT_WARNING, reasons: film.flag_reasons }
  }

  return null
}