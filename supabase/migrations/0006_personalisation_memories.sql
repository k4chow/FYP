-- NOACF personalisation (Part C): richer memory representation.
-- 1) Widen the memory `kind` vocabulary without dropping existing rows.
-- 2) Add evidence_type / scope / confidence / source_film_tmdb_id so
--    extraction can distinguish explicit statements from inferred readings and
--    tie a memory back to the film that prompted it.
-- All additive with backwards-compatible defaults; existing rows are preserved.
-- Run in the Supabase SQL editor after 0005_recommendations.sql.

alter table public.memories
  drop constraint if exists memories_kind_check;

alter table public.memories
  add constraint memories_kind_check
  check (kind in ('theme', 'preference', 'insight', 'aesthetic', 'narrative',
                  'emotional_response', 'viewing_intention'));

alter table public.memories
  add column if not exists evidence_type text not null default 'inferred';

alter table public.memories
  add column if not exists scope text not null default 'stable';

alter table public.memories
  add column if not exists confidence real;

alter table public.memories
  add column if not exists source_film_tmdb_id integer;

-- User-authored memories (onboarding, empty source_message_ids) were written
-- by the user about themselves, so treat them as explicit statements rather
-- than inferred guesses. System-proposed (and user-confirmed) memories keep the
-- 'inferred' default: confirmation is endorsement of our interpretation, not
-- a literal quote of something the user said.
update public.memories
  set evidence_type = 'explicit'
where evidence_type = 'inferred'
  and (source_message_ids is null or source_message_ids = '[]'::jsonb);