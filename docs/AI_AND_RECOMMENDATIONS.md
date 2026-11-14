# NOACF — AI, Chat Context, Memory, and Recommendations

> **Status note:** as of Phase 7 the assistant runs behind a provider
> abstraction (mock or OpenAI, D33), the deterministic recommendation engine
> (D35) is live, and the Film Assistant is ephemeral with explicit-constraint
> parsing (F12). Mood-based recommendations remain unimplemented. Sections
> below describe current behavior unless marked otherwise.

## 1. Implementation status

| Capability | Status | Verifiable evidence |
|---|---|---|
| Provider abstraction | **Implemented** | `server/app/llm/base.py`, `__init__.py` |
| Reflective assistant replies | **Implemented, mocked** | `server/app/llm/mock.py` |
| Real external model calls | **Implemented (OpenAI)** | `server/app/llm/openai.py`, `LLM_PROVIDER=openai` (D33) |
| Bounded chat context | **Implemented** | `server/app/context.py` |
| Confirmed-memory retrieval | **Implemented read path only** | `confirmed_memories` |
| Memory extraction/review/edit/forget | **Implemented** | Mock keyword proposals + review endpoints/UI (Phases 4–5) |
| Recommendations and explanations | **Implemented (deterministic)** | `server/app/recommendations.py`, Discover page (Phase 6, D35) |
| Mood-based recommendations | **Not implemented** | No mood field, extraction, or scoring |
| Recommendation feedback + style slider | **Implemented** | `recommendation_feedback` table, `/profile/preferences` (Phase 6, D36/D37) |
| Persisted Film Assistant (F10) | **Implemented** | saved as `type="discovery"` conversations via `/conversations`; `exclude_tmdb_ids` rotation on Regenerate/replies (Phase 7) |
| Explicit-constraint recommendations (F12) | **Implemented** | `server/app/constraints.py`; director/title/genre parsing validated against TMDB (Phase 7) |
| Named-film answers without refusal | **Implemented** | `_requested_title_cards`; already-logged films return close alternatives (Phase 7) |

## 2. Provider selection and interface

`get_llm()` is the only provider factory used by the conversation router. It is
cached with `lru_cache` and accepts `LLM_PROVIDER=mock` (default, deterministic)
or `openai` (D33, key via `OPENAI_API_KEY`, model via `OPENAI_MODEL`, default
`gpt-6-luna`); any other value raises `RuntimeError`
(`server/app/llm/__init__.py`). There is no automatic fallback chain.

The abstract `LLMProvider` defines:

- `opening(context) -> str`: first assistant message for a new conversation.
- `chat(messages, context) -> str`: reply to the latest user message.
- `extract_insights(messages, context) -> list[dict]`: memory-extraction seam,
  implemented in both providers — mock derives keyword proposals, OpenAI
  requests JSON mode (unparseable output raises so the conversation stays
  active for a retry).

`ChatContext` is a dataclass containing conversation type, title, optional raw
film row, watch type, confirmed-memory strings, display name, and user-turn
count. There is no model-specific prompt type, embedding object, or system
prompt field.

## 3. How the chatbot receives film and user context

For each new conversation, `_chat_context` in
`server/app/routers/conversations.py` assembles:

1. `conversation_type` and `title` from the conversation.
2. The joined `films` row when linked: title, year, genres, poster path, and
   metadata such as overview/runtime. TMDB data was cached earlier by
   `_ensure_film`; the mock does not call TMDB itself.
3. `watch_type` (`seen` or `planning`).
4. Up to five confirmed-memory contents, newest `updated_at` first.
5. The user’s `display_name` from `public.users`.
6. A turn count, currently the number of user messages in the conversation.

For a reply, `recent_messages` separately fetches at most 12 messages, newest
first, then reverses them to oldest-first. The UI still receives full history;
this limit applies only to the provider input. The two bounds can be changed
with `LLM_CONTEXT_MESSAGES` and `LLM_CONTEXT_MEMORIES` settings (defaults 12/5).

There is no watched-film lookup, rating aggregation, mood input, semantic
search, or recommendation candidate list in `ChatContext`.

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

Proposed and rejected memories are excluded by the query. The mock mentions a
confirmed memory on every third applicable user turn. The memory index
`memories_user_status_idx(user_id, status)` supports this lookup.

### Not implemented

- **Create:** `extract_insights` returns `[]`; ending a conversation does not
  call extraction or insert proposed memories.
- **Confirm/reject:** no memory endpoints or Review & Edit page exist.
- **Edit:** `content` is editable at the schema/RLS level, but there is no
  application edit flow.
- **Forget:** SQL has an owner delete policy, but there is no API or UI delete.
- **Contradiction resolution:** no detection or comparison code exists.
- **Provenance:** `source_message_ids` is stored by schema but not populated or
  read by current code, so it cannot yet explain recommendations.

The intended `proposed → confirmed | rejected` lifecycle is therefore a design
constraint for future work, not a completed user-control feature.

## 6. Recommendations: verified current behavior

There is no step-by-step recommendation algorithm in the current repository.
Specifically, there is no code that:

1. selects candidate films;
2. scores them against watched films, ratings, watchlist status, or memories;
3. accepts or extracts a mood;
4. generates a “why” explanation;
5. records “More like this” or “Not for me” feedback;
6. adjusts recommendations using the Settings slider.

The consequences for the requested preference inputs are:

| Input | How it is stored now | Effect on recommendations now |
|---|---|---|
| Watched/watchlist films | `user_films.status` | **None** — no recommendation reader |
| Ratings/dates/source | `user_films` fields | **None** |
| Reflection history | Verbatim `messages` | **None** directly; only bounded mock-chat use |
| Confirmed preferences | `memories.content` | **None** — no recommendation engine |
| Mood | No dedicated field or extraction | **None**; mood handling is undesigned |
| Recommendation style | Disabled UI slider | **None**; no persisted setting |

## 7. Intended recommendation approach (planned, not implemented)

Project notes propose reflection-informed, intention-based recommendations using
confirmed memories and film history, with human-readable explanations and a
feedback loop. The following is a **design outline, not verified behavior**:

1. End a reflection and propose candidate memories.
2. Let the user confirm/edit/reject them.
3. Use confirmed memories plus library history to select/rank candidates.
4. Show a “why” linked to source memories/messages.
5. Record explicit feedback for later refinement.

These questions were resolved in Phase 6: candidate sources (per-seed TMDB
recommendations + genre `/discover` pool), scoring (D35's formula), explanation
generation (per-card `why` + `source_memories`), feedback schema
(`recommendation_feedback`, D36), and cold-start behavior (popular TMDB picks
with an honest why-line). Mood representation is still unresolved and
unimplemented. pgvector remains deferred until plain SQL retrieval is proven
insufficient (D8); there is no embedding search today.

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

There is no serialized system prompt or model request payload to quote. The
mock’s “prompts” are Python template banks in `server/app/llm/mock.py`:
`_QUESTIONS_FILM`, `_QUESTIONS_PLANNING`, `_QUESTIONS_FREE`, `_ACKS`, and
`_REFLECTIONS`. Model name, temperature, token limits, and response-format
instructions are therefore not applicable in the current implementation.

### Retrieval

- **Film context:** relational join from `conversations` to the cached `films`
  row; TMDB is called only if a new film must first be cached.
- **Conversation retrieval:** latest N rows by `created_at`, not semantic
  relevance.
- **Memory retrieval:** latest K confirmed rows by `updated_at`, not embeddings
  or similarity search.
- **Library retrieval for chat:** not performed.

No pgvector, embeddings, RAG index, or recommendation-specific retrieval exists.

### Fallbacks

- TMDB metadata: catalogue first, then title+year search, then title-only
  search. Repeated TMDB transient errors receive bounded retries.
- Chat provider: only `mock` is supported; there is no fallback to another model
  or provider. A real-provider integration must define its own failure policy.
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
