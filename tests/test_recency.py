"""Recency-aware ranking: publish-date parse, near-dup prefers newer, news profiles."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from web_research.features.intelligence.engine import query_profile
from web_research.features.ranking.engine import (
    parse_result_date,
    recency_score,
    rerank_results,
    select_with_recency_diversity,
)


class ParseResultDateTests(unittest.TestCase):
    def test_url_path_date(self) -> None:
        r = {
            "title": "Claude Fable 5 Extends To July 19",
            "url": "https://www.forbes.com/sites/sandycarter/2026/07/13/claude-fable-5-extends-to-july-19/",
            "content": "through July 12 was earlier",
            "publishedDate": "",
        }
        self.assertEqual(parse_result_date(r), date(2026, 7, 13))

    def test_published_date_field_wins(self) -> None:
        r = {
            "title": "x",
            "url": "https://example.com/2020/01/01/old/",
            "content": "",
            "publishedDate": "2026-07-19",
        }
        self.assertEqual(parse_result_date(r), date(2026, 7, 19))

    def test_ignores_deadline_only_in_snippet(self) -> None:
        # Snippet mentions July 12 but no publish signal → None (do not invent).
        r = {
            "title": "Some undated post",
            "url": "https://example.com/posts/fable",
            "content": "extended through July 12 on paid plans",
            "publishedDate": "",
        }
        self.assertIsNone(parse_result_date(r))


class RecencyScoreTests(unittest.TestCase):
    def test_newer_beats_older(self) -> None:
        today = date(2026, 7, 19)
        fresh = recency_score(date(2026, 7, 13), today=today)
        older = recency_score(date(2026, 7, 7), today=today)
        self.assertGreater(fresh, older)
        self.assertGreater(fresh, 0.5)

    def test_none_is_zero(self) -> None:
        self.assertEqual(recency_score(None), 0.0)


class NearDupPrefersNewerTests(unittest.TestCase):
    @patch("web_research.features.ranking.engine.embed")
    @patch("web_research.features.ranking.engine.is_alive", return_value=True)
    def test_newer_update_survives_near_dup(self, _alive, mock_embed) -> None:
        # Identical embeddings → near-dup collapse; newer publish date must win.
        vec = [1.0, 0.0, 0.0]
        mock_embed.return_value = vec
        older = {
            "title": "Fable 5 Extends By Five More Days",
            "url": "https://www.forbes.com/sites/x/2026/07/07/extends-five-days/",
            "content": "through July 12",
            "publishedDate": "",
        }
        newer = {
            "title": "Fable 5 Extends To July 19",
            "url": "https://www.forbes.com/sites/x/2026/07/13/extends-to-july-19/",
            "content": "through July 19",
            "publishedDate": "",
        }
        # Put older first so score order would keep it without recency-aware dedup.
        out = rerank_results("fable 5", [older, newer], recency_weight=0.28, sim_cutoff=0.9)
        urls = [r["url"] for r in out]
        self.assertIn(newer["url"], urls)
        # Older near-dup should be dropped (or ranked below); at most one Forbes path.
        self.assertEqual(urls.count(newer["url"]), 1)
        # Newer should appear before older if both somehow kept; ideally only newer.
        if older["url"] in urls:
            self.assertLess(urls.index(newer["url"]), urls.index(older["url"]))
        else:
            self.assertEqual(len(out), 1)


class SelectRecencyDiversityTests(unittest.TestCase):
    def test_forces_newest_into_top_k(self) -> None:
        results = [
            {
                "title": "Old rank1",
                "url": "https://a.example/2026/07/01/a/",
                "content": "x",
            },
            {
                "title": "Old rank2",
                "url": "https://b.example/2026/07/02/b/",
                "content": "x",
            },
            {
                "title": "Newest low rank",
                "url": "https://c.example/2026/07/18/c/",
                "content": "x",
            },
        ]
        picked = select_with_recency_diversity(results, k=2)
        urls = {r["url"] for r in picked}
        self.assertIn("https://c.example/2026/07/18/c/", urls)
        self.assertEqual(len(picked), 2)


class ProductNewsProfileTests(unittest.TestCase):
    @patch("web_research.features.intelligence.engine.is_alive", return_value=False)
    def test_fable_anthropic_needs_recency(self, _alive) -> None:
        prof = query_profile("Fable 5 Anthropic")
        self.assertEqual(prof["intent"], "news")
        self.assertTrue(prof["needs_recency"])

    @patch("web_research.features.intelligence.engine.is_alive", return_value=False)
    def test_extends_trigger(self, _alive) -> None:
        prof = query_profile("claude fable 5 extends until")
        self.assertTrue(prof["needs_recency"])

    @patch("web_research.features.intelligence.engine.is_alive", return_value=False)
    def test_generic_google_digit_not_news(self, _alive) -> None:
        prof = query_profile("google chrome 3 tips")
        self.assertNotEqual(prof["intent"], "news")

    @patch("web_research.features.intelligence.engine.generate")
    @patch("web_research.features.intelligence.engine.is_alive", return_value=True)
    def test_heuristic_recency_sticky_against_llm(self, _alive, mock_gen) -> None:
        # LLM casually tags product-window query as evergreen — floor wins.
        mock_gen.return_value = (
            '{"intent":"general","needs_recency":false,'
            '"preferred_sites":[],"expected_format":"snippet",'
            '"expand_queries":["Fable 5 Anthropic"]}'
        )
        prof = query_profile("Fable 5 Anthropic")
        self.assertTrue(prof["needs_recency"])
        self.assertEqual(prof["intent"], "news")

    def test_title_month_day_without_year_is_not_publish_date(self) -> None:
        r = {
            "title": "Claude Fable 5 Extends To July 19",
            "url": "https://example.com/posts/fable-extends",
            "content": "x",
            "publishedDate": "",
        }
        self.assertIsNone(parse_result_date(r))


if __name__ == "__main__":
    unittest.main()
