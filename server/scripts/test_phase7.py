"""Phase 7 tests: explicit-constraint parsing (F12), constrained recommendations,
and the ephemeral Film Assistant (no persisted conversations).

Run from server/: python scripts/test_phase7.py
In-memory Supabase + mocked TMDB/LLM; no live requests, no live DB writes.
"""

import random
import sys
import unittest
from pathlib import Path
from unittest import mock

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))
sys.path.insert(0, str(SERVER_ROOT / "scripts"))

from test_large_import import FakeStore  # noqa: E402

from app import constraints  # noqa: E402
from app import recommendations as rec  # noqa: E402
from app.llm.base import ChatContext  # noqa: E402
from app.llm.mock import MockLLMProvider  # noqa: E402
from app.routers import assistant as assistant_router  # noqa: E402
from app.routers import conversations as conversations_router  # noqa: E402

USER = "user-a"

PTA_ID = 4762  # Paul Thomas Anderson (real TMDB id, hardcoded here)
THOR_TMDB = 284053  # Thor: Ragnarok


def _raw(tmdb_id, title, year, genre_ids, vote_average=7.0, vote_count=2500):
    return {
        "id": tmdb_id,
        "title": title,
        "release_date": f"{year}-01-01",
        "poster_path": None,
        "overview": "",
        "genre_ids": genre_ids,
        "popularity": 40.0,
        "vote_average": vote_average,
        "vote_count": vote_count,
    }


class ConstraintsTests(unittest.TestCase):
    """F12: parse an explicit director / title / genre from a message."""

    def _person(self, query):
        if "anderson" in query.casefold():
            return {"id": PTA_ID, "name": "Paul Thomas Anderson"}
        return None

    def _movies(self, query):
        if query.casefold().startswith("thor"):
            return [{"id": THOR_TMDB, "title": "Thor: Ragnarok"}]
        return []

    def _parse(self, text):
        with (
            mock.patch.object(
                constraints.tmdb, "search_person", side_effect=self._person
            ),
            mock.patch.object(
                constraints.tmdb, "search_movies", side_effect=self._movies
            ),
        ):
            return constraints.parse_constraints(text)

    def test_director_phrase_is_resolved_and_validated(self):
        ask = self._parse("i only want to be recommended paul thomas anderson films")
        self.assertEqual(ask["director"], "Paul Thomas Anderson")
        self.assertEqual(ask["person_id"], PTA_ID)
        self.assertTrue(constraints.has_constraint(ask))

    def test_director_by_and_directed_by_phrases(self):
        for text in (
            "recommend me some films by paul thomas anderson",
            "i'd love something directed by paul thomas anderson",
        ):
            self.assertEqual(self._parse(text)["person_id"], PTA_ID)

    def test_named_title_is_resolved(self):
        ask = self._parse("can you recommend me thor: ragnorok")
        self.assertEqual(ask["title"], "Thor: Ragnarok")
        self.assertEqual(ask["tmdb_id"], THOR_TMDB)

    def test_genre_is_detected(self):
        ask = self._parse("I'm in the mood for a good comedy")
        self.assertEqual(ask["genres"], ["Comedy"])

    def test_plain_mood_is_not_a_constraint(self):
        ask = self._parse("something comforting please")
        self.assertFalse(constraints.has_constraint(ask))
        self.assertEqual(
            (ask["director"], ask["person_id"], ask["title"], ask["genres"]),
            (None, None, None, []),
        )


class ConstrainedRecommendationsTests(unittest.TestCase):
    """Constrained runs serve a director/genre pool and never touch Discover's
    cache or `_last_served` state."""

    def setUp(self):
        self.store = FakeStore()
        self.store.tables.setdefault("users", []).append(
            {"id": USER, "recommendation_style": 30}
        )
        self.store.tables.setdefault("recommendation_feedback", [])
        self.calls = []

    def _discover(self, genre_ids=None, sort_by="popularity.desc", page=1,
                  year=None, person_id=None, min_votes=200):
        self.calls.append(
            {"genre_ids": genre_ids, "person_id": person_id, "min_votes": min_votes}
        )
        films = [
            _raw(111, "There Will Be Blood", 2007, [18]),
            _raw(112, "Phantom Thread", 2017, [18, 10749]),
        ]
        if sort_by.startswith("vote_count"):
            films = [_raw(113, "Boogie Nights", 1997, [18, 35])]
        return films

    def _run(self, **kwargs):
        with (
            mock.patch.object(rec, "supabase", self.store),
            mock.patch.object(rec, "list_for_user", return_value=[]),
            mock.patch.object(
                rec.tmdb, "discover_movies", side_effect=self._discover
            ),
            mock.patch.object(rec.tmdb, "movie_recommendations", return_value=[]),
        ):
            return rec.get_recommendations(USER, limit=3, **kwargs)

    def test_person_constraint_drives_the_pool(self):
        cards = self._run(person_id=PTA_ID)
        self.assertEqual({c["tmdb_id"] for c in cards}, {111, 112, 113})
        self.assertTrue(all(c["person_id"] == PTA_ID for c in self.calls))
        self.assertTrue(all(c["min_votes"] == 40 for c in self.calls))
        # Constrained runs leave Discover's cache and last-served state alone.
        self.assertNotIn(USER, rec._last_served)
        self.assertNotIn(USER, rec._cache)

    def test_genre_constraint_maps_to_genre_ids(self):
        self._run(genres=["Comedy"])
        self.assertTrue(all(c["genre_ids"] == [35] for c in self.calls))


class NamedFilmAssistantTests(unittest.TestCase):
    """A film the user named is answered, not refused (D36/F12)."""

    def _movies(self, query):
        if query.casefold().startswith("thor"):
            return [{"id": THOR_TMDB, "title": "Thor: Ragnarok"}]
        return []

    def _person(self, query):
        return None

    def _details(self, tmdb_id):
        if tmdb_id != THOR_TMDB:
            return None
        return {
            "id": THOR_TMDB,
            "title": "Thor: Ragnarok",
            "release_date": "2017-01-01",
            "genres": [{"name": "Action"}, {"name": "Comedy"}],
            "runtime": 130,
            "overview": "The God of Thunder battles Hela.",
            "poster_path": "/thor.jpg",
            "vote_average": 7.6,
        }

    def _recs(self, tmdb_id):
        return [
            _raw(118, "Guardians of the Galaxy", 2014, [28, 878]),
            _raw(128, "Doctor Strange", 2016, [28, 14]),
        ]

    def _run(self, library_ids=()):
        store = FakeStore()
        store.tables.setdefault("user_films", []).extend(
            {"user_id": USER, "films": {"tmdb_id": tid}} for tid in library_ids
        )
        provider = mock.MagicMock()
        provider.chat_discovery.return_value = {"reply": "", "films": []}
        with (
            mock.patch.object(conversations_router, "supabase", store),
            mock.patch.object(
                conversations_router, "get_llm", return_value=provider
            ),
            mock.patch.object(
                conversations_router.rec_svc,
                "get_recommendations",
                return_value=[],
            ),
            mock.patch.object(
                conversations_router.constraint_svc.tmdb,
                "search_person",
                side_effect=self._person,
            ),
            mock.patch.object(
                conversations_router.constraint_svc.tmdb,
                "search_movies",
                side_effect=self._movies,
            ),
            mock.patch.object(
                conversations_router.tmdb, "search_movies", side_effect=self._movies
            ),
            mock.patch.object(
                conversations_router.tmdb, "movie_details", side_effect=self._details
            ),
            mock.patch.object(
                conversations_router.tmdb,
                "movie_recommendations",
                side_effect=self._recs,
            ),
            mock.patch.object(conversations_router, "poster_url", return_value=""),
        ):
            return conversations_router._discovery_reply(
                [{"role": "user", "content": "can you recommend me thor: ragnorok"}],
                ChatContext(conversation_type="discovery"),
                USER,
            )

    def test_named_film_not_in_library_is_offered(self):
        reply, metadata = self._run()
        cards = metadata["recommendations"]
        self.assertEqual(cards[0]["title"], "Thor: Ragnarok")
        self.assertEqual(cards[0]["tmdb_id"], THOR_TMDB)
        self.assertIn("Thor: Ragnarok", reply or "")

    def test_named_film_already_logged_returns_alternatives(self):
        reply, metadata = self._run(library_ids=[THOR_TMDB])
        cards = metadata["recommendations"]
        self.assertNotIn(THOR_TMDB, [c["tmdb_id"] for c in cards])
        self.assertIn("already in your library", reply)


class EphemeralTurnTests(unittest.TestCase):
    """Phase 7: `discovery_turn` is stateless — no conversation/message rows."""

    def test_turn_returns_reply_and_recommendations_without_writes(self):
        store = FakeStore()
        store.tables.setdefault("users", [])
        store.tables.setdefault("memories", [])
        provider = mock.MagicMock()
        provider.chat_discovery.return_value = {
            "reply": "Try these two.",
            "films": [],
        }
        with (
            mock.patch.object(conversations_router, "supabase", store),
            mock.patch.object(
                conversations_router.context_svc,
                "confirmed_memories",
                return_value=[],
            ),
            mock.patch.object(
                conversations_router, "get_llm", return_value=provider
            ),
            mock.patch.object(
                conversations_router.rec_svc,
                "get_recommendations",
                return_value=[],
            ),
        ):
            result = conversations_router.discovery_turn(
                USER, [{"role": "user", "content": "something hopeful"}]
            )
        self.assertEqual(result["reply"], "Try these two.")
        self.assertEqual(result["recommendations"], [])
        self.assertNotIn("conversations", store.tables)
        self.assertNotIn("messages", store.tables)

    def test_opening_uses_the_discovery_prompt_bank(self):
        provider = MockLLMProvider(rng=random.Random(4))
        store = FakeStore()
        store.tables.setdefault("users", []).append(
            {"id": USER, "display_name": "Alex"}
        )
        with mock.patch.object(
            conversations_router, "get_llm", return_value=provider
        ), mock.patch.object(
            conversations_router.context_svc, "confirmed_memories", return_value=[]
        ), mock.patch.object(conversations_router, "supabase", store):
            opening = conversations_router.discovery_opening(USER)
        self.assertIn("find your next film", opening)


class AssistantRouterTests(unittest.TestCase):
    """The new /assistant router exists and parses its request body."""

    def test_chat_body_validation(self):
        from app.routers.assistant import ChatBody

        ok = ChatBody(messages=[{"role": "user", "content": "hi"}])
        self.assertEqual(len(ok.messages), 1)

    def test_opening_endpoint_returns_a_reply(self):
        provider = mock.MagicMock()
        provider.opening.return_value = "What are you in the mood for?"
        store = FakeStore()
        store.tables.setdefault("users", []).append(
            {"id": USER, "display_name": "Alex"}
        )
        with mock.patch.object(
            conversations_router, "get_llm", return_value=provider
        ), mock.patch.object(
            conversations_router.context_svc, "confirmed_memories", return_value=[]
        ), mock.patch.object(conversations_router, "supabase", store):
            res = assistant_router.opening(current={"id": USER})
        self.assertEqual(res, {"reply": "What are you in the mood for?"})


if __name__ == "__main__":
    unittest.main(verbosity=2)