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

## UI variation decisions (from mockup review)

| Screen | Chosen | Rejected | Why |
|---|---|---|---|
| Home | Full sidebar dashboard (screen 15) | 4 minimal layout options (16) | Most complete; consistent with the shell every other screen uses; options in 16 are subsets of it |
| Review & edit insights | Richer version (12) | Simplified restyle (13) | Adds "themes to add to your profile" and "Why am I seeing this?" — both required features |
| Add a Reflection | Hybrid: browse sections of 21 + selected-film bottom bar of 22 | Centered search-first layout (20) | Best interaction model: browse when unsure, explicit watch-type + CTA once a film is chosen |
| Reflection chat | Layout with End reflection button (11) | Variant without it (09) | "End reflection" is required to trigger the guided review flow; keeps 09's quick-reply chips |
| "What catches your attention" (07) | Repurposed into reflection-start flow | Use in onboarding | User annotation: "might be too cluttered" for onboarding; cleaner entry-points screen (10) covers the first reflection |
