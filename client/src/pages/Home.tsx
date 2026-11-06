import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { getMyFilmsPage } from '../lib/films'
import type { LibraryFilm } from '../lib/films'
import { getProfileSummary } from '../lib/profile'

// Rotating reflection prompts; one per day, deterministic (no backend needed).
const PROMPTS = [
  'What film do you find yourself thinking about for no obvious reason?',
  'Which character’s decision would you have made differently?',
  'What did a film once help you understand about yourself?',
  'Which film world would you actually want to live in — and which would you avoid?',
  'What feeling do you keep going back to the cinema to find?',
  'Which film ending still doesn’t sit right with you?',
  'What film character would you want as a friend?',
]

const dayOfYear = (d: Date) =>
  Math.floor((d.getTime() - new Date(d.getFullYear(), 0, 0).getTime()) / 86_400_000)

// Condense a full theme sentence into a short 1–4 word chip label so the home
// page reads as quick themes rather than echoing whole insights. The original
// sentence is still surfaced as the chip's tooltip, so nothing is lost.
function themeLabel(content: string): string {
  let text = content
    .trim()
    .replace(/^["“”']+/, '')
    .replace(/["“”'.,;:]+$/, '')
    .trim()
  // Drop trailing clauses that only restate the reflection.
  text = text.split(/\s+(?:in|during|across)\s+(?:this|your|these|the)\s+reflections?\b/i)[0]
  text = text.split(/\s+while\s+(?:reflecting|watching|thinking)\b/i)[0]
  // Drop leading filler phrases like "You kept returning to …".
  text = text.replace(
    /^you\b(?:\s+(?:were|are|keep|kept))?\s+(?:returning\s+to|drawn\s+to(?:wards?)?|attracted\s+to|gravitat\w*\s+to(?:wards?)?|tend\s+to(?:wards?)?|keep\s+coming\s+back\s+to)\s+/i,
    '',
  )
  text = text.replace(
    /^(?:your\s+)?(?:a\s+)?recurring\s+(?:pull|draw|thread|theme|attraction|interest|fascination|love|affinity|focus|obsession)\s+(?:to|toward|towards|for|in|with|around)\s+/i,
    '',
  )

  const words = text.split(/\s+/).filter(Boolean)
  let label = words.slice(0, 4).join(' ').replace(/[\s,.;:]+$/, '')
  // Trim trailing connectors, e.g. "grief and" -> "grief".
  let prev = ''
  while (prev !== label) {
    prev = label
    label = label.replace(/[\s,]+(?:and|or|of|the|a|an|to|in|on|with|about|for|that|while|but)$/i, '')
  }
  // Trim a leading article/connector left behind, e.g. "the sea" -> "sea".
  label = label.replace(/^[\s,]+/, '').replace(/^(?:the|a|an|of|to|in|on|with|about|for|and|or)\s+/i, '')
  if (!label) label = words.slice(0, 3).join(' ')
  return label ? label.charAt(0).toUpperCase() + label.slice(1) : content
}

export default function Home() {
  const { user } = useAuth()
  const [recent, setRecent] = useState<LibraryFilm[]>([])
  const [themes, setThemes] = useState<{ id: string; label: string; content: string }[]>([])

  useEffect(() => {
    getMyFilmsPage(undefined, 4, 0)
      .then((res) => setRecent(res.films))
      .catch(() => setRecent([]))
    getProfileSummary()
      .then((p) =>
        setThemes(
          p.groups.theme.map((t) => ({
            id: t.id,
            content: t.content,
            label: themeLabel(t.content),
          })),
        ),
      )
      .catch(() => setThemes([]))
  }, [])

  return (
    <div>
      <h1 className="page-title">
        Welcome back{user?.display_name ? `, ${user.display_name}` : ''}.
      </h1>
      <p className="muted">Continue your film journey.</p>

      <div className="action-cards">
        <Link className="action-card" to="/app/discover">
          <h3>Discover</h3>
          <p>Find your next film — recommendations shaped by your reflections.</p>
        </Link>
        <Link className="action-card" to="/app/reflections">
          <h3>Reflect</h3>
          <p>Start a guided reflection on something you've watched.</p>
        </Link>
      </div>

      <Link
        className="prompt-card"
        to={`/app/reflections/new?prompt=${encodeURIComponent(PROMPTS[dayOfYear(new Date()) % PROMPTS.length])}`}
      >
        <div style={{ flex: 1 }}>
          <p className="eyebrow">Prompt of the day</p>
          <p className="prompt-text">“{PROMPTS[dayOfYear(new Date()) % PROMPTS.length]}”</p>
        </div>
        <span className="prompt-cta">Reflect on this →</span>
      </Link>

      <div className="home-grid">
        <section className="card">
          <h2>Recently added</h2>
          {recent.length === 0 ? (
            <p className="muted">
              Your library is empty —{' '}
              <Link className="link" to="/app/films?add=1">
                add a film
              </Link>{' '}
              or{' '}
              <Link className="link" to="/app/import">
                import from Letterboxd
              </Link>
              .
            </p>
          ) : (
            <div className="film-row">
              {recent.map((film) => (
                <div key={film.id} className="film-poster home-poster" title={film.title}>
                  {film.poster_url ? (
                    <img src={film.poster_url} alt={film.title} loading="lazy" />
                  ) : (
                    <span className="no-poster">{film.title}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
        <aside className="card">
          <h2>Your profile themes</h2>
          {themes.length === 0 ? (
            <p className="muted" style={{ marginTop: '0.75rem' }}>
              No themes yet — finish a reflection and keep the insights that
              ring true, and your recurring themes will surface here.
            </p>
          ) : (
            <div className="chips" style={{ marginTop: '0.75rem' }}>
              {themes.map((theme) => (
                <span key={theme.id} className="chip" title={theme.content}>
                  {theme.label}
                </span>
              ))}
            </div>
          )}
          <Link
            className="link"
            to="/app/profile?tab=themes"
            style={{ display: 'inline-block', marginTop: '0.9rem' }}
          >
            View all profile themes →
          </Link>
        </aside>
      </div>
    </div>
  )
}
