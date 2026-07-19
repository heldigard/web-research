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
from web_research.features.ranking.engine import (
    annotate_quality,
    rerank_results,
    select_with_recency_diversity,
)
from web_research.features.read.engine import scrape_with_fallback
from web_research.features.search.engine import search_with_escalation
from web_research.features.synthesis.engine import synthesize
from web_research.shared.cache import get as cache_get
from web_research.shared.cache import set as cache_set
from web_research.shared.cli_helpers import apply_common
from web_research.shared.config import SCHEMA_VERSION
from web_research.shared.formatters import fmt_results
from web_research.shared.http import _debug, warn
from web_research.shared.ollama_api import is_alive


def _search_phase(
    args: argparse.Namespace, time_range: str, cache_params: dict, queries: list[str]
) -> tuple[list[dict], bool, dict]:
    """Return search results + escalation meta (cache-miss runs the cascade)."""
    cached = None if args.no_cache else cache_get("research", cache_params)
    if cached:
        _debug("cache", "research hit")
        meta = cast(
            dict,
            cached.get("meta")
            or {
                "engine_requested": args.engine,
                "engine_used": args.engine,
                "engines_tried": [args.engine],
                "escalated": False,
            },
        )
        return cast(list[dict], cached["results"]), True, meta
    _debug("cache", "research miss")
    results, meta = search_with_escalation(
        args.query, args.n, args.engine, "general", "en", time_range, queries=queries
    )
    if results and not args.no_cache:
        cache_set("research", cache_params, {"results": results, "meta": meta})
    return results, False, meta


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


def _scrape_with_recovery(
    results: list[dict],
    target: int,
    *,
    respect_robots: bool,
    no_cache: bool,
) -> tuple[list[dict], list[str], int]:
    """Scrape until ``target`` pages succeed or results are exhausted.

    Controllers often hit soft-404s / anti-bot on the top-ranked hits. Sliding
    the scrape window past failed URLs recovers evidence without a second
    full research call. Returns ``(scraped_results, markdowns, attempted)``.
    """
    if target <= 0 or not results:
        return [], [], 0

    fetch = partial(_scrape_cached, respect_robots=respect_robots, no_cache=no_cache)
    kept_results: list[dict] = []
    kept_mds: list[str] = []
    cursor = 0
    attempted = 0
    while len(kept_results) < target and cursor < len(results):
        need = target - len(kept_results)
        batch = results[cursor : cursor + need]
        cursor += len(batch)
        attempted += len(batch)
        with ThreadPoolExecutor(max_workers=min(len(batch), 4) or 1) as ex:
            mds = list(ex.map(fetch, [r["url"] for r in batch]))
        for r, md in zip(batch, mds, strict=True):
            if md:
                kept_results.append(r)
                kept_mds.append(md)
            if len(kept_results) >= target:
                break
    if attempted > target and kept_results:
        warn(
            "research",
            f"scrape recovery: got {len(kept_results)}/{target} after "
            f"trying {attempted} of {len(results)} results",
        )
    return kept_results, kept_mds, attempted


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
    # Month (not week): news chains often span 2–3 weeks (announce → extend).
    # A week filter can drop the earlier chapter that synthesis needs for a
    # correct timeline while still keeping results reasonably fresh.
    time_range = args.time or ("month" if profile.get("needs_recency") else "")
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

    results, cache_hit, search_meta = _search_phase(args, time_range, cache_params, queries)
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
                        "pipeline": {"search": search_meta},
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
    needs_fresh = bool(profile.get("needs_recency") or profile.get("intent") == "news")
    # Always mild recency; stronger for news so a 6-day-newer update beats the
    # original "extends to July 12" headline when embeddings look identical.
    recency_weight = 0.28 if needs_fresh else 0.12
    if is_alive() or needs_fresh:
        # Even without Ollama embeds, recency reordering still helps news.
        results = rerank_results(args.query, results, recency_weight=recency_weight)

    k = min(args.scrape, len(results))
    # For news, force the freshest dated hit into the scrape set even if
    # pure top-k score preferred an older near-duplicate.
    scrape_pool = select_with_recency_diversity(results, k) if needs_fresh else results[:k]
    # Preserve ranking order for the rest of the pipeline, but ensure pool
    # members lead so recovery still slides over the full result list.
    if needs_fresh and scrape_pool:
        pool_urls = {r.get("url") for r in scrape_pool}
        rest = [r for r in results if r.get("url") not in pool_urls]
        results = scrape_pool + rest

    top, mds, scrape_attempted = _scrape_with_recovery(
        results,
        k,
        respect_robots=not getattr(args, "no_robots", False),
        no_cache=args.no_cache,
    )
    docs = _build_docs(top, mds, args, profile.get("intent", "general"))

    source_names = ", ".join(dict.fromkeys(r.get("source", "searxng") for r in top)) or (
        search_meta.get("engine_used") or args.engine
    )
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

    pipeline = {
        "search": search_meta,
        "scraping": {
            "requested": k,
            "attempted": scrape_attempted,
            "succeeded": len(docs),
            "recovered": scrape_attempted > k and len(docs) > 0,
        },
    }

    if args.json:
        _print_json_research(
            args=args,
            profile=profile,
            top=top or results[: args.n],
            docs=docs,
            answer=answer,
            cache_hit=cache_hit,
            requested_scrapes=k,
            pipeline=pipeline,
        )
        return 0

    esc = ""
    if search_meta.get("escalated"):
        esc = f" · escalated {search_meta.get('engine_requested')}→{search_meta.get('engine_used')}"
    print(f"# Research: {args.query}\n")
    print(
        f"_Engine: {source_names}{esc} | Scraped: {len(docs)}/{k}"
        f" (tried {scrape_attempted}) | Date: {today}_\n"
    )

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
    pipeline: dict | None = None,
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
    scraping = (pipeline or {}).get("scraping") or {
        "requested": requested_scrapes,
        "succeeded": len(docs),
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "ok" if answer else "partial",
        "query": args.query,
        "generated_at": datetime.now(UTC).isoformat(),
        "cache_hit": cache_hit,
        "profile": profile,
        "pipeline": pipeline or {},
        "scraping": scraping,
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
