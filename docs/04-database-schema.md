# 04 — Database Schema

Defined in `supabase/migrations/0001_init.sql`; Phase 3 conversation fields
are added by `0002_conversation_context.sql`, persistent import jobs by
`0003_import_jobs.sql`, the onboarding flag by `0004_onboarding.sql`, and
recommendation style/feedback by `0005_recommendations.sql`. All PKs are UUIDs
(`gen_random_uuid()`). Every user-owned table has RLS enabled with
owner-only policies; `films` is a shared read-only catalogue (writes via
service role only).

## Tables

### users
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | References `auth.users(id)` — 1:1 with Supabase Auth |
| display_name | text | |
| onboarding_completed | boolean | default `false` for new signups (0004, D30) |
| recommendation_style | smallint | 0–100 similar↔exploratory slider, default 30 (0005, D37) |
| created_at | timestamptz | |

### films (shared catalogue)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| tmdb_id | int, unique | Nullable to allow manual entries |
| title / year | text / int | |
| genres | jsonb | e.g. `["Sci-Fi","Drama"]` |
| poster_path | text | TMDB path, resolved against image CDN |
| metadata | jsonb | Flexible TMDB extras (runtime, synopsis…) |

### user_films
| Column | Type | Notes |
|---|---|---|
| user_id, film_id | uuid FK | `unique(user_id, film_id)` |
| status | text | `watched` \| `watchlist` |
| source | text | `manual` \| `letterboxd` |
| rating | numeric(2,1) | 0–5, nullable (Letterboxd scale) |
| watched_on | date | nullable |

### conversations
| Column | Type | Notes |
|---|---|---|
| user_id | uuid FK | owner (RLS) |
| film_id | uuid FK, nullable | set for reflection sessions |
| type | text | `reflection` \| `discovery` |
| watch_type | text, nullable | `seen` \| `planning`; set for film reflections (0002) |
| status | text | `active` \| `completed` |
| title | text | Film reflection title or free-reflection prompt |
| ended_at | timestamptz, nullable | Set when the reflection is ended (0002) |

### messages (append-only, layer 1)
| Column | Type | Notes |
|---|---|---|
| conversation_id | uuid FK | RLS via parent conversation |
| role | text | `user` \| `assistant` \| `system` |
| content | text | verbatim, never updated |
| metadata | jsonb | e.g. quick-reply choices |

### memories (layer 2, user-controlled)
| Column | Type | Notes |
|---|---|---|
| user_id | uuid FK | owner (RLS) |
| content | text | the insight, user-editable |
| kind | text | `theme` \| `preference` \| `insight` |
| status | text | `proposed` → `confirmed` \| `rejected` (user-only transitions) |
| source_message_ids | jsonb | validated source-message UUIDs; provides both "Why am I seeing this?" traceability and the durable reflection linkage |

No separate insight table or conversation column is used: a memory is linked to
its reflection through the immutable `source_message_ids`, which the server
validates before insert and resolves back to owned messages when serialising.
Review edits update only `content`/`status`/`updated_at`, never the source ids.

### import_jobs (persistent Letterboxd imports, 0003)
| Column | Type | Notes |
|---|---|---|
| id / user_id | uuid PK / uuid FK | owner (RLS) |
| source_filename | text | original filename only, not the file |
| target_status | text | `watched` \| `watchlist` |
| status | text | `queued` → `processing` → `completed` \| `completed_with_errors` \| `failed` |
| total_rows / processed_rows | int | upload size / unique rows with an outcome |
| added_count / updated_count / duplicate_count | int | library outcomes |
| unmatched_count / failed_count | int | no TMDB match vs temporary failure |
| next_row | int | highest checkpointed row index + 1 |
| rows | jsonb | normalized name/year/rating/watched_on only |
| results | jsonb | per-row outcome + error, for resume |
| error | text, nullable | job-level failure detail |
| created_at / updated_at / completed_at | timestamptz | updated_at is the worker heartbeat |

The API never returns `rows` or `results`; it returns counts plus normalized
unmatched/failure details. RLS owner policies cover select/insert/update/delete.

### recommendation_feedback (0005, D36)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| user_id, tmdb_id | uuid FK / int | `unique(user_id, tmdb_id)`; upsert target |
| title | text | Denormalised so why-lines need no TMDB call |
| signal | text | `more_like_this` \| `not_for_me` (check constraint) |
| created_at | timestamptz | |

## Indexes
- `user_films(user_id, status)` — library views
- `conversations(user_id, status, updated_at desc)` — My Reflections list
- `messages(conversation_id, created_at)` — chat loading + context assembly
- `memories(user_id, status)` — profile + recommendation lookups
- `import_jobs(user_id, created_at desc)` — user job history
- `import_jobs(status, updated_at)` — startup recovery and stale-job checks
- `recommendation_feedback(user_id)` — per-user feedback loads for the engine

## Future
- pgvector embedding column on `memories`/`films` **only if** SQL retrieval
  proves insufficient for context assembly (decision D8).
