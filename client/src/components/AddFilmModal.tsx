import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../lib/api'
import { addFilm, formatRuntime, getFilmDetail, searchFilms } from '../lib/films'
import type { FilmDetail, LibraryFilm, SearchResult } from '../lib/films'

interface AddFilmModalProps {
  onClose: (added?: LibraryFilm) => void
}

// "Add a film" modal (F7): TMDB search -> film detail -> watched/watchlist ->
// start a reflection or just save to the library.
export default function AddFilmModal({ onClose }: AddFilmModalProps) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [detail, setDetail] = useState<FilmDetail | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [status, setStatus] = useState<'watched' | 'watchlist'>('watched')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => inputRef.current?.focus(), [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Debounced TMDB search.
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

  async function select(result: SearchResult) {
    setLoadingDetail(true)
    setError('')
    try {
      const d = await getFilmDetail(result.tmdb_id)
      setDetail(d)
      setStatus(d.in_library?.status === 'watchlist' ? 'watchlist' : 'watched')
    } catch {
      setError('Could not load film details.')
    } finally {
      setLoadingDetail(false)
    }
  }

  async function save(then: 'close' | 'reflect') {
    if (!detail) return
    setSaving(true)
    setError('')
    try {
      const added = await addFilm(detail.tmdb_id, status)
      onClose(added)
      if (then === 'reflect') navigate('/app/reflections')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save film')
      setSaving(false)
    }
  }

  const runtime = formatRuntime(detail?.runtime)
  const sub = detail
    ? [detail.year, ...detail.genres.slice(0, 2), runtime].filter(Boolean).join(' · ')
    : ''

  return (
    <div className="modal-backdrop" onClick={() => onClose()}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h2>Add a film</h2>
            <p className="muted" style={{ margin: '0.2rem 0 0' }}>
              Find a film to add to your collection.
            </p>
          </div>
          <button className="modal-close" onClick={() => onClose()} aria-label="Close">
            ✕
          </button>
        </div>

        {error && <p className="form-error">{error}</p>}
        {!detail && (
          <>
            <div className="search-input" style={{ marginTop: '1rem' }}>
              <span aria-hidden>⌕</span>
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search for a film…"
              />
              {query && (
                <button className="modal-close" onClick={() => setQuery('')} aria-label="Clear">
                  ✕
                </button>
              )}
            </div>
            {loadingDetail && <p className="muted">Loading film…</p>}
            {!loadingDetail && searching && <p className="muted">Searching…</p>}
            {!loadingDetail && !searching && query.trim().length >= 2 && results.length === 0 && (
              <p className="muted">No films found.</p>
            )}
            {!loadingDetail && (
              <div className="result-list">
                {results.map((r) => (
                  <button key={r.tmdb_id} className="result-item" onClick={() => select(r)}>
                    {r.poster_url ? (
                      <img className="result-thumb" src={r.poster_url} alt="" />
                    ) : (
                      <span className="result-thumb no-poster">No poster</span>
                    )}
                    <span>
                      <p className="t">{r.title}</p>
                      <p className="y">{r.year ?? '—'}</p>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </>
        )}

        {detail && (
          <>
            <button className="back-link" onClick={() => setDetail(null)}>
              ← Back to results
            </button>
            <div className="detail">
              {detail.poster_url && (
                <img className="detail-poster" src={detail.poster_url} alt={detail.title} />
              )}
              <div>
                {detail.in_library && <span className="badge">In your library</span>}
                <h3>{detail.title}</h3>
                <p className="sub">{sub}</p>
                <p className="overview">{detail.overview || 'No synopsis available.'}</p>
              </div>
            </div>

            <p style={{ margin: '1.1rem 0 0', fontWeight: 600 }}>
              Have you watched this film?
            </p>
            <div className="choice-row">
              <button
                className={`choice-card${status === 'watched' ? ' selected' : ''}`}
                onClick={() => setStatus('watched')}
              >
                <span className="tick">{status === 'watched' ? '✓' : ''}</span>
                <span>
                  <strong>Watched</strong>
                  <small>I've already seen this film</small>
                </span>
              </button>
              <button
                className={`choice-card${status === 'watchlist' ? ' selected' : ''}`}
                onClick={() => setStatus('watchlist')}
              >
                <span className="tick">{status === 'watchlist' ? '✓' : ''}</span>
                <span>
                  <strong>Plan to watch</strong>
                  <small>I haven't seen this film yet</small>
                </span>
              </button>
            </div>

            <p style={{ margin: '0 0 0.6rem', fontWeight: 600 }}>
              What would you like to do next?
            </p>
            <button
              className="action-card-btn primary"
              disabled={saving}
              onClick={() => save('reflect')}
            >
              <span className="icon" aria-hidden>▷</span>
              <span>
                <strong>Start a reflection</strong>
                <small>Explore your thoughts on this film now</small>
              </span>
            </button>
            <button
              className="action-card-btn"
              disabled={saving}
              onClick={() => save('close')}
            >
              <span className="icon" aria-hidden>⊞</span>
              <span>
                <strong>{detail.in_library ? 'Update status' : 'Save to My Films instead'}</strong>
                <small>Add this film to your collection without starting a reflection</small>
              </span>
            </button>
          </>
        )}
      </div>
    </div>
  )
}
