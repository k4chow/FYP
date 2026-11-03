# 01 — Requirements & Traceability

Source: `FYP Notes 2.pdf` (12 pages, fully extracted and analysed). This file
traces every requirement from the notes to the feature that implements it and
the UI screen(s) that surface it. Update the "Status" column per phase.

## Functional requirements

| # | Requirement (from notes) | Implementation | UI screen(s) | Status |
|---|---|---|---|---|
| F1 | Persistent conversation history; verbatim, never overwritten | `messages` table (layer 1) | Reflection chat | ✅ Done |
| F2 | Reflective profile built from conversations | `memories` table (layer 2); extraction now feeds Review & Edit | My Profile | Phase 5 (data lifecycle done; profile UI remains) |
| F3 | User controls every stored insight (confirm / edit / reject) | `memories.status` = proposed/confirmed/rejected + review endpoints | Review & Edit, Compare and refine | ✅ Done |
| F4 | Bounded LLM context (recent N messages + small set of confirmed memories), never full history | Server-side context assembler | — | ✅ Done |
| F5 | Swappable LLM provider (mock first) | `server/app/llm/` provider interface | — | ✅ Done |
| F6 | Letterboxd CSV import (no Netflix) | Persistent resumable import jobs + TMDB matching | Import screen, Settings | ✅ Done |
| F7 | Film catalogue with metadata/posters | TMDB API + `films`/`user_films` tables | My Films, Add a film | ✅ Done |
| F8 | Reflection-informed recommendations | Recommendation service over confirmed memories | Discover | Phase 6 |
| F9 | Every recommendation explains *why* | "why" strings generated from source memories | Discover cards, "Why am I seeing this?" | Phase 6 |
| F10 | Conversational discovery assistant | Film Assistant chat (`conversations.type='discovery'`) | Discover chat | Phase 6 |
| F11 | Recommendation feedback loop | "More like this" / "Not for me" → profile signals | Discover cards | Phase 6 |
| F12 | Auth (email/password) | Supabase Auth | Sign in / Sign up / Forgot password | ✅ Done |

## Non-functional requirements

| # | Requirement | Implementation | Status |
|---|---|---|---|
| N1 | Row Level Security on all user-data tables | RLS policies in `0001_init.sql` | ✅ Phase 0 |
| N2 | No secrets in version control | `.env` gitignored, `.env.example` placeholders | ✅ Phase 0 |
| N3 | JSONB only for genuinely flexible metadata | `metadata`, `source_message_ids`, `genres` columns | ✅ Phase 0 |
| N4 | pgvector only if plain SQL retrieval proves insufficient | Deferred decision (documented in 03-design-decisions) | Deferred |
| N5 | Film preferences ≠ mental-health inference; contradictions flagged, never silently overwritten | Deterministic proposals describe observable film/reflection preferences only; review cannot overwrite confirmed memories or source messages | ✅ Phase 4 (side-by-side contradiction UI remains Phase 5) |
| N6 | User-adjustable recommendation style (similar ↔ exploratory) | Settings slider → recommendation weights | Phase 6 |

## Onboarding flow (from notes + mockups)

1. Sign up → 2. Import Letterboxd (skippable) → 3. Pick ≥5 "films that stayed
with you" → 4. One "a little about you" question → 5. First reflection prompt
→ Home. Status: Phase 1–5 (incremental).
