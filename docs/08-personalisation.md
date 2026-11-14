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

## 4. Memory improvements (Part C)

`app/memories.py` now represents *why* and *how well* we know something, not
just the raw statement:

| Field | Values | Meaning |
|---|---|---|
| `kind` | `theme`, `preference`, `insight`, `aesthetic`, `narrative`, `emotional_response`, `viewing_intention` | The original three plus four new categories (migration widens the CHECK, keeps old rows). |
| `evidence_type` | `explicit` / `inferred` | Did the user say it, or did we interpret it? User-authored (onboarding) memories are explicit; system-proposed ones stay inferred even after confirmation. |
| `scope` | `stable` / `film_specific` / `session` | Lasting trait vs reaction to one film vs one-off mood. A temporary mood is never promoted to a trait. |
| `confidence` | coarse `0..1` | An ordinal, not a calibrated probability; `normalise_proposals` coerces it and defaults explicit→0.9, inferred→0.5. |
| `source_film_tmdb_id` | TMDB id | The film that prompted the memory. |

Rules preserved: never invent biography, never diagnose, never turn mood into
personality, and speculative reads stay marked `inferred` until the user
confirms them through the existing review workflow.

`recurring_themes(user_id)` detects focus words that appear in confirmed
memories from **two or more distinct films** (cross-film memory). It is purely
descriptive — a theme that recurs in the films the user discusses is never
assumed to describe their private life. It is wired into the reflection
extraction context so the extraction prompt can propose a cross-film pattern
only when the transcript supports it.

The OpenAI `extract_insights` prompt and the mock now emit `evidence_type`,
`scope`, `confidence` and `source_film_tmdb_id`.

Migration: `supabase/migrations/0006_personalisation_memories.sql`.

## 5. Request-aware recommendation pipeline (Part D)

The discovery assistant now follows the staged pipeline: **request → context →
candidates → personalised ranking → explanation → feedback**.

- **Request interpretation** — `constraints.parse_intent(text)` parses soft
  signals (mood, desired experience, novelty, explicit "no horror" style
  exclusions) separately from hard constraints. A mood never filters the pool
  and never becomes a permanent trait.
- **Candidate retrieval** — the chat pool widened to a configurable
  `recommendation_pool_size_chat` (default 40) instead of a hard-coded 8.
- **Personalised ranking** — the score is now
  `w_m·mood + w_t·taste + w_r·reflection + w_e·experience + w_n·novelty`,
  with weights from `config.py`. When a viewing intention is stated the weights
  are re-balanced to favour the current request over historical taste (a request
  for a "comforting comedy" outweighs a horror-leaning library; Test 1).
  Reflection memories are matched against candidate text (the "why", Test 9).
- **Diversity** — each card carries a `novelty_category`
  (`familiar / adjacent / exploratory`) and `match_dimensions`
  (`taste/reflection/mood/experience/novelty`) for transparent, non-identical
  picks (Tests 2, 5).
- **Explicit constraints before ranking** — library films, "not for me"
  feedback and request-level genre exclusions are removed pre-scoring (Test 4).
- **Record** — `record_recommendations` writes each served card to the new
  `recommendation_events` table (reason + dimensions + category), feeding
  discovery → reflection and discovery → discovery linkage.

Migration: `supabase/migrations/0007_recommendation_events.sql`.

## 6. Prompts and structured output (Parts G/H)

- `_SYSTEM_BASE` (reflection) now describes a warm, conversational,
  memory-aware, film-knowledgeable, spoiler-conscious companion. The rigid
  "ask exactly one follow-up question" rule is gone ("you may ask one genuine
  question when it deepens the reflection, but do not end every reply with
  one").
- `_SYSTEM_DISCOVERY` resolves the old empty-pool contradiction: recommend
  **only** from the candidate list, and if the list is empty ask one short
  clarifying question instead of inventing a film.
- `_context_block` renders the richer shared context (film dossier, mentioned
  films, discussed films, recurring themes, recent recommendations, viewing
  history) with `[kind, evidence[, scope]]` markers on memories.
- Cards now carry `match_dimensions`, `novelty_category` and
  `recommendation_reason` (additive — the frontend ignores unknown fields).
- A provider's named films are validated against the candidate pool; anything
  the model invents (even a real film) is dropped before display. `tmdb_id` is
  copied from the pool, never trusted from the model.
- The mock provider stays an unchanged deterministic fixture. Its
  "always asks a question" behaviour is a tested Phase-5 contract, while the
  production assistant's natural-conversation behaviour lives in the OpenAI
  prompt (the correct boundary between the dev double and the real model).

## 7. Tests (Part J)

New suite `server/scripts/test_personalisation.py` (19 tests; in-memory
Supabase + mocked TMDB, no live requests) covers:

- mood vs historical preference (Test 1), genre exclusion (4), watched
  exclusion (7), dimensions + diversity categories (5/8), graceful empty pool
  (6), evidence/confidence coercion (13/15), cross-film recurring themes (11),
  film dossier + mention resolution (9/10), conversational prompts (14), no
  fabricated memories (13), and recommendation-event persistence.

Run from `server/`: `python scripts/test_personalisation.py`.

## 8. Limitations

- Mood/experience affinity is **lexical** (overview/genre/title vocabulary), a
  deliberate, deterministic proxy — not semantic retrieval.
- `exclude_genres` matches singular genre names ("no horror") and may miss
  pluralised forms ("dramas").
- Assistant card themes/runtime come from the cached catalogue; a brand-new
  TMDB candidate shows overview-derived themes until it is cached (never
  fabricated).
- `recurring_themes` is keyword-based and purely descriptive.
- Migrations `0006`/`0007` must be applied; the code degrades gracefully if
  they are not (`.get()` access + try/except everywhere).

## 9. Follow-ups implemented (this phase)

- **Discovery -> reflection closed loop:** when a film is marked watched
  (`add_film` / `update_film`), `recommendations.mark_recommendations_watched`
  stamps `watched_at` on matching recommendation events
  (migration `0008_recommendation_events_watched.sql`); `user_context.
  recent_recommendations` now returns `watched_at` so a later reflection can
  see whether a suggestion was acted on.
- **Plural/negation genre exclusions:** `constraints._excluded_genres` now
  matches singular *and* plural forms ("no horror", "avoid slow dramas",
  "not comedies") via `_genre_forms`.

## 10. Remaining future work

- Semantic retrieval once lexical retrieval proves insufficient (pgvector still
  deferred, per D8).