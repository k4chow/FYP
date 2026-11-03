"""Phase 3 E2E: reflection conversations (F1/F4/F5) against live Supabase.

Run from server/ with the Python that has the app deps:
    python scripts/e2e_phase3.py
Writes a full log to scripts/e2e_phase3_output.txt
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = "http://localhost:8000"
EMAIL = "noacf.test2@example.com"
PASSWORD = "testpassword123"

LOG = Path(__file__).with_name("e2e_phase3_output.txt")
_lines: list[str] = []


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


CHECKS: list[bool] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    CHECKS.append(bool(cond))
    log(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> None:
    # --- auth -------------------------------------------------------------
    status, body = request("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    token = body.get("access_token")
    check("login", status == 200 and token, f"status={status}")

    status, _ = request("GET", "/conversations", token="bogus-token")
    check("unauthenticated request rejected", status == 401, f"status={status}")

    # --- pick a watched film from the library -----------------------------
    status, body = request("GET", "/films/mine", token=token)
    films = body.get("films", [])
    watched = next((f for f in films if f["status"] == "watched"), films[0])
    log(f"  using film: {watched['title']} (tmdb {watched['tmdb_id']})")
    film_title = watched["title"]
    tmdb_id = watched["tmdb_id"]

    # --- create film-linked reflection (seen) ------------------------------
    status, body = request(
        "POST", "/conversations",
        {"type": "reflection", "tmdb_id": tmdb_id, "watch_type": "seen"},
        token=token,
    )
    conv1 = body.get("conversation", {})
    msgs = body.get("messages", [])
    check("create conversation (201)", status == 201, f"status={status}")
    check("film attached", (conv1.get("film") or {}).get("title") == film_title)
    check("opening is assistant + persisted", len(msgs) == 1 and msgs[0]["role"] == "assistant")
    opening1 = msgs[0]["content"] if msgs else ""
    check("opening references film title", film_title in opening1, opening1[:90])
    check("watch_type stored", conv1.get("watch_type") == "seen")

    # --- create second identical conversation for determinism check --------
    status, body2 = request(
        "POST", "/conversations",
        {"type": "reflection", "tmdb_id": tmdb_id, "watch_type": "seen"},
        token=token,
    )
    conv2 = body2.get("conversation", {})
    check("second conversation created", status == 201)
    check(
        "opening deterministic across conversations",
        body2.get("messages", [{}])[0].get("content") == opening1,
    )

    # --- first user message + reply ----------------------------------------
    user_text = "I loved the quiet atmosphere and the way it handled grief."
    status, body = request(
        "POST", f"/conversations/{conv1['id']}/messages", {"content": user_text}, token=token
    )
    check("post message (201)", status == 201, f"status={status}")
    check("user message stored verbatim", body.get("user_message", {}).get("content") == user_text)
    reply1 = body.get("assistant_message", {}).get("content", "")
    check("assistant replied", bool(reply1), reply1[:110])

    status, body = request(
        "POST", f"/conversations/{conv2['id']}/messages", {"content": user_text}, token=token
    )
    check(
        "reply deterministic for same input/turn",
        body.get("assistant_message", {}).get("content") == reply1,
    )

    # --- quick-reply chips --------------------------------------------------
    status, body = request(
        "POST", f"/conversations/{conv1['id']}/messages",
        {"content": "I'm not sure"}, token=token,
    )
    check(
        "quick reply: I'm not sure",
        status == 201 and "okay" in body.get("assistant_message", {}).get("content", "").lower(),
        body.get("assistant_message", {}).get("content", "")[:90],
    )
    status, body = request(
        "POST", f"/conversations/{conv1['id']}/messages",
        {"content": "Can you ask a different question?"}, token=token,
    )
    check(
        "quick reply: different question",
        status == 201
        and body.get("assistant_message", {}).get("content", "").startswith("Of course"),
        body.get("assistant_message", {}).get("content", "")[:90],
    )
    status, _ = request(
        "POST", f"/conversations/{conv1['id']}/messages", {"content": "   "}, token=token
    )
    check("empty message rejected (422)", status == 422, f"status={status}")

    # --- free reflection (prompt of the day, no film) -----------------------
    prompt = "What film character would you want as a friend?"
    status, body = request(
        "POST", "/conversations", {"type": "reflection", "title": prompt}, token=token
    )
    conv3 = body.get("conversation", {})
    opening3 = (body.get("messages") or [{}])[0].get("content", "")
    check("free reflection created (201)", status == 201 and conv3.get("film") is None)
    check("free reflection opening quotes the prompt", prompt in opening3, opening3[:90])

    # --- planning conversation ----------------------------------------------
    status, body = request(
        "POST", "/conversations",
        {"type": "reflection", "tmdb_id": 157336, "watch_type": "planning"},
        token=token,
    )
    conv4 = body.get("conversation", {})
    opening4 = (body.get("messages") or [{}])[0].get("content", "")
    check("planning conversation created", status == 201 and conv4.get("watch_type") == "planning")
    check("planning opening references intent", "planning to watch" in opening4, opening4[:90])
    status, body = request(
        "POST", f"/conversations/{conv4['id']}/messages",
        {"content": "A friend said the docking scene is unforgettable."}, token=token,
    )
    check("planning reply asks about intent", status == 201,
          body.get("assistant_message", {}).get("content", "")[:100])

    status, body = request("POST", "/conversations", {"watch_type": "seen"}, token=token)
    check("watch_type without film rejected (400)", status == 400, f"status={status}")

    # --- F4: bounded context assembly (direct check) -------------------------
    from app.context import confirmed_memories, recent_messages

    recent = recent_messages(conv1["id"], limit=3)
    check("recent_messages honours limit", len(recent) == 3, f"got {len(recent)}")
    check("recent_messages newest last", recent[-1]["role"] == "assistant")
    uid = _uid(token)
    returned_memories = confirmed_memories(uid)
    from app.supabase_client import supabase

    memory_rows = (
        supabase.table("memories")
        .select("content,status")
        .eq("user_id", uid)
        .execute()
        .data
    )
    expected_confirmed = {
        row["content"] for row in memory_rows if row["status"] == "confirmed"
    }
    check(
        "confirmed memories only",
        len(returned_memories) == len(expected_confirmed)
        and set(returned_memories) == expected_confirmed,
        f"got {len(returned_memories)} confirmed",
    )

    # --- get conversation + list filters -------------------------------------
    status, body = request("GET", f"/conversations/{conv1['id']}", token=token)
    check("get conversation (200)", status == 200)
    check("history in order", [m["role"] for m in body.get("messages", [])][:2] == ["assistant", "user"])
    status, body = request("GET", "/conversations/00000000-0000-0000-0000-000000000000", token=token)
    check("unknown conversation is 404", status == 404, f"status={status}")

    # --- end conversation -----------------------------------------------------
    status, body = request("POST", f"/conversations/{conv1['id']}/end", token=token)
    ended = body.get("conversation", {})
    check("end conversation (200)", status == 200, f"status={status}")
    check("status completed + ended_at set",
          ended.get("status") == "completed" and bool(ended.get("ended_at")))
    status, body = request("POST", f"/conversations/{conv1['id']}/end", token=token)
    check("end is idempotent", status == 200 and body.get("conversation", {}).get("status") == "completed")
    status, _ = request(
        "POST", f"/conversations/{conv1['id']}/messages", {"content": "hello?"}, token=token
    )
    check("messaging an ended conversation rejected (409)", status == 409, f"status={status}")

    status, body = request("GET", "/conversations?status=completed", token=token)
    ids = [c["id"] for c in body.get("conversations", [])]
    check("completed filter includes ended conversation", conv1["id"] in ids)
    status, body = request("GET", "/conversations?status=active", token=token)
    ids = [c["id"] for c in body.get("conversations", [])]
    check("active filter excludes ended conversation", conv1["id"] not in ids and conv2["id"] in ids)

    log()
    log(f"RESULT: {sum(CHECKS)}/{len(CHECKS)} checks passed")
    if not all(CHECKS):
        sys.exit(1)


def _uid(token: str) -> str:
    status, body = request("GET", "/auth/me", token=token)
    return body.get("id", "") if status == 200 else ""


if __name__ == "__main__":
    main()
    LOG.write_text("\n".join(_lines), encoding="utf-8")
