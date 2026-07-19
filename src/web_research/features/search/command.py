"""``search`` subcommand: standard or smart search over the configured backends."""

from __future__ import annotations

import argparse
import json
from typing import cast

from web_research.features.intelligence.engine import query_profile, search_queries
from web_research.features.ranking.engine import annotate_quality, rerank_results
from web_research.features.search.engine import search_with_escalation
from web_research.features.synthesis.engine import synthesize
from web_research.shared.cache import get as cache_get
from web_research.shared.cache import set as cache_set
from web_research.shared.cli_helpers import apply_common
from web_research.shared.formatters import fmt_results, fmt_smart_results
from web_research.shared.http import _debug
from web_research.shared.results import snippets_to_docs, strip_internal

_EMPTY_SEARCH_META: dict = {
    "engine_requested": "",
    "engine_used": "",
    "engines_tried": [],
    "escalated": False,
}


def _recency_weight(profile: dict | None, *, smart: bool, rerank: bool) -> float:
    """Stronger recency mix-in for news/freshness-sensitive queries."""
    if profile and (profile.get("needs_recency") or profile.get("intent") == "news"):
        return 0.28
    if smart or rerank:
        # Mild bias: prefer newer near-ties without drowning evergreen docs.
        return 0.12
    return 0.0


def _run_pipeline(
    args: argparse.Namespace,
    cache_params: dict,
    queries: list[str] | None = None,
    profile: dict | None = None,
) -> tuple[list[dict], dict]:
    """Cache-miss path: escalate engines, annotate, rerank, trim, cache."""
    results, meta = search_with_escalation(
        args.query, args.n, args.engine, args.cat, args.lang, args.time, queries=queries
    )
    if args.smart:
        results = annotate_quality(results)
    if args.rerank or args.smart:
        results = rerank_results(
            args.query,
            results,
            recency_weight=_recency_weight(profile, smart=args.smart, rerank=args.rerank),
        )
    results = results[: args.n]
    if results and not args.no_cache:
        cache_set("search", cache_params, {"results": results, "meta": meta})
    return results, meta


def mode_search(args: argparse.Namespace) -> int:
    """Search mode: standard or smart."""
    apply_common(args)
    # Profile even on --rerank (no --smart) so recency weight can fire for
    # news-shaped queries; cheap when Ollama is down (rule-based only).
    profile = query_profile(args.query) if (args.smart or args.rerank) else None
    queries = search_queries(args.query, profile) if args.smart else [args.query]
    cache_params = {
        "q": args.query,
        "queries": queries,
        "n": args.n,
        "engine": args.engine,
        "cat": args.cat,
        "lang": args.lang,
        "time": args.time,
        "smart": args.smart,
        "rerank": args.rerank,
    }
    cached = None if args.no_cache else cache_get("search", cache_params)
    if cached:
        _debug("cache", "search hit")
        results = cast(list[dict], cached["results"])
        meta = cast(dict, cached.get("meta") or {**_EMPTY_SEARCH_META, "engine_used": args.engine})
    else:
        _debug("cache", "search miss")
        results, meta = _run_pipeline(args, cache_params, queries, profile=profile)

    if args.json:
        # Stable contract: bare result list (controllers/skills parse this).
        # Escalation provenance is only in human output + research --json.
        print(json.dumps(strip_internal(results), ensure_ascii=False, indent=2))
        return 0 if results else 1

    _emit_search_output(args, results, profile, meta)
    return 0 if results else 1


def _emit_search_output(
    args: argparse.Namespace,
    results: list[dict],
    profile: dict | None,
    meta: dict | None = None,
) -> None:
    """Print smart (profile + optional summary) or standard result listing."""
    if not args.smart:
        print(f"# Search: {args.query}\n")
        print(fmt_results(results))
        srcs = ", ".join(dict.fromkeys(r.get("source", "searxng") for r in results)) or "SearXNG"
        extra = " + Ollama rerank" if (args.rerank or args.smart) else ""
        esc = ""
        if meta and meta.get("escalated"):
            esc = f" · escalated from {meta.get('engine_requested')}"
        print(f"\n_({len(results)} results via {srcs}{extra}{esc})_")
        return

    summary = None
    if args.summary and results:
        summary = synthesize(args.query, snippets_to_docs(results), structured=True)
    print(fmt_smart_results(results, args.query, profile=profile, summary=summary, meta=meta))
