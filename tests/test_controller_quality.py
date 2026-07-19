"""Controller-facing quality: engine escalation, citation grounding, scrape recovery, ES profiles."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import web_research as wr
import web_research.shared.config as _config
from web_research.features.intelligence.engine import query_profile
from web_research.features.research.command import _scrape_with_recovery
from web_research.features.search.engine import escalation_chain, search_with_escalation
from web_research.features.synthesis.engine import (
    _render_structured,
    ground_structured_facts,
)

from ._helpers import _clear_cache


class EscalationChainTests(unittest.TestCase):
    def test_primary_first_then_free(self) -> None:
        with patch.object(_config, "reload_settings") as _rs:
            pass
        # Without paid keys, chain is free engines only after primary.
        with patch("web_research.features.search.engine.get_settings") as mock_settings:
            mock_settings.return_value = type(
                "S",
                (),
                {"minimax_api_key": "", "zai_api_key": ""},
            )()
            chain = escalation_chain("searxng")
        self.assertEqual(chain[0], "searxng")
        self.assertIn("duckduckgo", chain)
        self.assertNotIn("minimax", chain)
        self.assertNotIn("zai", chain)

    def test_paid_keys_extend_chain(self) -> None:
        with patch("web_research.features.search.engine.get_settings") as mock_settings:
            mock_settings.return_value = type(
                "S",
                (),
                {"minimax_api_key": "k", "zai_api_key": "z"},
            )()
            chain = escalation_chain("searxng")
        self.assertEqual(chain, ["searxng", "duckduckgo", "minimax", "zai"])

    def test_search_with_escalation_uses_second_engine(self) -> None:
        hits = [{"title": "D", "url": "https://d.example", "content": "c", "source": "duckduckgo"}]

        def fake_backends(query, num, engine, cat, lang, time_range, queries=None):
            if engine == "searxng":
                return []
            if engine == "duckduckgo":
                return hits
            return []

        with (
            patch(
                "web_research.features.search.engine.search_backends",
                side_effect=fake_backends,
            ),
            patch("web_research.features.search.engine.get_settings") as mock_settings,
        ):
            mock_settings.return_value = type(
                "S",
                (),
                {"minimax_api_key": "", "zai_api_key": ""},
            )()
            results, meta = search_with_escalation("q", 3, "searxng", "general", "en", "")
        self.assertEqual(results, hits)
        self.assertTrue(meta["escalated"])
        self.assertEqual(meta["engine_used"], "duckduckgo")
        self.assertEqual(meta["engines_tried"], ["searxng", "duckduckgo"])


class CitationGroundingTests(unittest.TestCase):
    def test_supported_claim_keeps_confidence(self) -> None:
        docs = [
            {
                "title": "Doc",
                "url": "https://x",
                "text": "Python 3.14 adds free-threading improvements for CPython.",
            }
        ]
        data = {
            "answer": "A",
            "facts": [
                {
                    "claim": "Python free-threading improvements land in CPython",
                    "source": 1,
                    "confidence": "high",
                }
            ],
            "unknowns": [],
        }
        out = ground_structured_facts(data, docs)
        self.assertEqual(out["facts"][0]["grounding"], "supported")
        self.assertEqual(out["facts"][0]["confidence"], "high")

    def test_unsupported_claim_demoted(self) -> None:
        docs = [
            {
                "title": "Doc",
                "url": "https://x",
                "text": "This page discusses garden vegetables and tomatoes only.",
            }
        ]
        data = {
            "answer": "A",
            "facts": [
                {
                    "claim": "Kubernetes 1.32 introduces in-place pod resize by default",
                    "source": 1,
                    "confidence": "high",
                }
            ],
            "unknowns": [],
        }
        out = ground_structured_facts(data, docs)
        self.assertEqual(out["facts"][0]["confidence"], "low")
        self.assertEqual(out["facts"][0]["grounding"], "unsupported")
        self.assertTrue(any("lexical support" in u for u in out["unknowns"]))

    def test_render_flags_ungrounded(self) -> None:
        docs = [{"title": "D", "url": "https://x", "text": "unrelated body about cats"}]
        payload = (
            '{"answer":"A","facts":[{"claim":"quantum entanglement drives blockchain '
            'throughput","source":1,"confidence":"high"}],"unknowns":[]}'
        )
        out, _data = _render_structured(payload, docs=docs)
        self.assertIn("ungrounded", out)
        self.assertIn("(low)", out)


class ScrapeRecoveryTests(unittest.TestCase):
    def test_slides_past_failed_urls(self) -> None:
        results = [
            {"title": "Bad1", "url": "https://bad1.example"},
            {"title": "Bad2", "url": "https://bad2.example"},
            {"title": "Good", "url": "https://good.example"},
        ]

        def fake_scrape(url: str, *, respect_robots: bool, no_cache: bool) -> str:
            if "good" in url:
                return "# good markdown"
            return ""

        with patch(
            "web_research.features.research.command._scrape_cached",
            side_effect=fake_scrape,
        ):
            top, mds, attempted = _scrape_with_recovery(
                results, target=1, respect_robots=True, no_cache=True
            )
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0]["url"], "https://good.example")
        self.assertEqual(mds[0], "# good markdown")
        self.assertEqual(attempted, 3)


class SpanishProfileTests(unittest.TestCase):
    @patch("web_research.features.intelligence.engine.is_alive", return_value=False)
    def test_es_troubleshooting(self, _alive) -> None:
        prof = query_profile("falló con excepción traceback en producción")
        self.assertEqual(prof["intent"], "troubleshooting")
        self.assertTrue(prof["needs_recency"])

    @patch("web_research.features.intelligence.engine.is_alive", return_value=False)
    def test_es_comparison(self, _alive) -> None:
        prof = query_profile("comparar fastapi vs django diferencia")
        self.assertEqual(prof["intent"], "comparison")
        self.assertEqual(prof["expected_format"], "table")

    @patch("web_research.features.intelligence.engine.is_alive", return_value=False)
    def test_es_news(self, _alive) -> None:
        prof = query_profile("últimas noticias del lanzamiento de kubernetes")
        self.assertEqual(prof["intent"], "news")
        self.assertTrue(prof["needs_recency"])

    @patch("web_research.features.intelligence.engine.is_alive", return_value=False)
    def test_docs_prefers_python_site(self, _alive) -> None:
        prof = query_profile("python api reference asyncio gather")
        self.assertEqual(prof["intent"], "docs")
        self.assertIn("site:docs.python.org", prof["preferred_sites"])


class SearchEmptyExitTests(unittest.TestCase):
    def setUp(self) -> None:
        _clear_cache()

    @patch("web_research.features.search.command.search_with_escalation")
    def test_empty_search_exits_one(self, mock_esc) -> None:
        mock_esc.return_value = (
            [],
            {
                "engine_requested": "searxng",
                "engine_used": "duckduckgo",
                "engines_tried": ["searxng", "duckduckgo"],
                "escalated": False,
            },
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = wr.main(["search", "no-hits-q", "-n", "2"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
