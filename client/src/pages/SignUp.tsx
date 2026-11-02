import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export default function SignUp() {
  const { signUp } = useAuth()
  const navigate = useNavigate()
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    setError(null)
    setBusy(true)
    try {
      await signUp(email, password, displayName.trim())
      navigate('/app')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create account')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="auth-page">
      <form className="auth-card" onSubmit={onSubmit}>
        <p className="brand">NOACF</p>
        <h1>Create your account</h1>
        <p className="muted">Your personal film journal awaits.</p>
        <div className="field">
          <label htmlFor="name">What should we call you?</label>
          <input
            id="name"
            type="text"
            autoComplete="nickname"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="email">Email address</label>
          <input
            id="email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="password">Password (min. 8 characters)</label>
          <input
            id="password"
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {error && <p className="form-error">{error}</p>}
        <button className="btn primary full" disabled={busy}>
          {busy ? 'Creating account…' : 'Create account'}
        </button>
        <p className="auth-alt">
          Already have an account? <Link to="/signin">Sign in</Link>
        </p>
      </form>
    </main>
  )
}
