# 04 — Database Schema

Defined in `supabase/migrations/0001_init.sql`. All PKs are UUIDs
(`gen_random_uuid()`). Every user-owned table has RLS enabled with
owner-only policies; `films` is a shared read-only catalogue (writes via
service role only).

## Tables

### users
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | References `auth.users(id)` — 1:1 with Supabase Auth |
| display_name | text | |
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
| status | text | `active` \| `completed` |
| title | text | |

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
| source_message_ids | jsonb | traceability for "Why am I seeing this?" |

## Indexes
- `user_films(user_id, status)` — library views
- `conversations(user_id, status, updated_at desc)` — My Reflections list
- `messages(conversation_id, created_at)` — chat loading + context assembly
- `memories(user_id, status)` — profile + recommendation lookups

## Future
- pgvector embedding column on `memories`/`films` **only if** SQL retrieval
  proves insufficient for context assembly (decision D8).
