"""Offline retrieval-quality eval (no network).

Fixture-based checks that guard the Fable-5 class failure mode and basic
ranking health. Not a full IR benchmark — a regression harness controllers
can trust to stay green in CI.

Metrics (deterministic fixtures):
  - publish-date parse accuracy
  - near-dup collapse keeps newer article
  - recency-aware order: newer dated news outranks older near-dup
  - select_with_recency_diversity forces freshest into top-k
  - MRR@3 for a tiny ranked list (ideal rank 1 = 1.0)
"""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from web_research.features.ranking.engine import (
    parse_result_date,
    recency_score,
    rerank_results,
    select_with_recency_diversity,
)

# ---------------------------------------------------------------------------
# Fixtures — simplified Forbes-style update chain
# ---------------------------------------------------------------------------
_OLDER = {
    "title": "Claude Fable 5 Extends By Five More Days",
    "url": "https://www.forbes.com/sites/x/2026/07/07/extends-five-days/",
    "content": "Anthropic extended Claude Fable 5 through July 12.",
    "publishedDate": "",
}
_NEWER = {
    "title": "Claude Fable 5 Extends To July 19",
    "url": "https://www.forbes.com/sites/x/2026/07/13/extends-to-july-19/",
    "content": "Anthropic extended Claude Fable 5 through July 19.",
    "publishedDate": "",
}
_EVERGREEN = {
    "title": "Claude Fable product page",
    "url": "https://www.anthropic.com/claude/fable",
    "content": "Claude Fable 5 overview and capabilities for developers.",
    "publishedDate": "",
}


def _mrr_at_k(ranked_urls: list[str], relevant: set[str], k: int = 3) -> float:
    for i, url in enumerate(ranked_urls[:k], 1):
        if url in relevant:
            return 1.0 / i
    return 0.0


class PublishDateEval(unittest.TestCase):
    def test_url_dates(self) -> None:
        self.assertEqual(parse_result_date(_OLDER), date(2026, 7, 7))
        self.assertEqual(parse_result_date(_NEWER), date(2026, 7, 13))
        self.assertIsNone(parse_result_date(_EVERGREEN))

    def test_recency_half_life_ordering(self) -> None:
        today = date(2026, 7, 19)
        self.assertGreater(
            recency_score(date(2026, 7, 13), today=today),
            recency_score(date(2026, 7, 7), today=today),
        )


class NearDupAndOrderEval(unittest.TestCase):
    @patch("web_research.features.ranking.engine.embed", return_value=[1.0, 0.0, 0.0])
    @patch("web_research.features.ranking.engine.is_alive", return_value=True)
    def test_near_dup_keeps_newer_only(self, _alive, _embed) -> None:
        out = rerank_results(
            "Fable 5 extends",
            [_OLDER, _NEWER],
            recency_weight=0.28,
            sim_cutoff=0.9,
        )
        urls = [r["url"] for r in out]
        self.assertIn(_NEWER["url"], urls)
        self.assertNotIn(_OLDER["url"], urls)

    @patch("web_research.features.ranking.engine.embed")
    @patch("web_research.features.ranking.engine.is_alive", return_value=True)
    def test_mrr_newer_is_first(self, _alive, mock_embed) -> None:
        # Query + both extension stories share a topic vector; evergreen is
        # orthogonal. Recency then breaks the older/newer tie.
        topic = [1.0, 0.0, 0.0]
        other = [0.0, 1.0, 0.0]

        def _emb(text: str):
            t = text.lower()
            if "extends" in t or "fable 5 anthropic" in t:
                return topic
            return other

        mock_embed.side_effect = _emb
        out = rerank_results(
            "Fable 5 Anthropic extends",
            [_OLDER, _NEWER, _EVERGREEN],
            recency_weight=0.28,
            sim_cutoff=0.99,
        )
        ranked = [r["url"] for r in out]
        mrr = _mrr_at_k(ranked, {_NEWER["url"]}, k=3)
        self.assertEqual(mrr, 1.0, f"expected newer first, got {ranked}")


class DiversityEval(unittest.TestCase):
    def test_forces_freshest_into_top_k(self) -> None:
        pool = [
            {**_OLDER, "url": "https://a.example/2026/07/01/a/"},
            {**_OLDER, "url": "https://b.example/2026/07/02/b/"},
            {**_NEWER, "url": "https://c.example/2026/07/18/c/"},
        ]
        picked = select_with_recency_diversity(pool, k=2)
        urls = {r["url"] for r in picked}
        self.assertIn("https://c.example/2026/07/18/c/", urls)
        self.assertEqual(len(picked), 2)


class EvalThresholds(unittest.TestCase):
    """Document the regression gates this suite enforces."""

    def test_gates(self) -> None:
        # Publish-date parse must recover CMS URL stamps.
        self.assertIsNotNone(parse_result_date(_NEWER))
        # Recency score separation for a 6-day gap must be material.
        today = date(2026, 7, 19)
        gap = recency_score(date(2026, 7, 13), today=today) - recency_score(
            date(2026, 7, 7), today=today
        )
        self.assertGreater(gap, 0.1)


if __name__ == "__main__":
    unittest.main()
