-- NOACF large-import fix: persistent, resumable Letterboxd import jobs.
-- rows stores only the normalized fields required to resume (name, year,
-- rating, watched_on); the original CSV and unrelated columns are not stored.
-- results maps row indexes to their outcome, allowing failed rows to be retried
-- without repeating successful TMDB work. Run after 0002_conversation_context.sql.

create table if not exists public.import_jobs (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references public.users (id) on delete cascade,
  source_filename text,
  target_status  text not null check (target_status in ('watched', 'watchlist')),
  status         text not null default 'queued'
                 check (status in ('queued', 'processing', 'completed',
                                   'completed_with_errors', 'failed')),
  total_rows     integer not null default 0,
  processed_rows integer not null default 0,
  added_count    integer not null default 0,
  updated_count  integer not null default 0,
  duplicate_count integer not null default 0,
  unmatched_count integer not null default 0,
  failed_count   integer not null default 0,
  next_row       integer not null default 0,
  rows           jsonb not null default '[]',
  results        jsonb not null default '{}',
  error          text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  completed_at   timestamptz
);

create index if not exists import_jobs_user_idx
  on public.import_jobs (user_id, created_at desc);
create index if not exists import_jobs_status_idx
  on public.import_jobs (status, updated_at);

alter table public.import_jobs enable row level security;

create policy import_jobs_select_own on public.import_jobs
  for select using (auth.uid() = user_id);
create policy import_jobs_insert_own on public.import_jobs
  for insert with check (auth.uid() = user_id);
create policy import_jobs_update_own on public.import_jobs
  for update using (auth.uid() = user_id);
create policy import_jobs_delete_own on public.import_jobs
  for delete using (auth.uid() = user_id);
