"""Persistent, batched Letterboxd import jobs.

The HTTP request only parses the CSV and creates a job. A daemon thread then
processes rows in checkpointed batches. Per-row outcomes make retries safe:
successful rows are never intentionally rematched, failed rows can be resumed,
and user_films remains idempotent through unique(user_id, film_id).
"""

import re
import threading
from datetime import datetime, timezone

from fastapi import HTTPException

from . import tmdb
from .routers.films import _ensure_film
from .supabase_client import supabase

BATCH_SIZE = 20
STALE_PROCESSING_SECONDS = 120
PAGE_SIZE = 1000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def launch_import(job_id: str, retry_failed: bool = False) -> None:
    """Run a job outside the request/response cycle."""
    threading.Thread(
        target=run_import_job,
        args=(job_id, retry_failed),
        daemon=True,
        name=f"letterboxd-import-{job_id[:8]}",
    ).start()


def recover_import_jobs() -> None:
    """Recover work left by a server restart. Claiming is atomic per job."""
    try:
        res = (
            supabase.table("import_jobs")
            .select("id,status")
            .in_("status", ["queued", "processing"])
            .execute()
        )
        for job in res.data:
            if job["status"] == "processing":
                supabase.table("import_jobs").update(
                    {"status": "queued", "updated_at": _now()}
                ).eq("id", job["id"]).eq("status", "processing").execute()
            launch_import(job["id"], retry_failed=True)
    except Exception as exc:  # Keep unrelated API routes available if unmigrated.
        print(f"Import-job recovery skipped: {exc}")


def get_own_job(import_id: str, user_id: str) -> dict:
    res = (
        supabase.table("import_jobs")
        .select("*")
        .eq("id", import_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Import job not found")
    return res.data[0]


def serialise_job(job: dict) -> dict:
    """Public job shape; never exposes the stored normalized row payload."""
    rows = job.get("rows") or []
    results = job.get("results") or {}
    unmatched: list[dict] = []
    failures: list[dict] = []
    for key, outcome in results.items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            continue
        if index >= len(rows):
            continue
        row = rows[index]
        if outcome.get("state") == "unmatched":
            unmatched.append({"row": index + 1, "name": row["name"], "year": row.get("year")})
        elif outcome.get("state") == "failed":
            failures.append(
                {
                    "row": index + 1,
                    "name": row["name"],
                    "year": row.get("year"),
                    "error": outcome.get("error") or "Temporary import failure",
                }
            )
    unmatched.sort(key=lambda item: item["row"])
    failures.sort(key=lambda item: item["row"])
    return {
        "id": job["id"],
        "source_filename": job.get("source_filename"),
        "target_status": job["target_status"],
        "status": job["status"],
        "total_rows": job["total_rows"],
        "processed_rows": job["processed_rows"],
        "added": job["added_count"],
        "updated": job["updated_count"],
        "duplicates": job["duplicate_count"],
        "unmatched_count": job["unmatched_count"],
        "failed": job["failed_count"],
        "next_row": job["next_row"],
        "error": job.get("error"),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "completed_at": job.get("completed_at"),
        "unmatched": unmatched,
        "failures": failures,
    }


def _library_map(user_id: str) -> dict[str, dict]:
    """Prefetch the library in pages instead of SELECTing once per CSV row."""
    library: dict[str, dict] = {}
    offset = 0
    while True:
        page = (
            supabase.table("user_films")
            .select("film_id,status,source,rating,watched_on")
            .eq("user_id", user_id)
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
            .data
        )
        for row in page:
            library[row["film_id"]] = row
        if len(page) < PAGE_SIZE:
            return library
        offset += PAGE_SIZE


def _norm_title(text: str) -> str:
    """Lowercase, punctuation-stripped title without leading articles."""
    lowered = re.sub(r"[^\w\s]", " ", (text or "").lower())
    words = [w for w in lowered.split() if w not in ("the", "a", "an")]
    return " ".join(words or lowered.split())


def _close_title(query: str, candidate: object) -> bool:
    """True when a TMDB result title closely matches the CSV row's name.

    Guards the no-year path: without a release year, blindly trusting the
    most popular search result once imported 'The Making of …' for a TV
    show and a different same-title film for an unreleased one.
    """
    a, b = _norm_title(query), _norm_title(str(candidate or ""))
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def _match_film(row: dict, cache: dict) -> dict | None:
    name = row["name"]
    year = row.get("year")
    key = (name.lower(), year)
    if key in cache:
        return cache[key]

    # D15: catalogue first, then TMDB title+year. D32: when the CSV gives a
    # year, only results whose release year matches exactly are accepted —
    # the most popular same-title film (usually a remake) must never be
    # imported alongside the intended one. No year match => unmatched.
    query = supabase.table("films").select("*").ilike("title", name)
    if year:
        query = query.eq("year", year)
    found = query.limit(1).execute().data
    if found:
        film = found[0]
    elif year:
        results = [
            r
            for r in tmdb.search_movies(name, year)
            if tmdb._year_from_release(r.get("release_date")) == year
        ]
        if not results:
            results = [
                r
                for r in tmdb.search_movies(name)
                if tmdb._year_from_release(r.get("release_date")) == year
            ]
        film = _ensure_film(results[0]["id"]) if results else None
    else:
        # No year in the CSV: only an unambiguous close title match is
        # accepted; anything else is left unmatched rather than guessed.
        results = tmdb.search_movies(name)
        exact = [r for r in results if _close_title(name, r.get("title"))]
        film = _ensure_film(exact[0]["id"]) if len(exact) == 1 else None
    cache[key] = film
    return film


def _number(value) -> float | None:
    return float(value) if value is not None else None


def _same_library_row(existing: dict, desired: dict) -> bool:
    return (
        existing.get("status") == desired["status"]
        and existing.get("source") == desired["source"]
        and _number(existing.get("rating")) == _number(desired.get("rating"))
        and existing.get("watched_on") == desired.get("watched_on")
    )


def _attempt_row(
    job: dict,
    row: dict,
    library: dict[str, dict],
    cache: dict,
    seen: set[str],
) -> tuple[str, dict | None, str | None]:
    """Return (outcome, user_films upsert payload or None, film_id or None)."""
    film = _match_film(row, cache)
    if film is None:
        return "unmatched", None, None
    film_id = film["id"]
    if film_id in seen:
        return "duplicate", None, film_id

    existing = library.get(film_id)
    # Watched always wins (D28): a watchlist import must never downgrade an
    # existing 'watched' row. Watchlist rows carry no rating/date, so there is
    # nothing else to merge — the row is already current.
    if existing and existing.get("status") == "watched" and job["target_status"] == "watchlist":
        return "duplicate", None, film_id
    # Missing values in a later import must not erase an existing rating/date.
    rating = row.get("rating")
    if rating is None and existing:
        rating = existing.get("rating")
    watched_on = row.get("watched_on") if job["target_status"] == "watched" else None
    if watched_on is None and existing and job["target_status"] == "watched":
        watched_on = existing.get("watched_on")

    payload = {
        "user_id": job["user_id"],
        "film_id": film_id,
        "status": job["target_status"],
        "source": "letterboxd",
        "rating": rating,
        "watched_on": watched_on,
    }
    if existing and _same_library_row(existing, payload):
        return "duplicate", None, film_id
    return ("updated" if existing else "added"), payload, film_id


def run_import_job(job_id: str, retry_failed: bool = False) -> None:
    """Claim and run a job. Safe to call directly in tests or in a worker thread."""
    try:
        claimed = (
            supabase.table("import_jobs")
            .update(
                {
                    "status": "processing",
                    "error": None,
                    "completed_at": None,
                    "updated_at": _now(),
                }
            )
            .eq("id", job_id)
            .eq("status", "queued")
            .execute()
        )
        if not claimed.data:
            return  # Another worker already claimed it, or it does not exist.
        job = claimed.data[0]
        rows = job.get("rows") or []
        results = dict(job.get("results") or {})
        counts = {
            "added_count": job["added_count"],
            "updated_count": job["updated_count"],
            "duplicate_count": job["duplicate_count"],
            "unmatched_count": job["unmatched_count"],
            "failed_count": job["failed_count"],
        }
        processed = job["processed_rows"]
        next_row = job["next_row"]
        library = _library_map(job["user_id"])
        cache: dict = {}
        seen: set[str] = set()

        pending = []
        for index in range(len(rows)):
            outcome = results.get(str(index))
            if outcome is None or (retry_failed and outcome.get("state") == "failed"):
                pending.append(index)

        for start in range(0, len(pending), BATCH_SIZE):
            batch = pending[start : start + BATCH_SIZE]
            for index in batch:
                key = str(index)
                previous = results.get(key)
                if previous and previous.get("state") == "failed":
                    counts["failed_count"] = max(0, counts["failed_count"] - 1)
                    processed = max(0, processed - 1)

                payload = None
                film_id = None
                try:
                    state, payload, film_id = _attempt_row(
                        job, rows[index], library, cache, seen
                    )
                    if payload is not None:
                        supabase.table("user_films").upsert(
                            payload, on_conflict="user_id,film_id"
                        ).execute()
                    outcome = {"state": state}
                except Exception as exc:
                    # One film's TMDB/DB failure must not abort the remaining rows.
                    state = "failed"
                    outcome = {"state": state, "error": str(exc)[:500]}
                    payload = None

                if state in ("added", "updated") and payload is not None:
                    library[film_id] = payload
                if film_id is not None and state != "failed":
                    seen.add(film_id)
                results[key] = outcome
                counts[f"{state}_count"] += 1
                processed += 1

            next_row = max(next_row, batch[-1] + 1)
            supabase.table("import_jobs").update(
                {
                    "results": results,
                    "processed_rows": processed,
                    **counts,
                    "next_row": next_row,
                    "status": "processing",
                    "updated_at": _now(),
                }
            ).eq("id", job_id).execute()

        final_status = "completed_with_errors" if counts["failed_count"] else "completed"
        supabase.table("import_jobs").update(
            {
                "results": results,
                "processed_rows": processed,
                **counts,
                "next_row": next_row,
                "status": final_status,
                "error": None,
                "updated_at": _now(),
                "completed_at": _now(),
            }
        ).eq("id", job_id).execute()
    except Exception as exc:
        # Job-level failures retain the last checkpoint and can be resumed.
        try:
            supabase.table("import_jobs").update(
                {"status": "failed", "error": str(exc)[:1000], "updated_at": _now()}
            ).eq("id", job_id).execute()
        except Exception as update_exc:
            print(f"Could not mark import {job_id} failed: {update_exc}")


