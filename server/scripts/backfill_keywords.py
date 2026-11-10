"""One-off backfill: cache TMDB keywords for existing films (D36).

Run from server/::

    python scripts/backfill_keywords.py            # every film
    python scripts/backfill_keywords.py --limit 50 # safety cap for a dry run

Films cached before the emotional-theme feature lack ``metadata.keywords``, so
the profile's theme counts would miss them. This walks the shared ``films``
table and tops up any row whose metadata has no ``keywords``.

Safe to re-run: rows that already carry keywords are skipped.
"""

import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))

from app import tmdb  # noqa: E402
from app.supabase_client import supabase  # noqa: E402

_PAGE = 500


def main() -> None:
    limit = None
    if len(sys.argv) >= 3 and sys.argv[1] == "--limit":
        limit = int(sys.argv[2])

    scanned = 0
    missing = 0
    backfilled = 0
    offset = 0

    while True:
        rows = (
            supabase.table("films")
            .select("id,tmdb_id,metadata")
            .range(offset, offset + _PAGE - 1)
            .execute()
            .data
            or []
        )
        if not rows:
            break

        for row in rows:
            scanned += 1
            metadata = row.get("metadata") or {}
            if metadata.get("keywords") or not row.get("tmdb_id"):
                continue
            missing += 1
            keywords = tmdb.movie_keywords(row["tmdb_id"])
            if not keywords:
                continue
            metadata = dict(metadata)
            metadata["keywords"] = keywords
            supabase.table("films").update(
                {"metadata": metadata}
            ).eq("id", row["id"]).execute()
            backfilled += 1
            print(f"backfilled tmdb {row['tmdb_id']}: {len(keywords)} keywords")

        if len(rows) < _PAGE or (limit is not None and scanned >= limit):
            break
        offset += _PAGE

    print(f"done: scanned={scanned} missing={missing} backfilled={backfilled}")


if __name__ == "__main__":
    main()