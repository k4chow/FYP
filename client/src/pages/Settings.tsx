import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { api, ApiError } from '../lib/api'
import { getMyFilms } from '../lib/films'

// Settings: account info, data & integrations (Letterboxd import), a
// placeholder for recommendation preferences (Phase 6), and password change.
export default function Settings() {
  const { user } = useAuth()
  const [importedCount, setImportedCount] = useState<number | null>(null)

  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [pwError, setPwError] = useState('')
  const [pwSuccess, setPwSuccess] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getMyFilms()
      .then((res) => setImportedCount(res.films.filter((f) => f.source === 'letterboxd').length))
      .catch(() => setImportedCount(null))
  }, [])

  async function changePassword(e: React.FormEvent) {
    e.preventDefault()
    setPwError('')
    setPwSuccess('')
    if (newPw.length < 8) {
      setPwError('New password must be at least 8 characters.')
      return
    }
    if (newPw !== confirmPw) {
      setPwError('New passwords do not match.')
      return
    }
    setSaving(true)
    try {
      await api('/auth/change-password', {
        method: 'POST',
        auth: true,
        body: { current_password: currentPw, new_password: newPw },
      })
      setPwSuccess('Password updated.')
      setCurrentPw('')
      setNewPw('')
      setConfirmPw('')
    } catch (err) {
      setPwError(err instanceof ApiError ? err.message : 'Could not update password')
    } finally {
      setSaving(false)
    }
  }

  const initial = (user?.display_name || user?.email || '?').charAt(0).toUpperCase()

  return (
    <div>
      <h1 className="page-title">Settings</h1>
      <p className="muted">Manage your account and recommendation preferences.</p>

      <div className="settings-grid">
        <section className="card">
          <h2>Profile</h2>
          <p className="muted">Your account information.</p>
          <div className="settings-row" style={{ marginTop: '0.75rem' }}>
            <div className="avatar lg">{initial}</div>
            <div className="grow">
              <h3>{user?.display_name || '—'}</h3>
              <p className="muted" style={{ fontSize: '0.9rem' }}>{user?.email}</p>
            </div>
          </div>
        </section>

        <section className="card">
          <h2>Data &amp; Integrations</h2>
          <p className="muted">Connect your film data to get personalised recommendations.</p>
          <div className="settings-row" style={{ marginTop: '0.75rem' }}>
            <div className="avatar lg" aria-hidden>L⃞</div>
            <div className="grow">
              <h3>Letterboxd</h3>
              <p className="muted" style={{ fontSize: '0.9rem' }}>
                {importedCount !== null && importedCount > 0
                  ? `${importedCount} film${importedCount === 1 ? '' : 's'} imported`
                  : 'Not connected — import a CSV export to get started'}
              </p>
            </div>
            <Link className="btn ghost" to="/app/import">
              Import CSV
            </Link>
          </div>
        </section>

        <section className="card">
          <h2>Recommendation Preferences</h2>
          <p className="muted">Adjust how NOACF recommends films for you.</p>
          <div style={{ marginTop: '0.75rem', opacity: 0.55 }}>
            <strong style={{ fontSize: '0.95rem' }}>Recommendation style</strong>
            <input type="range" min={0} max={100} defaultValue={30} disabled style={{ marginTop: '0.5rem' }} />
            <div className="slider-labels">
              <span>More similar</span>
              <span>More random</span>
            </div>
            <p className="muted" style={{ fontSize: '0.85rem' }}>
              Arrives with Discover in Phase 6.
            </p>
          </div>
        </section>

        <section className="card">
          <h2>Change Password</h2>
          <p className="muted">Update your account password.</p>
          <form onSubmit={changePassword} style={{ marginTop: '0.75rem', maxWidth: '26rem' }}>
            <div className="field">
              <label htmlFor="current-pw">Current password</label>
              <input
                id="current-pw"
                type="password"
                value={currentPw}
                onChange={(e) => setCurrentPw(e.target.value)}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="new-pw">New password</label>
              <input
                id="new-pw"
                type="password"
                value={newPw}
                onChange={(e) => setNewPw(e.target.value)}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="confirm-pw">Confirm new password</label>
              <input
                id="confirm-pw"
                type="password"
                value={confirmPw}
                onChange={(e) => setConfirmPw(e.target.value)}
                required
              />
            </div>
            {pwError && <p className="form-error">{pwError}</p>}
            {pwSuccess && <p className="success">{pwSuccess}</p>}
            <button className="btn primary" type="submit" disabled={saving}>
              {saving ? 'Updating…' : 'Update password'}
            </button>
          </form>
        </section>
      </div>
    </div>
  )
}
