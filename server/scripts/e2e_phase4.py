"""Phase 4 E2E: guided insight review (F3/D11/D12) against live Supabase.

Run from server/ with the Python that has the app deps:
    python scripts/e2e_phase4.py
Writes a full log to scripts/e2e_phase4_output.txt
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = "http://localhost:8000"
EMAIL = "noacf.test2@example.com"
PASSWORD = "testpassword123"
LOG = Path(__file__).with_name("e2e_phase4_output.txt")
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


def check(name: str, cond: bool, detail: str = "") -> None:
    CHECKS.append(bool(cond))
    log(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" 鈥?{detail}" if detail else ""))


def main() -> None:
    other_user_id = None
    try:
        status, body = request(
            "POST", "/auth/login", {"email": EMAIL, "password": PASSWORD}
        )
        token = body.get("access_token")
        check("owner login", status == 200 and bool(token), f"status={status}")

        status, _ = request("GET", "/memories", token="bogus-token")
        check("invalid token rejected", status == 401, f"status={status}")
        status, _ = request("GET", "/memories?status=unknown", token=token)
        check("invalid status filter rejected", status == 422, f"status={status}")

        # A second auth user proves the service-role server still scopes by owner.
        other_email = f"noacf.phase4.{int(time.time())}@example.com"
        from app.supabase_client import admin_auth_client, supabase

        created = admin_auth_client.auth.admin.create_user(
            {
                "email": other_email,
                "password": "testpassword123",
                "email_confirm": True,
                "user_metadata": {"display_name": "Phase 4 Other"},
            }
        )
        other_user_id = created.user.id if created and created.user else None
        if other_user_id:
            supabase.table("users").insert(
                {"id": other_user_id, "display_name": "Phase 4 Other"}
            ).execute()
            status, body = request(
                "POST",
                "/auth/login",
                {"email": other_email, "password": "testpassword123"},
            )
            other_token = body.get("access_token")
        else:
            status, other_token = 500, None
        check(
            "second user created for isolation",
            status == 200 and bool(other_token),
            f"status={status}",
        )

        status, body = request(
            "POST",
            "/conversations",
            {"type": "reflection", "title": "Phase 4 guided review"},
            token=token,
        )
        conv = body.get("conversation", {})
        conv_id = conv.get("id", "")
        check("create reflection", status == 201 and bool(conv_id), f"status={status}")

        user_texts = [
            "I loved the quiet atmosphere and the way it handled grief.",
            "The family scenes felt honest, and the hopeful ending stayed with me.",
            "That quiet honesty stayed with me, especially the hopeful family ending.",
        ]
        sent_ids: list[str] = []
        for text in user_texts:
            status, body = request(
                "POST", f"/conversations/{conv_id}/messages", {"content": text}, token
            )
            sent_ids.append((body.get("user_message") or {}).get("id", ""))
        check("three user messages stored", all(sent_ids), f"ids={len(sent_ids)}")

        status, before = request("GET", f"/conversations/{conv_id}", token=token)
        before_messages = before.get("messages", [])
        check("history loaded before ending", status == 200 and len(before_messages) == 7)


        status, body = request("POST", f"/conversations/{conv_id}/end", token=token)
        ended = body.get("conversation", {})
        proposals = body.get("proposed_memories", [])
        proposal_ids = [item.get("id") for item in proposals]
        check("end reflection", status == 200, f"status={status}")
        check(
            "completion state and ended_at",
            ended.get("status") == "completed" and bool(ended.get("ended_at")),
        )
        check("small set of proposals", 1 <= len(proposals) <= 3, str(len(proposals)))
        check(
            "all proposals begin proposed with valid kinds",
            bool(proposals)
            and all(
                item.get("status") == "proposed"
                and item.get("kind") in {"theme", "preference", "insight"}
                for item in proposals
            ),
        )
        message_ids = {message["id"] for message in before_messages}
        check(
            "proposal sources are valid and explanatory",
            all(
                item.get("explanation")
                and item.get("source_message_ids")
                and set(item["source_message_ids"]).issubset(message_ids)
                and item.get("source_messages")
                for item in proposals
            ),
        )

        status, repeat = request("POST", f"/conversations/{conv_id}/end", token=token)
        repeat_ids = [item.get("id") for item in repeat.get("proposed_memories", [])]
        check(
            "repeat ending is idempotent",
            status == 200 and sorted(repeat_ids) == sorted(proposal_ids),
            f"{len(repeat_ids)} memories",
        )
        status, linked = request(
            "GET", f"/conversations/{conv_id}/memories", token=token
        )
        check(
            "conversation memory lookup",
            status == 200
            and sorted(m["id"] for m in linked.get("memories", []))
            == sorted(proposal_ids),
        )
        status, listed = request("GET", "/memories?status=proposed", token=token)
        listed_ids = {item["id"] for item in listed.get("memories", [])}
        check(
            "proposed status lookup scoped to owner",
            status == 200 and set(proposal_ids).issubset(listed_ids),
        )

        status, _ = request(
            "GET", f"/conversations/{conv_id}/memories", token=other_token
        )
        check("cross-user conversation review rejected", status == 404, f"status={status}")
        status, _ = request(
            "PATCH",
            f"/memories/{proposal_ids[0]}",
            {"status": "confirmed"},
            token=other_token,
        )
        check("cross-user memory review rejected", status == 404, f"status={status}")
        status, other_list = request(
            "GET", "/memories?status=proposed", token=other_token
        )
        check(
            "other user's memory list excludes owner rows",
            status == 200
            and not set(proposal_ids)
            & {item["id"] for item in other_list.get("memories", [])},
        )

        check("mock produces one example per review action", len(proposals) == 3)
        if len(proposals) != 3:
            raise RuntimeError("The deterministic Phase 4 fixture did not produce 3 proposals")

        status, _ = request(
            "PATCH", f"/memories/{proposal_ids[0]}", {"status": "proposed"}, token
        )
        check("invalid proposed transition rejected", status == 422, f"status={status}")
        status, _ = request(
            "PATCH",
            f"/memories/{proposal_ids[1]}",
            {"status": "rejected", "content": "Cannot edit while rejecting"},
            token,
        )
        check("reject-with-edit rejected", status == 422, f"status={status}")
        status, _ = request(
            "PATCH",
            "/memories/00000000-0000-0000-0000-000000000000",
            {"status": "confirmed"},
            token,
        )
        check("unknown memory is 404", status == 404, f"status={status}")
        status, _ = request(
            "PATCH", "/memories/not-a-uuid", {"status": "confirmed"}, token
        )
        check("malformed memory id rejected", status == 422, f"status={status}")

        original_sources = [item["source_message_ids"] for item in proposals]
        status, body = request(
            "PATCH", f"/memories/{proposal_ids[0]}", {"status": "confirmed"}, token
        )
        confirmed = body.get("memory", {})
        check("confirm proposal", status == 200 and confirmed.get("status") == "confirmed")
        status, body = request(
            "PATCH",
            f"/memories/{proposal_ids[1]}",
            {
                "status": "confirmed",
                "content": "I prefer reflective films with honest family relationships.",
            },
            token,
        )
        edited = body.get("memory", {})
        check(
            "edit-and-confirm proposal",
            status == 200
            and edited.get("status") == "confirmed"
            and edited.get("content")
            == "I prefer reflective films with honest family relationships.",
        )
        check(
            "editing preserves source links",
            confirmed.get("source_message_ids") == original_sources[0]
            and edited.get("source_message_ids") == original_sources[1],
        )
        status, body = request(
            "PATCH", f"/memories/{proposal_ids[2]}", {"status": "rejected"}, token
        )
        rejected = body.get("memory", {})
        check("reject proposal", status == 200 and rejected.get("status") == "rejected")
        status, _ = request(
            "PATCH", f"/memories/{proposal_ids[0]}", {"status": "confirmed"}, token
        )
        check("repeat review transition rejected", status == 409, f"status={status}")

        status, confirmed_list = request("GET", "/memories?status=confirmed", token=token)
        confirmed_ids = {item["id"] for item in confirmed_list.get("memories", [])}
        check(
            "confirmed list contains both kept memories",
            status == 200 and {proposal_ids[0], proposal_ids[1]}.issubset(confirmed_ids),
        )
        status, rejected_list = request("GET", "/memories?status=rejected", token=token)
        rejected_ids = {item["id"] for item in rejected_list.get("memories", [])}
        check("rejected list contains removed memory", proposal_ids[2] in rejected_ids)
        status, proposed_list = request("GET", "/memories?status=proposed", token=token)
        remaining_ids = {item["id"] for item in proposed_list.get("memories", [])}
        check("reviewed memories leave proposed list", not set(proposal_ids) & remaining_ids)

        status, repeat = request("POST", f"/conversations/{conv_id}/end", token=token)
        repeated = repeat.get("proposed_memories", [])
        statuses = {item["id"]: item["status"] for item in repeated}
        check(
            "post-review repeat ending returns same rows without extraction",
            status == 200 and set(statuses) == set(proposal_ids),
        )
        check(
            "review statuses are stable after repeat ending",
            statuses
            == {
                proposal_ids[0]: "confirmed",
                proposal_ids[1]: "confirmed",
                proposal_ids[2]: "rejected",
            },
        )

        status, after = request("GET", f"/conversations/{conv_id}", token=token)
        check(
            "messages unchanged after ending and reviewing",
            status == 200 and after.get("messages") == before_messages,
        )
        status, _ = request(
            "POST", f"/conversations/{conv_id}/messages", {"content": "hello?"}, token
        )
        check("message to ended reflection rejected", status == 409, f"status={status}")
        status, _ = request(
            "POST",
            "/conversations/00000000-0000-0000-0000-000000000000/end",
            token=token,
        )
        check("missing conversation end is 404", status == 404, f"status={status}")
        status, _ = request("POST", "/conversations/not-a-uuid/end", token=token)
        check("malformed conversation id rejected", status == 422, f"status={status}")


        # Ending a reflection with no substantive user messages is safe and empty.
        status, body = request(
            "POST",
            "/conversations",
            {"type": "reflection", "title": "Phase 4 empty review"},
            token=token,
        )
        empty_id = (body.get("conversation") or {}).get("id", "")
        status, body = request("POST", f"/conversations/{empty_id}/end", token=token)
        check(
            "empty reflection ends without proposals",
            status == 200
            and (body.get("conversation") or {}).get("status") == "completed"
            and body.get("proposed_memories") == [],
        )

        # Malformed provider output is discarded by the persistence boundary.
        from app.memories import normalise_proposals

        source_message = before_messages[1]
        valid = {
            "content": "A valid source-grounded observation.",
            "kind": "insight",
            "explanation": "A concise explanation.",
            "source_message_ids": [source_message["id"]],
        }
        malformed = [
            None,
            "not an object",
            {"content": "Missing fields"},
            {**valid, "kind": "diagnosis"},
            {**valid, "source_message_ids": ["00000000-0000-0000-0000-000000000000"]},
            valid,
        ]
        normalised = normalise_proposals(malformed, [source_message])
        check(
            "malformed provider output cannot create invalid rows",
            len(normalised) == 1 and normalised[0]["content"] == valid["content"],
        )
        check("non-list provider output is discarded", normalise_proposals({}, []) == [])
    finally:
        if other_user_id:
            try:
                from app.supabase_client import admin_auth_client

                admin_auth_client.auth.admin.delete_user(other_user_id)
                log("temporary isolation user deleted")
            except Exception as exc:
                log(f"temporary isolation user cleanup failed: {type(exc).__name__}")

    log()
    log(f"RESULT: {sum(CHECKS)}/{len(CHECKS)} checks passed")
    if not all(CHECKS):
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    finally:
        LOG.write_text("\n".join(_lines), encoding="utf-8")

