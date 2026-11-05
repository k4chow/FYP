"""Phase 5 E2E: reflective profile (F2), onboarding flag, and the
watched-wins library rule against live Supabase + live TMDB.

Requires: uvicorn on :8000 and migration 0004_onboarding.sql applied.
Run from server/:  python scripts/e2e_phase5.py
Writes a full log to scripts/e2e_phase5_output.txt
"""

import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = "http://localhost:8000"
PASSWORD = "testpassword123"
LOG = Path(__file__).with_name("e2e_phase5_output.txt")
_lines: list[str] = []
CHECKS: list[bool] = []


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
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode())
        except Exception:
            payload = {}
        return exc.code, payload


def upload_csv(token: str, filename: str, csv_text: str):
    """Multipart upload to /import/letterboxd without extra dependencies."""
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: text/csv\r\n\r\n"
        f"{csv_text}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(BASE + "/import/letterboxd", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def check(name: str, cond: bool, detail: str = "") -> None:
    CHECKS.append(bool(cond))
    log(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def wait_import(token: str, import_id: str, timeout: int = 120) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, job = request("GET", f"/import/{import_id}", token=token)
        if status == 200 and job.get("status") not in ("queued", "processing"):
            return job
        time.sleep(1)
    raise TimeoutError(f"import {import_id} did not finish")


def signup(tag: str) -> tuple[str, str, str]:
    email = f"noacf.phase5.{tag}.{int(time.time())}@example.com"
    status, body = request(
        "POST", "/auth/signup",
        {"email": email, "password": PASSWORD, "display_name": f"Phase 5 {tag}"},
    )
    if status != 200:
        raise RuntimeError(f"signup failed: {status} {body}")
    return email, body["access_token"], body["user"]["id"]


def cleanup(*user_ids: str) -> None:
    from app.supabase_client import admin_auth_client

    for user_id in user_ids:
        if not user_id:
            continue
        try:
            admin_auth_client.auth.admin.delete_user(user_id)
            log(f"temporary user {user_id} deleted")
        except Exception as exc:
            log(f"cleanup failed for {user_id}: {type(exc).__name__}")


def main() -> None:
    user_a_id = user_b_id = None
    try:
        # --- Onboarding flag: new signups start incomplete -----------------
        _, token_a, user_a_id = signup("alice")
        status, me = request("GET", "/auth/me", token=token_a)
        check(
            "new signup starts with onboarding_completed=false",
            status == 200 and me.get("onboarding_completed") is False,
            f"me={me}",
        )

        # --- Profile summary: zero confirmed memories ----------------------
        status, profile = request("GET", "/profile/summary", token=token_a)
        stats = profile.get("stats", {})
        check(
            "empty profile summary is well-formed",
            status == 200
            and profile.get("summary") is None
            and stats.get("confirmed_insights") == 0
            and stats.get("films_watched") == 0
            and all(
                profile.get("groups", {}).get(k) == []
                for k in ("theme", "preference", "insight")
            ),
            f"status={status} profile={json.dumps(profile)[:200]}",
        )
        status, _ = request("GET", "/profile/summary")
        check(
            "profile summary requires auth",
            status in (401, 403, 422),
            f"status={status}",
        )
        status, _ = request("GET", "/profile/summary", token="not-a-real-token")
        check("profile summary rejects bogus token", status == 401, f"status={status}")

        # --- Onboarding completion -----------------------------------------
        status, done = request("POST", "/auth/onboarding-complete", token=token_a)
        check(
            "onboarding-complete flips the flag",
            status == 200 and done.get("onboarding_completed") is True,
            f"status={status} body={done}",
        )
        status, me = request("GET", "/auth/me", token=token_a)
        check("flag persists on /auth/me", me.get("onboarding_completed") is True)

        # --- Watched-wins via the live films API ---------------------------
        status, search = request("GET", "/films/search?q=Inception", token=token_a)
        inception = next(
            (r for r in search.get("results", []) if r.get("title") == "Inception"),
            None,
        )
        check("TMDB search finds Inception", inception is not None, f"status={status}")
        tmdb_id = inception["tmdb_id"]

        status, added = request(
            "POST", "/films/mine", {"tmdb_id": tmdb_id, "status": "watched"}, token_a
        )
        check(
            "manual add as watched",
            status in (200, 201) and added.get("status") == "watched",
        )
        status, again = request(
            "POST", "/films/mine", {"tmdb_id": tmdb_id, "status": "watchlist"}, token_a
        )
        check(
            "manual watchlist add never downgrades watched",
            again.get("status") == "watched",
            f"status={status} body={again}",
        )

        status, started = upload_csv(token_a, "watchlist.csv", "Name,Year\nInception,2010\n")
        check("watchlist import accepted", status in (200, 201, 202), f"status={status}")
        job = wait_import(token_a, started["import_id"])
        check(
            "watchlist import completed",
            job.get("status") in ("completed", "completed_with_errors"),
            f"job={job.get('status')} err={job.get('error')}",
        )
        status, mine = request("GET", "/films/mine?status=watched", token=token_a)
        row = next((f for f in mine.get("films", []) if f.get("tmdb_id") == tmdb_id), None)
        check(
            "import of watchlist.csv never downgrades watched",
            row is not None and row.get("status") == "watched",
            f"row={row}",
        )
        status, mine_all = request("GET", "/films/mine", token=token_a)
        counts = mine_all.get("counts", {})
        check(
            "library counts returned by API",
            counts.get("all") == 1
            and counts.get("watched") == 1
            and counts.get("watchlist") == 0,
            f"counts={counts}",
        )

        # --- Reflection -> review -> profile -------------------------------
        status, conv = request(
            "POST", "/conversations",
            {"type": "reflection", "title": "Phase 5 profile"}, token_a,
        )
        conv_id = conv["conversation"]["id"]
        for text in (
            "I keep coming back to quiet science fiction — films that trust silence.",
            "Arrival moved me because grief and wonder sat side by side.",
            "I think I prefer films that leave questions open at the end.",
        ):
            request("POST", f"/conversations/{conv_id}/messages", {"content": text}, token_a)
        status, ended = request("POST", f"/conversations/{conv_id}/end", token=token_a)
        proposals = ended.get("proposed_memories", [])
        check(
            "reflection produced proposed memories",
            status == 200 and len(proposals) >= 2,
            f"status={status} n={len(proposals)}",
        )

        status, profile = request("GET", "/profile/summary", token=token_a)
        check(
            "proposed memories never surface in the profile (D12)",
            profile.get("summary") is None
            and profile["stats"]["confirmed_insights"] == 0
            and profile["stats"]["proposed_awaiting_review"] == len(proposals),
            f"stats={profile.get('stats')}",
        )

        # Confirm one, edit-and-confirm another, confirm a third if present.
        m0, m1 = proposals[0], proposals[1]
        status, res = request(
            "PATCH", f"/memories/{m0['id']}", {"status": "confirmed"}, token_a
        )
        confirmed0 = res.get("memory", {})
        check(
            "confirm proposed memory",
            status == 200 and confirmed0.get("status") == "confirmed",
        )
        status, res = request(
            "PATCH", f"/memories/{m1['id']}",
            {"status": "confirmed", "content": "Edited: I love films that trust silence."},
            token_a,
        )
        confirmed1 = res.get("memory", {})
        check(
            "edit-and-confirm preserves source_message_ids",
            status == 200
            and confirmed1.get("content", "").startswith("Edited:")
            and confirmed1.get("source_message_ids") == m1.get("source_message_ids"),
            f"status={status}",
        )
        if len(proposals) > 2:
            request(
                "PATCH", f"/memories/{proposals[2]['id']}",
                {"status": "confirmed"}, token_a,
            )

        status, profile = request("GET", "/profile/summary", token=token_a)
        groups = profile.get("groups", {})
        flat = [m for k in ("theme", "preference", "insight") for m in groups.get(k, [])]
        check(
            "profile shows confirmed memories, grouped, with attribution",
            status == 200
            and isinstance(profile.get("summary"), str)
            and len(flat) == min(3, len(proposals))
            and all(
                (m.get("source_reflection") or {}).get("conversation_id") == conv_id
                for m in flat
            ),
            f"summary={str(profile.get('summary'))[:120]}",
        )

        # Edit a confirmed memory; reject a confirmed memory.
        status, res = request(
            "PATCH", f"/memories/{m0['id']}",
            {"status": "confirmed", "content": "Reworded confirmed insight."}, token_a,
        )
        edited = res.get("memory", {})
        check(
            "confirmed memory can be re-edited, sources preserved",
            status == 200
            and edited.get("content") == "Reworded confirmed insight."
            and edited.get("source_message_ids") == m0.get("source_message_ids"),
            f"status={status}",
        )
        status, res = request(
            "PATCH", f"/memories/{m1['id']}", {"status": "rejected"}, token_a
        )
        check("confirmed memory can be rejected (retracted)", status == 200)
        status, profile = request("GET", "/profile/summary", token=token_a)
        ids = {
            m["id"]
            for k in ("theme", "preference", "insight")
            for m in profile["groups"][k]
        }
        check(
            "rejected memory disappears from the profile",
            m1["id"] not in ids and m0["id"] in ids,
            f"ids={ids}",
        )

        # --- Ownership isolation -------------------------------------------
        _, token_b, user_b_id = signup("bob")
        status, _ = request(
            "PATCH", f"/memories/{m0['id']}", {"status": "rejected"}, token_b
        )
        check("other user cannot review my memory", status == 404, f"status={status}")
        status, profile_b = request("GET", "/profile/summary", token=token_b)
        check(
            "other user's profile is empty and isolated",
            status == 200
            and profile_b["stats"]["confirmed_insights"] == 0
            and profile_b["stats"]["films_watched"] == 0,
        )
        status, mine = request("GET", "/films/mine", token=token_b)
        check("other user sees none of my films", mine.get("counts", {}).get("all") == 0)

    finally:
        cleanup(user_a_id, user_b_id)

    log()
    log(f"RESULT: {sum(CHECKS)}/{len(CHECKS)} checks passed")
    if not all(CHECKS):
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    finally:
        LOG.write_text("\n".join(_lines), encoding="utf-8")

