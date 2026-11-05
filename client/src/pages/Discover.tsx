import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../lib/api'
import { createConversation } from '../lib/conversations'
import {
  clearFeedback,
  getRecommendations,
  sendFeedback,
  type FeedbackSignal,
  type Recommendation,
} from '../lib/recommendations'

// Discover (Phase 6: F8-F11): reflection-informed recommendation cards, each
// with a why-line, a "Why am I seeing this?" provenance panel, and explicit
// feedback (More like this / Not for me) that steers future picks. The Film
// Assistant entry point starts a discovery conversation (F10).
export default function Discover() {
  const navigate = useNavigate()
  const [recs, setRecs] = useState<Recommendation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<number | null>(null)
  const [feedback, setFeedback] = useState<Record<number, FeedbackSignal>>({})
  const [busy, setBusy] = useState<number | null>(null)
  const [startingChat, setStartingChat] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    getRecommendations(12)
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

  async function startAssistant() {
    if (startingChat) return
    setStartingChat(true)
    setError('')
    try {
      const res = await createConversation({ type: 'discovery', title: 'Film Assistant' })
      navigate(`/app/reflections/${res.conversation.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start the Film Assistant')
      setStartingChat(false)
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
        <button className="btn ghost" onClick={load} disabled={loading}>
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
        <button className="btn primary" onClick={startAssistant} disabled={startingChat}>
          {startingChat ? 'Starting…' : 'Chat with the Film Assistant'}
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
              </h3>
              {rec.genres.length > 0 && (
                <p className="meta">{rec.genres.slice(0, 2).join(' · ')}</p>
              )}
              <p className="why-line">{rec.why}</p>
              <button
                className="why-toggle"
                onClick={() => setExpanded(expanded === rec.tmdb_id ? null : rec.tmdb_id)}
              >
                {expanded === rec.tmdb_id ? 'Hide explanation' : 'Why am I seeing this?'}
              </button>
              {expanded === rec.tmdb_id && (
                <div className="why-panel">
                  <p>{rec.why}</p>
                  {rec.source_memories.length > 0 && (
                    <>
                      <p className="meta">Based on your confirmed insights:</p>
                      <ul>
                        {rec.source_memories.map((m) => (
                          <li key={m.id}>{m.content}</li>
                        ))}
                      </ul>
                    </>
                  )}
                </div>
              )}
              <div className="rec-actions">
                <button
                  className={`btn ghost small${feedback[rec.tmdb_id] === 'more_like_this' ? ' active' : ''}`}
                  disabled={busy === rec.tmdb_id}
                  onClick={() => giveFeedback(rec, 'more_like_this')}
                >
                  More like this
                </button>
                <button
                  className={`btn ghost small${feedback[rec.tmdb_id] === 'not_for_me' ? ' active' : ''}`}
                  disabled={busy === rec.tmdb_id}
                  onClick={() => giveFeedback(rec, 'not_for_me')}
                >
                  Not for me
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}

