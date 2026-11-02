import { Link } from 'react-router-dom'

export default function Landing() {
  return (
    <main className="landing">
      <p className="brand">NOACF</p>
      <h1>Films stay with us.</h1>
      <p className="muted">
        Your personal film journal — reflect on what you watch, build a profile
        you control, and discover what to watch next.
      </p>
      <div className="row">
        <Link className="btn primary" to="/signup">
          Get started
        </Link>
        <Link className="btn ghost" to="/signin">
          Sign in
        </Link>
      </div>
    </main>
  )
}
