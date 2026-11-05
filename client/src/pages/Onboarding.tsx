import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../lib/api'
import { createConversation, sendMessage } from '../lib/conversations'
import { addFilm, getImportJob, importLetterboxd, searchFilms } from '../lib/films'
import type { ImportJob, SearchResult } from '../lib/films'

// Onboarding (mockup flow): import → pick ≥5 films that stayed with you →
// one "a little about you" question → first reflection prompt → Home.
// Every step is skippable; finishing (or skipping) marks onboarding complete
// on the profile row so existing users never see this again.
const STEPS = ['Import', 'Your films', 'About you', 'First reflection'] as const
const MIN_PICKS = 5
const ABOUT_QUESTION =
  'A little about you — what draws you to films? A mood, a memory, a kind of story you keep returning to…'

export default function Onboarding() {
  const { completeOnboarding } = useAuth()
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [error, setError] = useState('')
  const [finishing, setFinishing] = useState(false)

  // Step 1 — Letterboxd import
  const [file, setFile] = useState<File | null>(null)
  const [job, setJob] = useState<ImportJob | null>(null)
  const [importing, setImporting] = useState(false)

  // Step 2 — film picker
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [picked, setPicked] = useState<SearchResult[]>([])
  const [savingPicks, setSavingPicks] = useState(false)

  // Step 3 — about you
  const [about, setAbout] = useState('')

  // Step 4 — first reflection
  const [starting, setStarting] = useState(false)

  async function finish() {
    if (finishing) return
    setFinishing(true)
    setError('')
    try {
      await completeOnboarding()
      navigate('/app', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not finish onboarding.')
      setFinishing(false)
    }
  }

  // ---- Step 1: import ----
  const importActive = job?.status === 'queued' || job?.status === 'processing'

  useEffect(() => {
    const id = job?.id
    if (!id || !importActive) return
    const timer = window.setInterval(() => {
      getImportJob(id).then(setJob).catch(() => undefined)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [job?.id, importActive])

  async function runImport() {
    if (!file) return
    setImporting(true)
    setError('')
    try {
      const started = await importLetterboxd(file)
      setJob(await getImportJob(started.import_id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start the import')
    } finally {
      setImporting(false)
    }
  }

  // ---- Step 2: film picker ----
  useEffect(() => {
    const q = query.trim()
    if (q.length < 2) {
      setResults([])
      setSearching(false)
      return
    }
    setSearching(true)
    const timer = setTimeout(() => {
      searchFilms(q)
        .then((res) => setResults(res.results))
        .catch(() => setResults([]))
        .finally(() => setSearching(false))
    }, 350)
    return () => clearTimeout(timer)
  }, [query])

  const isPicked = (tmdbId: number) => picked.some((p) => p.tmdb_id === tmdbId)

  function togglePick(film: SearchResult) {
    setPicked((current) =>
      isPicked(film.tmdb_id)
        ? current.filter((p) => p.tmdb_id !== film.tmdb_id)
        : [...current, film],
    )
  }

  async function savePicks() {
    if (savingPicks) return
    setSavingPicks(true)
    setError('')
    try {
      // Selections are added as watched. The watched-wins rule keeps any
      // already-watched overlaps intact.
      for (const film of picked) {
        await addFilm(film.tmdb_id, 'watched')
      }
      setStep(2)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save your picks.')
    } finally {
      setSavingPicks(false)
    }
  }

  // ---- Step 4: first reflection ----
  async function startFirstReflection() {
    if (starting) return
    setStarting(true)
    setError('')
    try {
      await completeOnboarding()
      const res = await createConversation({
        type: 'reflection',
        title: 'A little about me',
      })
      // The "about you" answer seeds the conversation as the first message.
      if (about.trim()) await sendMessage(res.conversation.id, about.trim())
      navigate(`/app/reflections/${res.conversation.id}`, { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start your reflection.')
      setStarting(false)
    }
  }

  return (
    <div className="onboarding">
      <p className="brand">NOACF</p>
      <div className="pills" style={{ justifyContent: 'center' }}>
        {STEPS.map((label, i) => (
          <span key={label} className={`pill${i === step ? ' active' : ''}`}>
            {i + 1}. {label}
          </span>
        ))}
      </div>
      {error && <p className="form-error">{error}</p>}

      {step === 0 && (
        <section className="card onboarding-card">
          <h1 className="page-title">Bring your film history</h1>
          <p className="muted">
            Already track films on Letterboxd? Import your history so NOACF
            knows what you've seen from day one.
          </p>
          <p className="import-tip">
            <strong>Recommended:</strong> choose <strong>watched.csv</strong> from
            the unzipped Letterboxd export — it contains your complete watch
            history.
          </p>
          <div className="upload-zone">
            <strong>{file ? file.name : 'Choose your watched.csv'}</strong>
            <input
              type="file"
              accept=".csv,text/csv"
              hidden
              id="onboarding-import"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null)
                setJob(null)
                setError('')
              }}
            />
            <div className="row" style={{ marginTop: '0.75rem' }}>
              <label className="btn ghost" htmlFor="onboarding-import">
                Choose CSV file
              </label>
              <button
                className="btn primary"
                disabled={!file || importing || importActive}
                onClick={runImport}
              >
                {importing
                  ? 'Uploading…'
                  : importActive
                    ? `Importing… ${job?.processed_rows ?? 0}/${job?.total_rows ?? 0}`
                    : job
                      ? 'Import another'
                      : 'Import'}
              </button>
            </div>
          </div>
          {job && !importActive && (
            <p className="muted">
              {job.status === 'completed' || job.status === 'completed_with_errors'
                ? `Imported ${job.added} films (${job.unmatched_count} unmatched).`
                : 'Import paused — you can resume it later from the Import page.'}
            </p>
          )}
          <div className="row onboarding-nav">
            <button className="link-button" onClick={() => setStep(1)}>
              Skip this step →
            </button>
            <button className="btn primary" onClick={() => setStep(1)}>
              Continue →
            </button>
          </div>
        </section>
      )}

      {step === 1 && (
        <section className="card onboarding-card">
          <h1 className="page-title">Films that stayed with you</h1>
          <p className="muted">
            Pick at least {MIN_PICKS} films that left a mark. We'll add them to
            your library as watched.
          </p>
          <div className="search-input">
            <span aria-hidden>⌕</span>
            <input
              value={query}
              placeholder="Search films…"
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          {searching && <p className="muted">Searching…</p>}
          {results.length > 0 && (
            <div className="picker-grid">
              {results.slice(0, 8).map((film) => (
                <button
                  key={film.tmdb_id}
                  className={`pick-card${isPicked(film.tmdb_id) ? ' selected' : ''}`}
                  onClick={() => togglePick(film)}
                >
                  <span className="film-poster">
                    {film.poster_url ? (
                      <img src={film.poster_url} alt={film.title} loading="lazy" />
                    ) : (
                      <span className="no-poster">{film.title}</span>
                    )}
                    {isPicked(film.tmdb_id) && <span className="pick-check">✓</span>}
                  </span>
                  <p>
                    {film.title}
                    {film.year ? ` (${film.year})` : ''}
                  </p>
                </button>
              ))}
            </div>
          )}
          <p className="muted">
            {picked.length} of {MIN_PICKS} selected
            {picked.length > 0 &&
              ` — ${picked.map((p) => p.title).slice(0, 3).join(', ')}${picked.length > 3 ? '…' : ''}`}
          </p>
          <div className="row onboarding-nav">
            <button className="link-button" onClick={() => setStep(2)}>
              Skip this step →
            </button>
            <button
              className="btn primary"
              disabled={picked.length < MIN_PICKS || savingPicks}
              onClick={savePicks}
            >
              {savingPicks ? 'Saving…' : 'Continue →'}
            </button>
          </div>
        </section>
      )}


      {step === 2 && (
        <section className="card onboarding-card">
          <h1 className="page-title">A little about you</h1>
          <p className="muted">{ABOUT_QUESTION}</p>
          <textarea
            className="insight-edit"
            rows={4}
            maxLength={500}
            placeholder="Write as much or as little as you like…"
            value={about}
            onChange={(e) => setAbout(e.target.value)}
          />
          <div className="row onboarding-nav">
            <button className="link-button" onClick={() => setStep(3)}>
              Skip this step →
            </button>
            <button className="btn primary" onClick={() => setStep(3)}>
              Continue →
            </button>
          </div>
        </section>
      )}

      {step === 3 && (
        <section className="card onboarding-card">
          <h1 className="page-title">Your first reflection</h1>
          <p className="muted">
            Ready to begin? We'll open your first reflection
            {about.trim()
              ? ' with what you just told us as the starting point.'
              : ' — pick any film that’s on your mind.'}{' '}
            There are no wrong answers; it's a conversation, not a review.
          </p>
          <div className="row onboarding-nav">
            <button className="link-button" disabled={finishing} onClick={finish}>
              {finishing ? 'Finishing…' : 'Skip to Home →'}
            </button>
            <button className="btn primary" disabled={starting} onClick={startFirstReflection}>
              {starting ? 'Opening…' : 'Start my first reflection →'}
            </button>
          </div>
        </section>
      )}
    </div>
  )
}

