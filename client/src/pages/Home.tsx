import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { getMyFilmsPage } from '../lib/films'
import type { LibraryFilm } from '../lib/films'

const PLACEHOLDER_THEMES = ['Connection', 'Time', 'Identity', 'Loneliness']

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

export default function Home() {
  const { user } = useAuth()
  const [recent, setRecent] = useState<LibraryFilm[]>([])

  useEffect(() => {
    getMyFilmsPage(undefined, 4, 0)
      .then((res) => setRecent(res.films))
      .catch(() => setRecent([]))
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
          <div className="chips" style={{ marginTop: '0.75rem' }}>
            {PLACEHOLDER_THEMES.map((theme) => (
              <span key={theme} className="chip">
                {theme}
              </span>
            ))}
          </div>
        </aside>
      </div>
    </div>
  )
}
