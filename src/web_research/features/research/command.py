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
from web_research.features.synthesis.engine import next_search_query, synthesize_result
from web_research.shared.cache import get as cache_get
from web_research.shared.cache import set as cache_set
from web_research.shared.cli_helpers import apply_common
from web_research.shared.config import SCHEMA_VERSION
from web_research.shared.formatters import fmt_results
from web_research.shared.http import _debug, warn
from web_research.shared.ollama_api import is_alive

# Single follow-up hop budget (keeps multi-hop cheap for agent loops).
_FOLLOWUP_SCRAPE = 2
_FOLLOWUP_SEARCH_N = 6


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


def _rank_results(query: str, results: list[dict], needs_fresh: bool) -> list[dict]:
    """Annotate + recency-aware rerank (shared by primary and follow-up hops)."""
    results = annotate_quality(results)
    recency_weight = 0.28 if needs_fresh else 0.12
    if is_alive() or needs_fresh:
        results = rerank_results(query, results, recency_weight=recency_weight)
    return results


def _prepare_scrape_order(results: list[dict], k: int, needs_fresh: bool) -> list[dict]:
    """Reorder so recency diversity leads the scrape window when news-sensitive."""
    if k <= 0 or not results:
        return results
    scrape_pool = select_with_recency_diversity(results, k) if needs_fresh else results[:k]
    if needs_fresh and scrape_pool:
        pool_urls = {r.get("url") for r in scrape_pool}
        rest = [r for r in results if r.get("url") not in pool_urls]
        return scrape_pool + rest
    return results


def _should_follow_up(
    *,
    args: argparse.Namespace,
    profile: dict,
    structured: dict | None,
    docs: list[dict],
) -> str | None:
    """Decide whether to run one extra search hop; return the follow-up query.

    Enabled by default for ``--smart`` unless ``--no-follow-up``. Fires when
    structured synthesis emits a concrete ``recommended_next_search`` and we
    already have at least one scraped doc (otherwise a hop would not help).
    """
    if not docs:
        return None
    if not getattr(args, "smart", False):
        return None
    if getattr(args, "no_follow_up", False):
        return None
    nxt = next_search_query(structured)
    if not nxt:
        return None
    # Avoid re-running essentially the same query.
    if nxt.strip().lower() == str(args.query).strip().lower():
        return None
    return nxt


def _merge_docs(primary: list[dict], extra: list[dict]) -> list[dict]:
    """Append follow-up docs, skipping URL duplicates (primary wins order)."""
    seen = {str(d.get("url", "")) for d in primary}
    out = list(primary)
    for d in extra:
        url = str(d.get("url", ""))
        if url and url in seen:
            continue
        if url:
            seen.add(url)
        out.append(d)
    return out


def _follow_up_hop(
    *,
    follow_query: str,
    args: argparse.Namespace,
    profile: dict,
    time_range: str,
    seen_urls: set[str],
    needs_fresh: bool,
) -> tuple[list[dict], list[dict], dict]:
    """One bounded search+scrape hop for a follow-up query.

    Returns ``(new_results_for_display, new_docs, hop_meta)``.
    """
    hop_meta: dict = {
        "query": follow_query,
        "fired": True,
        "docs_added": 0,
        "search": {},
        "scraping": {},
    }
    results, search_meta = search_with_escalation(
        follow_query,
        _FOLLOWUP_SEARCH_N,
        args.engine,
        "general",
        "en",
        time_range,
        queries=[follow_query],
    )
    hop_meta["search"] = search_meta
    if not results:
        hop_meta["fired"] = True
        hop_meta["reason"] = "no_results"
        return [], [], hop_meta

    # Drop URLs already scraped in the primary hop.
    fresh = [r for r in results if str(r.get("url", "")) not in seen_urls]
    if not fresh:
        hop_meta["reason"] = "all_urls_seen"
        return [], [], hop_meta

    fresh = _rank_results(follow_query, fresh, needs_fresh)
    k = min(_FOLLOWUP_SCRAPE, len(fresh))
    ordered = _prepare_scrape_order(fresh, k, needs_fresh)
    top, mds, attempted = _scrape_with_recovery(
        ordered,
        k,
        respect_robots=not getattr(args, "no_robots", False),
        no_cache=args.no_cache,
    )
    docs = _build_docs(top, mds, args, profile.get("intent", "general"))
    hop_meta["scraping"] = {
        "requested": k,
        "attempted": attempted,
        "succeeded": len(docs),
    }
    hop_meta["docs_added"] = len(docs)
    warn("research", f"follow-up hop: {follow_query!r} → +{len(docs)} docs")
    return fresh, docs, hop_meta


def mode_research(args: argparse.Namespace) -> int:
    """Research mode: search, scrape, extract, synthesize (+ optional 1 follow-up)."""
    apply_common(args)
    profile = query_profile(args.query)
    # Month (not week): news chains often span 2–3 weeks (announce → extend).
    # A week filter can drop the earlier chapter that synthesis needs for a
    # correct timeline while still keeping results reasonably fresh.
    time_range = args.time or ("month" if profile.get("needs_recency") else "")
    queries = search_queries(args.query, profile) if args.smart else [args.query]
    follow_up_enabled = bool(args.smart) and not getattr(args, "no_follow_up", False)
    cache_params = {
        "q": args.query,
        "queries": queries,
        "n": args.n,
        "engine": args.engine,
        "time": time_range,
        "scrape": args.scrape,
        "smart": args.smart,
        "code_analyze": getattr(args, "code_analyze", False),
        "follow_up": follow_up_enabled,
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

    needs_fresh = bool(profile.get("needs_recency") or profile.get("intent") == "news")
    results = _rank_results(args.query, results, needs_fresh)

    k = min(args.scrape, len(results))
    results = _prepare_scrape_order(results, k, needs_fresh)

    top, mds, scrape_attempted = _scrape_with_recovery(
        results,
        k,
        respect_robots=not getattr(args, "no_robots", False),
        no_cache=args.no_cache,
    )
    docs = _build_docs(top, mds, args, profile.get("intent", "general"))
    display_results = list(results)

    synth = (
        synthesize_result(
            args.query,
            docs,
            answer_mode=args.answer,
            structured=args.smart,
            no_cache=args.no_cache,
        )
        if docs
        else {"answer": None, "structured": None}
    )
    answer = synth.get("answer")
    structured = synth.get("structured")

    follow_meta: dict = {"fired": False}
    follow_q = _should_follow_up(args=args, profile=profile, structured=structured, docs=docs)
    if follow_q:
        seen = {str(d.get("url", "")) for d in docs}
        _extra_results, extra_docs, follow_meta = _follow_up_hop(
            follow_query=follow_q,
            args=args,
            profile=profile,
            time_range=time_range,
            seen_urls=seen,
            needs_fresh=needs_fresh,
        )
        if extra_docs:
            docs = _merge_docs(docs, extra_docs)
            # Re-synthesize over the expanded evidence (still one extra synth).
            synth = synthesize_result(
                args.query,
                docs,
                answer_mode=args.answer,
                structured=args.smart,
                no_cache=True,  # evidence set changed
            )
            answer = synth.get("answer")
            structured = synth.get("structured")
            follow_meta["re_synthesized"] = True
        # Keep follow-up hits available for snippet fallback display.
        if _extra_results:
            display_results = _merge_docs(
                [{"url": r.get("url"), "title": r.get("title"), **r} for r in display_results],
                _extra_results,
            )

    source_names = ", ".join(
        dict.fromkeys(str(d.get("source") or d.get("engine") or "searxng") for d in docs)
    ) or (search_meta.get("engine_used") or args.engine)
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    pipeline = {
        "search": search_meta,
        "scraping": {
            "requested": k,
            "attempted": scrape_attempted,
            "succeeded": len(docs) - int(follow_meta.get("docs_added") or 0),
            "recovered": scrape_attempted > k
            and (len(docs) - int(follow_meta.get("docs_added") or 0)) > 0,
        },
        "follow_up": follow_meta,
    }
    # Report total scraped including follow-up.
    pipeline["scraping"]["total_docs"] = len(docs)

    if args.json:
        _print_json_research(
            args=args,
            profile=profile,
            top=docs if docs else display_results[: args.n],
            docs=docs,
            answer=answer,
            cache_hit=cache_hit,
            requested_scrapes=k,
            pipeline=pipeline,
            structured=structured,
        )
        return 0

    esc = ""
    if search_meta.get("escalated"):
        esc = f" · escalated {search_meta.get('engine_requested')}→{search_meta.get('engine_used')}"
    hop = ""
    if follow_meta.get("docs_added"):
        hop = f" · follow-up +{follow_meta['docs_added']}"
    print(f"# Research: {args.query}\n")
    print(
        f"_Engine: {source_names}{esc} | Scraped: {len(docs)}/{k}"
        f" (tried {scrape_attempted}){hop} | Date: {today}_\n"
    )

    if not docs:
        print("_Could not scrape full content; showing search snippets:_\n")
        print(fmt_results(display_results))
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
    structured: dict | None = None,
) -> None:
    """Emit a stable evidence envelope for agents and cross-CLI orchestration."""
    # Prefer scraped docs as the source list (includes follow-up); fall back to
    # search hits when nothing was scraped.
    rows = docs if docs else top
    sources = []
    evidence = []
    for index, row in enumerate(rows, 1):
        url = str(row.get("url", ""))
        scraped = bool(row.get("extracted") or row.get("text")) if docs else False
        if docs:
            scraped = True
        sources.append(
            {
                "index": index,
                "title": row.get("title", ""),
                "url": url,
                "engine": row.get("engine", ""),
                "source": row.get("source", ""),
                "published_date": row.get("publishedDate", ""),
                "scraped": scraped if docs else False,
            }
        )
        evidence.append(
            {
                "source": index,
                "text": (row.get("extracted") or row.get("text") or row.get("content") or ""),
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
    if structured is not None:
        # Compact agent-facing fields only (full rendered answer is above).
        payload["structured"] = {
            "unknowns": structured.get("unknowns") if isinstance(structured, dict) else None,
            "recommended_next_search": (
                structured.get("recommended_next_search") if isinstance(structured, dict) else None
            ),
            "facts_count": (
                len(structured.get("facts") or []) if isinstance(structured, dict) else 0
            ),
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
