-- NOACF Phase 6: recommendation engine persistence (F11, N6).
-- 1) users.recommendation_style — the Settings slider position
--    (0 = "More like what I love", 100 = "Surprise me"; default 30).
-- 2) recommendation_feedback — explicit card feedback that steers future
--    recommendations: "more_like_this" rows become extra seeds and
--    "not_for_me" rows are hard exclusions.
-- Run in the Supabase SQL editor after 0004_onboarding.sql.

alter table public.users
  add column if not exists recommendation_style smallint not null default 30;

alter table public.users
  drop constraint if exists users_recommendation_style_range;
alter table public.users
  add constraint users_recommendation_style_range
  check (recommendation_style between 0 and 100);

create table if not exists public.recommendation_feedback (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  tmdb_id integer not null,
  -- Denormalised card title so "Because you asked for more like X"
  -- explanations never need an extra TMDB lookup.
  title text not null default '',
  signal text not null check (signal in ('more_like_this', 'not_for_me')),
  created_at timestamptz not null default now(),
  unique (user_id, tmdb_id)
);

create index if not exists recommendation_feedback_user_idx
  on public.recommendation_feedback (user_id);

alter table public.recommendation_feedback enable row level security;

create policy recommendation_feedback_select_own on public.recommendation_feedback
  for select using (auth.uid() = user_id);
create policy recommendation_feedback_insert_own on public.recommendation_feedback
  for insert with check (auth.uid() = user_id);
create policy recommendation_feedback_update_own on public.recommendation_feedback
  for update using (auth.uid() = user_id);
create policy recommendation_feedback_delete_own on public.recommendation_feedback
  for delete using (auth.uid() = user_id);
