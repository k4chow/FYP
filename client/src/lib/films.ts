import { api } from './api'

export interface LibraryFilm {
  id: string
  film_id: string
  tmdb_id: number | null
  title: string
  year: number | null
  genres: string[]
  runtime: number | null
  status: 'watched' | 'watchlist'
  source: 'manual' | 'letterboxd'
  rating: number | null
  watched_on: string | null
  added_at: string
  poster_url: string | null
}

export interface SearchResult {
  tmdb_id: number
  title: string
  year: number | null
  poster_url: string | null
  overview: string
}

export interface FilmDetail extends SearchResult {
  genres: string[]
  runtime: number | null
  in_library: { id: string; status: string; rating: number | null } | null
}

export interface LibraryCounts {
  all: number
  watched: number
  watchlist: number
}

export interface LibraryPage {
  films: LibraryFilm[]
  total: number
  limit: number
  offset: number
  counts: LibraryCounts
}

export interface ImportIssue {
  row: number
  name: string
  year: number | null
  error?: string
}

export interface ImportJob {
  id: string
  source_filename: string | null
  target_status: 'watched' | 'watchlist'
  status: 'queued' | 'processing' | 'completed' | 'completed_with_errors' | 'failed'
  total_rows: number
  processed_rows: number
  added: number
  updated: number
  duplicates: number
  unmatched_count: number
  failed: number
  next_row: number
  error: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
  unmatched: ImportIssue[]
  failures: ImportIssue[]
}

export interface ImportStart {
  import_id: string
  status: ImportJob['status']
  total_rows: number
}

export const getMyFilmsPage = (
  status?: 'watched' | 'watchlist',
  limit = 250,
  offset = 0,
) => {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (status) params.set('status', status)
  return api<LibraryPage>(`/films/mine?${params.toString()}`, { auth: true })
}

// Fetch every page so client-side filters/sorts operate on the full library,
// not just Supabase's first 1,000 rows. `counts` come from the server (exact
// per-status totals), not from the loaded pages.
// Pages are deduped by row id: while a Letterboxd import is running, new rows
// prepend to the added_at-desc ordering and shift later page windows, which
// would otherwise render the same film card several times.
export const getMyFilms = async (status?: 'watched' | 'watchlist') => {
  const films: LibraryFilm[] = []
  const seen = new Set<string>()
  let offset = 0
  let total = 0
  let counts: LibraryCounts | null = null
  do {
    const page = await getMyFilmsPage(status, 250, offset)
    for (const film of page.films) {
      if (!seen.has(film.id)) {
        seen.add(film.id)
        films.push(film)
      }
    }
    total = page.total
    counts = page.counts ?? counts
    offset += page.films.length
    if (page.films.length === 0) break
  } while (offset < total)
  return { films, counts }
}

export const searchFilms = (q: string) =>
  api<{ results: SearchResult[] }>(`/films/search?q=${encodeURIComponent(q)}`, {
    auth: true,
  })

export const getFilmDetail = (tmdbId: number) =>
  api<FilmDetail>(`/films/tmdb/${tmdbId}`, { auth: true })

export const addFilm = (tmdb_id: number, status: 'watched' | 'watchlist') =>
  api<LibraryFilm>('/films/mine', {
    method: 'POST',
    auth: true,
    body: { tmdb_id, status },
  })

export const removeFilm = (id: string) =>
  api<{ ok: boolean }>(`/films/mine/${id}`, { method: 'DELETE', auth: true })

export const importLetterboxd = (file: File) => {
  const formData = new FormData()
  formData.append('file', file)
  return api<ImportStart>('/import/letterboxd', {
    method: 'POST',
    auth: true,
    formData,
  })
}

export const getImportJob = (id: string) =>
  api<ImportJob>(`/import/${id}`, { auth: true })

export const resumeImportJob = (id: string) =>
  api<ImportJob>(`/import/${id}/resume`, { method: 'POST', auth: true })

export const formatRuntime = (minutes: number | null | undefined) =>
  minutes ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : null
