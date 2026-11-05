import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../lib/api'
import { reviewMemory } from '../lib/memories'
import type { Memory, MemoryKind } from '../lib/memories'
import { getProfileSummary } from '../lib/profile'
import type { ProfileSummary } from '../lib/profile'

const KIND_META: Record<MemoryKind, { label: string; icon: string; heading: string }> = {
  theme: { label: 'Theme', icon: '✦', heading: 'Recurring themes' },
  preference: { label: 'Viewing preference', icon: '▦', heading: 'How you like to watch' },
  insight: { label: 'Reflection insight', icon: '♡', heading: 'Insights about you' },
}
const KIND_ORDER: MemoryKind[] = ['theme', 'preference', 'insight']

const formatDate = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })

// "from your reflection on <film>, <date>" — attribution derived server-side
// from the validated conversation linkage.
function sourceLine(memory: Memory): string {
  const source = memory.source_reflection
  if (!source) return ''
  const film = source.film_title
    ? ` on ${source.film_title}${source.film_year ? ` (${source.film_year})` : ''}`
    : ''
  return `From your reflection${film}, ${formatDate(source.date)}`
}


// My Profile (F2): the reflective profile — a generated summary plus every
// confirmed insight, grouped by kind. Confirmed insights can still be edited
// or rejected here (D12: only confirmed memories ever appear; edits preserve
// source_message_ids server-side).
export default function Profile() {
  const [profile, setProfile] = useState<ProfileSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [savingId, setSavingId] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    getProfileSummary()
      .then(setProfile)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : 'Could not load your profile.'),
      )
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  async function runReview(
    memory: Memory,
    status: 'confirmed' | 'rejected',
    content?: string,
  ) {
    if (savingId) return
    setSavingId(memory.id)
    setError('')
    try {
      await reviewMemory(memory.id, status, content?.trim())
      setEditingId(null)
      setDraft('')
      // Reload so the summary text, stats and groups stay consistent.
      setProfile(await getProfileSummary())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save that change.')
    } finally {
      setSavingId(null)
    }
  }

  if (loading) return <p className="muted">Loading your profile…</p>
  if (!profile) return <p className="form-error">{error || 'Could not load your profile.'}</p>

  const { stats } = profile
  const confirmedTotal = KIND_ORDER.reduce((n, k) => n + profile.groups[k].length, 0)

  return (
    <div>
      <h1 className="page-title">My Profile</h1>
      <p className="muted" style={{ maxWidth: '44rem' }}>
        This is your reflective profile — built only from the insights you chose
        to keep after your reflections. Edit or remove anything that no longer
        feels true.
      </p>
      {error && <p className="form-error">{error}</p>}

      <div className="stat-strip">
        <div className="stat">
          <span className="stat-num">{stats.films_watched}</span>
          <span className="muted">films watched</span>
        </div>
        <div className="stat">
          <span className="stat-num">{stats.watchlist}</span>
          <span className="muted">on your watchlist</span>
        </div>
        <div className="stat">
          <span className="stat-num">{stats.confirmed_insights}</span>
          <span className="muted">confirmed insights</span>
        </div>
        <div className="stat">
          <span className="stat-num">{stats.reflections_completed}</span>
          <span className="muted">reflections completed</span>
        </div>
      </div>

      {stats.top_genres.length > 0 && (
        <div className="pills" style={{ marginBottom: '1.25rem' }}>
          {stats.top_genres.map((g) => (
            <span className="pill active" key={g.genre}>
              {g.genre} · {g.count}
            </span>
          ))}
        </div>
      )}

      {profile.summary && (
        <section className="card" style={{ marginBottom: '1.5rem' }}>
          <h2>Your profile so far</h2>
          {profile.summary.split('\n\n').map((paragraph, i) => (
            <p key={i} className={i === 0 ? '' : 'muted'}>
              {paragraph}
            </p>
          ))}
        </section>
      )}

      {confirmedTotal === 0 ? (
        <section className="card" style={{ textAlign: 'center', padding: '2.5rem 1.5rem' }}>
          <h2>Your profile is waiting for its first insight</h2>
          <p className="muted" style={{ maxWidth: '34rem', margin: '0 auto 1.25rem' }}>
            Complete a reflection on a film that stayed with you, keep the
            insights that ring true, and they'll start to paint your portrait
            here.
          </p>
          <Link className="btn primary" to="/app/reflections/new">
            Start your first reflection →
          </Link>
        </section>
      ) : (
        KIND_ORDER.map((kind) => {
          const items = profile.groups[kind]
          if (items.length === 0) return null
          const meta = KIND_META[kind]
          return (
            <section key={kind} style={{ marginBottom: '1.5rem' }}>
              <h2>
                {meta.icon} {meta.heading}
              </h2>
              <div className="insight-list">
                {items.map((memory) => {
                  const editing = editingId === memory.id
                  const saving = savingId === memory.id
                  const attribution = sourceLine(memory)
                  return (
                    <article className="insight-card" key={memory.id}>
                      <div className="insight-top">
                        <span className="insight-kind">
                          <span className="insight-icon" aria-hidden>
                            {meta.icon}
                          </span>
                          {meta.label}
                        </span>
                        <span className="insight-status confirmed">Confirmed</span>
                      </div>
                      {editing ? (
                        <textarea
                          className="insight-edit"
                          rows={3}
                          value={draft}
                          maxLength={500}
                          onChange={(e) => setDraft(e.target.value)}
                        />
                      ) : (
                        <p className="insight-text">{memory.content}</p>
                      )}
                      {attribution && <p className="insight-explanation">{attribution}</p>}
                      <div className="insight-actions">
                        {editing ? (
                          <>
                            <button
                              className="btn primary"
                              disabled={saving || !draft.trim()}
                              onClick={() => runReview(memory, 'confirmed', draft)}
                            >
                              {saving ? 'Saving…' : '✓ Save'}
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
                        ) : (
                          <>
                            <button
                              className="btn ghost"
                              disabled={saving}
                              onClick={() => {
                                setEditingId(memory.id)
                                setDraft(memory.content)
                                setError('')
                              }}
                            >
                              Edit
                            </button>
                            <button
                              className="btn ghost danger"
                              disabled={saving}
                              onClick={() => runReview(memory, 'rejected')}
                            >
                              {saving ? 'Removing…' : 'Remove'}
                            </button>
                          </>
                        )}
                      </div>
                    </article>
                  )
                })}
              </div>
            </section>
          )
        })
      )}

      {stats.proposed_awaiting_review > 0 && (
        <p className="muted">
          You have {stats.proposed_awaiting_review} insight
          {stats.proposed_awaiting_review === 1 ? '' : 's'} awaiting review —{' '}
          <Link className="link" to="/app/reflections">
            review them in My Reflections
          </Link>
          .
        </p>
      )}
    </div>
  )
}

