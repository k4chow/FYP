import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../lib/api'
import { getImportJob, importLetterboxd, resumeImportJob } from '../lib/films'
import type { ImportJob } from '../lib/films'

// Letterboxd import (F6): upload returns a job id promptly; persisted job
// progress is polled so large imports survive timeouts and page refreshes.
export default function Import() {
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [resuming, setResuming] = useState(false)
  const [job, setJob] = useState<ImportJob | null>(null)
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const active = job?.status === 'queued' || job?.status === 'processing'
  const finished = job?.status === 'completed' || job?.status === 'completed_with_errors'

  // Only the job id is kept locally; refreshing the page restores progress.
  useEffect(() => {
    const id = window.localStorage.getItem('noacf_import_job')
    if (!id) return
    getImportJob(id)
      .then(setJob)
      .catch(() => window.localStorage.removeItem('noacf_import_job'))
  }, [])

  useEffect(() => {
    if (job?.id) window.localStorage.setItem('noacf_import_job', job.id)
    else window.localStorage.removeItem('noacf_import_job')
  }, [job?.id])

  useEffect(() => {
    const id = job?.id
    if (!id || !active) return
    const timer = window.setInterval(() => {
      getImportJob(id)
        .then(setJob)
        .catch((err) =>
          setError(err instanceof ApiError ? err.message : 'Could not load import progress'),
        )
    }, 1000)
    return () => window.clearInterval(timer)
  }, [job?.id, active])

  async function run() {
    if (!file) return
    setUploading(true)
    setError('')
    setJob(null)
    try {
      const started = await importLetterboxd(file)
      setJob(await getImportJob(started.import_id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start the import')
    } finally {
      setUploading(false)
    }
  }

  async function resume() {
    if (!job) return
    setResuming(true)
    setError('')
    try {
      setJob(await resumeImportJob(job.id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not resume the import')
    } finally {
      setResuming(false)
    }
  }

  const heading = !job
    ? ''
    : job.status === 'queued'
      ? 'Import queued…'
      : job.status === 'processing'
        ? 'Importing your films…'
        : job.status === 'completed'
          ? 'Import complete.'
          : job.status === 'completed_with_errors'
            ? 'Import finished with temporary failures.'
            : 'Import paused after an error.'

  return (
    <div>
      <h1 className="page-title">Import from Letterboxd</h1>
      <p className="muted" style={{ maxWidth: '44rem' }}>
        Bring your film history with you. Upload a CSV from your Letterboxd
        export and we'll match it against TMDB to build your collection.
      </p>
      <p className="import-tip" style={{ maxWidth: '44rem' }}>
        <strong>Recommended:</strong> choose <strong>watched.csv</strong> from the
        unzipped export — it contains your complete watch history.
      </p>

      <div className="settings-grid">
        <section className="card">
          <h2>Your Letterboxd export</h2>
          <p className="muted">
            Choose <strong>watched.csv</strong> (your full watch history) — or use
            diary.csv, ratings.csv or watchlist.csv if you prefer.
          </p>
          <div className="upload-zone">
            <span className="cloud" aria-hidden>⇪</span>
            <strong>Choose your export file</strong>
            <span className="muted" style={{ fontSize: '0.9rem' }}>
              {file
                ? file.name
                : 'Select watched.csv from your unzipped Letterboxd export (recommended).'}
            </span>
            <input
              ref={inputRef}
              type="file"
              accept=".csv,text/csv"
              hidden
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null)
                setJob(null)
                setError('')
              }}
            />
            <div className="row" style={{ marginTop: '0.75rem' }}>
              <button className="btn ghost" onClick={() => inputRef.current?.click()}>
                Choose CSV file
              </button>
              <button className="btn primary" disabled={!file || uploading || active} onClick={run}>
                {uploading ? 'Uploading…' : active ? 'Import in progress' : 'Import'}
              </button>
            </div>
          </div>
          {error && <p className="form-error">{error}</p>}
          {job && (
            <div className="import-result" style={{ marginTop: '1rem' }}>
              <p style={{ fontWeight: 600 }}>{heading}</p>
              {active && (
                <progress
                  className="import-progress"
                  value={job.processed_rows}
                  max={job.total_rows}
                  aria-label="Import progress"
                />
              )}
              <p className="muted">
                {job.processed_rows} of {job.total_rows} rows processed
              </p>
              <div className="import-counts">
                <span><strong>{job.added}</strong> added</span>
                <span><strong>{job.updated}</strong> updated</span>
                <span><strong>{job.duplicates}</strong> duplicates / already current</span>
                <span><strong>{job.unmatched_count}</strong> unmatched</span>
                <span><strong>{job.failed}</strong> temporary failures</span>
              </div>

              {job.error && <p className="form-error">{job.error}</p>}
              {(job.status === 'failed' || job.status === 'completed_with_errors') && (
                <button className="btn ghost" disabled={resuming} onClick={resume}>
                  {resuming ? 'Resuming…' : 'Retry failed and remaining rows'}
                </button>
              )}

              {job.unmatched.length > 0 && (
                <>
                  <p className="muted" style={{ marginBottom: 0 }}>
                    No TMDB match was found for these rows (you can add them manually):
                  </p>
                  <ul>
                    {job.unmatched.map((u) => (
                      <li key={`unmatched-${u.row}`}>
                        {u.name}{u.year ? ` (${u.year})` : ''}
                      </li>
                    ))}
                  </ul>
                </>
              )}

              {job.failures.length > 0 && (
                <>
                  <p className="muted" style={{ marginBottom: 0 }}>
                    Temporary failures — these are not unmatched films and can be retried:
                  </p>
                  <ul>
                    {job.failures.map((f) => (
                      <li key={`failed-${f.row}`}>
                        {f.name}{f.year ? ` (${f.year})` : ''} — {f.error}
                      </li>
                    ))}
                  </ul>
                </>
              )}

              {finished && (
                <div className="row" style={{ marginTop: '1rem' }}>
                  <Link className="btn primary" to="/app/films">View My Films</Link>
                  <button
                    className="btn ghost"
                    onClick={() => {
                      setFile(null)
                      setJob(null)
                    }}
                  >
                    Import another file
                  </button>
                </div>
              )}
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
            <li>
              Download the archive and unzip it. Inside, select{' '}
              <strong>watched.csv</strong> — that file is your full watch
              history and the one we recommend uploading.
            </li>
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
