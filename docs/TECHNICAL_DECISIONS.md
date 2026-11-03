# NOACF — Technical Decisions

> Alternatives and original justifications are drawn from
> `docs/03-design-decisions.md` (D1–D22). “Consequences” below describes the
> resulting implementation. Sections explicitly marked **Recommendation /
> inference** are not claims about prior team reasoning.

## 1. Client/server structure: React + FastAPI in a monorepo

- **Chosen:** React + Vite + TypeScript client, FastAPI server, and one
  `client/ + server/ + supabase/` repository (D1, D2, D10).
- **Alternatives considered:** Next.js or Vue; Node/Express or Django; separate
  repositories.
- **Repository rationale:** team familiarity, no SSR requirement, Vite’s minimal
  development setup, Python’s LLM/ML ecosystem, FastAPI’s OpenAPI generation,
  and a single phase-by-phase commit history at FYP scale.
- **Consequences:** `client/package.json` contains a small React/Router
  dependency set; `server/requirements.txt` contains FastAPI, supabase-py, and
  HTTP/config support. Swagger is available at `/docs`. There is no SSR,
  production reverse proxy, or separate recommendation/ML service.

## 2. Supabase Postgres and a relational schema

- **Chosen:** managed Supabase Postgres, with relational core tables and JSONB
  only for flexible metadata (D3, D4).
- **Alternatives considered:** self-hosted Postgres, Firebase, MongoDB, or full
  JSONB documents.
- **Repository rationale:** built-in Auth, RLS, SQL familiarity, a free tier,
  and integrity/queryability for users, films, conversations, and library rows.
- **Consequences:** foreign keys and uniqueness provide real integrity—for
  example `unique(user_id, film_id)` makes imports idempotent. JSONB is limited
  to TMDB extras, message metadata, memory provenance, and import-job payloads.
  Migrations are SQL files run manually in Supabase rather than an ORM migration
  framework.

## 3. Server-mediated access with two Supabase clients

- **Chosen:** the browser talks only to FastAPI; the server has separate
  `supabase` (database) and `auth_client` (Auth) instances (D9, D14).
- **Alternatives considered:** direct client→Supabase access; a single shared
  client; raw REST Auth calls.
- **Repository rationale:** one place to enforce memory/context rules. Splitting
  clients prevents sign-in state from downgrading the shared PostgREST client
  from service-role to a user JWT, which caused an actual Phase 2 failure.
- **Consequences:** the TMDB key and service-role key never need to reach the
  browser. RLS remains enabled, but service-role DB calls bypass it, so every
  route must explicitly scope by user id. The Auth dependency validates every
  protected request with `auth_client.auth.get_user(token)`.

## 4. TMDB as metadata source and local cache

- **Chosen:** TMDB search/details and poster CDN, with `films` as a shared cache
  (D7).
- **Alternatives considered:** OMDb or IMDb scraping.
- **Repository rationale:** free API key, coverage, stable API, and poster CDN.
- **Consequences:** `server/app/tmdb.py` isolates external HTTP and maps details
  to a small internal shape. `_ensure_film` avoids repeat detail fetches. Search
  itself always goes to TMDB; there is no full local search index, cache TTL, or
  metadata refresh job. TMDB failure can therefore affect uncached films while
  existing catalogue/library data remains readable.

## 5. Letterboxd-only import and deterministic matching

- **Chosen:** Letterboxd CSV only; local catalogue first, then TMDB title+year
  first result, then title-only fallback; upsert by user/film (D6, D15).
- **Alternatives considered:** Netflix/IMDb imports, manual-only entry, fuzzy
  matching, or per-row manual review.
- **Repository rationale:** the project notes scoped Letterboxd; its documented
  CSV is straightforward; deterministic matching is explainable and avoids
  unnecessary TMDB calls. A review UI is deferred to onboarding work.
- **Consequences:** imports are reproducible but first-result ambiguity can
  mismatch films. Repeat viewings collapse into one `user_films` row. There is
  no Netflix integration or fuzzy-review interface.

## 6. Persistent background imports rather than one long request

- **Chosen:** create a persistent import job, process 20-row batches in a daemon
  thread, checkpoint per-row outcomes/counters, support resume and startup
  recovery (D20, D21).
- **Alternatives considered:** the original single synchronous request and
  client-only progress. The notes do not record evaluation of a specific queue
  product.
- **Repository rationale:** a real 1,600-row import caused partial commits and
  thousands of sequential external calls; a timeout or TMDB error must not
  leave unrecoverable work. Only normalized resume fields are stored, not the
  original CSV.
- **Consequences:** POST returns an import id promptly and the UI polls durable
  state. Resume and repeat imports are safe through per-row outcomes and
  `unique(user_id, film_id)`. The trade-off is operational simplicity versus
  scalability: daemon threads avoid new infrastructure but are not a distributed
  queue. Batch JSONB updates and per-row TMDB/DB calls still have a cost.

## 7. Bounded TMDB retries and per-row failure isolation

- **Chosen:** at most four attempts for network errors, 429, and 5xx, using
  bounded exponential backoff plus jitter; record a failed row and continue
  (D22).
- **Alternatives considered:** unlimited retries, a single fixed-delay retry,
  or simply increasing HTTP timeout/sequential retries.
- **Repository rationale:** temporary failures should not abort all remaining
  rows, and bounded jitter avoids hammering TMDB.
- **Consequences:** persistent rate limiting becomes a visible temporary row
  failure rather than a hidden indefinite wait. Unmatched titles and transient
  failures have different meanings in the API/UI. Non-transient HTTP errors are
  not retried.

## 8. Swappable provider with a deterministic mock first

- **Chosen:** an abstract `LLMProvider` and `MockLLMProvider`, selected by
  `LLM_PROVIDER=mock` (D5).
- **Alternatives considered:** direct OpenAI integration from day one.
- **Repository rationale:** no key was available, and deterministic responses
  make demos/tests reproducible. The intended future swap is a new provider
  class behind the same interface.
- **Consequences:** chat and context flow can be tested without network/model
  cost. The interface also has an `extract_insights` seam for Phase 4. However,
  the mock only selects templates/keywords; there is no real model, prompt
  configuration, safety layer, provider fallback, or evidence of real-LLM
  quality. Unknown provider names currently raise an error.

## 9. Bounded context, not full history

- **Chosen:** the latest 12 messages plus five most recently updated confirmed
  memories by default, configurable via settings (D18).
- **Alternatives considered:** full history or hard-coded limits.
- **Repository rationale:** predictable prompt cost and explicit user control;
  configurable bounds allow later evaluation of different window sizes.
- **Consequences:** `ChatContext` is small and testable, and proposed/rejected
  memories are excluded by SQL. Full history remains available to the UI. Long
  conversations can lose older details from assistant context; recency, not
  semantic relevance, determines which confirmed memories are included.

## 10. Append-only history and persisted assistant openings

- **Chosen:** store all user/assistant messages verbatim without in-place
  summarization, and persist the opening as the first message (D11, D16).
- **Alternatives considered:** in-place history summarization, a client-injected
  opening, or a system-prompt-only opening.
- **Repository rationale:** an auditable source of truth and future provenance
  for “why am I seeing this?”; one chat source from first render onward.
- **Consequences:** reload/resume uses the same stored history and mock replies
  are reproducible. No route edits/deletes messages. Retention grows with use,
  and append-only is currently enforced by application behavior plus limited
  RLS policies, not a trigger against service-role updates.

## 11. Proposed → confirmed/rejected memory lifecycle

- **Chosen in design:** user-controlled status transitions, with only confirmed
  memories allowed to influence later behavior (D12).
- **Alternative considered:** auto-saving extracted insights.
- **Repository rationale:** the user owns the reflective profile; auto-saving
  would undermine trust.
- **Current consequence:** the schema and confirmed-only retrieval enforce the
  read boundary. Ending a reflection extracts at most five validated proposed
  memories (`POST /conversations/{id}/end`), and review transitions are limited
  to `proposed → confirmed` / `proposed → rejected` (`PATCH /memories/{id}`),
  with edits saved only alongside confirmation. `source_message_ids` is
  populated at extraction time and powers the review screen's "Why am I seeing
  this?" traceability. Contradiction resolution remains absent.

## 12. Recommendation approach and pgvector are deferred

- **Chosen:** defer the recommendation engine until Phase 6 and pgvector until
  plain SQL retrieval is proven insufficient (D8 and requirements F8–F11).
- **Alternative considered:** adopting pgvector from Phase 0.
- **Repository rationale:** the notes explicitly avoid premature vector-search
  complexity. Reflection-informed recommendations should be built on confirmed
  memories rather than adding infrastructure before the retrieval need is known.
- **Current consequence:** there is no recommendation algorithm, embedding
  column, similarity search, mood model, or feedback schema to justify yet.
  Any specific future ranking approach would be a new design decision, not a
  repository-backed fact.

## 13. Watch context and ending semantics

- **Chosen:** store `seen|planning`; treat “First time watching” and “Rewatch” as
  UI-only framing (D17). Make ending idempotent and reject messages after
  completion with 409 (D19).
- **Alternatives considered:** four stored watch states or no watch context;
  duplicate-end errors or allowing post-completion messages.
- **Repository rationale:** seen/planning changes the assistant’s questions,
  while idempotent ending is safe under retries and keeps completed reflections
  stable for later review.
- **Consequences:** the schema stays small and the mock uses separate planning
  questions. The first-watch/rewatch nuance is not retained. Ending currently
  does not trigger memory extraction; that remains Phase 4 work.

## 14. Development auth convenience

- **Chosen:** auto-confirm development accounts with `email_confirm=True` and
  return generic forgot-password success (D13 and `auth.py`).
- **Alternative considered:** mandatory email verification from day one.
- **Repository rationale:** no SMTP was configured, and mandatory verification
  would block development testing. D13 explicitly says this must change before
  public deployment.
- **Consequences:** local sign-up is immediate, and reset requests do not reveal
  account existence. Actual reset-email delivery depends on Supabase SMTP.
  These are development conveniences, not production-ready identity policy.

## 15. Recommendations / inference for future decisions

The following are analysis and recommendations, **not recorded prior
justifications or implemented choices**:

1. **If import throughput must scale beyond one API process,** evaluate a real
   worker queue and database leasing. The current daemon-thread model is simpler
   and appropriate for development, but does not prove distributed scalability.
2. **Before adding a real LLM,** document provider, model/version, exact prompts,
   temperature, token/cost limits, output validation, and privacy/retention.
   Preserve the mock for deterministic CI rather than using it as evidence of
   model quality.
3. **Before implementing recommendations,** agree on a small explainable baseline
   (candidate source, weights, cold start, feedback storage, and evaluation
   metrics). Only introduce embeddings/pgvector if that baseline demonstrates a
   retrieval limitation.
4. **Before production use,** define message/import-job retention, account
   deletion, email verification, token storage, and operational backup/recovery
   requirements. Current schema/RLS does not answer those policy questions.
5. **For larger libraries/conversation histories,** evaluate server-side
   filtering and UI pagination. Current library loading is proven at 1,600 rows,
   but it aggregates all pages in the browser and other history endpoints are
   unpaginated.

## 16. Traceability quick reference

| Topic | Decision IDs | Implementation evidence |
|---|---|---|
| Stack/schema | D1–D4, D10 | `client/package.json`, `server/requirements.txt`, `0001_init.sql` |
| Provider | D5 | `server/app/llm/` |
| Import source/matching | D6, D15 | `server/app/import_jobs.py`, `routers/imports.py` |
| TMDB | D7 | `server/app/tmdb.py`, `routers/films.py` |
| Retrieval/vector search | D8 | Deferred; no vector code |
| Access model | D9, D14 | `supabase_client.py`, `deps.py` |
| History/memory | D11, D12, D16 | `messages`, `memories`, `conversations.py`, `context.py` |
| Auth environment | D13 | `routers/auth.py` |
| Chat context/ending | D16–D19 | `conversations.py`, `0002_conversation_context.sql` |
| Large imports | D20–D22 | `import_jobs.py`, `tmdb.py`, `0003_import_jobs.sql` |
