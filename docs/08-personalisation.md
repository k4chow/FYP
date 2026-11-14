# 08 — Interconnected, Memory-Aware Film Companion (Personalisation)

> **Status:** implemented incrementally. This document records the shared
> personalisation layer that makes reflection and discovery behave as one
> companion rather than two isolated assistants. Each phase commits the section
> covering what it added; see `git log` for the trace.

## 1. Overview

The goal is a single, coherent model of the user shared by both assistants:

- **Stable film preferences** (favourite genres, directors, actors, styles,
  tones, themes) — confirmed only.
- **Dynamic viewing context** (mood, intention, desired experience) — always
  derived from the *current* request and never persisted as a trait.
- **Reflective memories** (personal interpretations, recurring themes,
  emotional responses) — confirmed and relevance-retrieved.
- **Viewing history** (watched / watchlist / recommended) — always kept
  distinct; a film is never assumed watched just because it was discussed.

Context is **relevant, bounded and non-redundant**: the LLM sees what helps it
answer the current turn, not the largest possible prompt.

## 2. Shared personalisation layer (Part A)

New module `server/app/user_context.py` — the single service both assistants
read from:

| Function | Purpose |
|---|---|
| `confirmed_memories_rich` | Confirmed memories with `kind`, `evidence_type`, `scope`, `confidence` (newest first). Falls back to the pre-migration columns. |
| `relevant_memories` | Ranks confirmed memories by lexical overlap with the current request; explicit preferences are preferred over inferred readings. |
| `viewing_history` | Watched vs watchlist split with ratings, bounded for the prompt. |
| `discussed_films` | Titles from recent reflections (cross-film memory). |
| `recent_recommendations` | Recently served recommendations (discovery → reflection). |

`ChatContext` (in `app/llm/base.py`) gained optional fields so the provider —
and especially the OpenAI prompt — can distinguish richness from noise:
`film_context`, `memories_detail`, `mentioned_films`, `viewing_history`,
`discussed_films`, `recently_recommended`. All default empty, so existing
constructor call sites and the mock provider are unaffected.

`config.py` adds bounded budgets and (placeholder) ranking weights:
`llm_context_mentioned_films`, `llm_context_watched`, `llm_context_watchlist`,
`recommendation_pool_size_chat`, and `recommendation_weights_*`.

`_chat_context` in `routers/conversations.py` is the assembler: it ranks
memories for the current message, attaches the viewing history (discovery) or
discussed films + recent recommendations (reflection), and injects the film
dossier.

### Retrieval principles (implemented)

- Only **confirmed** memories are ever injected.
- Temporary mood is parsed from the current request only and never stored.
- Retrieval is bounded (`llm_context_memories`, plus the caps above).
- Explicit evidence is preferred over inferred readings; schema access is
  `.get()`-based so a missing column degrades gracefully.

## 3. Film knowledge retrieval (Part B)

New module `server/app/film_knowledge.py`:

- `film_context(film_row)` — a compact, truthful **dossier**: title, year,
  director, leading cast, genres, curated themes (via `themes.filter_keywords`
  over cached TMDB keywords), synopsis, runtime. Never a network call; always
  grounded in the cached `films` row.
- `enrich_metadata(tmdb_id, meta)` — backfills `keywords`, `director`, `cast`
  onto a film's metadata using TMDB, only for the missing pieces, and fails
  soft. `routers/films._ensure_film` owns the single cache write so enrichment
  stays on the existing catalogue path.
- `resolve_film_mentions(message)` — recognises another film named mid-
  reflection (quoted titles, "like / similar to / reminded me of" lead-ins, and
  titles already in the catalogue), resolves each to a TMDB id with the same
  leading-word guard as `constraints.py`, and caches the resolution. No LLM
  round-trip, no repeated lookups.

`tmdb.py` gained `movie_credits(tmdb_id)` (director + principal cast).

The reflection `messages` endpoint now passes the latest message as `query` to
`_chat_context`, which resolves `mentioned_films` and attaches the dossier, so
the reflection assistant can detect "this reminded me of *Eternal Sunshine*"
and discuss the connection using grounded metadata.

## 4. Planned (subsequent commits)

- Memory kinds, evidence/confidence/scope, cross-film memories (Part C).
- Request-aware recommendation ranking, diversity tiers, match dimensions and
  recommendation events (Part D).
- Rewritten reflection/discovery prompts and structured-output hardening
  (Parts G/H).
- Migration `0006_…`, `0007_…` and the `test_personalisation.py` suite.