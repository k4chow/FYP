import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../lib/api'
import { createConversation } from '../lib/conversations'
import { addFilm, getImportJob, getMyFilms, importLetterboxd, searchFilms } from '../lib/films'
import type { ImportJob, LibraryFilm, SearchResult } from '../lib/films'
import { saveQuestionnaire } from '../lib/profile'

// Onboarding (mockup flow, D38): import Letterboxd → pick ≥5 films that
// stayed with you → pick ONE film for your first reflection (suggested from
// your films; searching for another is fine) → after that reflection ends,
// an about-you questionnaire whose answers build the profile as confirmed
// preferences. Every step is skippable; finishing (or skipping) marks
// onboarding complete on the profile row so existing users never see this.
const STEPS = ['Import', 'Your films', 'First reflection', 'About you'] as const
const MIN_PICKS = 5
const MAX_SUGGESTIONS = 8
const QUESTIONNAIRE = [
  'What kinds of stories do you keep coming back to?',
  'How do you want a film to leave you feeling?',
  'What makes a film stay with you long after the credits roll?',
] as const

interface ReflectionPick {
  tmdb_id: number
  title: string
  year: number | null
  poster_url: string | null
  status: 'watched' | 'watchlist' | null
}

export default function Onboarding() {
  const { completeOnboarding } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  // Returning from the first reflection chat lands on ?step=3 (About you).
  const requested = Number.parseInt(searchParams.get('step') ?? '', 10)
  const [step, setStep] = useState(
    Number.isInteger(requested) && requested >= 0 && requested < STEPS.length ? requested : 0,
  )
  const [error, setError] = useState('')
  const [finishing, setFinishing] = useState(false)

  // Step 1 — Letterboxd import
  const [file, setFile] = useState<File | null>(null)
  const [job, setJob] = useState<ImportJob | null>(null)
  const [importing, setImporting] = useState(false)

  // Step 2 — film picker (shared search state is reused by step 3)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [picked, setPicked] = useState<SearchResult[]>([])
  const [savingPicks, setSavingPicks] = useState(false)

  // Step 3 — pick one film for the first reflection
  const [library, setLibrary] = useState<LibraryFilm[] | null>(null)
  const [pick, setPick] = useState<ReflectionPick | null>(null)
  const [starting, setStarting] = useState(false)

  // Step 4 — about-you questionnaire
  const [answers, setAnswers] = useState<string[]>(() => QUESTIONNAIRE.map(() => ''))
  const [savingAnswers, setSavingAnswers] = useState(false)

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


  // ---- Film search (steps 2 & 3) ----
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

  // ---- Step 2: film picker ----
  const isPicked = (tmdbId: number) => picked.some((p) => p.tmdb_id === tmdbId)

  function togglePick(film: SearchResult) {
    setPicked((current) =>
      isPicked(film.tmdb_id)
        ? current.filter((p) => p.tmdb_id !== film.tmdb_id)
        : [...current, film],
    )
  }

  function goToReflectionStep() {
    setQuery('')
    setResults([])
    setStep(2)
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
      goToReflectionStep()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save your picks.')
    } finally {
      setSavingPicks(false)
    }
  }

  // ---- Step 3: first reflection ----
  useEffect(() => {
    if (step !== 2 || library !== null) return
    getMyFilms()
      .then((res) => setLibrary(res.films))
      .catch(() => setLibrary([]))
  }, [step, library])

  // Suggest the user's own films: watched first, then highest rated, newest.
  const suggestions = (library ?? [])
    .filter((f) => f.tmdb_id != null)
    .sort(
      (a, b) =>
        (a.status === 'watched' ? 0 : 1) - (b.status === 'watched' ? 0 : 1) ||
        (b.rating ?? -1) - (a.rating ?? -1) ||
        b.added_at.localeCompare(a.added_at),
    )
    .slice(0, MAX_SUGGESTIONS)

  async function startReflection() {
    if (!pick || starting) return
    setStarting(true)
    setError('')
    try {
      const res = await createConversation({
        type: 'reflection',
        tmdb_id: pick.tmdb_id,
        watch_type: pick.status === 'watchlist' ? 'planning' : 'seen',
      })
      // Ending this reflection returns here at the About-you step (D38).
      navigate(`/app/reflections/${res.conversation.id}?onboarding=1`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start your reflection.')
      setStarting(false)
    }
  }

  // ---- Step 4: about-you questionnaire ----
  async function submitQuestionnaire() {
    if (savingAnswers) return
    setSavingAnswers(true)
    setError('')
    try {
      const payload = QUESTIONNAIRE.map((question, i) => ({
        question,
        answer: answers[i] ?? '',
      })).filter((item) => item.answer.trim())
      if (payload.length > 0) await saveQuestionnaire(payload)
      await completeOnboarding()
      navigate('/app', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save your answers.')
      setSavingAnswers(false)
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
            <button className="link-button" onClick={goToReflectionStep}>
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
          <h1 className="page-title">Your first reflection</h1>
          <p className="muted">
            Pick one film to reflect on — a recent favourite works well. These
            are suggested from your films; search below if you'd rather reflect
            on something else. It's a conversation, not a review.
          </p>
          {library === null ? (
            <p className="muted">Loading your films…</p>
          ) : suggestions.length > 0 ? (
            <div className="picker-grid">
              {suggestions.map((film) => (
                <button
                  key={film.id}
                  className={`pick-card${pick?.tmdb_id === film.tmdb_id ? ' selected' : ''}`}
                  onClick={() =>
                    setPick({
                      tmdb_id: film.tmdb_id as number,
                      title: film.title,
                      year: film.year,
                      poster_url: film.poster_url,
                      status: film.status,
                    })
                  }
                >
                  <span className="film-poster">
                    {film.poster_url ? (
                      <img src={film.poster_url} alt={film.title} loading="lazy" />
                    ) : (
                      <span className="no-poster">{film.title}</span>
                    )}
                    {pick?.tmdb_id === film.tmdb_id && <span className="pick-check">✓</span>}
                  </span>
                  <p>
                    {film.title}
                    {film.year ? ` (${film.year})` : ''}
                  </p>
                </button>
              ))}
            </div>
          ) : (
            <p className="muted">Your library is still empty — search for any film below.</p>
          )}
          <div className="search-input">
            <span aria-hidden>⌕</span>
            <input
              value={query}
              placeholder="Pick another film…"
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          {searching && <p className="muted">Searching…</p>}
          {results.length > 0 && (
            <div className="picker-grid">
              {results.slice(0, 8).map((film) => (
                <button
                  key={film.tmdb_id}
                  className={`pick-card${pick?.tmdb_id === film.tmdb_id ? ' selected' : ''}`}
                  onClick={() =>
                    setPick({
                      tmdb_id: film.tmdb_id,
                      title: film.title,
                      year: film.year,
                      poster_url: film.poster_url,
                      status: null,
                    })
                  }
                >
                  <span className="film-poster">
                    {film.poster_url ? (
                      <img src={film.poster_url} alt={film.title} loading="lazy" />
                    ) : (
                      <span className="no-poster">{film.title}</span>
                    )}
                    {pick?.tmdb_id === film.tmdb_id && <span className="pick-check">✓</span>}
                  </span>
                  <p>
                    {film.title}
                    {film.year ? ` (${film.year})` : ''}
                  </p>
                </button>
              ))}
            </div>
          )}
          <div className="row onboarding-nav">
            <button className="link-button" onClick={() => setStep(3)}>
              Skip this step →
            </button>
            <button className="btn primary" disabled={!pick || starting} onClick={startReflection}>
              {starting
                ? 'Opening…'
                : pick
                  ? `Reflect on ${pick.title} →`
                  : 'Start reflection →'}
            </button>
          </div>
        </section>
      )}

      {step === 3 && (
        <section className="card onboarding-card">
          <h1 className="page-title">A little about you</h1>
          <p className="muted">
            Last step — a few questions about you. Your answers join your
            reflective profile in your own words (editable anytime in My
            Profile) and help NOACF recommend films that fit.
          </p>
          {QUESTIONNAIRE.map((question, i) => (
            <div key={question} style={{ marginBottom: '1rem' }}>
              <p style={{ marginBottom: '0.4rem' }}>{question}</p>
              <textarea
                className="insight-edit"
                rows={3}
                maxLength={500}
                placeholder="Write as much or as little as you like…"
                value={answers[i]}
                onChange={(e) =>
                  setAnswers((current) =>
                    current.map((a, j) => (j === i ? e.target.value : a)),
                  )
                }
              />
            </div>
          ))}
          <div className="row onboarding-nav">
            <button className="link-button" disabled={finishing} onClick={finish}>
              {finishing ? 'Finishing…' : 'Skip and finish →'}
            </button>
            <button
              className="btn primary"
              disabled={savingAnswers}
              onClick={submitQuestionnaire}
            >
              {savingAnswers ? 'Saving…' : 'Save and finish →'}
            </button>
          </div>
        </section>
      )}
    </div>
  )
}
