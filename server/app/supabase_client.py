import httpx
from supabase import Client, ClientOptions, create_client

from .config import settings

if not settings.supabase_url or not settings.supabase_service_role_key:
    raise RuntimeError(
        "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in server/.env"
    )

# PostgREST per-request URLs and auth headers are supplied by the request
# builder, so this client only configures transport. Two deviations from the
# postgrest default session, both for the flaky dev network path (local
# proxy/NAT):
# - HTTP/2 disabled: the path mishandles h2 connections (the same reason git
#   push needs http.version=HTTP/1.1), surfacing as httpx.RemoteProtocolError
#   "Server disconnected" and intermittent 500s.
# - Keep-alive pooling disabled: idle pooled connections are silently dropped
#   by the middlebox, so each request opens a fresh connection instead.
_db_http = httpx.Client(
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=0),
    timeout=httpx.Timeout(120.0),
    follow_redirects=True,
    http2=False,
)

# Service-role client: bypasses RLS, so every query must be scoped to the
# authenticated user's id explicitly. RLS remains as defence in depth.
supabase: Client = create_client(
    settings.supabase_url,
    settings.supabase_service_role_key,
    options=ClientOptions(httpx_client=_db_http),
)

# Separate client for auth API calls. supabase-py propagates sign-in state
# into the client's PostgREST headers, which would silently downgrade the
# DB connection from service-role to a user token — so auth operations
# must never run on the shared `supabase` client.
auth_client: Client = create_client(
    settings.supabase_url, settings.supabase_service_role_key
)

# Dedicated client for ADMIN auth calls (create_user / update_user_by_id /
# delete_user). gotrue-py persists sign-in state on the client, so once
# `auth_client` performs sign_in_with_password, its Authorization header
# becomes the signed-in USER's JWT and subsequent admin calls on it fail
# with AuthApiError "User not allowed" (or "token is expired" once the
# user token lapses). This client must never perform a sign-in.
admin_auth_client: Client = create_client(
    settings.supabase_url, settings.supabase_service_role_key
)
