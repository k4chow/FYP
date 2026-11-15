"""Personalisation tests (Part J): reflection, memory and recommendation.

Run from server/: python scripts/test_personalisation.py
In-memory Supabase (FakeStore) + mocked TMDB/LLM; no live requests.
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
from app import film_knowledge  # noqa: E402
from app import memories as memory_svc  # noqa: E402
from app import recommendations as rec  # noqa: E402
from app.llm import openai as openai_mod  # noqa: E402
from app.llm.base import ChatContext  # noqa: E402
from app.routers import conversations as conversations_router  # noqa: E402

USER = "user-a"


def _raw(tmdb_id, title, year, genre_ids, overview="", vote_average=0.0, vote_count=0):
    return {
        "id": tmdb_id,
        "title": title,
        "release_date": f"{year}-01-01",
        "poster_path": None,
        "overview": overview,
        "genre_ids": genre_ids,
        "popularity": 50.0,
        "vote_average": vote_average,
        "vote_count": vote_count,
    }


class IntentParsingTests(unittest.TestCase):
    """Part D Stage 1: soft intention parsing is separate from hard constraints."""

    def test_mood_and_novelty(self):
        intent = constraints.parse_intent("make me think and surprise me")
        self.assertIn("intellectual", intent["moods"])
        self.assertTrue(intent["novelty"])

    def test_comfort_explicit_genre_exclusion(self):
        intent = constraints.parse_intent(
            "I want something comforting and light, no horror please"
        )
        self.assertIn("comfort", intent["moods"])
        self.assertEqual(intent["exclude_genres"], ["Horror"])

    def test_plural_genre_exclusion(self):
        self.assertEqual(
            constraints.parse_intent("avoid slow dramas")["exclude_genres"],
            ["Drama"],
        )
        self.assertEqual(
            constraints.parse_intent("not comedies")["exclude_genres"],
            ["Comedy"],
        )

    def test_explicit_directive_is_not_a_hard_constraint(self):
        ask = constraints.parse_constraints("something comforting please")
        self.assertFalse(constraints.has_constraint(ask))


class RecommendationIntentTests(unittest.TestCase):
    """Tests 1, 4, 7, 8: request-aware ranking and exclusions."""

    def setUp(self):
        self.store = FakeStore()
        self.store.tables.setdefault("users", []).append(
            {"id": USER, "recommendation_style": 30}
        )
        self.store.tables.setdefault("recommendation_feedback", [])
        self.store.tables.setdefault("user_films", []).append(
            {
                "user_id": USER,
                "status": "watched",
                "rating": 5.0,
                "films": {
                    "tmdb_id": 999,
                    "title": "The Conjuring",
                    "year": 2013,
                    "genres": ["Horror", "Thriller"],
                },
            }
        )

    def _run(self, intent=None, exclude_genres=None):
        def discover(genre_ids=None, sort_by="popularity.desc", page=1, year=None, **kw):
            return [
                _raw(2001, "Paddington 2", 2017, [35, 10751],
                     overview="A warm, comforting, heartwarming story of kindness.",
                     vote_average=7.8, vote_count=8000),
            ]

        def movie_recs(tmdb_id, page=1):
            return [
                _raw(1001, "Sinister", 2012, [27],
                     overview="A terrifying horror film.",
                     vote_average=6.8, vote_count=3000),
            ]

        with (
            mock.patch.object(rec, "supabase", self.store),
            mock.patch.object(rec, "list_for_user", return_value=[]),
            mock.patch.object(rec.tmdb, "discover_movies", side_effect=discover),
            mock.patch.object(rec.tmdb, "movie_recommendations", side_effect=movie_recs),
        ):
            rec.invalidate(USER)
            rec._last_served.clear()
            return rec.get_recommendations(
                USER, limit=12, intent=intent, exclude_genres=exclude_genres
            )

    def test_current_mood_overrides_history(self):
        neutral = self._run()
        self.assertEqual(neutral[0]["tmdb_id"], 1001)
        comfort = self._run(
            intent={"moods": ["comfort"], "novelty": False, "exclude_genres": []}
        )
        self.assertEqual(comfort[0]["tmdb_id"], 2001)
        self.assertIn("mood", comfort[0]["match_dimensions"])

    def test_negative_genre_excluded(self):
        cards = self._run(
            intent={"moods": [], "novelty": False, "exclude_genres": ["Horror"]}
        )
        ids = [c["tmdb_id"] for c in cards]
        self.assertNotIn(1001, ids)
        self.assertIn(2001, ids)

    def test_watched_film_is_never_seeded(self):
        cards = self._run()
        self.assertNotIn(999, [c["tmdb_id"] for c in cards])

    def test_cards_carry_dimensions_and_category(self):
        cards = self._run()
        for card in cards:
            self.assertIsInstance(card["match_dimensions"], list)
            self.assertIn(card["novelty_category"], ("familiar", "adjacent", "exploratory"))


class EmptyCandidateTests(unittest.TestCase):
    """Test 6: never fabricate films when nothing fits."""

    def test_fallback_reply_is_graceful(self):
        reply = conversations_router._fallback_reply([])
        self.assertIn("couldn't", reply)


class MemoryEvidenceTests(unittest.TestCase):
    """Tests 13/15: explicit vs inferred, grounded metadata."""

    MSG = "11111111-1111-1111-1111-111111111111"

    def _messages(self):
        return [
            {
                "id": self.MSG,
                "conversation_id": "22222222-2222-2222-2222-222222222222",
                "role": "user",
                "content": "I love films with ambiguous endings",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ]

    def test_new_kinds_and_evidence_are_normalised(self):
        raw = [
            {
                "content": "You respond to ambiguous endings.",
                "kind": "aesthetic",
                "explanation": "you said you love ambiguous endings",
                "source_message_ids": [self.MSG],
                "evidence_type": "explicit",
                "scope": "stable",
                "confidence": 0.9,
                "source_film_tmdb_id": 123,
            }
        ]
        proposals = memory_svc.normalise_proposals(raw, self._messages())
        self.assertEqual(len(proposals), 1)
        item = proposals[0]
        self.assertEqual(item["kind"], "aesthetic")
        self.assertEqual(item["evidence_type"], "explicit")
        self.assertEqual(item["confidence"], 0.9)
        self.assertEqual(item["source_film_tmdb_id"], 123)

    def test_inferred_default_and_confidence_fallback(self):
        raw = [
            {
                "content": "You may enjoy quiet observation.",
                "kind": "narrative",
                "explanation": "inferred",
                "source_message_ids": [self.MSG],
            }
        ]
        item = memory_svc.normalise_proposals(raw, self._messages())[0]
        self.assertEqual(item["evidence_type"], "inferred")
        self.assertEqual(item["scope"], "stable")
        self.assertEqual(item["confidence"], 0.5)

    def test_out_of_range_confidence_is_rejected(self):
        raw = [
            {
                "content": "You liked the pacing.",
                "kind": "preference",
                "explanation": "you praised the pacing",
                "source_message_ids": [self.MSG],
                "evidence_type": "explicit",
                "confidence": 7.0,
            }
        ]
        item = memory_svc.normalise_proposals(raw, self._messages())[0]
        self.assertEqual(item["confidence"], 0.9)

    def test_bad_source_ids_are_filtered(self):
        raw = [
            {
                "content": "You value patience in a story.",
                "kind": "theme",
                "explanation": "anchored",
                "source_message_ids": ["not-a-uuid", self.MSG],
            }
        ]
        proposals = memory_svc.normalise_proposals(raw, self._messages())
        self.assertEqual(proposals[0]["source_message_ids"], [self.MSG])

    def test_insert_falls_back_on_pre_migration_schema(self):
        """Without migration 0006 the rich insert fails; the fallback stores
        core fields and folds a new kind onto a legacy one."""
        memo = [
            {
                "content": "You respond to atmosphere.",
                "kind": "aesthetic",
                "explanation": "anchored",
                "source_message_ids": [self.MSG],
                "evidence_type": "explicit",
                "scope": "stable",
                "confidence": 0.9,
                "source_film_tmdb_id": None,
            }
        ]
        db = mock.MagicMock()
        # First insert (rich columns) raises; the retry (core columns) succeeds.
        db.table.return_value.insert.return_value.execute.side_effect = [
            RuntimeError("column evidence_type does not exist"),
            mock.MagicMock(data=[{"id": "m", "kind": "preference"}]),
        ]
        with mock.patch.object(memory_svc, "supabase", db):
            memory_svc.insert_proposals(USER, memo)
        self.assertEqual(db.table.return_value.insert.call_count, 2)
        legacy_rows = db.table.return_value.insert.call_args_list[1][0][0]
        self.assertNotIn("evidence_type", legacy_rows[0])
        self.assertEqual(legacy_rows[0]["kind"], "preference")


class CrossFilmThemeTests(unittest.TestCase):
    """Test 11: recurring themes across distinct films."""

    def test_recurring_theme_is_detected(self):
        rows = [
            {"content": "You kept returning to loneliness.", "source_reflection": {"film_title": "Her"}},
            {"content": "Loneliness surfaced again here.", "source_reflection": {"film_title": "Lost in Translation"}},
            {"content": "You loved the cinematography.", "source_reflection": {"film_title": "Blade Runner 2049"}},
        ]
        with mock.patch.object(memory_svc, "list_for_user", return_value=rows):
            themes = memory_svc.recurring_themes(USER)
        self.assertTrue(any(t["theme"] == "loneliness" for t in themes))
        films = next(t for t in themes if t["theme"] == "loneliness")["films"]
        self.assertEqual(films, ["Her", "Lost in Translation"])


class FilmKnowledgeTests(unittest.TestCase):
    """Tests 9/10: dossier assembly and mention resolution."""

    def test_film_context_dossier(self):
        dossier = film_knowledge.film_context(
            {
                "tmdb_id": 1,
                "title": "Her",
                "year": 2013,
                "genres": ["Drama", "Science Fiction"],
                "metadata": {
                    "director": "Spike Jonze",
                    "cast": ["Joaquin Phoenix", "Scarlett Johansson"],
                    "keywords": ["loneliness", "grieving"],
                    "overview": "A lonely writer develops a relationship with an OS.",
                    "runtime": 126,
                },
            }
        )
        self.assertEqual(dossier["director"], "Spike Jonze")
        self.assertEqual(dossier["cast"], ["Joaquin Phoenix", "Scarlett Johansson"])
        self.assertIn("loneliness", dossier["themes"])
        self.assertIn("grief", dossier["themes"])

    def test_mention_resolution(self):
        def search(query):
            return [{"id": 38, "title": "Eternal Sunshine of the Spotless Mind",
                     "release_date": "2004-03-19"}]

        with (
            mock.patch.object(film_knowledge, "_catalogue_titles", return_value=[]),
            mock.patch.object(film_knowledge.tmdb, "search_movies", side_effect=search),
        ):
            mentions = film_knowledge.resolve_film_mentions(
                "The ending reminded me a lot of Eternal Sunshine of the Spotless Mind"
            )
        self.assertEqual(len(mentions), 1)
        self.assertEqual(mentions[0]["tmdb_id"], 38)
        self.assertEqual(mentions[0]["title"], "Eternal Sunshine of the Spotless Mind")


class PromptTests(unittest.TestCase):
    """Tests 13/14: natural conversation, no fabricated memories, candidate-only."""

    def test_reflection_prompt_is_conversational(self):
        self.assertNotIn("exactly one follow-up question", openai_mod._SYSTEM_BASE)
        self.assertIn("never claim", openai_mod._SYSTEM_BASE)

    def test_discovery_prompt_is_candidate_only(self):
        self.assertIn("ONLY from the candidate", openai_mod._SYSTEM_DISCOVERY)
        self.assertIn("empty, ask one short clarifying question", openai_mod._SYSTEM_DISCOVERY)

    def test_context_block_reports_no_memories_when_none(self):
        block = openai_mod._context_block(ChatContext(conversation_type="reflection"))
        self.assertNotIn("you told me", block)
        self.assertNotIn("Confirmed memories", block)


class RecommendationEventsTests(unittest.TestCase):
    """Discovery -> reflection: persist what was recommended and why."""

    def test_record_recommendations_writes(self):
        db = mock.MagicMock()
        rec.record_recommendations(
            USER,
            [{"tmdb_id": 1, "title": "Her", "why": "loneliness",
              "match_dimensions": ["taste"], "novelty_category": "familiar"}],
            db=db,
        )
        db.table.assert_called_with("recommendation_events")
        rows = db.table.return_value.insert.call_args[0][0]
        self.assertEqual(rows[0]["tmdb_id"], 1)
        self.assertEqual(rows[0]["reason"], "loneliness")
        self.assertEqual(rows[0]["match_dimensions"], ["taste"])

    def test_mark_recommendations_watched(self):
        db = mock.MagicMock()
        rec.mark_recommendations_watched(USER, [1, 2], db=db)
        db.table.assert_called_with("recommendation_events")
        db.table.return_value.update.assert_called_once()
        db.table.return_value.update.return_value.eq.assert_called_once_with(
            "user_id", USER
        )
        db.table.return_value.update.return_value.eq.return_value.in_.assert_called_once_with(
            "tmdb_id", [1, 2]
        )


class DiscoveryBackfillTests(unittest.TestCase):
    """Bug fix: a discovery turn always serves up to three distinct picks by
    topping up whatever the provider named from the ranked, filtered pool."""

    def test_single_or_missing_pick_is_backfilled_to_three(self):
        pool = [
            {
                "tmdb_id": 1, "title": "Alpha", "year": 2000, "genres": ["Drama"],
                "overview": "A.", "poster_url": "", "vote_average": 7.0, "why": "",
            },
            {
                "tmdb_id": 2, "title": "Beta", "year": 2001, "genres": ["Comedy"],
                "overview": "B.", "poster_url": "", "vote_average": 6.0, "why": "",
            },
            {
                "tmdb_id": 3, "title": "Gamma", "year": 2002, "genres": ["Thriller"],
                "overview": "C.", "poster_url": "", "vote_average": 6.5, "why": "",
            },
        ]
        provider = mock.MagicMock()
        provider.chat_discovery.return_value = {"reply": "Try these.", "films": []}
        provider.chat.return_value = "plain"

        store = mock.MagicMock()
        store.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

        with (
            mock.patch.object(conversations_router, "supabase", store),
            mock.patch.object(conversations_router, "get_llm", return_value=provider),
            mock.patch.object(
                conversations_router.rec_svc, "get_recommendations", return_value=pool
            ),
            mock.patch.object(conversations_router.rec_svc, "record_recommendations"),
        ):
            reply, metadata = conversations_router._discovery_reply(
                [{"role": "user", "content": "something good"}],
                ChatContext(conversation_type="discovery"),
                USER,
            )

        cards = metadata["recommendations"]
        self.assertEqual(len(cards), 3)
        self.assertEqual(len({c["tmdb_id"] for c in cards}), 3)
        self.assertEqual({c["tmdb_id"] for c in cards}, {1, 2, 3})


if __name__ == "__main__":
    unittest.main(verbosity=2)