import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError } from '../lib/api'
import { createConversation } from '../lib/conversations'
import { formatRuntime, getFilmDetail, getMyFilms, searchFilms } from '../lib/films'
import type { LibraryFilm, SearchResult } from '../lib/films'

// The film chosen to reflect on — from the library or straight from TMDB.
interface Picked {
  film_id: string | null
  tmdb_id: number | null
  title: string
  year: number | null
  genres: string[]
  runtime: number | null
  poster_url: string | null
  library_status: 'watched' | 'watchlist' | null
}

// Mockup browse genres -> TMDB genre names.
const GENRE_CHIPS: { label: string; match: string[] }[] = [
  { label: 'All', match: [] },
  { label: 'Sci-Fi', match: ['Science Fiction'] },
  { label: 'Drama', match: ['Drama'] },
  { label: 'Fantasy', match: ['Fantasy'] },
  { label: 'Thriller', match: ['Thriller'] },
  { label: 'Animation', match: ['Animation'] },
  { label: 'Comedy', match: ['Comedy'] },
  { label: 'Horror', match: ['Horror'] },
  { label: 'Action', match: ['Action'] },
]

const fromLibrary = (f: LibraryFilm): Picked => ({
  film_id: f.film_id,
  tmdb_id: f.tmdb_id,
  title: f.title,
  year: f.year,
  genres: f.genres,
  runtime: f.runtime,
  poster_url: f.poster_url,
  library_status: f.status,
})

// Start-a-reflection flow (F1): pick a film (search or browse the library),
// say whether you've seen it or are planning to, then start the conversation.
// Deep links: ?tmdb=<id> (from Add a film) and ?prompt=<text> (Home prompt).
export default function ReflectionNew() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const prompt = params.get('prompt')?.trim() ?? ''
  const preselectTmdb = Number(params.get('tmdb') ?? '') || null

  const [library, setLibrary] = useState<LibraryFilm[]>([])
  const [loadingLibrary, setLoadingLibrary] = useState(true)
  const [genre, setGenre] = useState('All')
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [picked, setPicked] = useState<Picked | null>(null)
  const [watchType, setWatchType] = useState<'seen' | 'planning'>('seen')
  // Mockup's "First time watching"/"Rewatch" — UI framing only, both are 'seen'.
  const [seenFlavor, setSeenFlavor] = useState<'first' | 'rewatch'>('first')
  const [loadingPick, setLoadingPick] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    getMyFilms()
      .then((res) => setLibrary(res.films))
      .catch(() => setLibrary([]))
      .finally(() => setLoadingLibrary(false))
  }, [])

  // Debounced TMDB search (same pattern as Add a film).
  useEffect(() => {
    const q = query.trim()
    if (q.length < 2) {
      setResults([])
      setSearching(false)
      return
    }
    setSearching(true)
    const timer = setTimeout(() => {
      searchFilms(q)
        .then((res) => setResults(res.results))
        .catch(() => setResults([]))
        .finally(() => setSearching(false))
    }, 350)
    return () => clearTimeout(timer)
  }, [query])

  function choose(p: Picked) {
    setPicked(p)
    setWatchType(p.library_status === 'watchlist' ? 'planning' : 'seen')
    setSeenFlavor('first')
  }

  async function pickFromSearch(tmdbId: number) {
    setLoadingPick(true)
    setError('')
    try {
      const d = await getFilmDetail(tmdbId)
      choose({
        film_id: null,
        tmdb_id: d.tmdb_id,
        title: d.title,
        year: d.year,
        genres: d.genres,
        runtime: d.runtime,
        poster_url: d.poster_url,
        library_status:
          (d.in_library?.status as 'watched' | 'watchlist' | undefined) ?? null,
      })
    } catch {
      setError('Could not load film details.')
    } finally {
      setLoadingPick(false)
    }
  }

  // Deep link from Add a film: /app/reflections/new?tmdb=<id>.
  useEffect(() => {
    if (preselectTmdb) pickFromSearch(preselectTmdb)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preselectTmdb])

  const genreMatch = (f: LibraryFilm) => {
    const chip = GENRE_CHIPS.find((c) => c.label === genre)
    return !chip || chip.match.length === 0 || chip.match.some((m) => f.genres.includes(m))
  }
  const recentWatched = library
    .filter((f) => f.status === 'watched' && genreMatch(f))
    .slice(0, 6)
  const watchlist = library
    .filter((f) => f.status === 'watchlist' && genreMatch(f))
    .slice(0, 6)

  async function start() {
    if (!picked || starting) return
    setStarting(true)
    setError('')
    try {
      const res = await createConversation({
        type: 'reflection',
        ...(picked.film_id
          ? { film_id: picked.film_id }
          : { tmdb_id: picked.tmdb_id ?? undefined }),
        watch_type: watchType,
      })
      navigate(`/app/reflections/${res.conversation.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start the reflection.')
      setStarting(false)
    }
  }

  async function startPrompt() {
    if (starting) return
    setStarting(true)
    setError('')
    try {
      const res = await createConversation({ type: 'reflection', title: prompt })
      navigate(`/app/reflections/${res.conversation.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start the reflection.')
      setStarting(false)
    }
  }

  const runtime = formatRuntime(picked?.runtime)
  const inSearch = query.trim().length >= 2

  return (
    <div>
      <Link className="back-link" style={{ marginTop: 0 }} to="/app/reflections">
        ← Back to My Reflections
      </Link>
      <h1 className="page-title">Add a Reflection</h1>
      <p className="muted">
        Choose a film you've watched and tell us about your experience.
      </p>

      {prompt && (
        <div className="prompt-card">
          <div style={{ flex: 1 }}>
            <p className="eyebrow">Prompt of the day</p>
            <p className="prompt-text">“{prompt}”</p>
          </div>
          <button className="btn primary" disabled={starting} onClick={startPrompt}>
            Reflect on this →
          </button>
        </div>
      )}

      <div className="films-toolbar">
        <div className="search-input">
          <span aria-hidden>⌕</span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search for a film…"
          />
        </div>
      </div>

      {error && <p className="form-error">{error}</p>}

      {inSearch ? (
        <>
          <h2 className="picker-heading">Search results</h2>
          {searching && <p className="muted">Searching…</p>}
          {!searching && results.length === 0 && (
            <p className="muted">No films found for “{query.trim()}”.</p>
          )}
          <div className="picker-grid">
            {results.map((r) => (
              <PickCard
                key={r.tmdb_id}
                title={r.title}
                poster_url={r.poster_url}
                selected={picked?.tmdb_id === r.tmdb_id}
                onClick={() => pickFromSearch(r.tmdb_id)}
              />
            ))}
          </div>
        </>
      ) : (
        <>
          <div className="pills" style={{ margin: '0.25rem 0 1.25rem', flexWrap: 'wrap' }}>
            {GENRE_CHIPS.map((c) => (
              <button
                key={c.label}
                className={`pill${genre === c.label ? ' active' : ''}`}
                onClick={() => setGenre(c.label)}
              >
                {c.label}
              </button>
            ))}
          </div>

          <h2 className="picker-heading">Recently watched</h2>
          {loadingLibrary ? (
            <p className="muted">Loading your films…</p>
          ) : recentWatched.length === 0 ? (
            <p className="muted">
              Nothing here yet — search above, or{' '}
              <Link className="link" to="/app/films?add=1">
                add a film
              </Link>
              .
            </p>
          ) : (
            <div className="picker-row">
              {recentWatched.map((f) => (
                <PickCard
                  key={f.id}
                  title={f.title}
                  poster_url={f.poster_url}
                  selected={picked?.film_id === f.film_id}
                  onClick={() => choose(fromLibrary(f))}
                />
              ))}
            </div>
          )}

          <h2 className="picker-heading">From your watchlist</h2>
          {loadingLibrary ? (
            <p className="muted">Loading your films…</p>
          ) : watchlist.length === 0 ? (
            <p className="muted">
              Your watchlist is empty{genre !== 'All' ? ' for this genre' : ''}.
            </p>
          ) : (
            <div className="picker-row">
              {watchlist.map((f) => (
                <PickCard
                  key={f.id}
                  title={f.title}
                  poster_url={f.poster_url}
                  selected={picked?.film_id === f.film_id}
                  onClick={() => choose(fromLibrary(f))}
                />
              ))}
            </div>
          )}
        </>
      )}

      {loadingPick && <p className="muted">Loading film…</p>}

      {picked && (
        <div className="picker-bar">
          {picked.poster_url ? (
            <img className="result-thumb" src={picked.poster_url} alt="" />
          ) : (
            <span className="result-thumb no-poster">No poster</span>
          )}
          <div className="grow">
            <p className="t">{picked.title}</p>
            <p className="sub">
              {[picked.year, ...picked.genres.slice(0, 2), runtime]
                .filter(Boolean)
                .join(' · ')}
            </p>
          </div>
          {picked.library_status === 'watched' ? (
            <div className="pills">
              <button
                className={`pill${seenFlavor === 'first' ? ' active' : ''}`}
                onClick={() => {
                  setSeenFlavor('first')
                  setWatchType('seen')
                }}
              >
                First time watching
              </button>
              <button
                className={`pill${seenFlavor === 'rewatch' ? ' active' : ''}`}
                onClick={() => {
                  setSeenFlavor('rewatch')
                  setWatchType('seen')
                }}
              >
                Rewatch
              </button>
            </div>
          ) : (
            <div className="pills">
              <button
                className={`pill${watchType === 'seen' ? ' active' : ''}`}
                onClick={() => setWatchType('seen')}
              >
                I've seen it
              </button>
              <button
                className={`pill${watchType === 'planning' ? ' active' : ''}`}
                onClick={() => setWatchType('planning')}
              >
                Planning to watch
              </button>
            </div>
          )}
          <button className="btn primary" disabled={starting} onClick={start}>
            {starting ? 'Starting…' : 'Start reflection →'}
          </button>
        </div>
      )}
    </div>
  )
}

function PickCard({
  title,
  poster_url,
  selected,
  onClick,
}: {
  title: string
  poster_url: string | null
  selected: boolean
  onClick: () => void
}) {
  return (
    <button className={`pick-card${selected ? ' selected' : ''}`} onClick={onClick}>
      <span className="film-poster">
        {poster_url ? (
          <img src={poster_url} alt={title} loading="lazy" />
        ) : (
          <span className="no-poster">{title}</span>
        )}
        {selected && <span className="pick-check">✓</span>}
      </span>
      <p>{title}</p>
    </button>
  )
}

