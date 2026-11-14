-- NOACF personalisation follow-up (Part E/F): track when a recommended film
-- is later watched, closing the discovery -> reflection loop. Additive; run
-- after 0007_recommendation_events.sql.

alter table public.recommendation_events
  add column if not exists watched_at timestamptz;