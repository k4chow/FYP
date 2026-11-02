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

export interface ImportResult {
  total_rows: number
  matched: number
  unmatched: { name: string; year: number | null }[]
}

export const getMyFilms = () =>
  api<{ films: LibraryFilm[] }>('/films/mine', { auth: true })

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
  return api<ImportResult>('/import/letterboxd', {
    method: 'POST',
    auth: true,
    formData,
  })
}

export const formatRuntime = (minutes: number | null | undefined) =>
  minutes ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : null
