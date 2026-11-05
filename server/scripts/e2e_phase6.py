"""Phase 6 E2E: recommendation engine (F8/F9), feedback loop (F11),
style preferences (N6), and the Film Assistant discovery chat (F10)
against live Supabase + live TMDB.

Requires: uvicorn on :8000 and migration 0005_recommendations.sql applied.
Run from server/:  python scripts/e2e_phase6.py
Writes a full log to scripts/e2e_phase6_output.txt
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Why-lines contain "★"/"—"; the Windows console is cp1252 by default.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"
PASSWORD = "testpassword123"
LOG = Path(__file__).with_name("e2e_phase6_output.txt")
_lines: list[str] = []
CHECKS: list[bool] = []

ARRIVAL = 329865  # Arrival (2016), rated 5, watched
LA_LA_LAND = 313369  # watchlist


def log(msg: str = "") -> None:
    print(msg)
    _lines.append(str(msg))


def request(method: str, path: str, body=None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode())
        except Exception:
            payload = {}
        return exc.code, payload


def check(name: str, cond: bool, detail: str = "") -> None:
    CHECKS.append(bool(cond))
    log(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def signup(tag: str) -> tuple[str, str]:
    email = f"noacf.phase6.{tag}.{int(time.time())}@example.com"
    status, body = request(
        "POST", "/auth/signup",
        {"email": email, "password": PASSWORD, "display_name": f"Phase 6 {tag}"},
    )
    if status != 200:
        raise RuntimeError(f"signup failed: {status} {body}")
    return body["access_token"], body["user"]["id"]


def cleanup(user_id: str | None) -> None:
    if not user_id:
        return
    from app.supabase_client import admin_auth_client

    try:
        admin_auth_client.auth.admin.delete_user(user_id)
        log(f"temporary user {user_id} deleted")
    except Exception as exc:
        log(f"cleanup failed: {type(exc).__name__}")


def seed_memory(user_id: str, content: str) -> None:
    """Insert a confirmed memory directly (review flow is Phase 4's surface)."""
    from app.supabase_client import supabase

    supabase.table("memories").insert(
        {
            "user_id": user_id,
            "content": content,
            "kind": "preference",
            "status": "confirmed",
            "source_message_ids": [],
        }
    ).execute()


def main() -> None:
    user_id = None
    try:
        status, health = request("GET", "/health")
        check("server healthy on 0.6.0", status == 200 and health.get("version") == "0.6.0")

        token, user_id = signup("recs")

        # --- Cold start: no library yet → popular TMDB fallback -------------
        status, body = request("GET", "/recommendations", token=token)
        recs = body.get("recommendations", [])
        check("cold start returns cards", status == 200 and len(recs) > 0,
              f"{len(recs)} cards")
        check(
            "cold start why is honest about the fallback",
            recs and all("Popular on TMDB" in c["why"] for c in recs),
        )
        check(
            "cards carry explanation + provenance fields",
            recs and all(
                isinstance(c.get("source_memories"), list) and c.get("why")
                for c in recs
            ),
        )

        # --- Preferences (N6) ------------------------------------------------
        status, prefs = request("GET", "/profile/preferences", token=token)
        check("default style is 30", status == 200 and prefs.get("recommendation_style") == 30)
        status, prefs = request(
            "PATCH", "/profile/preferences", {"recommendation_style": 85}, token
        )
        check("style slider saves", status == 200 and prefs.get("recommendation_style") == 85)
        status, _ = request("PATCH", "/profile/preferences", {"recommendation_style": 150}, token)
        check("out-of-range style rejected (422)", status == 422)

        # --- Seed the profile: library + one confirmed memory ----------------
        status, _ = request(
            "POST", "/films/mine",
            {"tmdb_id": ARRIVAL, "status": "watched", "rating": 5}, token,
        )
        check("Arrival added (watched, 5 stars)", status == 201)
        status, _ = request(
            "POST", "/films/mine", {"tmdb_id": LA_LA_LAND, "status": "watchlist"}, token
        )
        check("La La Land added (watchlist)", status == 201)
        seed_memory(user_id, "You love quiet, hopeful sci-fi stories.")

        status, body = request("GET", "/recommendations", token=token)
        recs = body.get("recommendations", [])
        ids = [c["tmdb_id"] for c in recs]
        check("seeded run returns cards", status == 200 and len(recs) > 0,
              f"{len(recs)} cards")
        check("library films are never recommended",
              ARRIVAL not in ids and LA_LA_LAND not in ids)
        check(
            "at least one card cites the confirmed insight (F8/F9)",
            any(c["source_memories"] for c in recs),
            next((c["why"] for c in recs if c["source_memories"]), "none"),
        )
        check(
            "at least one card explains via the library (rating/watchlist)",
            any('rated "Arrival"' in c["why"] or "watchlist" in c["why"] for c in recs),
            recs[0]["why"] if recs else "none",
        )

        # --- Feedback loop (F11) --------------------------------------------
        target = recs[0]
        status, fb = request(
            "POST", "/recommendations/feedback",
            {"tmdb_id": target["tmdb_id"], "signal": "not_for_me", "title": target["title"]},
            token,
        )
        check("not_for_me feedback accepted", status == 200 and fb.get("signal") == "not_for_me")
        status, body = request("GET", "/recommendations", token=token)
        ids = [c["tmdb_id"] for c in body.get("recommendations", [])]
        check("not_for_me film excluded afterwards (cache invalidated)",
              status == 200 and target["tmdb_id"] not in ids)
        status, fb = request(
            "POST", "/recommendations/feedback",
            {"tmdb_id": 157336, "signal": "more_like_this", "title": "Interstellar"},
            token,
        )
        check("more_like_this feedback accepted", status == 200)
        status, body = request("GET", "/recommendations", token=token)
        check(
            "recommendations still healthy after feedback seed",
            status == 200 and len(body.get("recommendations", [])) > 0,
        )
        status, _ = request("DELETE", f"/recommendations/feedback/{target['tmdb_id']}", token=token)
        check("feedback can be undone", status == 200)
        status, _ = request(
            "POST", "/recommendations/feedback",
            {"tmdb_id": 1, "signal": "love_it"}, token,
        )
        check("invalid signal rejected (422)", status == 422)

        # --- Film Assistant discovery conversation (F10) ---------------------
        status, convo = request(
            "POST", "/conversations", {"type": "discovery", "title": "Film Assistant"}, token
        )
        conv = convo.get("conversation", {})
        opening = [m for m in convo.get("messages", []) if m.get("role") == "assistant"]
        check("discovery conversation created with assistant opening",
              status == 201 and conv.get("type") == "discovery" and bool(opening))
        status, reply = request(
            "POST", f"/conversations/{conv['id']}/messages",
            {"content": "I want something hopeful and quiet, maybe sci-fi."}, token,
        )
        check("assistant replies in discovery chat",
              status == 201 and bool((reply.get("assistant_message") or {}).get("content")))
        status, ended = request("POST", f"/conversations/{conv['id']}/end", token=token)
        check("discovery conversation ends cleanly",
              status == 200 and ended.get("conversation", {}).get("status") == "completed")
    finally:
        cleanup(user_id)
        LOG.write_text("\n".join(_lines), encoding="utf-8")
        log(f"\n{sum(CHECKS)}/{len(CHECKS)} checks passed")


if __name__ == "__main__":
    main()

