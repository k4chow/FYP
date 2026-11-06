import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError } from '../lib/api'
import DisapprovalNote from '../components/DisapprovalNote'
import {
  createConversation,
  endConversation,
  getConversation,
  sendMessage,
} from '../lib/conversations'
import type { ChatMessage, Conversation } from '../lib/conversations'
import { addFilm, formatRuntime } from '../lib/films'
import { sendFeedback } from '../lib/recommendations'

// Mood chips from the wireframe — one-tap openers for the Film Assistant.
const MOODS = [
  'Surprise me',
  'Something comforting',
  'Mind-bending sci-fi',
  'A good cry',
]

// A film card as the server embeds it in assistant message metadata
// (`metadata.recommendations`): verified TMDB data, no recommendation-engine
// fields (score/why) — the assistant's own picks, not the Discover feed.
interface AssistantRec {
  tmdb_id: number
  title: string
  year: number | null
  genres: string[]
  runtime: number | null
  overview: string
  poster_url: string | null
  vote_average: number
  themes: string[]
}

// Film Assistant (F10): chat on the left, live recommendation cards on the
// right. Assistant replies carry verified TMDB cards in message metadata and
// the newest set of picks is always what the right panel shows.
export default function Assistant() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const existingId = searchParams.get('c')

  const [conversation, setConversation] = useState<Conversation | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [ending, setEnding] = useState(false)
  const [added, setAdded] = useState<Record<number, boolean>>({})
  const [busyCard, setBusyCard] = useState<number | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [notFound, setNotFound] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    const request = existingId
      ? getConversation(existingId)
      : createConversation({ type: 'discovery', title: 'Film Assistant' })
    request
      .then((res) => {
        if (cancelled) return
        if (res.conversation.type !== 'discovery') {
          // Reflection conversations belong to the reflection chat page.
          navigate(`/app/reflections/${res.conversation.id}`, { replace: true })
          return
        }
        setConversation(res.conversation)
        setMessages(res.messages)
      })
      .catch((err) =>
        err instanceof ApiError && err.status === 404
          ? setNotFound(true)
          : setError('Could not open the Film Assistant.'),
      )
    return () => {
      cancelled = true
    }
  }, [existingId, navigate])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, sending])

  // The newest assistant message with recommendations wins.
  const recs = useMemo<AssistantRec[]>(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const message = messages[i]
      if (message.role !== 'assistant') continue
      const found = (message.metadata ?? {}) as { recommendations?: AssistantRec[] }
      if (Array.isArray(found.recommendations) && found.recommendations.length > 0) {
        return found.recommendations
      }
    }
    return []
  }, [messages])

  const active = conversation?.status === 'active'

  async function send(raw: string) {
    const content = raw.trim()
    const id = conversation?.id
    if (!content || !id || sending || !active) return
    setSending(true)
    setError('')
    setInput('')
    // Optimistic user bubble; replaced by the server's stored messages.
    const tempId = `temp-${Date.now()}`
    setMessages((ms) => [
      ...ms,
      { id: tempId, role: 'user', content, metadata: {}, created_at: new Date().toISOString() },
    ])
    try {
      const res = await sendMessage(id, content)
      setMessages((ms) => [
        ...ms.filter((m) => m.id !== tempId),
        res.user_message,
        res.assistant_message,
      ])
    } catch (err) {
      setMessages((ms) => ms.filter((m) => m.id !== tempId))
      setError(err instanceof ApiError ? err.message : 'Could not send your message.')
    } finally {
      setSending(false)
    }
  }

  async function end() {
    if (!conversation || ending) return
    setEnding(true)
    setError('')
    try {
      await endConversation(conversation.id)
      navigate('/app/discover')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not end the chat.')
      setEnding(false)
    }
  }

  async function moreLikeThis(rec: AssistantRec) {
    if (busyCard === rec.tmdb_id || sending || !active) return
    setBusyCard(rec.tmdb_id)
    setError('')
    try {
      await sendFeedback(rec.tmdb_id, 'more_like_this', rec.title)
      await send(`Something more like ${rec.title}, please.`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save your feedback.')
    } finally {
      setBusyCard(null)
    }
  }

  async function addToWatchlist(rec: AssistantRec) {
    if (busyCard === rec.tmdb_id || added[rec.tmdb_id]) return
    setBusyCard(rec.tmdb_id)
    setError('')
    try {
      await addFilm(rec.tmdb_id, 'watchlist')
      setAdded((a) => ({ ...a, [rec.tmdb_id]: true }))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not add the film.')
    } finally {
      setBusyCard(null)
    }
  }

  if (notFound) {
    return (
      <div>
        <Link className="back-link" style={{ marginTop: 0 }} to="/app/discover">
          ← Back to Discover
        </Link>
        <p className="muted">This chat no longer exists.</p>
      </div>
    )
  }

  return (
    <div className="assistant-layout">
      <section className="card chat-panel">
        <header className="chat-head">
          <span className="chat-avatar" aria-hidden>
            ▤
          </span>
          <div className="grow">
            <h2>Film Assistant</h2>
            <p className="muted">Tell it your mood — it picks the films</p>
          </div>
          {active && (
            <button className="btn ghost" onClick={end} disabled={ending}>
              {ending ? 'Ending…' : '✕ End chat'}
            </button>
          )}
        </header>

        <div className="chat-msgs">
          {messages.map((m) => (
            <div key={m.id} className={`msg-row ${m.role}`}>
              <div className="msg">
                {m.content}
                <span className="msg-meta">
                  {new Date(m.created_at).toLocaleTimeString(undefined, {
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </span>
              </div>
            </div>
          ))}
          {sending && <p className="typing">The Film Assistant is thinking…</p>}
          <div ref={bottomRef} />
        </div>

        {error && (
          <p className="form-error" style={{ padding: '0 1.1rem' }}>
            {error}
          </p>
        )}

        {active ? (
          <>
            <div className="chat-input-row">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && send(input)}
                placeholder="What are you in the mood for…"
                disabled={sending}
              />
              <button
                className="btn primary"
                onClick={() => send(input)}
                disabled={sending || !input.trim()}
                aria-label="Send"
              >
                ➤
              </button>
            </div>
            <div className="quick-replies">
              {MOODS.map((mood) => (
                <button
                  key={mood}
                  className="chip-btn"
                  disabled={sending}
                  onClick={() => send(mood)}
                >
                  {mood}
                </button>
              ))}
            </div>
          </>
        ) : (
          <div className="chat-done">
            <span>Chat ended ✓</span>
            <Link to="/app/discover">Back to Discover</Link>
            <button
              className="link-button"
              onClick={() => navigate('/app/discover/assistant')}
            >
              Start a new chat
            </button>

          </div>
        )}
      </section>


      <aside className="assistant-recs">
        <div className="assistant-recs-head">
          <h2>Here are some recommendations for you</h2>
          <button
            className="btn ghost small"
            disabled={sending || !active}
            onClick={() => send('Can you suggest something different?')}
          >
            ↻ Regenerate
          </button>
        </div>

        {recs.length === 0 ? (
          <p className="muted assistant-recs-empty">
            {sending
              ? 'Finding films…'
              : 'Tell the assistant what you feel like watching and its picks will appear here.'}
          </p>
        ) : (
          <div className="assistant-rec-cards">
            {recs.map((rec) => (
              <article
                key={rec.tmdb_id}
                className={`card assistant-rec-card${expanded === rec.tmdb_id ? ' expanded' : ''}`}
              >
                <div className="assistant-rec-poster">
                  {rec.poster_url ? (
                    <img src={rec.poster_url} alt={rec.title} loading="lazy" />
                  ) : (
                    <span className="no-poster">{rec.title}</span>
                  )}
                  <button
                    className={`bookmark-btn${added[rec.tmdb_id] ? ' active' : ''}`}
                    title={added[rec.tmdb_id] ? 'On your watchlist' : 'Add to watchlist'}
                    aria-label="Add to watchlist"
                    disabled={busyCard === rec.tmdb_id || added[rec.tmdb_id]}
                    onClick={() => addToWatchlist(rec)}
                  >
                    ⚑
                  </button>
                </div>
                <div className="assistant-rec-body">
                  <h3>
                    {rec.title}
                    {rec.year ? ` (${rec.year})` : ''}
                    {rec.vote_average > 0 && (
                      <span className="rec-rating" title="TMDB rating (out of 5)">
                        {' '}⭐ {(rec.vote_average / 2).toFixed(1)}
                      </span>
                    )}
                  </h3>
                  <p className="meta">
                    {[
                      rec.genres.slice(0, 2).join(' · '),
                      formatRuntime(rec.runtime ?? null),
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                  {(rec.themes?.length ?? 0) > 0 && (
                    <div className="theme-tags">
                      {rec.themes!.map((theme) => (
                        <span key={theme} className="theme-tag">
                          {theme}
                        </span>
                      ))}
                    </div>
                  )}
                  <p className="overview">{rec.overview || 'No synopsis available.'}</p>
                  <DisapprovalNote title={rec.title} year={rec.year} />
                  {expanded === rec.tmdb_id && (
                    <div className="assistant-rec-details">
                      <p className="meta">
                        TMDB rating: {rec.vote_average > 0 ? `${(rec.vote_average / 2).toFixed(1)} / 5` : 'unrated'}
                        {rec.themes.length > 0 && rec.themes.length > 2
                          ? ` · more themes: ${rec.themes.slice(2).join(', ')}`
                          : ''}
                      </p>
                    </div>
                  )}
                  <div className="rec-card-actions">
                    <button
                      className="btn ghost small"
                      onClick={() =>
                        setExpanded(expanded === rec.tmdb_id ? null : rec.tmdb_id)
                      }
                    >
                      {expanded === rec.tmdb_id ? 'Hide details' : 'View details'}
                    </button>
                    <button
                      className="btn ghost small"
                      disabled={busyCard === rec.tmdb_id || added[rec.tmdb_id]}
                      onClick={() => addToWatchlist(rec)}
                    >
                      {added[rec.tmdb_id] ? '✓ On watchlist' : '+ Add to watchlist'}
                    </button>
                    <button
                      className="btn ghost small"
                      disabled={busyCard === rec.tmdb_id || sending || !active}
                      onClick={() => moreLikeThis(rec)}
                    >
                      More like this
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </aside>
    </div>
  )
}

