"""Authentication routes (F12).

Server-mediated auth: the client only ever talks to this API; the server
uses the Supabase service-role key. Signup uses the admin API with
email_confirm=True so no SMTP setup is needed for development.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..deps import get_current_user
from ..supabase_client import supabase

router = APIRouter()


class SignUpBody(BaseModel):
    email: str
    password: str = Field(min_length=8)
    display_name: str | None = None


class LoginBody(BaseModel):
    email: str
    password: str


class ForgotBody(BaseModel):
    email: str


def _get_display_name(user_id: str) -> str | None:
    res = (
        supabase.table("users")
        .select("display_name")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    return res.data[0]["display_name"] if res.data else None


def _session_response(user_id: str, email: str, access_token: str) -> dict:
    return {
        "access_token": access_token,
        "user": {
            "id": user_id,
            "email": email,
            "display_name": _get_display_name(user_id),
        },
    }


@router.post("/signup")
def signup(body: SignUpBody) -> dict:
    try:
        created = supabase.auth.admin.create_user(
            {
                "email": body.email,
                "password": body.password,
                "email_confirm": True,
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not create account: {exc}")

    user = created.user
    supabase.table("users").insert(
        {"id": user.id, "display_name": body.display_name}
    ).execute()

    session = supabase.auth.sign_in_with_password(
        {"email": body.email, "password": body.password}
    )
    return _session_response(user.id, user.email, session.session.access_token)


@router.post("/login")
def login(body: LoginBody) -> dict:
    try:
        res = supabase.auth.sign_in_with_password(
            {"email": body.email, "password": body.password}
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if res.session is None or res.user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return _session_response(res.user.id, res.user.email, res.session.access_token)


@router.post("/forgot-password")
def forgot_password(body: ForgotBody) -> dict:
    # Always return ok — never reveal whether an account exists.
    try:
        supabase.auth.reset_password_for_email(body.email)
    except Exception:
        pass
    return {"ok": True}


@router.get("/me")
def me(current: dict = Depends(get_current_user)) -> dict:
    # Self-heal: ensure the profile row exists (signup also inserts it, but
    # this covers users created before the profile table existed).
    supabase.table("users").upsert({"id": current["id"]}, on_conflict="id").execute()
    return {
        "id": current["id"],
        "email": current["email"],
        "display_name": _get_display_name(current["id"]),
    }
