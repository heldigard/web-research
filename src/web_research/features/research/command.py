"""``research`` subcommand: search -> scrape top K -> extract -> cited synthesis."""

# vs-soft-allow  — research command orchestrator. Apparent depth comes from a
# sequential pipeline (search -> rerank -> scrape -> synthesize), not nested
# business logic; splitting would just scatter one linear flow across files.
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from typing import cast

from web_research.features.intelligence.code_analyze import enrich_with_local_code
from web_research.features.intelligence.engine import focused_extract, query_profile, search_queries
from web_research.features.ranking.engine import annotate_quality, rerank_results
from web_research.features.read.engine import scrape_with_fallback
from web_research.features.search.engine import search_backends
from web_research.features.synthesis.engine import synthesize
from web_research.shared.cache import get as cache_get
from web_research.shared.cache import set as cache_set
from web_research.shared.cli_helpers import apply_common
from web_research.shared.config import SCHEMA_VERSION
from web_research.shared.formatters import fmt_results
from web_research.shared.http import _debug
from web_research.shared.ollama_api import is_alive


def _search_phase(
    args: argparse.Namespace, time_range: str, cache_params: dict, queries: list[str]
) -> tuple[list[dict], bool]:
    """Return search results (cache-miss path runs the backend dispatch)."""
    cached = None if args.no_cache else cache_get("research", cache_params)
    if cached:
        _debug("cache", "research hit")
        return cast(list[dict], cached["results"]), True
    _debug("cache", "research miss")
    results = search_backends(
        args.query, args.n, args.engine, "general", "en", time_range, queries=queries
    )
    if results and not args.no_cache:
        cache_set("research", cache_params, {"results": results})
    return results, False


def _scrape_cached(url: str, *, respect_robots: bool, no_cache: bool) -> str:
    """Scrape one URL with on-disk caching (mirrors the ``read`` command).

    Cache prefix ``scrape`` is keyed on ``url`` + ``respect_robots`` so a
    re-run of the same research hits the cache instead of re-scraping — the
    scrape phase is the most expensive step (Firecrawl JS render, paid Z.AI
    reader API). Empty results are not cached: a failed fetch may simply be
    a transient outage, and re-running should retry.
    """
    cache_params = {"url": url, "respect_robots": respect_robots}
    cached = None if no_cache else cache_get("scrape", cache_params)
    if cached:
        _debug("cache", f"scrape hit {url}")
        return cast(str, cached["markdown"])
    md = scrape_with_fallback(url, respect_robots=respect_robots)
    if md and not no_cache:
        cache_set("scrape", cache_params, {"markdown": md})
    return md


def _build_docs(
    top: list[dict], mds: list[str], args: argparse.Namespace, intent: str
) -> list[dict]:
    """Pair scraped markdown with its result, optionally LLM-extracting the relevant part."""
    code_section = ""
    if getattr(args, "code_analyze", False):
        code_section = enrich_with_local_code(args.query)
    docs = []
    for r, md in zip(top, mds, strict=True):
        if not md:
            continue
        extracted = focused_extract(md, args.query, intent) if args.smart else md
        if code_section:
            extracted = code_section + extracted
        docs.append(
            {
                "url": r["url"],
                "title": r["title"],
                "text": md[: args.max_chars],
                "extracted": extracted[: args.max_chars],
                "engine": r.get("engine", ""),
                "source": r.get("source", ""),
                "publishedDate": r.get("publishedDate", ""),
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
        "code_analyze": getattr(args, "code_analyze", False),
    }

    results, cache_hit = _search_phase(args, time_range, cache_params, queries)
    if not results:
        if args.json:
            print(
                json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "status": "no_results",
                        "query": args.query,
                        "generated_at": datetime.now(UTC).isoformat(),
                        "cache_hit": cache_hit,
                        "sources": [],
                        "evidence": [],
                        "answer": None,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        print(f"_No results for: {args.query}_", file=sys.stderr)
        return 1

    results = annotate_quality(results)
    if is_alive():
        results = rerank_results(args.query, results)

    k = min(args.scrape, len(results))
    top = results[:k]
    urls = [r["url"] for r in top]
    fetch = partial(
        _scrape_cached,
        respect_robots=not getattr(args, "no_robots", False),
        no_cache=args.no_cache,
    )
    with ThreadPoolExecutor(max_workers=min(k, 4) or 1) as ex:
        mds = list(ex.map(fetch, urls))

    docs = _build_docs(top, mds, args, profile.get("intent", "general"))

    source_names = ", ".join(dict.fromkeys(r.get("source", "searxng") for r in top))
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    answer = (
        synthesize(
            args.query,
            docs,
            answer_mode=args.answer,
            structured=args.smart,
            no_cache=args.no_cache,
        )
        if docs
        else None
    )

    if args.json:
        _print_json_research(
            args=args,
            profile=profile,
            top=top or results[: args.n],
            docs=docs,
            answer=answer,
            cache_hit=cache_hit,
            requested_scrapes=k,
        )
        return 0

    print(f"# Research: {args.query}\n")
    print(f"_Engine: {source_names} | Scraped: {len(docs)}/{k} | Date: {today}_\n")

    if not docs:
        print("_Could not scrape full content; showing search snippets:_\n")
        print(fmt_results(results))
        return 0

    if answer:
        print(answer.strip())
        print("\n---\n## Sources")
        _print_source_list(docs)
        return 0

    _print_full_docs(docs)
    return 0


def _print_json_research(
    *,
    args: argparse.Namespace,
    profile: dict,
    top: list[dict],
    docs: list[dict],
    answer: str | None,
    cache_hit: bool,
    requested_scrapes: int,
) -> None:
    """Emit a stable evidence envelope for agents and cross-CLI orchestration."""
    docs_by_url = {str(doc.get("url", "")): doc for doc in docs}
    sources = []
    evidence = []
    for index, result in enumerate(top, 1):
        url = str(result.get("url", ""))
        doc = docs_by_url.get(url)
        sources.append(
            {
                "index": index,
                "title": result.get("title", ""),
                "url": url,
                "engine": result.get("engine", ""),
                "source": result.get("source", ""),
                "published_date": result.get("publishedDate", ""),
                "scraped": doc is not None,
            }
        )
        evidence.append(
            {
                "source": index,
                "text": (
                    doc.get("extracted", "") if doc is not None else result.get("content", "")
                ),
            }
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "ok" if answer else "partial",
        "query": args.query,
        "generated_at": datetime.now(UTC).isoformat(),
        "cache_hit": cache_hit,
        "profile": profile,
        "scraping": {"requested": requested_scrapes, "succeeded": len(docs)},
        "answer": answer.strip() if answer else None,
        "sources": sources,
        "evidence": evidence,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _print_source_list(docs: list[dict]) -> None:
    """Print the cited-sources footer ([n] title - url)."""
    for i, d in enumerate(docs, 1):
        print(f"[{i}] {d['title']} - {d['url']}")


def _print_full_docs(docs: list[dict]) -> None:
    """Fallback when synthesis produced no answer: dump each doc's full text."""
    for i, d in enumerate(docs, 1):
        print(f"## [{i}] {d['title']}\n{d['url']}\n\n{d['text']}\n")
