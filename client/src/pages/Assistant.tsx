import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../lib/api'
import DisapprovalNote from '../components/DisapprovalNote'
import {
  createConversation,
  getConversation,
  listConversations,
  sendMessage,
} from '../lib/conversations'
import type {
  AssistantRecommendation,
  ChatMessage,
} from '../lib/conversations'
import { addFilm, formatRuntime } from '../lib/films'
import { sendFeedback } from '../lib/recommendations'

// Mood chips from the wireframe — one-tap openers for the Film Assistant.
const MOODS = [
  'Surprise me',
  'Something comforting',
  'Mind-bending sci-fi',
  'A good cry',
]

// A recommendation card returned by a Film Assistant turn: verified TMDB data
// (the assistant's own picks), not the Discover feed's scored/sorted cards.
type AssistantRec = AssistantRecommendation

// The assistant chat is persisted server-side as a discovery conversation;
// nothing is stored in the browser (no sessionStorage transcript). We render
// the backend messages, mapping any recommendation cards out of their metadata.
interface LocalMessage {
  role: 'user' | 'assistant'
  content: string
  createdAt: string
  recommendations?: AssistantRec[]
}

function toLocal(message: ChatMessage): LocalMessage {
  const metadata = (message.metadata ?? {}) as {
    recommendations?: AssistantRec[]
  }
  return {
    role: message.role === 'assistant' ? 'assistant' : 'user',
    content: message.content,
    createdAt: message.created_at,
    recommendations: Array.isArray(metadata.recommendations)
      ? metadata.recommendations
      : undefined,
  }
}
// Film Assistant (F10): chat on the left, live recommendation cards on the
// right. Turns are saved to the backend (a discovery conversation); ending the
// chat returns to Discover, leaving the transcript resumable from history.
export default function Assistant() {
  const navigate = useNavigate()
  const [messages, setMessages] = useState<LocalMessage[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [ready, setReady] = useState(false)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [added, setAdded] = useState<Record<number, boolean>>({})
  const [busyCard, setBusyCard] = useState<number | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [error, setError] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  // Resume the most recent active assistant conversation, or open a new one
  // (the create endpoint persists the assistant's opening message for us).
  useEffect(() => {
    let cancelled = false
    async function init() {
      setError('')
      try {
        const list = await listConversations('active', 'discovery')
        const assistant = list.conversations.find((c) => !c.title)
        let res = assistant
          ? await getConversation(assistant.id)
          : await createConversation({ type: 'discovery' })
        // A failed earlier creation can leave an empty conversation behind
        // (no opening message). Start fresh instead of showing a blank chat.
        if (res.messages.length === 0) {
          res = await createConversation({ type: 'discovery' })
        }
        if (cancelled) return
        setConversationId(res.conversation.id)
        setMessages(res.messages.map(toLocal))
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err.message
              : 'Could not open the Film Assistant.',
          )
        }
      } finally {
        if (!cancelled) setReady(true)
      }
    }
    init()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, sending])

  // The newest assistant message with recommendations wins.
  const recs = useMemo<AssistantRec[]>(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const message = messages[i]
      if (
        message.role === 'assistant' &&
        (message.recommendations?.length ?? 0) > 0
      ) {
        return message.recommendations as AssistantRec[]
      }
    }
    return []
  }, [messages])

  // Every film already shown this session; we pass these each turn so the next
  // reply (and every Regenerate) surfaces fresh films rather than repeats.
  function collectShown(list: LocalMessage[]): number[] {
    const shown = new Set<number>()
    for (const message of list) {
      for (const rec of message.recommendations ?? []) shown.add(rec.tmdb_id)
    }
    return Array.from(shown)
  }

  async function send(raw: string) {
    const content = raw.trim()
    if (!content || sending || !conversationId) return
    setSending(true)
    setError('')
    setInput('')
    try {
      const res = await sendMessage(conversationId, content, collectShown(messages))
      setMessages((prev) => [
        ...prev,
        toLocal(res.user_message),
        toLocal(res.assistant_message),
      ])
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : 'Could not send your message.',
      )
    } finally {
      setSending(false)
    }
  }

  // Ending simply returns to Discover; the chat stays saved in the backend.
  function end() {
    navigate('/app/discover')
  }

  async function moreLikeThis(rec: AssistantRec) {
    if (busyCard === rec.tmdb_id || sending) return
    setBusyCard(rec.tmdb_id)
    setError('')
    try {
      await sendFeedback(rec.tmdb_id, 'more_like_this', rec.title)
      await send(`Something more like ${rec.title}, please.`)
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : 'Could not save your feedback.',
      )
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
      setError(
        err instanceof ApiError ? err.message : 'Could not add the film.',
      )
    } finally {
      setBusyCard(null)
    }
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
          <button className="btn ghost" onClick={end} disabled={sending}>
            ✕ End chat
          </button>
        </header>

        <div className="chat-msgs">
          {!ready && messages.length === 0 && (
            <p className="muted">Loading your Film Assistant…</p>
          )}
          {messages.map((m, i) => (
            <div
              key={`${m.role}-${m.createdAt}-${i}`}
              className={`msg-row ${m.role}`}
            >
              <div className="msg">
                {m.content}
                <span className="msg-meta">
                  {new Date(m.createdAt).toLocaleTimeString(undefined, {
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

        <div className="chat-input-row">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && send(input)}
            placeholder="What are you in the mood for…"
            disabled={sending || !ready}
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
              disabled={sending || !ready}
              onClick={() => send(mood)}
            >
              {mood}
            </button>
          ))}
        </div>
      </section>
<aside className="assistant-recs">
        <div className="assistant-recs-head">
          <h2>Here are some recommendations for you</h2>
          <button
            className="btn ghost small"
            disabled={sending || !ready}
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
                className={`card assistant-rec-card${
                  expanded === rec.tmdb_id ? ' expanded' : ''
                }`}
              >
                <div className="assistant-rec-poster">
                  {rec.poster_url ? (
                    <img src={rec.poster_url} alt={rec.title} loading="lazy" />
                  ) : (
                    <span className="no-poster">{rec.title}</span>
                  )}
                  <button
                    className={`bookmark-btn${
                      added[rec.tmdb_id] ? ' active' : ''
                    }`}
                    title={
                      added[rec.tmdb_id]
                        ? 'On your watchlist'
                        : 'Add to watchlist'
                    }
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
                        {' '}
                        ⭐ {(rec.vote_average / 2).toFixed(1)}
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
                  <p className="overview">
                    {rec.overview || 'No synopsis available.'}
                  </p>
                  <DisapprovalNote title={rec.title} year={rec.year} />
                  {expanded === rec.tmdb_id && (
                    <div className="assistant-rec-details">
                      <p className="meta">
                        TMDB rating:{' '}
                        {rec.vote_average > 0
                          ? `${(rec.vote_average / 2).toFixed(1)} / 5`
                          : 'unrated'}
                        {rec.themes.length > 2
                          ? ` · more themes: ${rec.themes.slice(2).join(', ')}`
                          : ''}
                      </p>
                    </div>
                  )}
                  <div className="rec-card-actions">
                    <button
                      className="btn ghost small"
                      onClick={() =>
                        setExpanded(
                          expanded === rec.tmdb_id ? null : rec.tmdb_id,
                        )
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
                      disabled={busyCard === rec.tmdb_id || sending}
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