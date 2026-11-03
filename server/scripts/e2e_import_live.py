"""Live HTTP verification for persistent Letterboxd imports.

Uses an existing catalogue film not already in the test library, plus one
intentionally unmatched title. The added fixture and job are removed afterwards.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.supabase_client import supabase  # noqa: E402

BASE = "http://localhost:8000"
EMAIL = "noacf.test2@example.com"
PASSWORD = "testpassword123"
OUTPUT = Path(__file__).with_name("e2e_import_live_output.txt")
lines = []


def log(message):
    print(message, flush=True)
    lines.append(str(message))


def request(method, path, body=None, token=None, multipart=None):
    headers = {}
    data = None
    if multipart is not None:
        boundary = f"----noacf{uuid4().hex}"
        data = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{multipart['filename']}\"\r\n"
            "Content-Type: text/csv\r\n\r\n"
            f"{multipart['content']}\r\n--{boundary}--\r\n"
        ).encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def main():
    status, session = request("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    assert status == 200, session
    token = session["access_token"]
    user_id = session["user"]["id"]

    library = supabase.table("user_films").select("film_id").eq("user_id", user_id).execute().data
    existing_ids = {row["film_id"] for row in library}
    films = supabase.table("films").select("id,title,year").limit(100).execute().data
    film = next(row for row in films if row["id"] not in existing_ids and row["year"])
    log(f"Fixture film: {film['title']} ({film['year']})")

    csv_text = (
        "Name,Year,Rating,Watched Date\n"
        f"{film['title']},{film['year']},4.5,2026-01-15\n"
        f"{film['title']},{film['year']},4.5,2026-01-15\n"
        "Noacf Unmatched Qzx 000,2099,,\n"
    )
    import_id = None
    try:
        started_at = time.monotonic()
        status, started = request(
            "POST", "/import/letterboxd", token=token,
            multipart={"filename": "watched.csv", "content": csv_text},
        )
        elapsed = time.monotonic() - started_at
        assert status == 202, started
        import_id = started["import_id"]
        assert started["total_rows"] == 3
        log(f"PASS POST returned {status} in {elapsed:.2f}s with import_id={import_id}")

        job = None
        for _ in range(90):
            status, job = request("GET", f"/import/{import_id}", token=token)
            assert status == 200, job
            if job["status"] not in ("queued", "processing"):
                break
            time.sleep(1)
        assert job and job["status"] == "completed", job
        assert job["processed_rows"] == 3, job
        assert job["added"] == 1, job
        assert job["duplicates"] == 1, job
        assert job["unmatched_count"] == 1, job
        assert job["failed"] == 0, job
        assert len(job["unmatched"]) == 1 and job["failures"] == []
        assert "rows" not in job and "results" not in job
        log(f"PASS background job completed with truthful counts: {job}")

        status, _ = request("GET", f"/import/{import_id}", token="bogus")
        assert status == 401
        status, _ = request("GET", "/import/00000000-0000-0000-0000-000000000000", token=token)
        assert status == 404
        status, _ = request("POST", f"/import/{import_id}/resume", token=token)
        assert status == 400
        log("PASS auth, ownership 404, and completed-resume validation")

        stored = (
            supabase.table("user_films").select("id")
            .eq("user_id", user_id).eq("film_id", film["id"]).execute().data
        )
        assert len(stored) == 1
        log("PASS exactly one user_films row persisted for duplicate CSV rows")
    finally:
        if import_id:
            supabase.table("import_jobs").delete().eq("id", import_id).execute()
        supabase.table("user_films").delete().eq("user_id", user_id).eq("film_id", film["id"]).execute()
        log("Cleanup complete: import job and added fixture removed")


if __name__ == "__main__":
    try:
        main()
    finally:
        OUTPUT.write_text("\n".join(lines), encoding="utf-8")
