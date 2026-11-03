# 02 — Architecture

## Overview

```
React client (Vite + TS)  ──►  FastAPI server  ──►  Supabase Postgres (RLS)
        localhost:5173           localhost:8000         │
                                 │                      └── Auth (GoTrue)
                                 ├──► TMDB API (film metadata/posters)
                                 └──► LLM provider (mock → swappable)
```

The client never calls the database or external APIs directly; all data flows
through the FastAPI server, which enforces the memory lifecycle and assembles
bounded LLM context.

## The 3-layer model (core of the thesis)

### Layer 1 — Conversation history (source of truth)
Every user and assistant message is stored verbatim in `messages`, linked to a
`conversations` row. History is **append-only**: it is never summarised in
place, edited, or overwritten. Any derived artefact can be traced back to it.

### Layer 2 — Reflective profile (user-controlled memory)
Insights extracted from conversations become `memories` rows with:
- `status`: `proposed` → (`confirmed` | `rejected`) — set **only by the user**
  via the Review & Edit flow. Proposed memories never influence anything.
- `source_message_ids` (JSONB): the exact messages the insight came from,
  enabling "Why am I seeing this?" explainability.
- `kind`: `theme` | `preference` | `insight`.

Contradictions are never silently overwritten: new extraction can only create
`proposed` rows, while confirmed memories remain untouched. Side-by-side
comparison/refinement UI is the Phase 5 continuation.

### Layer 3 — Reflection & discovery
Confirmed memories + film history drive:
- intention-based recommendations (themes/moods the user reflected on, not just
  collaborative filtering), each with a human-readable *why*;
- the Film Assistant (discovery conversations) which can ask clarifying
  questions before recommending.

## LLM context assembly (Phase 3–4)

The server builds a **bounded** JSON payload per turn:
`system prompt + film metadata (if any) + last N messages + K confirmed memories`
— never the full history and never proposed/rejected memories. Defaults are
N=12 and K=5 (`LLM_CONTEXT_MESSAGES` / `LLM_CONTEXT_MEMORIES`). This keeps
token cost predictable and honours user control.

## Provider seam

`server/app/llm/` exposes an `LLMProvider` interface (`opening(context)`,
`chat(messages, context)`, `extract_insights(messages, context)`).
`MockLLMProvider` returns deterministic reflective responses so all flows are
testable without an API key; an `OpenAIProvider` drops in behind the same
interface later. Select the provider with `LLM_PROVIDER` (default `mock`).

Phase 4 insight extraction receives the same bounded recent-message window as
chat, plus message ids for citations. It emits at most three source-grounded
proposals; the server validates content, kind, explanation, and source ids
before inserting `proposed` memories. The Review & Edit API is the only path
that changes review status, and it cannot alter source messages or source ids.

## Large-import processing

`POST /import/letterboxd` only validates and normalizes the upload, then returns
an import id. A background worker processes 20-row batches and persists per-row
outcomes, counters, and checkpoints in `import_jobs`. TMDB retries are bounded
with exponential backoff and jitter. Failed rows can be resumed without
rematching successful rows; queued/processing jobs are recovered on startup.
Library reads are paginated (`limit`/`offset` + `total`) so 1,600+ film libraries
are not truncated by PostgREST's default page size.
