# 03 — Design Decisions

Each entry: decision → alternatives considered → rationale. Written to be
reusable as thesis justification material.

| # | Decision | Alternatives | Rationale |
|---|---|---|---|
| D1 | React + Vite + TypeScript client | Next.js, Vue | Team familiarity (same structure as previous project); Vite is fast and minimal; no SSR requirement |
| D2 | FastAPI server | Node/Express, Django | Python ecosystem for LLM/ML work; async-first; automatic OpenAPI docs; already installed in dev environment |
| D3 | Supabase Postgres | Self-hosted Postgres, Firebase, MongoDB | Managed Postgres with built-in Auth, RLS for per-user data isolation, generous free tier, SQL familiarity |
| D4 | Relational schema, JSONB only for flexible metadata | Full JSONB documents | Queryability and integrity for core entities; JSONB reserved for genuinely variable data (`metadata`, `source_message_ids`) |
| D5 | Mock LLM provider behind an interface | Direct OpenAI integration from day 1 | No key available yet; deterministic mock makes every flow testable and demos reproducible; swap is one class |
| D6 | Letterboxd CSV import only | Netflix/IMDb import, manual entry only | Notes scoped it this way; Letterboxd export is a clean documented CSV; avoids scope creep |
| D7 | TMDB for film metadata | OMDb, IMDb scraping | Free API key, good coverage, poster CDN, stable API |
| D8 | pgvector deferred | Adopt pgvector from Phase 0 | Notes explicitly say add it only if plain SQL retrieval is insufficient — avoids premature complexity |
| D9 | Server-mediated DB access (not direct client→Supabase) | Client talks to Supabase directly | Single place to enforce memory lifecycle and context assembly; RLS still enabled as defence in depth |
| D10 | Monorepo (`client/` + `server/` + `supabase/`) | Separate repos | FYP scale; one commit history maps cleanly onto phases; mirrors previous project structure |
| D11 | Append-only messages; derived profile in separate table | In-place summarisation of history | Source of truth must be auditable; enables "why am I seeing this" traceability via `source_message_ids` |
| D12 | Proposed→confirmed memory lifecycle | Auto-save insights | Central requirement: the user owns their reflective profile; auto-saving would undermine trust |
| D13 | Dev accounts auto-confirmed (`email_confirm: true` on signup) | Require email verification from day 1 | No SMTP configured in the dev Supabase project; mandatory verification would block all testing. Must be switched on before any public deployment |
| D14 | Two Supabase clients: `supabase` (DB only) + `auth_client` (auth API only) | Single shared client; raw REST auth calls | supabase-py propagates sign-in state into the client's PostgREST headers, silently downgrading later DB calls from service-role to a user JWT (surfaced as an RLS 500 on `films` upsert during Phase 2). Separate instances make the correct behaviour structural, not order-dependent |
| D15 | Import matching: local catalogue first, then TMDB title+year first result (title-only fallback); upserts make re-import idempotent; unmatched rows reported, not dropped | Fuzzy matching; per-row manual review UI (as in the onboarding mockup) | Deterministic and explainable for thesis evaluation; catalogue-first avoids repeat TMDB calls; the mockup's review-before-confirm step is deferred to the onboarding flow (Phase 5), keeping the Settings/Import path simple |
| D16 | The assistant's opening message is persisted as the first `messages` row | Client-injected placeholder; system prompt only | Chat history has one source of truth from the first render; opening messages remain auditable and appear in every later reload |
| D17 | Store `watch_type` as `seen` \| `planning`; the mockup's “First time watching” / “Rewatch” choice is UI-only framing | Four stored states; no watch context | Seen/planning is the distinction that changes the assistant's questions; first-watch versus rewatch can be added later if it proves useful without complicating the initial contract |
| D18 | Bounded context defaults to the last 12 messages + 5 most recently updated confirmed memories, configurable via settings | Full history; hard-coded limits | Makes F4 explicit and testable; keeps prompt cost predictable while allowing evaluation with different window sizes |
| D19 | Ending a conversation is idempotent; posting to a completed conversation returns 409 | 409 on duplicate end; allow post-completion messages | Double-clicks and retries are safe; completed reflections remain stable for the Phase 4 review flow |
| D20 | Letterboxd imports are persistent background jobs with per-row outcomes and batch checkpoints | One long synchronous request; client-only progress | A 1,600-row import needs thousands of external calls; one timeout or TMDB error must not strand a partial library with no recovery path. Queued/processing jobs are recovered on startup and failed rows can be resumed |
| D21 | Import jobs store only normalized resume fields + outcomes, never the original CSV | Store the uploaded file or every CSV column | Resume needs name/year/rating/watched date only; minimizing retained data is safer and keeps the job table small. Duplicates mean repeat CSV rows or already-current library rows; transient failures are distinct from unmatched titles |
| D22 | TMDB 429/network/upstream retries use bounded exponential backoff with jitter (4 attempts max) | Unlimited retries; one fixed-delay retry; larger HTTP timeouts | Transient failures are isolated to one film and remaining rows continue; bounded jittered retries avoid hammering TMDB without hiding architectural problems |

## UI variation decisions (from mockup review)

| Screen | Chosen | Rejected | Why |
|---|---|---|---|
| Home | Full sidebar dashboard (screen 15) | 4 minimal layout options (16) | Most complete; consistent with the shell every other screen uses; options in 16 are subsets of it |
| Review & edit insights | Richer version (12) | Simplified restyle (13) | Adds "themes to add to your profile" and "Why am I seeing this?" — both required features |
| Add a Reflection | Hybrid: browse sections of 21 + selected-film bottom bar of 22 | Centered search-first layout (20) | Best interaction model: browse when unsure, explicit watch-type + CTA once a film is chosen |
| Reflection chat | Layout with End reflection button (11) | Variant without it (09) | "End reflection" is required to trigger the guided review flow; keeps 09's quick-reply chips |
| "What catches your attention" (07) | Repurposed into reflection-start flow | Use in onboarding | User annotation: "might be too cluttered" for onboarding; cleaner entry-points screen (10) covers the first reflection |
