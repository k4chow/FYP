from supabase import Client, create_client

from .config import settings

if not settings.supabase_url or not settings.supabase_service_role_key:
    raise RuntimeError(
        "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in server/.env"
    )

# Service-role client: bypasses RLS, so every query must be scoped to the
# authenticated user's id explicitly. RLS remains as defence in depth.
supabase: Client = create_client(
    settings.supabase_url, settings.supabase_service_role_key
)

# Separate client for auth API calls. supabase-py propagates sign-in state
# into the client's PostgREST headers, which would silently downgrade the
# DB connection from service-role to a user token — so auth operations
# must never run on the shared `supabase` client.
auth_client: Client = create_client(
    settings.supabase_url, settings.supabase_service_role_key
)
