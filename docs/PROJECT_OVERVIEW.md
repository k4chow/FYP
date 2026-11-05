# NOACF — Project Overview

> **Verification basis:** current implementation in `client/`, `server/`, and
> `supabase/migrations/`, plus project notes in `docs/01-requirements.md` and
> `docs/03-design-decisions.md`. This document distinguishes working behavior
> from mockups and plans; it does not treat a mockup as proof of implementation.

## 1. Purpose

NOACF (“Not Only A Cinephile”) is a reflection-first personal film journal. Its
purpose is to help a user record not only *what* they watched, but *what the
film meant to them*. The intended thesis differentiator is a user-controlled
reflective profile derived from conversations, which would later support
explainable recommendations and conversational discovery.

The application is **not** intended to infer mental-health states from film
preferences (requirement N5 in `docs/01-requirements.md`). The current code does
not perform such inference.

## 2. Goals and current scope

### Implemented and usable

- Email/password sign-up, login, logout, current-user restoration, password
  change, and a forgot-password request flow (`server/app/routers/auth.py`,
  `client/src/auth/AuthContext.tsx`).
- A shared film catalogue backed by TMDB metadata and posters, plus per-user
  watched/watchlist libraries (`server/app/routers/films.py`).
- Film search, details, adding, updating through the API, and removing from the
  library. The UI directly exposes search/add/remove; rating/date updates are
  API capabilities rather than a complete editing UI.
- Large Letterboxd CSV imports as persistent, resumable background jobs with
  progress and per-row outcomes (`server/app/import_jobs.py`).
- Reflection conversations linked to a film or a free-form daily prompt. Chat
  history is persisted, can be resumed, and can be ended.
- A deterministic mock assistant that produces reflective questions without a
  model API key (`server/app/llm/mock.py`).
- Paginated library retrieval so libraries larger than 1,000 rows are not
  silently truncated (`GET /films/mine`, `client/src/lib/films.ts`).

### Implemented but mocked or partial

- **The assistant is not a real AI model.** `MockLLMProvider` selects templates
  and keywords deterministically. No external LLM request is made.
- **Insight extraction is scripted, not learned.** Ending a reflection runs
  `MockLLMProvider.extract_insights`, which derives at most five proposals from
  keyword signals and conversation stats; the server validates and stores them
  as `proposed` memories for the Review & Edit screen (confirm, edit, reject,
  "Why am I seeing this?").
- Home’s “Your profile themes” values are hard-coded placeholders
  (`client/src/pages/Home.tsx`).
- Home’s prompt of the day is a client-side seven-item rotation, not an
  AI-generated or personalized prompt.

### Planned / absent in the current code

- Contradiction resolution between stored insights.
- A reflective profile UI and real themes/insights on Home (Phase 5).
- Mood-based recommendations (no mood field, extraction, or scoring). The rest
  of Phase 6 is done: `/app/discover` renders the deterministic recommendation
  engine with why-lines, feedback toggles, and a Film Assistant discovery chat;
  the Settings style slider is live (`/profile/preferences`).
- The full guided onboarding sequence from the notes; sign-up and import exist,
  but mandatory film selection and the about-you step are not implemented.
- Formal usability evaluation and Phase 7 results (`docs/07-evaluation.md`).

## 3. Main user flows that exist

### 3.1 Account and session

1. The user signs up or logs in through React.
2. FastAPI calls Supabase Auth using `auth_client`; sign-up also creates the
   `public.users` profile and signs the user in.
3. The returned access token is stored in browser `localStorage` under
   `noacf_token` (`client/src/lib/api.ts`).
4. `AuthProvider` calls `GET /auth/me` on startup to restore the session.
5. Authenticated API calls send `Authorization: Bearer <token>`. FastAPI
   verifies it in `get_current_user` (`server/app/deps.py`).

Forgot-password calls Supabase’s reset-email function and returns success
without revealing whether the account exists. Actual email delivery requires
SMTP configuration in Supabase; it is not guaranteed by application code.
Development sign-up uses `email_confirm=True`, so email confirmation is not
required in the current development flow.

### 3.2 Add and browse films

1. In Add a film or Add a Reflection, a debounced search calls
   `GET /films/search?q=...`.
2. FastAPI queries TMDB and returns at most eight simplified results.
3. Selecting a result calls `GET /films/tmdb/{tmdb_id}` for genres, runtime,
   overview, poster, and current library status.
4. Saving calls `POST /films/mine`; `_ensure_film` caches the TMDB details in the
   shared `films` table and upserts the user’s `user_films` relationship.
5. My Films loads every page of `GET /films/mine`, then applies search, status
   filters, and sorting client-side (`client/src/pages/MyFilms.tsx`).

The server also exposes `PATCH /films/mine/{user_film_id}` and
`DELETE /films/mine/{user_film_id}`. The current card menu uses DELETE; PATCH is
available to API clients but is not a full edit form in the UI.

### 3.3 Letterboxd import

1. The user selects an unzipped Letterboxd `diary.csv`, `ratings.csv`,
   `watched.csv`, or `watchlist.csv` (maximum 5 MB).
2. `POST /import/letterboxd` validates UTF-8 CSV and `Name`/`Year` columns,
   normalizes only name/year/rating/watched date, inserts an `import_jobs` row,
   and returns **202** with an `import_id`.
3. `launch_import` starts a daemon thread. `run_import_job` claims the queued
   job, prefetches the user’s library in 1,000-row pages, and processes 20-row
   batches.
4. Each title is matched local-catalogue-first, then TMDB title+year, then TMDB
   title-only. Successful library writes upsert `user_films`.
5. After every batch, outcomes, counters, and `next_row` are checkpointed.
   Polling `GET /import/{id}` returns progress without exposing the stored CSV
   payload. The browser stores only the job id so a refresh restores progress.
6. Unmatched titles and temporary failures are separate outcomes. Failed or
   stale jobs can be resumed; queued/processing jobs are also recovered on
   startup (`recover_import_jobs`).

Outcome meanings: **added** = new library row; **updated** = an existing row
changed; **duplicates** = repeat CSV row or already-current row; **unmatched** =
no film found; **failed** = retryable TMDB/DB error. A film has only one
`user_films` row, so repeat viewings collapse. First-result TMDB matching can be
wrong for ambiguous titles; there is no fuzzy-match review UI.

### 3.4 Start, resume, and end a reflection

1. Add a Reflection accepts a library film, TMDB result, or Home prompt. Film
   choices include `seen` or `planning` watch context.
2. `POST /conversations` creates the conversation and persists an assistant
   opening as the first message.
3. `POST /conversations/{id}/messages` stores user text verbatim, assembles the
   last 12 messages plus at most 5 confirmed memories, invokes the mock, and
   stores its reply.
4. My Reflections lists active/completed conversations. Opening one loads full
   history for display; the bounded window applies only to assistant context.
5. End reflection sets `status='completed'` and `ended_at`. Repeat end calls are
   safe; further messages return 409.

“First time watching”/“Rewatch” is UI-only; both map to `seen`. The completion
screen says guided insight review arrives in Phase 4—it does not extract
memories.

## 4. Requirements traceability (verified)

| Requirement | Current status | Evidence / qualification |
|---|---|---|
| F1 Persistent verbatim history | **Implemented** | `conversations.py`, `messages`, Phase 3 E2E |
| F2 Reflective profile | **Schema only / planned** | `memories` exists; profile UI is a placeholder |
| F3 User-controlled insights | **Planned** | Status constraints exist; no review endpoints/UI |
| F4 Bounded assistant context | **Implemented** | `context.py`; 12 messages + 5 confirmed memories |
| F5 Swappable LLM provider | **Interface + mock implemented** | `LLMProvider`; no real provider |
| F6 Letterboxd import | **Implemented** | Persistent jobs, resume, unit and live tests |
| F7 Film catalogue | **Implemented** | TMDB, shared cache, library CRUD/pagination |
| F8–F11 Recommendations/discovery | **Not implemented** | No recommendation service, explanations, or feedback |
| F12 Auth | **Implemented with dev caveat** | Supabase Auth; sign-up auto-confirmed in dev |

Non-functional status: RLS and gitignored secrets are implemented; the
service-role architecture still requires careful owner filtering. pgvector is
deferred. Recommendation-style controls and mental-health-specific memory rules
remain future work. Full account/data-retention controls are absent.

## 5. Known limitations and maintenance risks

1. **No real model behavior.** Mock replies can sound reflective but do not
   understand a film or user. No real model prompts, safety filters, or generated
   recommendations should be claimed in evaluation.
2. **Memory is mostly a schema seam.** Confirmed rows would be read into chat,
   but there is no implemented way to create, confirm, edit, reject, or forget
   them through the application.
3. **Background jobs use daemon threads**, not a distributed queue. This fits a
   single-process development server, not proof of multi-server scalability.
   Per-batch JSONB writes and per-row external calls also remain substantial.
4. **Crash-window counters:** if a process stops after library upserts but
   before a checkpoint, resume treats those rows as duplicates. Final counters
   are job outcomes, not a guaranteed historical insertion audit.
5. **Retention controls are incomplete.** Messages, memories, catalogue rows,
   and import jobs have no scheduled deletion or user-facing retention policy.
6. **Some lists are not paginated** (`GET /conversations` and full message
   history), and My Films loads all pages before client-side filtering. This is
   verified at 1,600 rows but may need a different UX at larger scales.
7. **Test coverage is uneven.** Import and conversation flows have scripted
   evidence; there are no client component tests, real-provider tests,
   memory-lifecycle tests, recommendation tests, or multi-worker import stress
   tests in the repository.
8. **Development choices need review before deployment:** sign-up is
   auto-confirmed and the bearer token is stored in localStorage.

## 6. Verification evidence in the repository

- `server/scripts/test_large_import_output.txt`: 7/7 tests pass, including a
  1,600-row mocked-TMDB import and failure/resume cases.
- `server/scripts/e2e_phase3_output.txt`: 34/34 conversation checks pass.
- `server/scripts/e2e_import_live_output.txt`: live background import and
  duplicate/unmatched/auth checks pass, followed by fixture cleanup.
- `server/scripts/e2e_library_pagination_output.txt`: all 1,608 baseline-plus-
  fixture rows were returned over four pages, then baseline was restored.
- `npm.cmd run build` (`tsc -b && vite build`) verifies the client production
  build. No component/browser test suite is present.
