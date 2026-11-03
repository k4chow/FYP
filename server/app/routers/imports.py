"""Letterboxd CSV import API (F6): persistent background jobs.

POST parses and normalizes the file, stores a job, and returns promptly.
Progress and truthful per-row outcomes are available through GET /import/{id};
failed or stale jobs can be resumed without repeating successful work.
"""

import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from ..deps import get_current_user
from ..import_jobs import (
    STALE_PROCESSING_SECONDS,
    get_own_job,
    launch_import,
    serialise_job,
)
from ..supabase_client import supabase

router = APIRouter()

MAX_FILE_BYTES = 5_000_000


def _parse_date(value: str | None) -> str | None:
    value = (value or "").strip()
    return value if len(value) == 10 and value[4] == "-" and value[7] == "-" else None


def _parse_rating(value: str | None) -> float | None:
    try:
        rating = float((value or "").strip())
    except ValueError:
        return None
    return rating if 0.5 <= rating <= 5 else None


def _normalise_rows(reader: csv.DictReader, target_status: str) -> list[dict]:
    """Keep only fields required for matching/resume, never the original CSV."""
    rows = []
    for row in reader:
        name = (row.get("Name") or "").strip()
        if not name:
            continue
        year_text = (row.get("Year") or "").strip()
        rows.append(
            {
                "name": name,
                "year": int(year_text) if year_text.isdigit() else None,
                "rating": _parse_rating(row.get("Rating")),
                "watched_on": (
                    _parse_date(row.get("Watched Date")) or _parse_date(row.get("Date"))
                    if target_status == "watched"
                    else None
                ),
            }
        )
    return rows


@router.post("/letterboxd", status_code=202)
async def import_letterboxd(
    file: UploadFile, current: dict = Depends(get_current_user)
) -> dict:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 5 MB)")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File is not valid UTF-8 CSV")

    reader = csv.DictReader(io.StringIO(text))
    columns = set(reader.fieldnames or [])
    if "Name" not in columns or "Year" not in columns:
        raise HTTPException(
            status_code=400,
            detail=(
                "Not a Letterboxd export CSV — expected 'Name' and 'Year' "
                "columns (use diary.csv, ratings.csv, watched.csv or "
                "watchlist.csv from your Letterboxd export)."
            ),
        )

    target_status = (
        "watchlist" if "watchlist" in (file.filename or "").lower() else "watched"
    )
    rows = _normalise_rows(reader, target_status)
    if not rows:
        raise HTTPException(status_code=400, detail="No film rows found in the file")

    job = (
        supabase.table("import_jobs")
        .insert(
            {
                "user_id": current["id"],
                "source_filename": file.filename,
                "target_status": target_status,
                "total_rows": len(rows),
                "rows": rows,
                "results": {},
            }
        )
        .execute()
        .data[0]
    )
    launch_import(job["id"])
    return {"import_id": job["id"], "status": job["status"], "total_rows": len(rows)}


@router.get("/{import_id}")
def get_import(import_id: str, current: dict = Depends(get_current_user)) -> dict:
    return serialise_job(get_own_job(import_id, current["id"]))


@router.post("/{import_id}/resume", status_code=202)
def resume_import(import_id: str, current: dict = Depends(get_current_user)) -> dict:
    job = get_own_job(import_id, current["id"])
    if job["status"] == "completed":
        raise HTTPException(status_code=400, detail="Import is already complete")
    if job["status"] == "processing":
        updated_at = datetime.fromisoformat(job["updated_at"])
        age = datetime.now(timezone.utc) - updated_at
        if age < timedelta(seconds=STALE_PROCESSING_SECONDS):
            raise HTTPException(status_code=409, detail="Import is already processing")

    updated = (
        supabase.table("import_jobs")
        .update(
            {
                "status": "queued",
                "error": None,
                "completed_at": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", import_id)
        .execute()
        .data[0]
    )
    launch_import(import_id, retry_failed=True)
    return serialise_job(updated)
