# NOACF — AI, Chat Context, Memory, and Recommendations

> **Status note:** as of the personalisation phase the assistant runs behind a
> provider abstraction (mock or OpenAI, D33) and the deterministic
> recommendation engine (D35) is live. A shared personalisation layer
> (`app/user_context.py`, `app/film_knowledge.py`) now feeds both assistants
> relevance-ranked memories, viewing history, film dossiers and film-mention
> resolution; request-aware (mood/experience/novelty) ranking is implemented.
> Full details live in `docs/08-personalisation.md`.

## 1. Implementation status

| Capability | Status | Verifiable evidence |
|---|---|---|
| Provider abstraction | **Implemented** | `server/app/llm/base.py`, `__init__.py` |
| Reflective assistant replies | **Implemented** | `mock.py` (dev) + `openai.py` (production, `LLM_PROVIDER=openai`) |
| Real external model calls | **Implemented (OpenAI)** | `server/app/llm/openai.py`, `LLM_PROVIDER=openai` (D33) |
| Bounded chat context | **Implemented** | `server/app/context.py` |
| Film knowledge in reflection | **Implemented** | `film_knowledge.film_context`, `resolve_film_mentions` (docs/08) |
| Confirmed-memory retrieval | **Implemented (relevance-ranked)** | `user_context.relevant_memories`, `context.confirmed_memories` |
| Memory extraction/review/edit/forget | **Implemented** | 7 kinds + evidence/scope/confidence in `memories.py`; review endpoints/UI; `/profile/summary` groups all kinds |
| Recommendations and explanations | **Implemented (deterministic)** | `server/app/recommendations.py`, Discover page (Phase 6, D35) |
| Mood / intention-based recommendations | **Implemented (lexical)** | `constraints.parse_intent`, request-aware weights in `recommendations.py` (docs/08) |
| Recommendation feedback + style slider | **Implemented** | `recommendation_feedback` table, `/profile/preferences` (Phase 6, D36/D37) |
| Persisted Film Assistant (F10) | **Implemented** | saved as `type="discovery"` conversations via `/conversations`; `exclude_tmdb_ids` rotation on Regenerate/replies (Phase 7) |
| Explicit-constraint recommendations (F12) | **Implemented** | `server/app/constraints.py`; director/title/genre parsing validated against TMDB (Phase 7) |
| Named-film answers without refusal | **Implemented** | `_requested_title_cards`; already-logged films return close alternatives (Phase 7) |
| Discovery serves three distinct picks | **Implemented** | `_discovery_reply` backfill + `_SYSTEM_DISCOVERY` bias (docs/08) |

## 2. Provider selection and interface

`get_llm()` is the only provider factory used by the conversation router. It is
cached with `lru_cache` and accepts `LLM_PROVIDER=mock` (default, deterministic)
or `openai` (D33, key via `OPENAI_API_KEY`, model via `OPENAI_MODEL`, default
`gpt-6-luna`); any other value raises `RuntimeError`
(`server/app/llm/__init__.py`). There is no automatic fallback chain.

The abstract `LLMProvider` defines:

- `opening(context) -> str`: first assistant message for a new conversation.
- `chat(messages, context) -> str`: reflection reply to the latest user message.
- `chat_discovery(messages, context) -> dict`: recommender turn, returning
  `{"reply", "films": [...]}` (the router grounds and backfills the films).
- `extract_insights(messages, context) -> list[dict]`: memory-extraction seam,
  implemented in both providers — mock derives keyword proposals, OpenAI
  requests JSON mode (unparseable output raises so the conversation stays
  active for a retry).

`ChatContext` is a dataclass containing conversation type, title, the raw film
row plus a compact `film_context` dossier, watch type, confirmed memories
(`memories` strings plus `memories_detail` with kind/evidence/scope), display
name, user-turn count, `mentioned_films`, `viewing_history` / `discussed_films`
/ `recent_recommended`, and the discovery `suggestions` pool with the rendered
`request` and `intent`. There is no model-specific prompt type or embedding.

## 3. How the chatbot receives film and user context

For each conversation turn, `_chat_context` in
`server/app/routers/conversations.py` assembles:

1. `conversation_type` and `title` from the conversation.
2. The linked `films` row plus a compact **film dossier** (`film_context`:
   title, year, director, leading cast, genres, curated themes, synopsis,
   runtime). TMDB data was cached earlier by `_ensure_film`, which backfills
   keywords/director/cast via `film_knowledge.enrich_metadata`.
3. `watch_type` (`seen` or `planning`).
4. **Relevance-ranked** confirmed memories (up to `llm_context_memories` by
   default) via `user_context.relevant_memories`; explicit preferences rank
   above inferred readings, and `memories_detail` keeps kind/evidence/scope.
5. The user’s `display_name` from `public.users`.
6. A turn count (number of user messages in the conversation).
7. `mentioned_films` — other films named in the latest message, resolved by
   `film_knowledge.resolve_film_mentions`.
8. `viewing_history` (discovery) — watched/watchlist split with ratings — or
   `discussed_films` + `recent_recommendations` + `recurring_themes`
   (reflection).

For a reply, `recent_messages` separately fetches at most 12 messages, newest
first, then reverses them to oldest-first. The UI still receives full history;
these limits apply only to the provider input. Bounds are configured with
`LLM_CONTEXT_MESSAGES` / `LLM_CONTEXT_MEMORIES` (defaults 12/5) plus the
personalisation caps in `config.py`.

`ChatContext` also carries the discovery candidate pool (`suggestions`) and the
rendered current request (`request` for hard constraints, `intent` for soft
mood/experience/exclusion signals).

## 4. Deterministic mock behavior step by step

`MockLLMProvider` uses no randomness and no network calls:

### Opening

- Film + `planning`: asks what draws the user to the film and what they hope it
  will make them feel.
- Film + other watch context: asks what stayed with the user after watching.
- No film + title (for example, Home’s prompt): quotes the prompt and asks what
  is coming up for the user.
- Otherwise: generic invitation to reflect. Display name is included when set.

### Normal reply

1. Read the latest user-role message from the bounded history.
2. Normalize it and recognize exact quick-reply phrases.
3. For ordinary text, choose an acknowledgement using `turn % len(_ACKS)`.
4. If the message contains a genre attached to the film, mention that genre and
   film. Otherwise extract up to three lowercase words of at least five letters,
   excluding a fixed stopword list, and optionally quote the first keyword in a
   reflective template.
5. When confirmed memories exist and `turn % 3 == 2`, append one memory selected
   deterministically from the bounded list.
6. Select a follow-up question from the planning, film, or free-reflection bank
   using the turn count (plus an offset for “different question”).

### Quick replies

- “I’m not sure”: acknowledges uncertainty and asks for a single-word feeling.
- “Can you ask a different question?”: selects the next question-bank entry.
- “Maybe later”: reassures the user that existing text is saved.

This is deterministic template logic, **not natural-language understanding or
AI generation**. Repeating the same film, text, and turn produces the same
reply, which is verified in the Phase 3 E2E script.

## 5. Memory lifecycle: what exists and what does not

### Implemented retrieval

`confirmed_memories(user_id)` selects only rows where:

- `user_id` matches the caller;
- `status = 'confirmed'`;
- ordering is `updated_at DESC`;
- at most K contents are returned (default five).

The OpenAI path instead ranks memories for the current message via
`user_context.relevant_memories` (lexical overlap, explicit over inferred),
bounded by `llm_context_memories`. Proposed and rejected memories are always
excluded. The memory index `memories_user_status_idx(user_id, status)` supports
these lookups.

### Extraction, review, and forget

- **Create** — `end_conversation` calls `extract_insights`; `normalise_proposals`
  validates and `insert_proposals` persists them as `status = 'proposed'`, with
  `kind`, `evidence_type`, `scope`, `confidence`, `source_film_tmdb_id`.
  Pre-migration schemas fall back to the core columns + legacy kinds.
- **Review** — `proposed → confirmed | rejected`, with optional edit, via
  `/memories/{id}` and the Review & Edit UI. Rejected is terminal.
- **Forget** — owner delete (API + UI) and cascaded deletion when a reflection
  is deleted, via `delete_for_messages`.
- **Provenance** — `source_message_ids` is populated and read back, so memories
  cite their source messages and recommendations attribute `source_memories`.
- **Cross-film** — `recurring_themes` surfaces words recurring across distinct
  films (descriptive only).

## 6. Recommendations: verified current behavior

The deterministic engine in `server/app/recommendations.py` (D35) implements the
full pipeline:

1. **Load signals** — library rows (status/rating), `recommendation_feedback`
   (more_like_this / not_for_me), confirmed memories, `recommendation_style`.
2. **Candidates** — per-seed TMDB recommendations plus a genre `/discover`
   pool; the Film Assistant uses a wider configurable pool
   (`recommendation_pool_size_chat`, default 40).
3. **Exclusions** — library films and `not_for_me` are removed, plus any genre
   the user excludes in the current request. Explicit constraints
   (director/title/genre) rebuild the pool.
4. **Ranking** —
   `w_m·mood + w_t·taste + w_r·reflection + w_e·experience + w_n·novelty`
   (weights re-balanced toward a stated intention), plus a quality prior and a
   popularity term weighted by the style slider.
5. **Explain** — every card carries a `why` line, `source_memories`,
   `match_dimensions` and `novelty_category` (`familiar`/`adjacent`/
   `exploratory`).
6. **Feedback** — "More like this" seeds and "Not for me" excludes, both
   invalidating the per-user cache; served cards are recorded in
   `recommendation_events`.

The Film Assistant (`chat_discovery`) selects from a verified candidate pool and
is backfilled to up to three distinct cards, so it never fabricates films.

| Input | How it is stored | Effect on recommendations |
|---|---|---|
| Watched/watchlist films | `user_films.status` + rating | Seeds the pool; watched films are excluded |
| Ratings | `user_films.rating` | Rating-weighted seeds |
| Reflection history | verbatim `messages` | Extracted into memories; discussed films cross-referenced |
| Confirmed memories | `memories` | Keyword/genre affinity + reflection dimension |
| Mood / intention | parsed from the request only | Re-balances ranking weights (never persisted) |
| Recommendation style | `users.recommendation_style` | Popularity term (niche ↔ mainstream) |

## 7. Recommendation approach

Reflection-informed, intention-based recommendations are now implemented (see
`docs/08-personalisation.md`): end a reflection → propose memories → confirm /
edit / reject → confirmed memories + library history select and rank candidates
→ show a why-line → record feedback. pgvector remains deferred (D8); there is
no embedding search today, and mood/experience affinity is a deterministic
lexical proxy rather than semantic retrieval.

## 8. Deterministic logic versus AI decisions

| Behavior | Current category |
|---|---|
| TMDB search/details and metadata mapping | Deterministic external API lookup |
| Import matching and first-result selection | Deterministic application logic |
| Import retries, checkpoints, and resume | Deterministic application logic |
| Library filters/sorts and prompt-of-day rotation | Deterministic client logic |
| Chat openings/replies | Deterministic mock templates, or OpenAI chat completions when `LLM_PROVIDER=openai` |
| Memory retrieval by status/time | Deterministic SQL query |
| Memory extraction | Mock keyword proposals, or OpenAI JSON-mode extraction |
| Recommendation ranking/explanations | Deterministic scoring formula (D35) — not an AI judgment |

No current output should be presented as an independent AI judgment. When a
real provider is introduced, its prompt, model/version, temperature, safety
handling, structured-output validation, cost limits, and evaluation will need to
be documented separately.

## 9. Prompts, retrieval, and fallback behavior

### Model prompts

The OpenAI provider defines serialised system prompts `_SYSTEM_BASE`
(reflection), `_SYSTEM_DISCOVERY` (recommendation) and `_KIND_DEFINITIONS`
(memory kinds) in `server/app/llm/openai.py`; the mock’s “prompts” are Python
template banks in `server/app/llm/mock.py` (`_QUESTIONS_FILM`,
`_QUESTIONS_PLANNING`, `_QUESTIONS_FREE`, `_ACKS`, `_REFLECTIONS`). The full
prompt wording lives in those modules rather than this document.

### Retrieval

- **Film context:** relational join from `conversations` to the cached `films`
  row, plus a `film_context` dossier (director/cast/themes); TMDB is called only
  if a film is new or missing keywords/director/cast.
- **Conversation retrieval:** latest N rows by `created_at`, not semantic
  relevance.
- **Memory retrieval:** relevance-ranked confirmed memories via
  `user_context.relevant_memories` (lexical overlap, explicit over inferred),
  bounded by `llm_context_memories`; not embeddings or similarity search.
- **Viewing-history / other-film retrieval:** `user_context.viewing_history`
  (watched/watchlist) for discovery, `discussed_films` + `recent_recommendations`
  for reflection, and `film_knowledge.resolve_film_mentions` for films named in
  the current message.

No pgvector, embeddings, or RAG index exists.

### Fallbacks

- TMDB metadata: catalogue first, then title+year search, then title-only
  search. Repeated TMDB transient errors receive bounded retries.
- Discovery candidates: the provider's named films are grounded against TMDB and
  backfilled from the ranked pool; an empty pool degrades to a clarifying
  question, never a fabricated film.
- Chat provider: `mock` (default) or `openai`. There is no automatic fallback
  chain between providers; a model/API error in a discovery turn degrades to the
  candidate pool (and reflection chat keeps the conversation active for a retry).
- Import: failed rows are retained for resume instead of silently converting
  them to “unmatched” or dropping them.

## 10. Evaluation boundaries and recommendations

- The Phase 3/5/6 E2E suites verify deterministic chat behavior, bounded
  context helpers, the review flow, and the recommendation loop (seeding,
  exclusions, memory attribution, feedback, style bounds) — not model quality,
  empathy, safety, or factual accuracy.
- No test demonstrates preference *learning* beyond the deterministic signals,
  mood awareness, or explanation faithfulness against human judgment.
- **Recommendation:** keep the mock provider's deterministic fixtures for CI
  and evaluate the OpenAI provider's model behavior separately. Record exact
  prompts/model settings and test that proposed/rejected memories never enter
  context.
- **Recommendation:** evaluate recommendation relevance and explanation
  provenance with real users in Phase 7. The Phase 6 tests verify the engine's
  mechanics, not that its picks feel right.
