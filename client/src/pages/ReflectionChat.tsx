import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../lib/api'
import { endConversation, getConversation, sendMessage } from '../lib/conversations'
import type { ChatMessage, Conversation } from '../lib/conversations'
import { formatRuntime } from '../lib/films'

// Quick-reply chips — the mock LLM answers these deterministically.
const QUICK_REPLIES = ["I'm not sure", 'Can you ask a different question?', 'Maybe later']

// Reflection chat (F1): film panel on the left, conversation on the right.
// Messages render straight from the server — the history is the source of truth.
export default function ReflectionChat() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [conversation, setConversation] = useState<Conversation | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [ending, setEnding] = useState(false)
  const [error, setError] = useState('')
  const [notFound, setNotFound] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!id) return
    getConversation(id)
      .then((res) => {
        setConversation(res.conversation)
        setMessages(res.messages)
      })
      .catch((err) =>
        err instanceof ApiError && err.status === 404
          ? setNotFound(true)
          : setError('Could not load this reflection.'),
      )
  }, [id])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, sending])

  const active = conversation?.status === 'active'

  async function send(raw: string) {
    const content = raw.trim()
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
    if (!id || ending) return
    setEnding(true)
    setError('')
    try {
      const res = await endConversation(id)
      setConversation(res.conversation)
      navigate(`/app/reflections/${id}/review`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not end the reflection.')
    } finally {
      setEnding(false)
    }
  }

  if (notFound) {
    return (
      <div>
        <Link className="back-link" style={{ marginTop: 0 }} to="/app/reflections">
          ← Back to My Reflections
        </Link>
        <p className="form-error">Reflection not found.</p>
      </div>
    )
  }
  if (!conversation) {
    return error ? (
      <p className="form-error">{error}</p>
    ) : (
      <p className="muted">Loading…</p>
    )
  }

  const film = conversation.film
  const heading = film ? `Reflecting on ${film.title}` : 'Free reflection'
  const runtime = formatRuntime(film?.runtime)

  return (
    <div className="chat-layout">
      <aside className="card chat-film">
        <Link className="back-link" style={{ marginTop: 0 }} to="/app/reflections">
          ← My Reflections
        </Link>
        {film ? (
          <>
            {film.poster_url ? (
              <img className="poster" src={film.poster_url} alt={film.title} />
            ) : (
              <div className="film-poster" style={{ marginTop: '0.75rem' }}>
                <span className="no-poster">{film.title}</span>
              </div>
            )}
            <h2>{film.title}</h2>
            <p className="sub">
              {[film.year, ...film.genres.slice(0, 2), runtime]
                .filter(Boolean)
                .join(' · ')}
            </p>
            <span className="badge">
              {conversation.watch_type === 'planning' ? 'Planning to watch' : 'Watched'}
            </span>
            <p className="overview">{film.overview || 'No synopsis available.'}</p>
          </>
        ) : (
          <>
            <p className="eyebrow" style={{ marginTop: '0.75rem' }}>
              Prompt
            </p>
            <h2 style={{ marginTop: '0.35rem' }}>
              {conversation.title ?? 'Free reflection'}
            </h2>
            <p className="overview">
              No film attached — a space for whatever is on your mind.
            </p>
          </>
        )}
      </aside>

      <section className="card chat-panel">
        <header className="chat-head">
          <span className="chat-avatar" aria-hidden>
            ▦
          </span>
          <div className="grow">
            <h2>{heading}</h2>
            <p className="muted">Take your time — there are no right or wrong answers</p>
          </div>
          {active && (
            <button className="btn ghost" onClick={end} disabled={ending}>
              {ending ? 'Ending…' : '✕ End reflection'}
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
          {sending && <p className="typing">NOACF is thinking…</p>}
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
                placeholder="Share your thoughts…"
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
              {QUICK_REPLIES.map((chip) => (
                <button
                  key={chip}
                  className="chip-btn"
                  disabled={sending}
                  onClick={() => send(chip)}
                >
                  {chip}
                </button>
              ))}
            </div>
          </>
        ) : (
          <div className="chat-done">
            <span>Reflection complete ✓ — your messages remain unchanged.</span>
            <Link to={`/app/reflections/${id}/review`}>Review proposed insights</Link>
            <Link to="/app/reflections">Back to My Reflections</Link>
          </div>
        )}
      </section>
    </div>
  )
}
