"""Multi-hop follow-up: next_search_query + single research hop wiring."""

from __future__ import annotations

import io
import json
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from unittest.mock import patch

import web_research as wr
from web_research.features.research.command import (
    _merge_docs,
    _should_follow_up,
)
from web_research.features.synthesis.engine import next_search_query


class NextSearchQueryTests(unittest.TestCase):
    def test_extracts_usable_query(self) -> None:
        self.assertEqual(
            next_search_query({"recommended_next_search": "Fable 5 first extension date"}),
            "Fable 5 first extension date",
        )

    def test_rejects_noise(self) -> None:
        self.assertIsNone(next_search_query({"recommended_next_search": "none"}))
        self.assertIsNone(next_search_query({"recommended_next_search": "n/a"}))
        self.assertIsNone(next_search_query({"recommended_next_search": "ab"}))
        self.assertIsNone(next_search_query(None))
        self.assertIsNone(next_search_query({}))


class ShouldFollowUpTests(unittest.TestCase):
    def test_requires_smart_and_query(self) -> None:
        args = Namespace(smart=True, no_follow_up=False, query="Fable 5")
        docs = [{"url": "https://x", "text": "body"}]
        structured = {"recommended_next_search": "prior Fable 5 extension July 2026"}
        self.assertEqual(
            _should_follow_up(args=args, profile={}, structured=structured, docs=docs),
            "prior Fable 5 extension July 2026",
        )
        args.smart = False
        self.assertIsNone(
            _should_follow_up(args=args, profile={}, structured=structured, docs=docs)
        )
        args.smart = True
        args.no_follow_up = True
        self.assertIsNone(
            _should_follow_up(args=args, profile={}, structured=structured, docs=docs)
        )

    def test_skips_identical_query(self) -> None:
        args = Namespace(smart=True, no_follow_up=False, query="same query here")
        docs = [{"url": "https://x"}]
        structured = {"recommended_next_search": "same query here"}
        self.assertIsNone(
            _should_follow_up(args=args, profile={}, structured=structured, docs=docs)
        )


class MergeDocsTests(unittest.TestCase):
    def test_dedupes_by_url(self) -> None:
        a = [{"url": "https://a", "title": "A"}, {"url": "https://b", "title": "B"}]
        b = [{"url": "https://b", "title": "B2"}, {"url": "https://c", "title": "C"}]
        merged = _merge_docs(a, b)
        self.assertEqual([d["url"] for d in merged], ["https://a", "https://b", "https://c"])
        self.assertEqual(merged[1]["title"], "B")  # primary wins


class FollowUpIntegrationTests(unittest.TestCase):
    @patch("ollama_client.is_alive", return_value=False)
    def test_follow_up_hop_merges_and_resynthesizes(self, _alive) -> None:
        import web_research.features.research.command as research_cmd

        primary = {
            "title": "Primary",
            "url": "https://a.example/p",
            "content": "snippet",
            "engine": "searxng",
            "source": "a",
            "publishedDate": "",
        }
        follow = {
            "title": "Follow",
            "url": "https://b.example/f",
            "content": "more",
            "engine": "searxng",
            "source": "b",
            "publishedDate": "",
        }
        meta = {
            "engine_requested": "searxng",
            "engine_used": "searxng",
            "engines_tried": ["searxng"],
            "escalated": False,
        }
        synth_calls: list[dict] = []

        def fake_synth(query, docs, **kwargs):
            synth_calls.append({"query": query, "n_docs": len(docs), **kwargs})
            if len(docs) == 1:
                return {
                    "answer": "partial [1]",
                    "structured": {
                        "recommended_next_search": "Fable 5 earlier extension date July",
                        "unknowns": ["prior date unknown"],
                    },
                }
            return {
                "answer": "complete timeline [1][2]",
                "structured": {"recommended_next_search": "", "unknowns": []},
            }

        with (
            patch.object(
                research_cmd,
                "search_with_escalation",
                side_effect=[
                    ([primary], meta),
                    ([follow], meta),
                ],
            ),
            patch.object(
                research_cmd,
                "scrape_with_fallback",
                side_effect=["body primary", "body follow"],
            ),
            patch.object(research_cmd, "synthesize_result", side_effect=fake_synth),
            patch.object(research_cmd, "is_alive", return_value=False),
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = wr.main(
                    [
                        "research",
                        "Fable 5 Anthropic",
                        "--smart",
                        "--json",
                        "--scrape",
                        "1",
                        "-n",
                        "2",
                    ]
                )

        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["answer"], "complete timeline [1][2]")
        self.assertTrue(payload["pipeline"]["follow_up"]["fired"])
        self.assertEqual(payload["pipeline"]["follow_up"]["docs_added"], 1)
        self.assertEqual(len(payload["sources"]), 2)
        self.assertEqual(len(synth_calls), 2)
        self.assertEqual(synth_calls[1]["n_docs"], 2)

    @patch("ollama_client.is_alive", return_value=False)
    def test_no_follow_up_flag_skips_hop(self, _alive) -> None:
        import web_research.features.research.command as research_cmd

        primary = {
            "title": "Primary",
            "url": "https://a.example/p",
            "content": "snippet",
            "engine": "searxng",
            "source": "a",
            "publishedDate": "",
        }
        meta = {
            "engine_requested": "searxng",
            "engine_used": "searxng",
            "engines_tried": ["searxng"],
            "escalated": False,
        }
        with (
            patch.object(
                research_cmd, "search_with_escalation", return_value=([primary], meta)
            ) as mock_search,
            patch.object(research_cmd, "scrape_with_fallback", return_value="body"),
            patch.object(
                research_cmd,
                "synthesize_result",
                return_value={
                    "answer": "partial",
                    "structured": {
                        "recommended_next_search": "should not run this query now",
                    },
                },
            ),
            patch.object(research_cmd, "is_alive", return_value=False),
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = wr.main(
                    [
                        "research",
                        "Fable 5",
                        "--smart",
                        "--no-follow-up",
                        "--json",
                        "--scrape",
                        "1",
                    ]
                )
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["pipeline"]["follow_up"]["fired"])
        self.assertEqual(mock_search.call_count, 1)


if __name__ == "__main__":
    unittest.main()
