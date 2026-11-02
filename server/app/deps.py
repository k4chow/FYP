"""Shared FastAPI dependencies."""

from fastapi import Header, HTTPException

from .supabase_client import auth_client


def get_current_user(authorization: str = Header(...)) -> dict:
    """Verify the Supabase access token and return the user's id + email."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        res = auth_client.auth.get_user(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if res is None or res.user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {"id": res.user.id, "email": res.user.email}
