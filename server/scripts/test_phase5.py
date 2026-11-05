"""Phase 5 regression tests: watched-wins status rule (Bug D) and the
randomised reflection prompt bank (D27).

Run from server/: python scripts/test_phase5.py
In-memory Supabase + mocked TMDB; no live requests, no live DB writes.
"""

import random
import sys
import unittest
from pathlib import Path
from unittest import mock

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))
sys.path.insert(0, str(SERVER_ROOT / "scripts"))

from test_large_import import FakeStore  # noqa: E402  (shared in-memory store)

from app import import_jobs  # noqa: E402
from app.llm.base import ChatContext  # noqa: E402
from app.llm.mock import (  # noqa: E402
    _QUESTIONS_FILM,
    _QUESTIONS_FREE,
    _QUESTIONS_PLANNING,
    MockLLMProvider,
)
from app.routers import films as films_router  # noqa: E402


class WatchedWinsImportTests(unittest.TestCase):
    """Bug D: an import must never downgrade an existing 'watched' row."""

    def setUp(self):
        self.store = FakeStore()
        for patcher in (
            mock.patch.object(import_jobs, "supabase", self.store),
            mock.patch.object(import_jobs, "_ensure_film", side_effect=self.ensure_film),
            mock.patch.object(import_jobs.tmdb, "search_movies", side_effect=self.search),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def search(self, name, year=None):
        return [{"id": 4242}]

    def ensure_film(self, tmdb_id):
        film = next(
            (f for f in self.store.tables["films"] if f["tmdb_id"] == tmdb_id), None
        )
        if film is None:
            film = {
                "id": f"film-{tmdb_id}", "tmdb_id": tmdb_id, "title": "Shared Film",
                "year": 2000, "genres": [], "poster_path": None, "metadata": {},
            }
            self.store.tables["films"].append(film)
        return film

    def new_job(self, rows, target_status):
        return self.store.table("import_jobs").insert(
            {
                "user_id": "user-a",
                "source_filename": f"{target_status}.csv",
                "target_status": target_status,
                "total_rows": len(rows),
                "rows": rows,
                "results": {},
            }
        ).execute().data[0]

    def library_row(self):
        rows = self.store.tables["user_films"]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_watched_then_watchlist_stays_watched(self):
        watched_row = {
            "name": "Shared Film", "year": 2000,
            "rating": 4.5, "watched_on": "2024-01-01",
        }
        import_jobs.run_import_job(self.new_job([watched_row], "watched")["id"])
        self.assertEqual(self.library_row()["status"], "watched")

        watchlist_row = {
            "name": "Shared Film", "year": 2000, "rating": None, "watched_on": None,
        }
        job = self.new_job([watchlist_row], "watchlist")
        import_jobs.run_import_job(job["id"])
        job = next(j for j in self.store.tables["import_jobs"] if j["id"] == job["id"])
        row = self.library_row()
        self.assertEqual(row["status"], "watched")  # never downgraded
        self.assertEqual(row["rating"], 4.5)  # rating not erased
        self.assertEqual(row["watched_on"], "2024-01-01")
        self.assertEqual(job["duplicate_count"], 1)  # counted as no-op
        self.assertEqual(job["updated_count"], 0)

    def test_watchlist_then_watched_upgrades(self):
        watchlist_row = {
            "name": "Shared Film", "year": 2000, "rating": None, "watched_on": None,
        }
        import_jobs.run_import_job(self.new_job([watchlist_row], "watchlist")["id"])
        self.assertEqual(self.library_row()["status"], "watchlist")

        watched_row = {
            "name": "Shared Film", "year": 2000,
            "rating": 4.5, "watched_on": "2024-01-01",
        }
        import_jobs.run_import_job(self.new_job([watched_row], "watched")["id"])
        row = self.library_row()
        self.assertEqual(row["status"], "watched")  # upgrade is allowed
        self.assertEqual(row["rating"], 4.5)

    def test_manual_watchlist_add_never_downgrades_watched(self):
        def ensure(tmdb_id):
            return {
                "id": f"film-{tmdb_id}", "tmdb_id": tmdb_id, "title": "Shared Film",
                "year": 2000, "genres": [], "poster_path": None, "metadata": {},
            }

        with (
            mock.patch.object(films_router, "supabase", self.store),
            mock.patch.object(films_router, "_ensure_film", side_effect=ensure),
        ):
            films_router.add_film(
                films_router.AddFilmBody(tmdb_id=4242, status="watched"),
                current={"id": "user-a"},
            )
            again = films_router.add_film(
                films_router.AddFilmBody(tmdb_id=4242, status="watchlist"),
                current={"id": "user-a"},
            )
        self.assertEqual(again["status"], "watched")
        self.assertEqual(self.library_row()["status"], "watched")



class YearStrictMatchingTests(unittest.TestCase):
    """D32: a Letterboxd row with a year must never match a same-title film
    from a different year (the remake-duplicate bug)."""

    def setUp(self):
        self.store = FakeStore()
        self.searches = []
        for patcher in (
            mock.patch.object(import_jobs, "supabase", self.store),
            mock.patch.object(import_jobs, "_ensure_film", side_effect=self.ensure_film),
            mock.patch.object(import_jobs.tmdb, "search_movies", side_effect=self.search),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    # TMDB title+year finds nothing; title-only returns remake-first results.
    def search(self, name, year=None):
        self.searches.append((name, year))
        if year is not None:
            return []
        return [
            {"id": 447277, "release_date": "2023-05-18"},  # popular remake
            {"id": 10144, "release_date": "1989-11-17"},  # intended version
        ]

    def ensure_film(self, tmdb_id):
        film = next(
            (f for f in self.store.tables["films"] if f["tmdb_id"] == tmdb_id), None
        )
        if film is None:
            film = {
                "id": f"film-{tmdb_id}", "tmdb_id": tmdb_id, "title": "The Little Mermaid",
                "year": {447277: 2023, 10144: 1989}.get(tmdb_id),
                "genres": [], "poster_path": None, "metadata": {},
            }
            self.store.tables["films"].append(film)
        return film

    def run_job(self, row):
        job = self.store.table("import_jobs").insert(
            {
                "user_id": "user-a", "source_filename": "watched.csv",
                "target_status": "watched", "total_rows": 1,
                "rows": [row], "results": {},
            }
        ).execute().data[0]
        import_jobs.run_import_job(job["id"])
        return next(j for j in self.store.tables["import_jobs"] if j["id"] == job["id"])

    def test_year_fallback_picks_matching_release_year(self):
        job = self.run_job(
            {"name": "The Little Mermaid", "year": 1989, "rating": None, "watched_on": None}
        )
        rows = self.store.tables["user_films"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["film_id"], "film-10144")  # 1989, not the remake
        self.assertEqual(job["added_count"], 1)

    def test_year_fallback_remarks_unmatched_when_no_year_match(self):
        def only_remake(name, year=None):
            if year is not None:
                return []
            return [{"id": 447277, "release_date": "2023-05-18"}]

        with mock.patch.object(
            import_jobs.tmdb, "search_movies", side_effect=only_remake
        ):
            job = self.run_job(
                {"name": "The Little Mermaid", "year": 1989, "rating": None, "watched_on": None}
            )
        self.assertEqual(self.store.tables["user_films"], [])  # never guessed
        self.assertEqual(job["unmatched_count"], 1)

    def test_row_without_year_still_uses_first_result(self):
        job = self.run_job(
            {"name": "The Little Mermaid", "year": None, "rating": None, "watched_on": None}
        )
        rows = self.store.tables["user_films"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["film_id"], "film-447277")
        self.assertEqual(job["added_count"], 1)


def _bank_for(context: ChatContext):
    if context.watch_type == "planning" and context.film:
        return _QUESTIONS_PLANNING
    if context.film:
        return _QUESTIONS_FILM
    return _QUESTIONS_FREE


def _question_in(reply: str, context: ChatContext) -> str | None:
    film = (context.film or {}).get("title") or "the film"
    for template in _bank_for(context):
        question = template.format(film=film)
        if question in reply:
            return question
    return None


def _run_session(seed: int, turns: int = 12):
    provider = MockLLMProvider(rng=random.Random(seed))
    context = ChatContext(
        film={"title": "Arrival", "genres": ["Science Fiction"]}, watch_type="seen"
    )
    messages = []
    questions = []
    for turn in range(turns):
        messages.append(
            {
                "role": "user",
                "content": f"The quiet atmosphere felt hopeful and moving, reflection {turn}.",
            }
        )
        reply = provider.chat(messages, context)
        messages.append({"role": "assistant", "content": reply})
        question = _question_in(reply, context)
        assert question is not None, f"no bank question found in reply: {reply}"
        questions.append(question)
    return questions


class RandomisedPromptBankTests(unittest.TestCase):
    def test_seeded_rng_is_reproducible(self):
        self.assertEqual(_run_session(seed=42), _run_session(seed=42))

    def test_seeded_sessions_vary(self):
        first_questions = {_run_session(seed=s)[0] for s in range(6)}
        self.assertGreater(
            len(first_questions), 1, "different seeds should vary the first question"
        )

    def test_no_immediate_repetition_within_session(self):
        questions = _run_session(seed=1, turns=14)  # longer than the film bank
        for previous, current in zip(questions, questions[1:]):
            self.assertNotEqual(previous, current)

    def test_bank_is_exhausted_before_repeating(self):
        first_cycle = _run_session(seed=5)[: len(_QUESTIONS_FILM)]
        self.assertEqual(len(set(first_cycle)), len(first_cycle))

    def test_different_question_chip_changes_the_question(self):
        provider = MockLLMProvider(rng=random.Random(3))
        context = ChatContext(film={"title": "Arrival", "genres": []}, watch_type="seen")
        messages = [
            {"role": "user", "content": "The ending stayed with me, quiet and hopeful."}
        ]
        first_reply = provider.chat(messages, context)
        first_question = _question_in(first_reply, context)
        messages.append({"role": "assistant", "content": first_reply})
        messages.append({"role": "user", "content": "Can you ask a different question?"})
        second_reply = provider.chat(messages, context)
        second_question = _question_in(second_reply, context)
        self.assertIsNotNone(second_question)
        self.assertNotEqual(first_question, second_question)

    def test_opening_is_sampled_and_seeded_reproducible(self):
        context = ChatContext(film={"title": "Arrival", "genres": []}, watch_type="seen")
        a = MockLLMProvider(rng=random.Random(9)).opening(context)
        b = MockLLMProvider(rng=random.Random(9)).opening(context)
        self.assertEqual(a, b)
        self.assertIn("Arrival", a)


if __name__ == "__main__":
    unittest.main(verbosity=2)
