-- NOACF personalisation (Parts D/F): recommendation events.
-- Persists what was recommended and why, so a later reflection on a recommended
-- film can surface the reason it was suggested (discovery -> reflection), and
-- the assistant can avoid repeating the same picks without justification
-- (discovery -> discovery). Additive; run after 0006_personalisation_memories.sql.

create table if not exists public.recommendation_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  tmdb_id integer not null,
  title text not null default '',
  reason text,
  match_dimensions jsonb not null default '[]',
  novelty_category text,
  created_at timestamptz not null default now()
);

create index if not exists recommendation_events_user_idx
  on public.recommendation_events (user_id, created_at desc);

alter table public.recommendation_events enable row level security;

create policy recommendation_events_select_own on public.recommendation_events
  for select using (auth.uid() = user_id);
create policy recommendation_events_insert_own on public.recommendation_events
  for insert with check (auth.uid() = user_id);
create policy recommendation_events_update_own on public.recommendation_events
  for update using (auth.uid() = user_id);
create policy recommendation_events_delete_own on public.recommendation_events
  for delete using (auth.uid() = user_id);