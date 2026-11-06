"""Automated large-import tests with in-memory Supabase and mocked TMDB.

Run from server/: python scripts/test_large_import.py
No real TMDB requests are made and no live database rows are changed.
"""

import asyncio
import copy
import io
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException, UploadFile

from app import import_jobs, tmdb
from app.routers import films as films_router
from app.routers import imports as imports_router


class Result:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class FakeQuery:
    def __init__(self, store, table):
        self.store = store
        self.table = table
        self.filters = []
        self._data = None
        self._update = None
        self._delete = False
        self._limit = None
        self._range = None
        self._count = None
        self._order = None

    def select(self, _fields="*", count=None):
        self._count = count
        return self

    def insert(self, row):
        row = dict(row)
        row.setdefault("id", str(uuid4()))
        if self.table == "import_jobs":
            defaults = {
                "status": "queued", "processed_rows": 0, "added_count": 0,
                "updated_count": 0, "duplicate_count": 0, "unmatched_count": 0,
                "failed_count": 0, "next_row": 0, "rows": [], "results": {},
                "error": None, "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(), "completed_at": None,
            }
            for key, value in defaults.items():
                row.setdefault(key, value)
        elif self.table == "user_films":
            row.setdefault("added_at", datetime.now(timezone.utc).isoformat())
        self.store.tables[self.table].append(row)
        self._data = [dict(row)]
        return self

    def update(self, values):
        self._update = values
        return self

    def delete(self):
        self._delete = True
        return self

    def upsert(self, row, on_conflict=None):
        row = dict(row)
        rows = self.store.tables[self.table]
        found = None
        if self.table == "user_films":
            found = next((r for r in rows if r["user_id"] == row["user_id"] and r["film_id"] == row["film_id"]), None)
        elif self.table == "films":
            found = next((r for r in rows if r.get("tmdb_id") == row.get("tmdb_id")), None)
        if found:
            found.update(row)
            self._data = [dict(found)]
        else:
            self.insert(row)
        return self

    def eq(self, field, value):
        self.filters.append(lambda row: row.get(field) == value)
        return self

    def neq(self, field, value):
        self.filters.append(lambda row: row.get(field) != value)
        return self

    def in_(self, field, values):
        self.filters.append(lambda row: row.get(field) in values)
        return self

    def ilike(self, field, value):
        self.filters.append(lambda row: str(row.get(field, "")).lower() == value.lower())
        return self

    def order(self, field, desc=False):
        self._order = (field, desc)
        return self

    def limit(self, value):
        self._limit = value
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        if self._data is not None:
            return Result(self._data)
        rows = self.store.tables[self.table]
        matched = [row for row in rows if all(f(row) for f in self.filters)]
        if self._delete:
            self.store.tables[self.table] = [row for row in rows if row not in matched]
            return Result([dict(row) for row in matched])
        if self._update is not None:
            if self.table == "import_jobs" and "results" in self._update and self._update.get("status") == "processing":
                self.store.checkpoint_calls += 1
                if self.store.checkpoint_calls == self.store.fail_checkpoint_at:
                    raise RuntimeError("simulated checkpoint failure")
            for row in matched:
                row.update(copy.deepcopy(self._update))
            return Result([dict(row) for row in matched])
        if self._order:
            field, desc = self._order
            matched.sort(key=lambda row: row.get(field) or "", reverse=desc)
        count = len(matched) if self._count == "exact" else None
        if self._range:
            matched = matched[self._range[0] : self._range[1] + 1]
        if self._limit is not None:
            matched = matched[: self._limit]
        return Result([dict(row) for row in matched], count)


class FakeStore:
    def __init__(self):
        self.tables = {"import_jobs": [], "films": [], "user_films": []}
        self.fail_checkpoints = 0
        self.checkpoint_calls = 0
        self.fail_checkpoint_at = -1

    def table(self, name):
        return FakeQuery(self, name)


class LargeImportTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.fail_names = set()
        self.unmatched_names = set()
        self.titles = {}
        self.name_ids = {}
        for patcher in (
            mock.patch.object(import_jobs, "supabase", self.store),
            mock.patch.object(import_jobs, "_ensure_film", side_effect=self.ensure_film),
            mock.patch.object(import_jobs.tmdb, "search_movies", side_effect=self.search),
            mock.patch.object(imports_router, "supabase", self.store),
            mock.patch.object(imports_router, "launch_import", side_effect=self.launch),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def search(self, name, year=None):
        if name in self.fail_names:
            raise HTTPException(status_code=502, detail="simulated TMDB outage")
        if name in self.unmatched_names:
            return []
        if name not in self.name_ids:
            self.name_ids[name] = 1_000_000 + len(self.name_ids)
        tmdb_id = self.name_ids[name]
        self.titles[tmdb_id] = (name, year)
        return [
            {"id": tmdb_id, "release_date": f"{year or 2000}-01-01", "title": name}
        ]

    def ensure_film(self, tmdb_id):
        existing = next((f for f in self.store.tables["films"] if f["tmdb_id"] == tmdb_id), None)
        if existing:
            return existing
        title, year = self.titles[tmdb_id]
        film = {
            "id": f"film-{tmdb_id}", "tmdb_id": tmdb_id, "title": title,
            "year": year, "genres": [], "poster_path": None, "metadata": {},
        }
        self.store.tables["films"].append(film)
        return film

    def launch(self, job_id, retry_failed=False):
        import_jobs.run_import_job(job_id, retry_failed=retry_failed)

    @staticmethod
    def rows(count, prefix="Realistic Film"):
        return [
            {
                "name": f"{prefix} {index:04d}",
                "year": 1970 + (index % 50),
                "rating": 3.5,
                "watched_on": "2026-01-15",
            }
            for index in range(count)
        ]

    def new_job(self, rows, user_id="user-a"):
        return self.store.table("import_jobs").insert(
            {
                "user_id": user_id,
                "source_filename": "watched.csv",
                "target_status": "watched",
                "total_rows": len(rows),
                "rows": rows,
                "results": {},
            }
        ).execute().data[0]

    def job(self, job_id):
        return next(j for j in self.store.tables["import_jobs"] if j["id"] == job_id)

    def test_1600_rows_and_repeat_import(self):
        rows = self.rows(1600)
        first = self.new_job(rows)
        import_jobs.run_import_job(first["id"])
        job = self.job(first["id"])
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["total_rows"], 1600)
        self.assertEqual(job["processed_rows"], 1600)
        self.assertEqual(job["added_count"], 1600)
        self.assertEqual(job["failed_count"], 0)
        self.assertEqual(job["next_row"], 1600)
        self.assertEqual(len(job["results"]), 1600)
        self.assertEqual(len(self.store.tables["user_films"]), 1600)

        # Repeating the identical import must not create or update library rows.
        second = self.new_job(rows)
        import_jobs.run_import_job(second["id"])
        repeated = self.job(second["id"])
        self.assertEqual(repeated["status"], "completed")
        self.assertEqual(repeated["duplicate_count"], 1600)
        self.assertEqual(repeated["added_count"], 0)
        self.assertEqual(repeated["updated_count"], 0)
        self.assertEqual(len(self.store.tables["user_films"]), 1600)

    def test_transient_failure_continues_and_resume_retries(self):
        rows = self.rows(60)
        self.fail_names.add(rows[30]["name"])
        created = self.new_job(rows)
        import_jobs.run_import_job(created["id"])
        failed = self.job(created["id"])
        self.assertEqual(failed["status"], "completed_with_errors")
        self.assertEqual(failed["processed_rows"], 60)
        self.assertEqual(failed["added_count"], 59)
        self.assertEqual(failed["failed_count"], 1)
        self.assertIn("59", failed["results"])  # Work continued after the failure.
        self.assertEqual(len(self.store.tables["user_films"]), 59)

        self.fail_names.clear()
        imports_router.resume_import(created["id"], current={"id": "user-a"})
        resumed = self.job(created["id"])
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(resumed["processed_rows"], 60)
        self.assertEqual(resumed["added_count"], 60)
        self.assertEqual(resumed["failed_count"], 0)
        self.assertEqual(len(self.store.tables["user_films"]), 60)

    def test_mid_import_checkpoint_failure_and_resume(self):
        rows = self.rows(60)
        self.store.fail_checkpoint_at = 2  # First 20 rows are durably checkpointed.
        created = self.new_job(rows)
        import_jobs.run_import_job(created["id"])
        failed = self.job(created["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["processed_rows"], 20)
        self.assertEqual(failed["next_row"], 20)
        # The second batch's upserts happened before its checkpoint failed.
        self.assertEqual(len(self.store.tables["user_films"]), 40)

        imports_router.resume_import(created["id"], current={"id": "user-a"})
        resumed = self.job(created["id"])
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(resumed["processed_rows"], 60)
        self.assertEqual(resumed["added_count"], 40)
        self.assertEqual(resumed["duplicate_count"], 20)
        self.assertEqual(len(self.store.tables["user_films"]), 60)


    def test_duplicates_unmatched_and_existing_update(self):
        film = self.rows(1)[0]
        unmatched = {"name": "Definitely Not A Real Film", "year": 2099, "rating": None, "watched_on": None}
        self.unmatched_names.add(unmatched["name"])
        created = self.new_job([film, dict(film), unmatched])
        import_jobs.run_import_job(created["id"])
        job = self.job(created["id"])
        self.assertEqual(job["added_count"], 1)
        self.assertEqual(job["duplicate_count"], 1)
        self.assertEqual(job["unmatched_count"], 1)
        self.assertEqual(job["failed_count"], 0)
        public = import_jobs.serialise_job(job)
        self.assertEqual(public["unmatched"][0]["name"], unmatched["name"])
        self.assertNotIn("rows", public)
        self.assertNotIn("results", public)

        changed = dict(film, rating=5.0, watched_on=None)
        second = self.new_job([changed])
        import_jobs.run_import_job(second["id"])
        self.assertEqual(self.job(second["id"])["updated_count"], 1)
        stored = self.store.tables["user_films"][0]
        self.assertEqual(stored["rating"], 5.0)
        self.assertEqual(stored["watched_on"], film["watched_on"])  # Not erased.

    def test_malformed_rows_and_user_isolation(self):
        csv_text = (
            "Name,Year,Rating,Watched Date\n"
            ",2020,4,2020-01-01\n"
            "Valid Film,not-a-year,99,not-a-date\n"
        )
        upload = UploadFile(file=io.BytesIO(csv_text.encode()), filename="watched.csv")
        started = asyncio.run(imports_router.import_letterboxd(upload, current={"id": "user-a"}))
        self.assertEqual(started["total_rows"], 1)
        job = self.job(started["import_id"])
        self.assertEqual(job["rows"], [{"name": "Valid Film", "year": None, "rating": None, "watched_on": None}])
        with self.assertRaises(HTTPException) as denied:
            import_jobs.get_own_job(job["id"], "user-b")
        self.assertEqual(denied.exception.status_code, 404)

        bad_upload = UploadFile(file=io.BytesIO(b"Title,Date\nArrival,2020-01-01\n"), filename="watched.csv")
        with self.assertRaises(HTTPException) as malformed:
            asyncio.run(imports_router.import_letterboxd(bad_upload, current={"id": "user-a"}))
        self.assertEqual(malformed.exception.status_code, 400)

    def test_library_api_paginates_1600_rows(self):
        for index in range(1600):
            film_id = f"film-{index}"
            self.store.tables["user_films"].append(
                {
                    "id": str(index), "user_id": "user-a", "film_id": film_id,
                    "status": "watched", "source": "letterboxd", "rating": None,
                    "watched_on": None, "added_at": f"{index:04d}",
                    "films": {
                        "id": film_id, "tmdb_id": index, "title": f"Film {index}",
                        "year": 2000, "genres": [], "poster_path": None, "metadata": {},
                    },
                }
            )
        with mock.patch.object(films_router, "supabase", self.store):
            first = films_router.my_films(status=None, limit=500, offset=0, current={"id": "user-a"})
            second = films_router.my_films(status=None, limit=500, offset=500, current={"id": "user-a"})
            third = films_router.my_films(status=None, limit=500, offset=1000, current={"id": "user-a"})
            fourth = films_router.my_films(status=None, limit=500, offset=1500, current={"id": "user-a"})
        self.assertEqual(
            (len(first["films"]), len(second["films"]), len(third["films"]), len(fourth["films"])),
            (500, 500, 500, 100),
        )
        self.assertEqual((first["total"], second["total"], third["total"]), (1600, 1600, 1600))


class TmdbBackoffTests(unittest.TestCase):
    class Response:
        def __init__(self, status):
            self.status_code = status

        def json(self):
            return {"results": [{"id": 1}]}

    def test_429_backoff_is_bounded_with_jitter(self):
        with (
            mock.patch.object(tmdb.settings, "tmdb_api_key", "test-key"),
            mock.patch.object(tmdb.random, "uniform", return_value=0.25),
            mock.patch.object(tmdb.time, "sleep") as sleep,
            mock.patch.object(tmdb.httpx, "get") as get,
        ):
            get.side_effect = [self.Response(429), self.Response(429), self.Response(200)]
            self.assertEqual(tmdb._get("/search/movie", {}), {"results": [{"id": 1}]})
            self.assertEqual(get.call_count, 3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [1.25, 2.25])

            get.reset_mock()
            sleep.reset_mock()
            get.side_effect = [self.Response(429)] * tmdb.MAX_ATTEMPTS
            with self.assertRaises(HTTPException) as limited:
                tmdb._get("/search/movie", {})
            self.assertEqual(limited.exception.status_code, 502)
            self.assertEqual(get.call_count, tmdb.MAX_ATTEMPTS)
            self.assertEqual(sleep.call_count, tmdb.MAX_ATTEMPTS - 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)


