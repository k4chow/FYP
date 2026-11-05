"""One-time cleanup for the remake-duplicate bug (fixed in code by D32).

Before D32, a Letterboxd import whose title+year TMDB search came back empty
fell back to the most popular same-title film, so re-importing the same CSV
could add BOTH versions of a remake pair (e.g. The Little Mermaid 2023 AND
1989) to a user's library. unique(user_id, film_id) cannot catch that because
the two versions are different films rows.

This script finds every (user, normalised title) group with more than one
library row and keeps a single row:

  1. Prefer rows whose film year matches a year stated for that title in the
     user's own import-job CSV rows (the stored `rows` payload).
  2. If no year information decides it, keep the earliest-added row.
  3. Rating / watched_on from a discarded row are merged into the kept row
     when the kept row lacks them, so no user data is lost.

Usage (from server/):
    python scripts/cleanup_duplicate_films.py           # dry run, prints plan
    python scripts/cleanup_duplicate_films.py --apply   # perform the deletes
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.supabase_client import supabase

APPLY = "--apply" in sys.argv


def norm(title: object) -> str:
    return " ".join(str(title or "").split()).casefold()


def main() -> None:
    rows = (
        supabase.table("user_films")
        .select(
            "id,user_id,film_id,status,source,rating,watched_on,added_at,"
            "films(title,year,tmdb_id)"
        )
        .execute()
        .data
    )

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        film = row.get("films") or {}
        groups[(row["user_id"], norm(film.get("title")))].append({**row, "_film": film})

    duplicates = {k: v for k, v in groups.items() if len(v) > 1}
    if not duplicates:
        print("No duplicate library rows found. Nothing to do.")
        return

    # Per-user CSV years per title, reconstructed from stored import jobs.
    years_cache: dict[str, dict[str, set[int]]] = {}

    def csv_years(user_id: str) -> dict[str, set[int]]:
        if user_id not in years_cache:
            jobs = (
                supabase.table("import_jobs")
                .select("rows")
                .eq("user_id", user_id)
                .execute()
                .data
            )
            by_title: dict[str, set[int]] = defaultdict(set)
            for job in jobs:
                for item in job.get("rows") or []:
                    year = item.get("year")
                    if isinstance(year, int):
                        by_title[norm(item.get("name"))].add(year)
            years_cache[user_id] = by_title
        return years_cache[user_id]

    kept_count = deleted_count = 0
    for (user_id, title), group in sorted(duplicates.items()):
        wanted_years = csv_years(user_id).get(title, set())
        year_matches = [r for r in group if r["_film"].get("year") in wanted_years]
        candidates = year_matches or sorted(group, key=lambda r: r["added_at"])
        # Among candidates prefer one carrying user data, then earliest added.
        keep = sorted(
            candidates,
            key=lambda r: (r.get("rating") is None, r["added_at"]),
        )[0]
        discard = [r for r in group if r["id"] != keep["id"]]

        print(
            f"user={user_id} title={keep['_film'].get('title')!r} "
            f"csv_years={sorted(wanted_years) or '?'}"
        )
        print(
            f"  KEEP   {keep['_film'].get('year')} tmdb={keep['_film'].get('tmdb_id')} "
            f"added={keep['added_at']} rating={keep.get('rating')}"
        )

        # Merge rating/watched_on from discarded rows if the kept row lacks them.
        updates: dict = {}
        if keep.get("rating") is None:
            merged = next((r["rating"] for r in discard if r.get("rating") is not None), None)
            if merged is not None:
                updates["rating"] = merged
        if keep.get("watched_on") is None:
            merged = next(
                (r["watched_on"] for r in discard if r.get("watched_on")), None
            )
            if merged is not None:
                updates["watched_on"] = merged
        if updates:
            print(f"  MERGE  into kept row: {updates}")
            if APPLY:
                supabase.table("user_films").update(updates).eq("id", keep["id"]).execute()

        for row in discard:
            print(
                f"  DELETE {row['_film'].get('year')} tmdb={row['_film'].get('tmdb_id')} "
                f"added={row['added_at']} rating={row.get('rating')}"
            )
            if APPLY:
                supabase.table("user_films").delete().eq("id", row["id"]).execute()
            deleted_count += 1
        kept_count += 1

    mode = "APPLIED" if APPLY else "DRY RUN (re-run with --apply to execute)"
    print(f"\n{mode}: {len(duplicates)} duplicate groups, {deleted_count} rows to delete.")


if __name__ == "__main__":
    main()
