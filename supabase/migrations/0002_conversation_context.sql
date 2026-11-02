-- NOACF Phase 3 migration: reflection-chat context fields on conversations
--   watch_type: was the film already seen, or is the user planning to watch it?
--     ('seen' covers the mockup's "First time watching" / "Rewatch" choices —
--      that distinction is UI-only framing, not stored)
--   ended_at:   set by POST /conversations/{id}/end; status becomes 'completed'
-- Run in the Supabase SQL editor after 0001_init.sql.

alter table public.conversations
  add column if not exists watch_type text
    check (watch_type in ('seen', 'planning'));

alter table public.conversations
  add column if not exists ended_at timestamptz;
