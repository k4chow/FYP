import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { deleteConversation, listConversations } from '../lib/conversations'
import type { Conversation } from '../lib/conversations'

// "My Reflections" (F1): resume active conversations, revisit completed ones.
export default function Reflections() {
  const [conversations, setConversations] = useState<Conversation[] | null>(null)
  const [error, setError] = useState('')
  const [deletingId, setDeletingId] = useState<string | null>(null)

  useEffect(() => {
    listConversations(undefined, 'reflection')
      .then((res) => setConversations(res.conversations))
      .catch(() => setError('Could not load your reflections.'))
  }, [])

  const active = (conversations ?? []).filter((c) => c.status === 'active')
  const completed = (conversations ?? []).filter((c) => c.status === 'completed')

  async function remove(c: Conversation) {
    const label = c.film ? ` on ${c.film.title}` : ''
    if (!window.confirm(`Delete this reflection${label}? Its saved insights will be removed too.`)) {
      return
    }
    setDeletingId(c.id)
    try {
      await deleteConversation(c.id)
      setConversations((prev) => (prev ?? []).filter((x) => x.id !== c.id))
    } catch {
      setError('Could not delete that reflection.')
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">My Reflections</h1>
          <p className="muted">
            Reflect as often as you like — a single film can hold more than one
            conversation, and your words are always kept verbatim.
          </p>
        </div>
        <Link className="btn primary" to="/app/reflections/new">
          ＋ Start a reflection
        </Link>
      </div>

      {error && <p className="form-error">{error}</p>}
      {conversations === null && !error && <p className="muted">Loading…</p>}

      {conversations !== null && conversations.length === 0 && (
        <div className="dashed-cards" style={{ gridTemplateColumns: '1fr' }}>
          <Link className="dashed-card" to="/app/reflections/new">
            <strong>＋ Start your first reflection</strong>
            <span className="muted">Pick a film and talk through what it meant to you.</span>
          </Link>
        </div>
      )}

      {active.length > 0 && (
        <Section
          title="In progress"
          subtitle="Pick up where you left off."
          items={active}
          deletingId={deletingId}
          onDelete={remove}
        />
      )}
      {completed.length > 0 && (
        <Section
          title="Completed"
          subtitle="Reflections you've ended."
          items={completed}
          deletingId={deletingId}
          onDelete={remove}
        />
      )}
    </div>
  )
}

function Section({
  title,
  subtitle,
  items,
  deletingId,
  onDelete,
}: {
  title: string
  subtitle: string
  items: Conversation[]
  deletingId: string | null
  onDelete: (c: Conversation) => void
}) {
  return (
    <section style={{ marginTop: '1.75rem' }}>
      <h2 className="picker-heading">{title}</h2>
      <p className="muted" style={{ margin: '-0.35rem 0 0' }}>
        {subtitle}
      </p>
      <div className="conv-list">
        {items.map((c) => (
          <div key={c.id} className="conv-row">
            <Link to={`/app/reflections/${c.id}`} className="conv-link">
              {c.film?.poster_url ? (
                <img className="result-thumb" src={c.film.poster_url} alt="" />
              ) : (
                <span className="result-thumb no-poster">{c.film ? 'No poster' : '✎'}</span>
              )}
              <span className="conv-main">
                <span className="t">
                  {c.film?.title ?? c.title ?? 'Free reflection'}
                </span>
                <span className="y">
                  {c.film ? `${c.film.year ?? ''} · ` : ''}
                  {c.watch_type === 'planning' ? 'Planning to watch' : c.film ? 'Watched' : 'Prompt'}
                  {' · '}
                  {new Date(c.updated_at).toLocaleDateString(undefined, {
                    month: 'short',
                    day: 'numeric',
                  })}
                </span>
              </span>
              <span className={`badge${c.status === 'completed' ? ' done' : ''}`}>
                {c.status === 'completed' ? 'Completed' : 'In progress'}
              </span>
              <span className="conv-chevron" aria-hidden>
                ›
              </span>
            </Link>
            <button
              className="conv-delete"
              title="Delete reflection"
              aria-label="Delete reflection"
              disabled={deletingId === c.id}
              onClick={() => onDelete(c)}
            >
              {deletingId === c.id ? '…' : '🗑'}
            </button>
          </div>
        ))}
      </div>
    </section>
  )
}
