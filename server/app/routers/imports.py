"""Letterboxd CSV import (F6).

Accepts any export file with `Name` and `Year` columns (diary.csv,
ratings.csv, watched.csv, watchlist.csv). Rows are matched to TMDB by
title + year (first result), cached in `films`, and upserted into
`user_films` with source='letterboxd'. Re-importing updates ratings and
never creates duplicates.
"""

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from .. import tmdb
from ..deps import get_current_user
from ..supabase_client import supabase
from .films import _ensure_film

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


@router.post("/letterboxd")
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

    status = (
        "watchlist" if "watchlist" in (file.filename or "").lower() else "watched"
    )
    rows = [r for r in reader if (r.get("Name") or "").strip()]
    if not rows:
        raise HTTPException(status_code=400, detail="No film rows found in the file")

    matched = 0
    unmatched: list[dict] = []
    cache: dict[tuple[str, int | None], dict | None] = {}

    for row in rows:
        name = row["Name"].strip()
        year_text = (row.get("Year") or "").strip()
        year = int(year_text) if year_text.isdigit() else None
        key = (name.lower(), year)

        if key not in cache:
            film = None
            # 1. Our own catalogue first — avoids a TMDB call when possible.
            query = supabase.table("films").select("*").ilike("title", name)
            if year:
                query = query.eq("year", year)
            found = query.limit(1).execute().data
            if found:
                film = found[0]
            else:
                # 2. TMDB search: title + year, then title only as fallback.
                results = tmdb.search_movies(name, year) or tmdb.search_movies(name)
                if results:
                    film = _ensure_film(results[0]["id"])
            cache[key] = film

        film = cache[key]
        if film is None:
            unmatched.append({"name": name, "year": year})
            continue

        watched_on = (
            (_parse_date(row.get("Watched Date")) or _parse_date(row.get("Date")))
            if status == "watched"
            else None
        )
        supabase.table("user_films").upsert(
            {
                "user_id": current["id"],
                "film_id": film["id"],
                "status": status,
                "source": "letterboxd",
                "rating": _parse_rating(row.get("Rating")),
                "watched_on": watched_on,
            },
            on_conflict="user_id,film_id",
        ).execute()
        matched += 1

    return {"total_rows": len(rows), "matched": matched, "unmatched": unmatched}
