import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      await api('/auth/forgot-password', { method: 'POST', body: { email } })
    } finally {
      // Always show the same message — never reveal whether the email exists.
      setSent(true)
      setBusy(false)
    }
  }

  return (
    <main className="auth-page">
      <form className="auth-card" onSubmit={onSubmit}>
        <p className="brand">NOACF</p>
        <h1>Reset your password</h1>
        {sent ? (
          <p className="muted">
            If an account exists for {email}, a reset link has been sent.
          </p>
        ) : (
          <>
            <p className="muted">
              Enter your email and we'll send you a reset link.
            </p>
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
            <button className="btn primary full" disabled={busy}>
              {busy ? 'Sending…' : 'Send reset link'}
            </button>
          </>
        )}
        <Link className="link" to="/signin">
          ← Back to sign in
        </Link>
      </form>
    </main>
  )
}
