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

Contradictions (e.g. a new insight conflicting with a confirmed one) are
surfaced to the user for resolution — never silently overwritten.

### Layer 3 — Reflection & discovery
Confirmed memories + film history drive:
- intention-based recommendations (themes/moods the user reflected on, not just
  collaborative filtering), each with a human-readable *why*;
- the Film Assistant (discovery conversations) which can ask clarifying
  questions before recommending.

## LLM context assembly (Phase 3)

The server builds a **bounded** JSON payload per turn:
`system prompt + film metadata (if any) + last N messages + K confirmed memories`
— never the full history and never proposed/rejected memories. This keeps
token cost predictable and honours user control.

## Provider seam

`server/app/llm/` exposes a `LLMProvider` protocol (`chat(messages, context)`,
`extract_insights(conversation)`). `MockLLMProvider` returns deterministic
scripted responses so all flows are testable without an API key; an
`OpenAIProvider` drops in behind the same interface later.
