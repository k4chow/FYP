-- NOACF initial schema (Phase 0)
-- 3-layer architecture:
--   Layer 1: conversations + messages (source of truth, never overwritten)
--   Layer 2: memories (user-controlled reflective profile)
--   Layer 3: films + user_films (reflection & discovery surface)
-- Run in the Supabase SQL editor.

create extension if not exists "pgcrypto";

-- users: application profile, 1:1 with Supabase Auth (auth.users)
create table if not exists public.users (
  id           uuid primary key references auth.users (id) on delete cascade,
  display_name text,
  created_at   timestamptz not null default now()
);

-- films: shared catalogue metadata (not user-owned)
create table if not exists public.films (
  id          uuid primary key default gen_random_uuid(),
  tmdb_id     integer unique,
  title       text not null,
  year        integer,
  genres      jsonb not null default '[]',
  poster_path text,
  metadata    jsonb not null default '{}',
  created_at  timestamptz not null default now()
);

-- user_films: a user's relationship to a film
create table if not exists public.user_films (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references public.users (id) on delete cascade,
  film_id    uuid not null references public.films (id) on delete cascade,
  status     text not null check (status in ('watched', 'watchlist')),
  source     text not null default 'manual' check (source in ('manual', 'letterboxd')),
  rating     numeric(2,1) check (rating is null or (rating >= 0 and rating <= 5)),
  watched_on date,
  added_at   timestamptz not null default now(),
  unique (user_id, film_id)
);

create index if not exists user_films_user_idx on public.user_films (user_id, status);

-- conversations: reflection sessions and discovery chats
create table if not exists public.conversations (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references public.users (id) on delete cascade,
  film_id    uuid references public.films (id) on delete set null,
  type       text not null check (type in ('reflection', 'discovery')),
  title      text,
  status     text not null default 'active' check (status in ('active', 'completed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists conversations_user_idx
  on public.conversations (user_id, status, updated_at desc);

-- messages: conversation history — the source of truth, never overwritten
create table if not exists public.messages (
  id              uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations (id) on delete cascade,
  role            text not null check (role in ('user', 'assistant', 'system')),
  content         text not null,
  metadata        jsonb not null default '{}',
  created_at      timestamptz not null default now()
);

create index if not exists messages_conversation_idx
  on public.messages (conversation_id, created_at);

-- memories: reflective profile (layer 2). Insights are proposed by the
-- system and only used after the user confirms them (user-controlled).
create table if not exists public.memories (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references public.users (id) on delete cascade,
  content            text not null,
  kind               text not null default 'insight'
                     check (kind in ('theme', 'preference', 'insight')),
  status             text not null default 'proposed'
                     check (status in ('proposed', 'confirmed', 'rejected')),
  source_message_ids jsonb not null default '[]',
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create index if not exists memories_user_status_idx
  on public.memories (user_id, status);

-- Row Level Security: users only ever see their own rows. The server uses
-- the service role key (bypasses RLS); these policies protect direct access.
alter table public.users         enable row level security;
alter table public.films         enable row level security;
alter table public.user_films    enable row level security;
alter table public.conversations enable row level security;
alter table public.messages      enable row level security;
alter table public.memories      enable row level security;

create policy users_select_own on public.users
  for select using (auth.uid() = id);
create policy users_insert_own on public.users
  for insert with check (auth.uid() = id);
create policy users_update_own on public.users
  for update using (auth.uid() = id);

-- films is a shared catalogue: read for all authenticated users,
-- writes service-role only (no write policies for regular users)
create policy films_select_all on public.films
  for select using (auth.role() = 'authenticated');

create policy user_films_select_own on public.user_films
  for select using (auth.uid() = user_id);
create policy user_films_insert_own on public.user_films
  for insert with check (auth.uid() = user_id);
create policy user_films_update_own on public.user_films
  for update using (auth.uid() = user_id);
create policy user_films_delete_own on public.user_films
  for delete using (auth.uid() = user_id);

create policy conversations_select_own on public.conversations
  for select using (auth.uid() = user_id);
create policy conversations_insert_own on public.conversations
  for insert with check (auth.uid() = user_id);
create policy conversations_update_own on public.conversations
  for update using (auth.uid() = user_id);
create policy conversations_delete_own on public.conversations
  for delete using (auth.uid() = user_id);

create policy messages_select_own on public.messages
  for select using (exists (
    select 1 from public.conversations c
    where c.id = conversation_id and c.user_id = auth.uid()));
create policy messages_insert_own on public.messages
  for insert with check (exists (
    select 1 from public.conversations c
    where c.id = conversation_id and c.user_id = auth.uid()));

create policy memories_select_own on public.memories
  for select using (auth.uid() = user_id);
create policy memories_insert_own on public.memories
  for insert with check (auth.uid() = user_id);
create policy memories_update_own on public.memories
  for update using (auth.uid() = user_id);
create policy memories_delete_own on public.memories
  for delete using (auth.uid() = user_id);
