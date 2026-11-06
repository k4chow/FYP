"""Phase 6 tests: the deterministic recommendation engine (F8/F9/F11/N6)
and the Film Assistant discovery conversation banks (F10).

Run from server/: python scripts/test_phase6.py
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

from app import recommendations as rec  # noqa: E402
from app.llm.base import ChatContext  # noqa: E402
from app.llm.mock import (  # noqa: E402
    _OPENERS_DISCOVERY,
    _QUESTIONS_DISCOVERY,
    MockLLMProvider,
)
from app.routers import conversations as conversations_router  # noqa: E402

USER = "user-a"

# Library: Arrival (rated 4.5, watched) + La La Land (watchlist).
ARRIVAL = 329
LA_LA_LAND = 313369
NOT_FOR_ME = 999001
INTERSTELLAR = 157336  # explicit "more like this" feedback seed


def _tmdb(
    tmdb_id,
    title,
    year,
    genre_ids,
    overview="",
    popularity=50.0,
    vote_average=0.0,
    vote_count=0,
):
    return {
        "id": tmdb_id,
        "title": title,
        "release_date": f"{year}-01-01",
        "poster_path": None,
        "overview": overview,
        "genre_ids": genre_ids,
        "popularity": popularity,
        "vote_average": vote_average,
        "vote_count": vote_count,
    }


TMDB_RECS = {
    ARRIVAL: [
        _tmdb(335984, "Blade Runner 2049", 2017, [878, 18, 9648]),
        _tmdb(264660, "Ex Machina", 2014, [18, 878]),
        _tmdb(LA_LA_LAND, "La La Land", 2016, [10749, 10402]),  # in library
        _tmdb(NOT_FOR_ME, "Generic Action", 2020, [28]),  # not-for-me
    ],
    LA_LA_LAND: [_tmdb(244786, "Whiplash", 2014, [18, 10402])],
    INTERSTELLAR: [
        _tmdb(
            286217, "The Martian", 2015, [878, 12, 18],
            overview="A quiet, hopeful story of survival on Mars.",
        ),
    ],
}

DISCOVER = [
    _tmdb(438631, "Dune", 2021, [878, 12], vote_average=8.0, vote_count=9000),
    _tmdb(562, "Die Hard", 1988, [28, 53]),  # off-profile genres
]

# Only surfaced by randomised refresh pages (page/year beyond the defaults).
EXTRA_DISCOVER = [
    _tmdb(901, "Extra Drama", 1999, [18], vote_average=7.5, vote_count=1500),
    _tmdb(902, "Extra Sci-Fi", 2003, [878], vote_average=7.0, vote_count=1200),
    _tmdb(903, "Extra Comedy", 1994, [35], vote_average=7.2, vote_count=1400),
    _tmdb(904, "Extra Crime", 2011, [80], vote_average=6.9, vote_count=1100),
]

MEMORY = {
    "id": "mem-1",
    "content": "You love quiet, hopeful sci-fi stories.",
    "kind": "preference",
}


class RecommendationEngineTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.store.tables.setdefault("users", []).append(
            {"id": USER, "recommendation_style": 30}
        )
        self.store.tables.setdefault("user_films", []).extend(
            [
                {
                    "user_id": USER,
                    "status": "watched",
                    "rating": 4.5,
                    "films": {
                        "tmdb_id": ARRIVAL,
                        "title": "Arrival",
                        "year": 2016,
                        "genres": ["Science Fiction", "Drama"],
                    },
                },
                {
                    "user_id": USER,
                    "status": "watchlist",
                    "rating": None,
                    "films": {
                        "tmdb_id": LA_LA_LAND,
                        "title": "La La Land",
                        "year": 2016,
                        "genres": ["Romance", "Music", "Comedy", "Drama"],
                    },
                },
            ]
        )
        self.store.tables.setdefault("recommendation_feedback", []).extend(
            [
                {"user_id": USER, "tmdb_id": NOT_FOR_ME, "title": "Generic Action",
                 "signal": "not_for_me"},
                {"user_id": USER, "tmdb_id": INTERSTELLAR, "title": "Interstellar",
                 "signal": "more_like_this"},
            ]
        )
        self.discover_calls = []

        for patcher in (
            mock.patch.object(rec, "supabase", self.store),
            mock.patch.object(rec, "list_for_user", return_value=[MEMORY]),
            mock.patch.object(
                rec.tmdb, "movie_recommendations",
                side_effect=lambda tmdb_id: TMDB_RECS.get(tmdb_id, []),
            ),
            mock.patch.object(
                rec.tmdb, "discover_movies", side_effect=self._discover,
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        rec.invalidate(USER)
        rec._last_served.clear()

    def _discover(
        self, genre_ids=None, sort_by="popularity.desc", page=1, year=None
    ):
        self.discover_calls.append((genre_ids, sort_by, page, year))
        if page != 1 or year is not None:
            # Randomised refresh pages surface candidates the default pages
            # never show, so a refresh can genuinely change the grid.
            return DISCOVER + EXTRA_DISCOVER
        return DISCOVER

    def cards(self):
        return rec.get_recommendations(USER, limit=12)

    def test_cards_carry_tmdb_rating(self):
        dune = next(c for c in self.cards() if c["tmdb_id"] == 438631)
        self.assertEqual(dune["vote_average"], 8.0)

    def test_refresh_excludes_last_served_and_widens_pool(self):
        served = {c["tmdb_id"] for c in self.cards()}
        self.assertEqual(len(served), 6)
        random.seed(11)
        refreshed = rec.get_recommendations(USER, limit=3, refresh=True)
        self.assertEqual(len(refreshed), 3)
        # A refresh must surface films the user has not just seen, not the
        # same cards reordered (D36).
        self.assertFalse({c["tmdb_id"] for c in refreshed} & served)
        # Refresh bypassed the cache and widened the pool: an extra
        # randomised discover page ran (page/year beyond the defaults).
        self.assertTrue(
            any(
                page != 1 or year is not None
                for _, _, page, year in self.discover_calls
            )
        )

    def test_refresh_draw_is_reproducible_from_clean_state(self):
        random.seed(11)
        refreshed = rec.get_recommendations(USER, limit=3, refresh=True)
        rec.invalidate(USER)
        rec._last_served.clear()
        random.seed(11)
        again = rec.get_recommendations(USER, limit=3, refresh=True)
        self.assertEqual(
            [c["tmdb_id"] for c in refreshed], [c["tmdb_id"] for c in again]
        )

    def test_refresh_bypasses_cache(self):
        self.cards()  # primes the cache
        before = len(self.discover_calls)
        self.cards()  # cache hit: no new discover calls
        self.assertEqual(len(self.discover_calls), before)
        rec.get_recommendations(USER, limit=3, refresh=True)
        self.assertGreater(len(self.discover_calls), before)

    def test_library_and_not_for_me_are_excluded(self):
        ids = [c["tmdb_id"] for c in self.cards()]
        self.assertNotIn(LA_LA_LAND, ids)  # already in the library
        self.assertNotIn(ARRIVAL, ids)
        self.assertNotIn(NOT_FOR_ME, ids)  # explicit "not for me" (F11)

    def test_feedback_seed_tops_the_list_with_provenance(self):
        top = self.cards()[0]
        self.assertEqual(top["tmdb_id"], 286217)  # The Martian
        self.assertIn('more like "Interstellar"', top["why"])
        self.assertEqual(
            [m["id"] for m in top["source_memories"]], ["mem-1"]
        )

    def test_rated_seed_why_and_memory_affinity(self):
        blade_runner = next(c for c in self.cards() if c["tmdb_id"] == 335984)
        self.assertIn('rated "Arrival" 4.5★', blade_runner["why"])
        # sci-fi alias in the memory matches the candidate's genre (F8/F9).
        self.assertEqual(
            [m["id"] for m in blade_runner["source_memories"]], ["mem-1"]
        )
        self.assertIn("quiet, hopeful sci-fi", blade_runner["why"])

    def test_watchlist_seed_and_genre_fallback_why(self):
        whiplash = next(c for c in self.cards() if c["tmdb_id"] == 244786)
        self.assertIn('on your watchlist', whiplash["why"])
        # Discover-only candidate with no memory: top-genre fallback (F9).
        die_hard = next(c for c in self.cards() if c["tmdb_id"] == 562)
        self.assertIn("films lead your library", die_hard["why"])

    def test_style_slider_reweights_scores(self):
        # style=30 (default): similarity-weighted seed score dominates.
        base = {c["tmdb_id"]: c["score"] for c in self.cards()}
        # style=0 ("More like what I love"): seed contribution maxed.
        self.store.tables["users"][0]["recommendation_style"] = 0
        rec.invalidate(USER)
        similar = {c["tmdb_id"]: c["score"] for c in self.cards()}
        # style=100 ("Surprise me"): seeds dampened, off-profile boosted.
        self.store.tables["users"][0]["recommendation_style"] = 100
        rec.invalidate(USER)
        explore = {c["tmdb_id"]: c["score"] for c in self.cards()}

        self.assertGreater(similar[335984], base[335984])
        self.assertLess(explore[335984], base[335984])
        # Die Hard shares no genre with the user's top genres: explore bonus.
        self.assertGreater(explore[562], similar[562])

    def test_deterministic_ordering(self):
        first = [c["tmdb_id"] for c in self.cards()]
        rec.invalidate(USER)
        second = [c["tmdb_id"] for c in self.cards()]
        self.assertEqual(first, second)

    def test_limit_is_respected(self):
        self.assertEqual(len(rec.get_recommendations(USER, limit=3)), 3)


class ColdStartTests(unittest.TestCase):
    """No library, feedback, or memories: fall back to popular TMDB picks."""

    def setUp(self):
        self.store = FakeStore()
        self.store.tables.setdefault("users", []).append(
            {"id": USER, "recommendation_style": 30}
        )
        self.store.tables.setdefault("recommendation_feedback", [])
        self.discover_calls = []
        for patcher in (
            mock.patch.object(rec, "supabase", self.store),
            mock.patch.object(rec, "list_for_user", return_value=[]),
            mock.patch.object(
                rec.tmdb, "movie_recommendations", side_effect=lambda _id: []
            ),
            mock.patch.object(
                rec.tmdb, "discover_movies", side_effect=self._discover
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        rec.invalidate(USER)

    def _discover(
        self, genre_ids=None, sort_by="popularity.desc", page=1, year=None
    ):
        self.discover_calls.append(genre_ids)
        return DISCOVER

    def test_popular_fallback_with_cold_start_why(self):
        cards = rec.get_recommendations(USER, limit=5)
        self.assertTrue(cards)
        self.assertIsNone(self.discover_calls[0])  # no genre filter possible
        self.assertTrue(all("Popular on TMDB" in c["why"] for c in cards))
        self.assertTrue(all(c["source_memories"] == [] for c in cards))


class DiscoveryAssistantMockTests(unittest.TestCase):
    """F10: discovery conversations get their own prompt bank."""

    def test_opening_is_discovery_flavoured(self):
        provider = MockLLMProvider(rng=random.Random(4))
        opening = provider.opening(ChatContext(conversation_type="discovery"))
        self.assertIn("find your next film", opening)
        self.assertTrue(any(o in opening for o in _OPENERS_DISCOVERY))

    def test_questions_come_from_discovery_bank(self):
        provider = MockLLMProvider(rng=random.Random(4))
        context = ChatContext(conversation_type="discovery")
        messages = [{"role": "user", "content": "I want something hopeful."}]
        reply = provider.chat(messages, context)
        self.assertTrue(any(q in reply for q in _QUESTIONS_DISCOVERY))

    def test_reflection_opening_unchanged_without_discovery(self):
        provider = MockLLMProvider(rng=random.Random(4))
        opening = provider.opening(ChatContext(conversation_type="reflection"))
        self.assertNotIn("find your next film", opening)

    def test_chat_discovery_returns_reply_and_films(self):
        provider = MockLLMProvider(rng=random.Random(4))
        turn = provider.chat_discovery(
            [{"role": "user", "content": "Something mind-bending please."}],
            ChatContext(conversation_type="discovery"),
        )
        self.assertEqual(set(turn), {"reply", "films"})
        self.assertGreaterEqual(len(turn["films"]), 1)
        self.assertLessEqual(len(turn["films"]), 3)
        self.assertTrue(all(film["title"] for film in turn["films"]))

    def test_chat_discovery_picks_from_candidate_pool(self):
        """D36: with an engine pool available the mock picks from it and
        passes tmdb_ids through so grounding never has to re-search."""
        provider = MockLLMProvider(rng=random.Random(1))
        pool = [
            {
                "tmdb_id": 1, "title": "Alpha", "year": 2000,
                "genres": ["Drama"], "why": "Because Drama films lead your library",
                "overview": "", "poster_url": None, "vote_average": 7.0,
            },
            {
                "tmdb_id": 2, "title": "Beta", "year": 2001,
                "genres": ["Comedy"], "why": "",
                "overview": "", "poster_url": None, "vote_average": 6.0,
            },
        ]
        turn = provider.chat_discovery(
            [{"role": "user", "content": "something comforting"}],
            ChatContext(conversation_type="discovery", suggestions=pool),
        )
        self.assertEqual(
            sorted(film["tmdb_id"] for film in turn["films"]), [1, 2]
        )
        self.assertIn("Alpha", turn["reply"])

    def test_chat_discovery_canned_path_skips_library_titles(self):
        from app.llm.mock import _MOCK_FILMS

        provider = MockLLMProvider(rng=random.Random(1))
        taken = [film["title"] for film in _MOCK_FILMS[:-1]]
        turn = provider.chat_discovery(
            [{"role": "user", "content": "something comforting"}],
            ChatContext(conversation_type="discovery", library_titles=taken),
        )
        taken_casefold = {title.casefold() for title in taken}
        self.assertTrue(
            all(film["title"].casefold() not in taken_casefold for film in turn["films"])
        )


class DiscoveryGroundingTests(unittest.TestCase):
    """F10: assistant film picks are grounded against TMDB before they are
    shown; unresolvable titles are dropped and library films are skipped."""

    WHIPLASH = 244786

    def setUp(self):
        self.store = mock.MagicMock()
        self.store.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

    def search(self, name, year=None):
        if name == "Whiplash":
            return [{"id": self.WHIPLASH, "title": "Whiplash"}]
        return []

    def details(self, tmdb_id):
        if tmdb_id != self.WHIPLASH:
            return None
        return {
            "id": self.WHIPLASH,
            "title": "Whiplash",
            "release_date": "2014-01-01",
            "genres": [{"name": "Drama"}],
            "runtime": 106,
            "overview": "A drummer pushes himself too far.",
            "poster_path": "/whiplash.jpg",
            "vote_average": 8.4,
        }

    def _run(self, provider, library_data=None, pool=None):
        self.store.table.return_value.select.return_value.eq.return_value.execute.return_value.data = (
            library_data or []
        )
        with (
            mock.patch.object(conversations_router, "supabase", self.store),
            mock.patch.object(
                conversations_router, "get_llm", return_value=provider
            ),
            mock.patch.object(
                conversations_router.rec_svc,
                "get_recommendations",
                return_value=pool or [],
            ),
            mock.patch.object(
                conversations_router.tmdb, "search_movies", side_effect=self.search
            ),
            mock.patch.object(
                conversations_router.tmdb,
                "movie_details",
                side_effect=self.details,
            ),
            mock.patch.object(conversations_router, "poster_url", return_value=""),
        ):
            return conversations_router._discovery_reply(
                [{"role": "user", "content": "something hopeful"}],
                ChatContext(conversation_type="discovery"),
                USER,
            )

    def _provider(self, failing=False):
        provider = mock.MagicMock()
        if failing:
            provider.chat_discovery.side_effect = RuntimeError("bad json")
        else:
            provider.chat_discovery.return_value = {
                "reply": "Try these.",
                "films": [
                    {"title": "Arrival", "year": 2016, "themes": ["Time"]},
                    {"title": "Whiplash", "year": 2014, "themes": ["Ambition"]},
                    {"title": "Made Up Movie", "year": 2099},
                ],
            }
        provider.chat.return_value = "plain fallback reply"
        return provider

    def test_films_are_grounded_and_library_films_skipped(self):
        reply, metadata = self._run(
            self._provider(),
            library_data=[{"films": {"tmdb_id": ARRIVAL}}],  # Arrival in library
        )
        self.assertEqual(reply, "Try these.")
        cards = metadata["recommendations"]
        self.assertEqual([c["tmdb_id"] for c in cards], [self.WHIPLASH])
        card = cards[0]
        self.assertEqual(card["year"], 2014)
        self.assertEqual(card["genres"], ["Drama"])
        self.assertEqual(card["runtime"], 106)
        self.assertEqual(card["vote_average"], 8.4)
        self.assertEqual(card["poster_url"], "")
        self.assertEqual(metadata["kind"], "suggestions")

    def test_ungroundable_turn_falls_back_to_plain_chat(self):
        reply, metadata = self._run(self._provider(failing=True))
        self.assertEqual(reply, "plain fallback reply")
        self.assertEqual(metadata, {})

    def test_failing_provider_still_recommends_from_pool(self):
        """D36: a broken provider must not turn the assistant into a plain
        chatbot — the engine pool keeps every turn a recommendation."""
        pool = [
            {
                "tmdb_id": 42,
                "title": "Pool Pick",
                "year": 2001,
                "genres": ["Drama"],
                "overview": "A pool pick.",
                "why": "Because Drama films lead your library",
                "poster_url": "http://p/42.jpg",
                "vote_average": 7.1,
            },
            {
                "tmdb_id": 43,
                "title": "Second Pick",
                "year": 2002,
                "genres": ["Comedy"],
                "overview": "",
                "why": "",
                "poster_url": None,
                "vote_average": 6.0,
            },
        ]
        reply, metadata = self._run(self._provider(failing=True), pool=pool)
        cards = metadata["recommendations"]
        self.assertEqual([c["tmdb_id"] for c in cards], [42, 43])
        self.assertEqual(cards[0]["runtime"], None)
        self.assertIn("Pool Pick and Second Pick", reply)
        self.assertNotEqual(reply, "plain fallback reply")

    def test_provider_tmdb_ids_pass_through_without_search(self):
        provider = self._provider()
        provider.chat_discovery.return_value = {
            "reply": "Try Whiplash.",
            "films": [
                {
                    "tmdb_id": self.WHIPLASH,
                    "title": "Whiplash",
                    "year": 2014,
                    "themes": ["Ambition"],
                }
            ],
        }
        calls = []
        original_search = self.search

        def counting_search(name, year=None):
            calls.append(name)
            return original_search(name, year)

        with mock.patch.object(
            conversations_router.tmdb, "search_movies", side_effect=counting_search
        ):
            _, metadata = self._run(provider)
        self.assertEqual(calls, [])  # pool ids never re-searched
        self.assertEqual(
            [c["tmdb_id"] for c in metadata["recommendations"]], [self.WHIPLASH]
        )

    def test_pool_cards_exclude_library_films(self):
        """Films the user already logged are never recommended, even when the
        provider names a pool film that is in the library."""
        provider = self._provider()
        provider.chat_discovery.return_value = {
            "reply": "Try Whiplash.",
            "films": [{"tmdb_id": self.WHIPLASH, "title": "Whiplash", "year": 2014}],
        }
        _, metadata = self._run(
            provider, library_data=[{"films": {"tmdb_id": self.WHIPLASH}}]
        )
        self.assertEqual(metadata["recommendations"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

