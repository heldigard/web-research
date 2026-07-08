"""``research`` subcommand: search -> scrape top K -> extract -> cited synthesis."""

# vs-soft-allow  — research command orchestrator. Apparent depth comes from a
# sequential pipeline (search -> rerank -> scrape -> synthesize), not nested
# business logic; splitting would just scatter one linear flow across files.
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from typing import cast

from web_research.features.intelligence.engine import focused_extract, query_profile, search_queries
from web_research.features.ranking.engine import annotate_quality, rerank_results
from web_research.features.read.engine import scrape_with_fallback
from web_research.features.search.engine import search_backends
from web_research.features.synthesis.engine import synthesize
from web_research.shared.cache import get as cache_get
from web_research.shared.cache import set as cache_set
from web_research.shared.cli_helpers import apply_common
from web_research.shared.formatters import fmt_results
from web_research.shared.http import _debug
from web_research.shared.ollama_api import is_alive


def _search_phase(
    args: argparse.Namespace, time_range: str, cache_params: dict, queries: list[str]
) -> list[dict]:
    """Return search results (cache-miss path runs the backend dispatch)."""
    cached = None if args.no_cache else cache_get("research", cache_params)
    if cached:
        _debug("cache", "research hit")
        return cast(list[dict], cached["results"])
    _debug("cache", "research miss")
    results = search_backends(
        args.query, args.n, args.engine, "general", "en", time_range, queries=queries
    )
    if results and not args.no_cache:
        cache_set("research", cache_params, {"results": results})
    return results


def _build_docs(
    top: list[dict], mds: list[str], args: argparse.Namespace, intent: str
) -> list[dict]:
    """Pair scraped markdown with its result, optionally LLM-extracting the relevant part."""
    docs = []
    for r, md in zip(top, mds, strict=True):
        if not md:
            continue
        extracted = focused_extract(md, args.query, intent) if args.smart else md
        docs.append(
            {
                "url": r["url"],
                "title": r["title"],
                "text": md[: args.max_chars],
                "extracted": extracted[: args.max_chars],
            }
        )
    return docs


def mode_research(args: argparse.Namespace) -> int:
    """Research mode: search, scrape, extract, synthesize."""
    apply_common(args)
    profile = query_profile(args.query)
    time_range = args.time or ("week" if profile.get("needs_recency") else "")
    queries = search_queries(args.query, profile) if args.smart else [args.query]
    cache_params = {
        "q": args.query,
        "queries": queries,
        "n": args.n,
        "engine": args.engine,
        "time": time_range,
        "scrape": args.scrape,
        "smart": args.smart,
    }

    results = _search_phase(args, time_range, cache_params, queries)
    if not results:
        print(f"_No results for: {args.query}_", file=sys.stderr)
        return 1

    results = annotate_quality(results)
    if is_alive():
        results = rerank_results(args.query, results)

    k = min(args.scrape, len(results))
    top = results[:k]
    urls = [r["url"] for r in top]
    fetch = partial(scrape_with_fallback, respect_robots=not getattr(args, "no_robots", False))
    with ThreadPoolExecutor(max_workers=min(k, 4) or 1) as ex:
        mds = list(ex.map(fetch, urls))

    docs = _build_docs(top, mds, args, profile.get("intent", "general"))

    source_names = ", ".join(dict.fromkeys(r.get("source", "searxng") for r in top))
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    print(f"# Research: {args.query}\n")
    print(f"_Engine: {source_names} | Scraped: {len(docs)}/{k} | Date: {today}_\n")

    if not docs:
        print("_Could not scrape full content; showing search snippets:_\n")
        print(fmt_results(results))
        return 0

    answer = synthesize(args.query, docs, answer_mode=args.answer, structured=args.smart)
    if answer:
        print(answer.strip())
        print("\n---\n## Sources")
        _print_source_list(docs)
        return 0

    _print_full_docs(docs)
    return 0


def _print_source_list(docs: list[dict]) -> None:
    """Print the cited-sources footer ([n] title - url)."""
    for i, d in enumerate(docs, 1):
        print(f"[{i}] {d['title']} - {d['url']}")


def _print_full_docs(docs: list[dict]) -> None:
    """Fallback when synthesis produced no answer: dump each doc's full text."""
    for i, d in enumerate(docs, 1):
        print(f"## [{i}] {d['title']}\n{d['url']}\n\n{d['text']}\n")
