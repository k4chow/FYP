import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../lib/api'
import { importLetterboxd } from '../lib/films'
import type { ImportResult } from '../lib/films'

// Letterboxd import (F6): upload a CSV from a Letterboxd export, the server
// matches rows to TMDB and fills the library. Matched/unmatched summary shown.
export default function Import() {
  const [file, setFile] = useState<File | null>(null)
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  async function run() {
    if (!file) return
    setImporting(true)
    setError('')
    setResult(null)
    try {
      setResult(await importLetterboxd(file))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Import failed')
    } finally {
      setImporting(false)
    }
  }

  return (
    <div>
      <h1 className="page-title">Import from Letterboxd</h1>
      <p className="muted" style={{ maxWidth: '44rem' }}>
        Bring your film history with you. Upload a CSV from your Letterboxd
        export and we'll match it against TMDB to build your collection.
      </p>

      <div className="settings-grid">
        <section className="card">
          <h2>Your Letterboxd export</h2>
          <p className="muted">
            CSV file — diary.csv, ratings.csv, watched.csv or watchlist.csv.
          </p>
          <div className="upload-zone">
            <span className="cloud" aria-hidden>⇪</span>
            <strong>Choose your export file</strong>
            <span className="muted" style={{ fontSize: '0.9rem' }}>
              {file ? file.name : 'Select a CSV from your downloaded Letterboxd export.'}
            </span>
            <input
              ref={inputRef}
              type="file"
              accept=".csv,text/csv"
              hidden
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null)
                setResult(null)
                setError('')
              }}
            />
            <div className="row" style={{ marginTop: '0.75rem' }}>
              <button className="btn ghost" onClick={() => inputRef.current?.click()}>
                Choose CSV file
              </button>
              <button className="btn primary" disabled={!file || importing} onClick={run}>
                {importing ? 'Importing…' : 'Import'}
              </button>
            </div>
          </div>
          {error && <p className="form-error">{error}</p>}
          {importing && (
            <p className="muted">Matching your films against TMDB — this can take a moment.</p>
          )}
          {result && (
            <div className="import-result" style={{ marginTop: '1rem' }}>
              <p style={{ fontWeight: 600 }}>
                Import complete — matched {result.matched} of {result.total_rows} films.
              </p>
              {result.unmatched.length > 0 && (
                <>
                  <p className="muted" style={{ marginBottom: 0 }}>
                    We couldn't match these (add them manually if you like):
                  </p>
                  <ul>
                    {result.unmatched.map((u) => (
                      <li key={`${u.name}-${u.year}`}>
                        {u.name}
                        {u.year ? ` (${u.year})` : ''}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <div className="row" style={{ marginTop: '1rem' }}>
                <Link className="btn primary" to="/app/films">
                  View My Films
                </Link>
                <button
                  className="btn ghost"
                  onClick={() => {
                    setFile(null)
                    setResult(null)
                  }}
                >
                  Import another file
                </button>
              </div>
            </div>
          )}
        </section>

        <section className="card">
          <h2>Need help finding your export?</h2>
          <ol className="steps">
            <li>Open Letterboxd in your browser and go to your account settings.</li>
            <li>
              Find the{' '}
              <a className="link" href="https://letterboxd.com/settings/data/" target="_blank" rel="noreferrer">
                Import &amp; Export
              </a>{' '}
              section and export your data.
            </li>
            <li>Download the archive, unzip it, and pick a film-history CSV.</li>
          </ol>
        </section>

        <section className="card">
          <h2>Your data, your choice</h2>
          <p className="muted" style={{ marginBottom: 0 }}>
            We store each imported film's title, year, your rating and watched
            date — nothing else from the file. You can remove any imported film
            from My Films at any time, and re-importing never creates
            duplicates.
          </p>
        </section>
      </div>
    </div>
  )
}
