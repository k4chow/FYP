# NOACF — Setup and Testing

> No real credentials are included here. Replace every placeholder with your
> own development values. Never commit `.env`, Supabase service-role keys, TMDB
> keys, account passwords, or bearer tokens.

## 0. Production deployment (AWS)

The app is deployed on the shared lab AWS box (`cp1.latte-lab.org`, Ubuntu
24.04) at **https://cp1.latte-lab.org/noacf/** — path-based hosting on the
lab domain, which already has a certbot TLS certificate, so no separate
domain or DNS setup is needed:

- Code: `~/noacf` (git clone of this repository; `git pull` to update).
- Backend: `noacf.service` (systemd) runs uvicorn from
  `~/noacf/server/.venv` on `127.0.0.1:8001`. Env vars live in
  `~/noacf/server/.env` (same keys as local). Logs: `journalctl -u noacf`.
- Client: built on the server with the sub-path base
  (`VITE_API_URL=https://cp1.latte-lab.org/noacf-api npm run build --
  --base=/noacf/`; React Router picks the base up via
  `import.meta.env.BASE_URL`). Output in `~/noacf/client/dist`.
- nginx: two `location` blocks inside the existing `cp1.latte-lab.org` site
  (`/etc/nginx/sites-enabled/reflexia`): `/noacf/` serves `dist` with SPA
  fallback to `/noacf/index.html`, and `/noacf-api/` proxies to the backend
  with the prefix stripped. The unrelated `reflexia` app keeps `/` and
  `/api/` — do not remove its blocks.
- A dedicated domain (finnickodairisalive.com) was considered but never
  registered; if one is ever pointed at the server, serve `dist` at the root
  with base `/` and proxy `/api/` instead of the path setup.

`OPENAI_MODEL=gpt-6.1-luna` must be present in `~/noacf/server/.env` (the
server reads it from `.env` / its process environment).

To deploy an update:

```bash
cd ~/noacf && git pull
cd server && .venv/bin/python scripts/backfill_keywords.py   # one-off: cache TMDB keywords for film themes
cd server && .venv/bin/pip install -r requirements.txt   # if deps changed
sudo systemctl restart noacf                             # if server code changed
cd ../client && npm install && \
  VITE_API_URL=https://cp1.latte-lab.org/noacf-api npm run build -- --base=/noacf/
```

## 1. Prerequisites
## 1. Prerequisites

- Python 3.12 with `venv` and `pip` (the project’s documented runtime).
- A current Node.js/npm version compatible with the installed Vite 8 toolchain.
- A Supabase project with Postgres and Auth enabled.
- A TMDB API key for live film search/details. It is not needed to import the
  Python modules or run the mocked large-import unit suite, but live TMDB calls
  fail without it.
- Git and a terminal. Commands below use Windows PowerShell conventions;
  `npm.cmd` avoids PowerShell script-policy issues.
- Optional: SMTP configured in Supabase for actual forgot-password emails.

No external LLM account is needed: the only implemented provider is the
in-process deterministic mock.

## 2. Repository layout

```text
FYP/
  client/                 React + Vite + TypeScript
  server/
    app/                  FastAPI application and workers
    scripts/              Automated and live verification scripts
    requirements.txt
    .env.example
  supabase/migrations/    SQL schema, in execution order
  docs/                   Requirements, architecture, decisions, testing
```

## 3. Database setup

Run these files in the Supabase SQL editor, in order:

1. `supabase/migrations/0001_init.sql` — core tables, constraints, indexes, RLS.
2. `supabase/migrations/0002_conversation_context.sql` — conversation
   `watch_type` and `ended_at`.
3. `supabase/migrations/0003_import_jobs.sql` — persistent import jobs and RLS.

The scripts use `if not exists` for tables/indexes/columns, but policy creation
is not idempotent; do not blindly rerun a completed migration. There is no
Supabase CLI or migration runner configured in the repository, so SQL-editor
execution is the verified setup method.

Development sign-up uses `email_confirm=True`. For a public deployment, review
that choice and enable proper email verification/SMTP rather than copying the
development behavior unchanged.

## 4. Backend setup

From `server/`:

```powershell
cd C:\Users\cheri\Projects\FYP\server
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `server/.env` with your own values:

```dotenv
TMDB_API_KEY=<your_tmdb_key>
SUPABASE_URL=https://<your-project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<your_service_role_key>
LLM_PROVIDER=mock
```

Optional settings supported by `server/app/config.py`:

```dotenv
LLM_CONTEXT_MESSAGES=12
LLM_CONTEXT_MEMORIES=5
CORS_ORIGINS=["http://localhost:5173"]
```

`LLM_PROVIDER=mock` is currently the only valid provider value. Do not set an
invented OpenAI model/key; no such provider exists in the code.

Start FastAPI from `server/`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Useful URLs: `http://localhost:8000/health` (liveness/version) and
`http://localhost:8000/docs` (Swagger). On startup,
`recover_import_jobs()` looks for queued/processing imports and resumes them.
The service-role key is required at module import time.

## 5. Frontend setup

From `client/`:

```powershell
cd C:\Users\cheri\Projects\FYP\client
npm.cmd install
npm.cmd run dev
```

Vite defaults to `http://localhost:5173`. The client uses
`http://localhost:8000` for the API by default. To target another backend, set
this in `client/.env.local` (not committed):

```dotenv
VITE_API_URL=http://localhost:8000
```

The client deliberately has no Supabase URL/key or TMDB key configuration.

Production verification:

```powershell
npm.cmd run build
npm.cmd run lint
```

`build` runs `tsc -b && vite build`; `lint` runs oxlint. The build has passing
verification evidence from development. The lint command is available, but no
saved lint report is included in the repository, so this document does not
claim a particular lint result. `npm.cmd run preview` serves the production
build locally.

## 6. Automated tests

### 6.1 Isolated large-import suite

From `server/`:

```powershell
.\.venv\Scripts\python.exe scripts\test_large_import.py
```

This built-in `unittest` suite uses an in-memory Supabase fake and mocked TMDB.
It makes no real TMDB calls and changes no live rows. It covers:

- 1,600 valid rows and exact persisted outcome counts;
- repeat-import idempotency and duplicate handling;
- unmatched versus updated/existing films;
- malformed CSV values and user isolation;
- mid-import checkpoint failure and resume;
- transient row failure followed by resume;
- 429 backoff, jitter, and maximum attempts;
- 1,600-row library API pagination.

Expected result: 7 tests, `OK`. Saved evidence:
`server/scripts/test_large_import_output.txt`.

### 6.2 Live conversation E2E

With Supabase and Uvicorn running:

```powershell
.\.venv\Scripts\python.exe scripts\e2e_phase3.py
```

This logs in through the API and exercises conversation creation, deterministic
openings/replies, verbatim messages, quick replies, blank validation, free and
planning reflections, bounded context helpers, unknown ids, ending/idempotency,
409-after-end, and status filters. Saved result: 34/34 checks in
`server/scripts/e2e_phase3_output.txt`.

The script creates conversation/message fixtures in the target development
account and does not delete them. Use a throwaway account/project, not a
personal or production one.

### 6.3 Live import verification

```powershell
.\.venv\Scripts\python.exe scripts\e2e_import_live.py
```

This verifies prompt 202 creation, background completion, added/duplicate/
unmatched counts, auth/unknown-job behavior, completed-resume validation, and a
single persisted row for duplicate CSV rows. It cleans its added library
fixture and job in `finally`. Saved evidence:
`server/scripts/e2e_import_live_output.txt`.

The intentionally unmatched row causes live TMDB searches. This is not a
fully mocked test; run it only against the intended development project.

### 6.4 Live 1,600-row pagination verification

```powershell
.\.venv\Scripts\python.exe scripts\e2e_library_pagination.py
```

This inserts 1,600 temporary catalogue/library fixtures directly, calls the
paginated endpoint until completion, verifies all fixture rows and totals, then
deletes only fixtures in its dedicated high TMDB-id range. The saved run returned
1,608 baseline-plus-fixture rows in pages of 500/500/500/108 and restored the
baseline (`e2e_library_pagination_output.txt`). Use only a disposable test
project and inspect the script before running it elsewhere.

### 6.5 Live guided insight review E2E (Phase 4)

With Supabase and Uvicorn running:

```powershell
.\.venv\Scripts\python.exe scripts\e2e_phase4.py
```

This exercises the full F3 flow: ending a reflection generates validated
proposed memories with `source_message_ids`; `GET /memories` status filters;
`GET /conversations/{id}/memories`; and `PATCH /memories/{id}` confirm,
edit-then-confirm (wording changes, source links preserved), and reject. It
also verifies cross-user isolation (a second temporary account, deleted
afterwards), invalid transitions/input, idempotent repeat ending, that ending
and reviewing never modify the append-only messages, that malformed provider
output cannot create invalid rows, and that empty reflections end without
proposals. Saved result: 40/40 checks in `server/scripts/e2e_phase4_output.txt`.

**Credential note:** the live scripts currently target a development test
account configured in source. Those values are intentionally not reproduced in
this document. Use a throwaway account and prefer moving live-test credentials
to environment variables before sharing scripts more broadly.

### 6.6 Live recommendations + questionnaire E2E (Phase 6)

```powershell
cd server
.\.venv\Scripts\python.exe scripts\e2e_phase6.py
```

Creates a disposable user, seeds films and a confirmed memory, and exercises
recommendations, feedback, the style slider, the Film Assistant chat, and the
onboarding questionnaire (`POST /profile/questionnaire` → confirmed
preferences in `/profile/summary`). Saved result: 25/25 checks in
`server/scripts/e2e_phase6_output.txt`.

### 6.7 Isolated Phase 7 suite (explicit constraints + ephemeral assistant)

```powershell
cd server
.\.venv\Scripts\python.exe scripts\test_phase7.py
```

This built-in `unittest` suite reuses the in-memory Supabase `FakeStore` from
`test_large_import.py` and mocks TMDB/LLM, so it makes no live requests and
writes no rows. It covers (13 tests):

- F12 explicit-constraint parsing: a director ("…by Paul Thomas Anderson"), a
  named title ("recommend me Thor: Ragnarok"), and a genre, each validated
  against TMDB so only names that actually appear in the message are accepted;
- constrained candidate-pool rebuild for a director/genre, without mutating the
  Discover engine's `_cache` or `_last_served` state;
- named-film answers that are never refused: a film the user named is offered
  directly, and a film already in their library returns close alternatives;
- the stateless `discovery_turn`: it returns a reply and recommendations and
  writes no `conversations`/`messages` rows, so the ephemeral Film Assistant
  leaves reflection history and the Discover grid untouched.

Expected result: 13 tests, `OK`.

## 7. Manual feature verification

### Auth

1. Sign up with a new development email; confirm the app opens Home without an
   email-verification step (development behavior).
2. Log out, log in, and refresh: `/auth/me` should restore the session.
3. Change the password in Settings and log in with the new password.
4. Request a reset email. The UI request succeeds generically; delivery depends
   on Supabase SMTP, so do not treat the response as proof of email delivery.

### Film library and TMDB

1. Add a film through the modal, select watched or watchlist, and verify it in
   My Films and Home’s recently added row.
2. Add the same film again: the database should keep one user/film row.
3. Verify search/status/sort and Remove from library. Check that another
   account cannot see or remove the first account’s films.
4. For a large library, confirm all pages load; filtering is client-side after
   aggregation.

### Letterboxd import

1. Use a small CSV first. Confirm POST returns quickly and the page shows
   queued/processing progress rather than waiting for the entire file.
2. Verify added, updated, duplicate/already-current, unmatched, and temporary
   failure counts independently. Unmatched does not mean retryable failure.
3. Refresh the page during an import: the saved import id should restore job
   progress. Restart Uvicorn during a test import in a disposable project and
   verify startup recovery resumes queued/processing work.
4. If temporary failures occur, use “Retry failed and remaining rows” and check
   that successful work is not intentionally rematched.
5. Repeat the same import: no duplicate library rows should appear.

### Reflection chat

1. Start from Home’s prompt, from a library film, or from Add a film → Start a
   reflection. Check the appropriate seen/planning opening.
2. Send ordinary text and each quick-reply chip. Reload the page and verify the
   exact history returns, including the assistant opening.
3. Repeat the same message in a fresh conversation of the same film: the mock
   samples its questions from prompt banks (D27), so a fresh session should
   usually ask DIFFERENT questions — no fixed sequence, no immediate
   repetition within one session.
4. End the reflection twice and verify it stays completed; further messages are
   rejected. Resume active conversations from My Reflections.
5. Confirm the UI labels guided review as Phase 4. No proposed memories should
   be claimed or expected yet.

### Explicitly incomplete checks

- There is no mood input or mood-aware recommendation behaviour to test.

### Onboarding (D38 flow)

1. Sign up with a fresh account: you land on onboarding automatically
   (`onboarding_completed = false` routes everything there).
2. Import step: the UI recommends `watched.csv`; it is the ONLY skippable
   step ("Skip this step →" continues without importing).
3. Your films: no skip — the continue button stays disabled until ≥5 films
   are picked via search (added as watched).
4. First reflection: no skip — the step suggests films from your library
   (watched and highly rated first); the search box lets you pick any other
   film. Starting opens the normal reflection chat with `?onboarding=1`.
5. End the reflection: you return to onboarding's About-you questionnaire
   (not the review flow). All three answers are required; opening
   `/onboarding?step=3` directly without ≥5 films and a completed reflection
   bounces you back to the missing step.
6. My Profile should now list the answers as confirmed preferences with the
   explanation "You wrote this about yourself.", and Home no longer redirects
   to onboarding.

Phase 6 surfaces that SHOULD now work: Discover cards with why-lines and a
"Why am I seeing this?" panel, More like this / Not for me feedback that
visibly changes the next load, the Settings recommendation-style slider
(persists via `/profile/preferences`), and the Film Assistant discovery chat.
These require migration `0005_recommendations.sql` applied to Supabase first.

## 8. Troubleshooting

- **Server fails at startup about Supabase settings:** check `server/.env` for
  `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`; these are mandatory.
- **401 from protected routes:** verify the bearer token is present and valid;
  `/auth/me` uses the same validation path.
- **TMDB 500/502 errors:** check the key and TMDB availability/rate limits.
  Existing cached films can still be read; uncached searches/details may fail.
- **Import job missing after migration:** apply all three SQL files in order.
  Startup recovery intentionally logs and skips recovery if the table is absent,
  but import endpoints require it.
- **Only part of a large library appears:** use the updated client/server and
  check `total`, `limit`, and `offset` in `/films/mine`. The old unpaginated flow
  could truncate at 1,000 rows.
- **No chat history after ending:** ending does not delete history. Load the
  completed conversation again. No memory extraction should be expected.
- **PowerShell blocks npm:** use `npm.cmd` as shown above.
- **GitHub push is unrelated to app tests:** documentation changes do not require
  a commit or push unless explicitly requested.

## 9. Test-evidence limitations

The saved outputs are useful development evidence, not a complete acceptance
suite. Missing coverage includes browser/component tests, direct RLS tests for
every table, real LLM behavior, memory lifecycle, recommendations, live/browser
E2E for the ephemeral Phase 7 assistant endpoints, accessibility,
production deployment, and concurrent multi-worker import behavior. The
repository’s `docs/07-evaluation.md` remains a plan for later evaluation rather
than a record of completed user research.
