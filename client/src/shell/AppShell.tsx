import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

interface NavItem {
  to: string
  label: string
  icon: string
  end?: boolean
}

const NAV: NavItem[] = [
  { to: '/app', label: 'Home', icon: '⌂', end: true },
  { to: '/app/discover', label: 'Discover', icon: '✦' },
  { to: '/app/films', label: 'My Films', icon: '🎞' },
  { to: '/app/reflections', label: 'My Reflections', icon: '✎' },
  { to: '/app/profile', label: 'My Profile', icon: '◉' },
  { to: '/app/settings', label: 'Settings', icon: '⚙' },
]

export default function AppShell() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()
  const initial = (user?.display_name || user?.email || '?').charAt(0).toUpperCase()

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <p className="brand">
            NOACF
            <small>Your personal film journal</small>
          </p>
          <Link
            to="/app/profile"
            className="avatar"
            title={user?.email}
            aria-label="My Profile"
          >
            {initial}
          </Link>
        </div>
        <nav className="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? 'active' : '')}
            >
              <span aria-hidden>{item.icon}</span>
              <span className="label">{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="quick-add">
          <p className="quick-add-label">Quick add</p>
          <NavLink to="/app/reflections/new">
            <span aria-hidden>✎</span>
            <span className="label">Start a reflection</span>
          </NavLink>
          <NavLink to="/app/films?add=1">
            <span aria-hidden>＋</span>
            <span className="label">Add a film</span>
          </NavLink>
          <NavLink to="/app/import">
            <span aria-hidden>⇪</span>
            <span className="label">Import from Letterboxd</span>
          </NavLink>
        </div>
        <div className="sidebar-footer">
          <button
            className="btn ghost full"
            onClick={() => {
              signOut()
              navigate('/')
            }}
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
