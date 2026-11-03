"""Verify live /films/mine pagination with 1,600 temporary fixtures.

Fixtures are inserted directly (not through the importer) and deleted by their
dedicated TMDB id range in finally. Existing user library rows are untouched.
"""

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.supabase_client import supabase  # noqa: E402

BASE = "http://localhost:8000"
FIRST_TMDB_ID = 9_000_000
FIXTURES = 1600
OUTPUT = Path(__file__).with_name("e2e_library_pagination_output.txt")
lines = []


def log(message):
    print(message, flush=True)
    lines.append(str(message))


def call(path, method="GET", body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode())


def chunks(items, size=250):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def cleanup(user_id):
    fixtures = (
        supabase.table("films").select("id")
        .gte("tmdb_id", FIRST_TMDB_ID).lt("tmdb_id", FIRST_TMDB_ID + FIXTURES)
        .execute().data
    )
    ids = [row["id"] for row in fixtures]
    for batch in chunks(ids):
        supabase.table("user_films").delete().eq("user_id", user_id).in_("film_id", batch).execute()
    supabase.table("films").delete().gte("tmdb_id", FIRST_TMDB_ID).lt(
        "tmdb_id", FIRST_TMDB_ID + FIXTURES
    ).execute()


def main():
    session = call(
        "/auth/login", "POST",
        {"email": "noacf.test2@example.com", "password": "testpassword123"},
    )
    token = session["access_token"]
    user_id = session["user"]["id"]
    baseline = call("/films/mine?limit=1&offset=0", token=token)["total"]
    log(f"Baseline library total: {baseline}")
    cleanup(user_id)  # Defensive cleanup of an interrupted prior fixture run.
    try:
        films = [
            {
                "tmdb_id": FIRST_TMDB_ID + index,
                "title": f"NOACF Pagination Fixture {index:04d}",
                "year": 2000 + (index % 20),
                "genres": [],
                "poster_path": None,
                "metadata": {},
            }
            for index in range(FIXTURES)
        ]
        film_ids = []
        for batch in chunks(films):
            inserted = supabase.table("films").upsert(batch, on_conflict="tmdb_id").execute().data
            film_ids.extend(row["id"] for row in inserted)
        user_rows = [
            {
                "user_id": user_id, "film_id": film_id, "status": "watched",
                "source": "manual", "rating": None, "watched_on": None,
            }
            for film_id in film_ids
        ]
        for batch in chunks(user_rows):
            supabase.table("user_films").upsert(batch, on_conflict="user_id,film_id").execute()
        log(f"Inserted {len(user_rows)} temporary library fixtures")

        returned = []
        page_sizes = []
        total = None
        for offset in range(0, baseline + FIXTURES + 500, 500):
            page = call(f"/films/mine?limit=500&offset={offset}", token=token)
            total = page["total"]
            page_sizes.append(len(page["films"]))
            returned.extend(page["films"])
            if len(page["films"]) < 500:
                break
        fixture_count = sum(f["title"].startswith("NOACF Pagination Fixture ") for f in returned)
        assert total == baseline + FIXTURES, (total, baseline)
        assert len(returned) == baseline + FIXTURES, len(returned)
        assert fixture_count == FIXTURES, fixture_count
        assert page_sizes == [500, 500, 500, 108], page_sizes
        log(f"PASS total={total}, pages={page_sizes}, fixture rows returned={fixture_count}")
    finally:
        cleanup(user_id)
        after = call("/films/mine?limit=1&offset=0", token=token)["total"]
        assert after == baseline, (after, baseline)
        log(f"Cleanup complete: baseline restored to {after}")


if __name__ == "__main__":
    try:
        main()
    finally:
        OUTPUT.write_text("\n".join(lines), encoding="utf-8")
