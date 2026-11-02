import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

// Placeholder poster tiles until TMDB integration (Phase 2).
const PLACEHOLDER_FILMS = ['Past Lives', 'Interstellar', 'Her', 'Dune']
const PLACEHOLDER_THEMES = ['Connection', 'Time', 'Identity', 'Loneliness']

export default function Home() {
  const { user } = useAuth()

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

      <div className="home-grid">
        <section className="card">
          <h2>Picked for you</h2>
          <p className="muted">
            Recommendations arrive in Phase 6 — these are placeholders.
          </p>
          <div className="film-row">
            {PLACEHOLDER_FILMS.map((title) => (
              <div key={title} className="film-tile">
                {title}
              </div>
            ))}
          </div>
        </section>
        <aside className="card">
          <h2>Your profile themes</h2>
          <p className="muted">
            Themes from your reflections appear here (Phase 5).
          </p>
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
