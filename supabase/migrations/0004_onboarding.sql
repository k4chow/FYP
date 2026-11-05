-- NOACF Phase 5: onboarding completion flag on the users profile row.
-- New signups default to false and are routed through the onboarding flow;
-- accounts that already exist when this migration runs are grandfathered as
-- completed so they are never forced back through onboarding.
-- Run in the Supabase SQL editor after 0003_import_jobs.sql.

alter table public.users
  add column if not exists onboarding_completed boolean not null default false;

-- Grandfather every account that predates the onboarding flow.
update public.users set onboarding_completed = true
where onboarding_completed = false;
