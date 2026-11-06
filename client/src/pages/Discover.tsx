import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../lib/api'
import {
  clearFeedback,
  getRecommendations,
  sendFeedback,
  type FeedbackSignal,
  type Recommendation,
} from '../lib/recommendations'

// Discover (Phase 6: F8-F11): reflection-informed recommendation cards, each
// with a why-line, a TMDB critic rating next to the title, and a split pill
// bar (thumbs up / thumbs down) that steers future picks. The Film Assistant
// entry point opens the dedicated two-panel assistant page.
// Outline thumb icons matching the wireframe's pill bar.
function ThumbIcon({ down = false }: { down?: boolean }) {
  return down ? (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M17 14V2" />
      <path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z" />
    </svg>
  ) : (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M7 10v12" />
      <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
    </svg>
  )
}

export default function Discover() {
  const navigate = useNavigate()
  const [recs, setRecs] = useState<Recommendation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState<Record<number, FeedbackSignal>>({})
  const [busy, setBusy] = useState<number | null>(null)

  const load = useCallback((refresh = false) => {
    setLoading(true)
    setError('')
    getRecommendations(12, refresh)
      .then((res) => setRecs(res.recommendations))
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : 'Could not load recommendations'),
      )
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  async function giveFeedback(rec: Recommendation, signal: FeedbackSignal) {
    if (busy === rec.tmdb_id) return
    setBusy(rec.tmdb_id)
    setError('')
    try {
      if (feedback[rec.tmdb_id] === signal) {
        await clearFeedback(rec.tmdb_id)
        setFeedback((f) => {
          const next = { ...f }
          delete next[rec.tmdb_id]
          return next
        })
        return
      }
      await sendFeedback(rec.tmdb_id, signal, rec.title)
      setFeedback((f) => ({ ...f, [rec.tmdb_id]: signal }))
      if (signal === 'not_for_me') {
        // Hidden immediately; the server also excludes it from future runs.
        setRecs((rs) => rs.filter((r) => r.tmdb_id !== rec.tmdb_id))
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save feedback')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div>
      <div className="discover-header">
        <div>
          <h1 className="page-title">Discover</h1>
          <p className="muted">
            Picked from your library, ratings, and confirmed insights — every pick
            tells you why it's here.
          </p>
        </div>
        <button className="btn ghost" onClick={() => load(true)} disabled={loading}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      <section className="card assistant-card">
        <div className="grow">
          <h2>Film Assistant</h2>
          <p className="muted">
            Not sure what you're in the mood for? Chat it through and let the
            conversation shape your next watch.
          </p>
        </div>
        <button
          className="btn primary"
          onClick={() => navigate('/app/discover/assistant')}
        >
          Chat with the Film Assistant
        </button>
      </section>

      {error && <p className="form-error">{error}</p>}

      {loading && recs.length === 0 ? (
        <p className="muted">Finding films for you…</p>
      ) : recs.length === 0 ? (
        <section className="card">
          <h2>Nothing to show yet</h2>
          <p className="muted">
            Import or add a few films you love and confirm some insights from a
            reflection — your recommendations will grow from there.
          </p>
        </section>
      ) : (
        <div className="film-grid discover-grid">
          {recs.map((rec) => (
            <article key={rec.tmdb_id} className="film-card rec-card">
              <div className="film-poster">
                {rec.poster_url ? (
                  <img src={rec.poster_url} alt={rec.title} loading="lazy" />
                ) : (
                  <span className="no-poster">{rec.title}</span>
                )}
              </div>
              <h3>
                {rec.title}
                {rec.year ? ` (${rec.year})` : ''}
                {rec.vote_average > 0 && (
                  <span className="rec-rating" title="TMDB rating (out of 5)">
                    {' '}
                    <span className="star">★</span>{' '}
                    {(rec.vote_average / 2).toFixed(1)}
                  </span>
                )}
              </h3>
              {rec.genres.length > 0 && (
                <p className="meta">{rec.genres.slice(0, 2).join(' · ')}</p>
              )}
              <p className="why-line">“{rec.why}”</p>
              <div className="rec-actions">
                <button
                  className={`rec-btn up${feedback[rec.tmdb_id] === 'more_like_this' ? ' active' : ''}`}
                  disabled={busy === rec.tmdb_id}
                  aria-label="More like this"
                  title="More like this"
                  onClick={() => giveFeedback(rec, 'more_like_this')}
                >
                  <ThumbIcon />
                </button>
                <button
                  className={`rec-btn down${feedback[rec.tmdb_id] === 'not_for_me' ? ' active' : ''}`}
                  disabled={busy === rec.tmdb_id}
                  aria-label="Not for me"
                  title="Not for me"
                  onClick={() => giveFeedback(rec, 'not_for_me')}
                >
                  <ThumbIcon down />
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}

