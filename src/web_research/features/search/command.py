"""``search`` subcommand: standard or smart search over the configured backends."""

from __future__ import annotations

import argparse
import json
from typing import cast

from web_research.features.intelligence.engine import query_profile, search_queries
from web_research.features.ranking.engine import annotate_quality, rerank_results
from web_research.features.search.engine import search_backends
from web_research.features.synthesis.engine import synthesize
from web_research.shared.cache import get as cache_get
from web_research.shared.cache import set as cache_set
from web_research.shared.cli_helpers import apply_common
from web_research.shared.formatters import fmt_results, fmt_smart_results
from web_research.shared.http import _debug
from web_research.shared.results import snippets_to_docs, strip_internal


def _run_pipeline(
    args: argparse.Namespace, cache_params: dict, queries: list[str] | None = None
) -> list[dict]:
    """Cache-miss path: dispatch to backends, annotate, rerank, trim, cache."""
    results = search_backends(
        args.query, args.n, args.engine, args.cat, args.lang, args.time, queries=queries
    )
    if args.smart:
        results = annotate_quality(results)
    if args.rerank or args.smart:
        results = rerank_results(args.query, results)
    results = results[: args.n]
    if results and not args.no_cache:
        cache_set("search", cache_params, {"results": results})
    return results


def mode_search(args: argparse.Namespace) -> int:
    """Search mode: standard or smart."""
    apply_common(args)
    profile = query_profile(args.query) if args.smart else None
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
        "summary": args.summary,
    }
    cached = None if args.no_cache else cache_get("search", cache_params)
    if cached:
        _debug("cache", "search hit")
        results = cast(list[dict], cached["results"])
    else:
        _debug("cache", "search miss")
        results = _run_pipeline(args, cache_params, queries)

    if args.json:
        print(json.dumps(strip_internal(results), ensure_ascii=False, indent=2))
        return 0

    _emit_search_output(args, results, profile)
    return 0


def _emit_search_output(
    args: argparse.Namespace, results: list[dict], profile: dict | None
) -> None:
    """Print smart (profile + optional summary) or standard result listing."""
    if not args.smart:
        print(f"# Search: {args.query}\n")
        print(fmt_results(results))
        srcs = ", ".join(dict.fromkeys(r.get("source", "searxng") for r in results)) or "SearXNG"
        extra = " + Ollama rerank" if (args.rerank or args.smart) else ""
        print(f"\n_({len(results)} results via {srcs}{extra})_")
        return

    summary = None
    if args.summary and results:
        summary = synthesize(args.query, snippets_to_docs(results), structured=True)
    print(fmt_smart_results(results, args.query, profile=profile, summary=summary))
