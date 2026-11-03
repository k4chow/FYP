import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../lib/api'
import { getConversation } from '../lib/conversations'
import type { Conversation } from '../lib/conversations'
import { formatRuntime } from '../lib/films'
import { getConversationMemories, reviewMemory } from '../lib/memories'
import type { Memory, MemoryKind } from '../lib/memories'

const KIND_META: Record<MemoryKind, { label: string; icon: string }> = {
  theme: { label: 'Theme', icon: '✦' },
  preference: { label: 'Viewing preference', icon: '▦' },
  insight: { label: 'Reflection insight', icon: '♡' },
}

// Guided review (F3/D12): every generated insight stays proposed until the
// user keeps it, edits and keeps it, or removes it. Source messages are shown
// only through each insight's explicit citations — never as an LLM debug view.
export default function ReviewReflection() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [conversation, setConversation] = useState<Conversation | null>(null)
  const [memories, setMemories] = useState<Memory[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [savingId, setSavingId] = useState<string | null>(null)
  const [whyId, setWhyId] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    let cancelled = false
    Promise.all([getConversation(id), getConversationMemories(id)])
      .then(([conversationRes, memoryRes]) => {
        if (cancelled) return
        setConversation(conversationRes.conversation)
        setMemories(memoryRes.memories)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 404) setNotFound(true)
        else setError('Could not load the proposed insights for this reflection.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [id])

  function replaceMemory(updated: Memory) {
    setMemories((items) =>
      (items ?? []).map((item) => (item.id === updated.id ? updated : item)),
    )
  }

  async function runReview(
    memory: Memory,
    status: 'confirmed' | 'rejected',
    content?: string,
  ) {
    if (savingId) return
    setSavingId(memory.id)
    setError('')
    try {
      const res = await reviewMemory(memory.id, status, content?.trim())
      replaceMemory(res.memory)
      setEditingId(null)
      setDraft('')
      setWhyId(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save that decision.')
    } finally {
      setSavingId(null)
    }
  }

  function beginEdit(memory: Memory) {
    setEditingId(memory.id)
    setDraft(memory.content)
    setError('')
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

  if (loading || !conversation || memories === null) {
    return error ? <p className="form-error">{error}</p> : <p className="muted">Loading review…</p>
  }

  const film = conversation.film
  const runtime = film ? formatRuntime(film.runtime) : null
  const pending = memories.filter((memory) => memory.status === 'proposed')
  const reviewed = memories.filter((memory) => memory.status !== 'proposed')
  const complete = memories.length > 0 && pending.length === 0


  return (
    <div>
      <div className="page-header review-header">
        <div>
          <p className="eyebrow">Review and edit</p>
          <h1 className="page-title">Help us keep what feels right.</h1>
          <p className="muted">
            These tentative observations are based only on this reflection. Nothing shapes
            your profile unless you choose to keep it.
          </p>
        </div>
        <span className={`badge${conversation.status === 'completed' ? ' done' : ''}`}>
          {conversation.status === 'completed' ? 'Reflection complete' : 'Reflection active'}
        </span>
      </div>

      <div className="review-layout">
        <aside className="card review-film">
          {film ? (
            <>
              {film.poster_url ? (
                <img className="review-poster" src={film.poster_url} alt={`${film.title} poster`} />
              ) : (
                <span className="review-poster no-poster">No poster</span>
              )}
              <h2>{film.title}</h2>
              <p className="muted">
                {[film.year, ...film.genres.slice(0, 3), runtime].filter(Boolean).join(' · ')}
              </p>
              <span className="badge">
                {conversation.watch_type === 'planning' ? 'Planning to watch' : 'Watched'}
              </span>
            </>
          ) : (
            <>
              <span className="review-poster no-poster">✎</span>
              <h2>{conversation.title ?? 'Free reflection'}</h2>
              <p className="muted">A prompt reflection without a film attached.</p>
              <span className="badge">Prompt</span>
            </>
          )}
          <Link className="btn ghost full" to={`/app/reflections/${conversation.id}`}>
            View conversation
          </Link>
        </aside>

        <section className="card review-panel">
          <div className="review-panel-head">
            <div>
              <h2>Key insights and themes from your reflection</h2>
              <p className="muted">
                Keep the observations that fit, edit the wording, or remove anything that
                does not. Proposed insights are not used by the assistant.
              </p>
            </div>
            <span className="badge">{pending.length} pending</span>
          </div>

          {error && <p className="form-error">{error}</p>}

          {complete && (
            <div className="review-complete" role="status">
              <strong>All proposed insights reviewed ✓</strong>
              <span>
                {reviewed.filter((memory) => memory.status === 'confirmed').length} kept ·{' '}
                {reviewed.filter((memory) => memory.status === 'rejected').length} removed
              </span>
            </div>
          )}

          {memories.length === 0 && (
            <div className="review-empty">
              <h3>No proposed insights yet</h3>
              <p className="muted">
                {conversation.status === 'active'
                  ? 'This reflection is still active. End it when you are ready to review proposed insights.'
                  : 'This reflection did not contain enough substantive user messages to propose an insight. Your original messages remain unchanged.'}
              </p>
              {conversation.status === 'active' && (
                <Link className="btn primary" to={`/app/reflections/${conversation.id}`}>
                  Return to reflection
                </Link>
              )}
            </div>
          )}

          <div className="insight-list">
            {memories.map((memory) => {
              const meta = KIND_META[memory.kind]
              const editing = editingId === memory.id
              const saving = savingId === memory.id
              const showingWhy = whyId === memory.id
              return (
                <article className="insight-card" key={memory.id}>
                  <div className="insight-top">
                    <span className="insight-icon" aria-hidden>
                      {meta.icon}
                    </span>
                    <span className="insight-kind">{meta.label}</span>
                    {memory.status !== 'proposed' && (
                      <span className={`insight-status ${memory.status}`}>
                        {memory.status === 'confirmed' ? 'Kept' : 'Removed'}
                      </span>
                    )}
                  </div>

                  {editing ? (
                    <textarea
                      className="insight-edit"
                      value={draft}
                      maxLength={500}
                      rows={4}
                      aria-label="Edit proposed insight"
                      onChange={(event) => setDraft(event.target.value)}
                    />
                  ) : (
                    <p className="insight-text">{memory.content}</p>
                  )}

                  <p className="insight-explanation">{memory.explanation}</p>

                  {showingWhy && (
                    <div className="source-panel">
                      <strong>Why am I seeing this?</strong>
                      <p className="muted">
                        This insight cites only the message{memory.source_messages.length === 1 ? '' : 's'} below.
                        The original conversation is append-only and cannot be edited here.
                      </p>
                      {memory.source_messages.map((source) => (
                        <blockquote className="source-msg" key={source.id}>
                          <span>{source.role === 'user' ? 'You wrote' : 'Assistant prompt'}</span>
                          “{source.content}”
                        </blockquote>
                      ))}
                    </div>
                  )}

                  <div className="insight-actions">
                    {editing ? (
                      <>
                        <button
                          className="btn primary"
                          disabled={saving || !draft.trim()}
                          onClick={() => runReview(memory, 'confirmed', draft)}
                        >
                          {saving ? 'Saving…' : '✓ Save and keep'}
                        </button>
                        <button
                          className="btn ghost"
                          disabled={saving}
                          onClick={() => {
                            setEditingId(null)
                            setDraft('')
                          }}
                        >
                          Cancel
                        </button>
                      </>
                    ) : memory.status === 'proposed' ? (
                      <>
                        <button
                          className="btn primary"
                          disabled={saving}
                          onClick={() => runReview(memory, 'confirmed')}
                        >
                          {saving ? 'Saving…' : '✓ Keep'}
                        </button>
                        <button
                          className="btn ghost"
                          disabled={saving}
                          onClick={() => beginEdit(memory)}
                        >
                          Edit
                        </button>
                        <button
                          className="btn ghost danger"
                          disabled={saving}
                          onClick={() => runReview(memory, 'rejected')}
                        >
                          Remove
                        </button>
                      </>
                    ) : null}
                    <button
                      className="link-button"
                      type="button"
                      onClick={() => setWhyId(showingWhy ? null : memory.id)}
                    >
                      ⓘ {showingWhy ? 'Hide source' : 'Why am I seeing this?'}
                    </button>
                  </div>
                </article>
              )
            })}
          </div>
        </section>
      </div>

      <div className="review-footer">
        <Link className="btn ghost" to="/app/reflections">
          ← Back
        </Link>
        <div className="row">
          <Link className="btn ghost" to="/app/reflections">
            Skip for now
          </Link>
          <button className="btn primary" onClick={() => navigate('/app/reflections')}>
            {complete ? 'Finish review →' : 'Save progress and continue →'}
          </button>
        </div>
      </div>
    </div>
  )
}

