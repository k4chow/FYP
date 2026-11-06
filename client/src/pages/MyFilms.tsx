import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import AddFilmModal from '../components/AddFilmModal'
import DisapprovalNote from '../components/DisapprovalNote'
import { getMyFilms, removeFilm } from '../lib/films'
import type { LibraryCounts, LibraryFilm } from '../lib/films'

type Filter = 'all' | 'watched' | 'watchlist'
type Sort = 'added' | 'title' | 'year'

// My Films (F7): the user's library as a poster grid with status filters,
// client-side search/sort, per-film menu, and quick-add entry points.
export default function MyFilms() {
  const [films, setFilms] = useState<LibraryFilm[]>([])
  const [counts, setCounts] = useState<LibraryCounts | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<Sort>('added')
  const [menuFor, setMenuFor] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [toast, setToast] = useState('')
  const [params, setParams] = useSearchParams()

  useEffect(() => {
    getMyFilms()
      .then((res) => {
        setFilms(res.films)
        setCounts(res.counts)
      })
      .catch(() => setError('Could not load your films.'))
      .finally(() => setLoading(false))
  }, [])

  // Quick add in the sidebar links here with ?add=1.
  useEffect(() => {
    if (params.get('add') === '1') {
      setModalOpen(true)
      setParams({}, { replace: true })
    }
  }, [params, setParams])

  // Profile stats deep-link here with ?filter=watched|watchlist.
  useEffect(() => {
    const f = params.get('filter')
    if (f === 'watched' || f === 'watchlist') {
      setFilter(f)
      setParams({}, { replace: true })
    }
  }, [params, setParams])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(''), 3000)
    return () => clearTimeout(t)
  }, [toast])

  const visible = useMemo(() => {
    let list = films.filter((f) => filter === 'all' || f.status === filter)
    const q = query.trim().toLowerCase()
    if (q) list = list.filter((f) => f.title.toLowerCase().includes(q))
    const sorted = [...list]
    if (sort === 'title') sorted.sort((a, b) => a.title.localeCompare(b.title))
    if (sort === 'year') sorted.sort((a, b) => (b.year ?? 0) - (a.year ?? 0))
    return sorted
  }, [films, filter, query, sort])

  async function remove(film: LibraryFilm) {
    setMenuFor(null)
    try {
      await removeFilm(film.id)
      setFilms((fs) => fs.filter((f) => f.id !== film.id))
      setCounts((c) =>
        c
          ? { ...c, all: c.all - 1, [film.status]: c[film.status] - 1 }
          : c,
      )
      setToast(`Removed “${film.title}”`)
    } catch {
      setToast('Could not remove film')
    }
  }

  function closeModal(added?: LibraryFilm) {
    setModalOpen(false)
    if (added) {
      const existing = films.find((f) => f.id === added.id)
      setFilms((fs) => [added, ...fs.filter((f) => f.id !== added.id)])
      if (!existing) {
        setCounts((c) =>
          c
            ? {
                ...c,
                all: c.all + 1,
                [added.status]: c[added.status as 'watched' | 'watchlist'] + 1,
              }
            : c,
        )
      }
      setToast(`Added “${added.title}” to your films`)
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">My Films</h1>
          <p className="muted" style={{ margin: 0 }}>
            {counts
              ? `${counts.all} film${counts.all === 1 ? '' : 's'} in your library — ready for another look.`
              : 'Your film collection, ready for another look.'}
          </p>
        </div>
        <button className="btn primary" onClick={() => setModalOpen(true)}>
          + Add a film
        </button>
      </div>

      <div className="films-toolbar">
        <div className="search-input">
          <span aria-hidden>⌕</span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search your films…"
          />
        </div>
        <div className="pills">
          {(['all', 'watched', 'watchlist'] as Filter[]).map((f) => (
            <button
              key={f}
              className={`pill${filter === f ? ' active' : ''}`}
              onClick={() => setFilter(f)}
            >
              {f === 'all' ? 'All films' : f === 'watched' ? 'Watched' : 'Watchlist'}
              {counts ? ` (${counts[f]})` : ''}
            </button>
          ))}
        </div>
        <label className="sort-select">
          Sort by:
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="added">Recently Added</option>
            <option value="title">Title</option>
            <option value="year">Year</option>
          </select>
        </label>
      </div>

      {loading && <p className="muted">Loading your films…</p>}
      {error && <p className="form-error">{error}</p>}

      {!loading && !error && films.length === 0 && (
        <p className="muted">
          No films yet — add one manually, or import your Letterboxd history below.
        </p>
      )}
      {!loading && !error && films.length > 0 && visible.length === 0 && (
        <p className="muted">No films match this view.</p>
      )}

      <div className="film-grid">
        {visible.map((film) => (
          <div key={film.id} className="film-card">
            <div className="film-poster">
              {film.poster_url ? (
                <img src={film.poster_url} alt={film.title} loading="lazy" />
              ) : (
                <span className="no-poster">{film.title}</span>
              )}
            </div>
            <button
              className={`card-menu-btn${menuFor === film.id ? ' open' : ''}`}
              onClick={() => setMenuFor(menuFor === film.id ? null : film.id)}
              aria-label="Film options"
            >
              ⋮
            </button>
            {menuFor === film.id && (
              <>
                <div className="menu-overlay" onClick={() => setMenuFor(null)} />
                <div className="menu-pop">
                  <button className="danger" onClick={() => remove(film)}>
                    Remove from library
                  </button>
                </div>
              </>
            )}
            <h3>{film.title}</h3>
            <p className="meta">
              {[film.year, film.status === 'watched' ? 'Watched' : 'Watchlist']
                .filter(Boolean)
                .join(' · ')}
            </p>
            <DisapprovalNote title={film.title} year={film.year} />
          </div>
        ))}
      </div>

      <div className="dashed-cards">
        <button className="dashed-card" onClick={() => setModalOpen(true)}>
          <strong>
            <span aria-hidden>＋</span> Add a film
          </strong>
          <span className="muted">Search TMDB and add to your collection</span>
        </button>
        <Link className="dashed-card" to="/app/import">
          <strong>
            <span aria-hidden>⇪</span> Import from Letterboxd
          </strong>
          <span className="muted">Import your watch history for a faster start</span>
        </Link>
      </div>

      {modalOpen && <AddFilmModal onClose={closeModal} />}
      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
