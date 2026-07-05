"""Ranking: semantic rerank, source-quality scoring, deduplication."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from web_research.shared.ollama_api import cosine, embed, is_alive


def source_quality_score(url: str, title: str, content: str) -> float:
    """Score a source by domain authority and content specificity.

    Returns a value between 0 and 1.
    """
    if not url:
        return 0.0
    domain = urlparse(url).netloc.lower()
    authority_domains = {
        "docs.python.org",
        "developer.mozilla.org",
        "docs.github.com",
        "learn.microsoft.com",
        "cloud.google.com",
        "aws.amazon.com",
        "docs.aws.amazon.com",
        "fastapi.tiangolo.com",
        "flask.palletsprojects.com",
        "django.readthedocs.io",
        "docs.angular.io",
        "react.dev",
        "docs.spring.io",
        "go.dev",
        "rust-lang.org",
        "doc.rust-lang.org",
        "pkg.go.dev",
        "pypi.org",
        "npmjs.com",
        "stackoverflow.com",
        "github.com",
        "git-scm.com",
        "openai.com",
        "platform.openai.com",
        "developers.openai.com",
        "anthropic.com",
        "claude.ai",
    }
    score = 0.0
    if any(d in domain for d in authority_domains):
        score += 0.4
    if "blog" in domain or "medium.com" in domain:
        score += 0.1
    if len(content) >= 80:
        score += 0.2
    if title and query_word_overlap(title, content) > 0.3:
        score += 0.2
    if "/docs/" in url or "reference" in url.lower():
        score += 0.2
    return min(score, 1.0)


def query_word_overlap(title: str, content: str) -> float:
    """Simple token overlap heuristic for relevance."""
    title_words = set(title.lower().split())
    content_words = set(content.lower().split())
    if not title_words:
        return 0.0
    overlap = title_words & content_words
    return len(overlap) / len(title_words)


def rerank_results(
    query: str,
    results: list[dict],
    sim_cutoff: float = 0.93,
    quality_weight: float = 0.3,
) -> list[dict]:
    """Order by composite score (semantic similarity + source quality); drop near-duplicates.

    Embeds are parallelized (ThreadPoolExecutor) instead of sequential N+1 calls.
    ``_quality`` is reused if already present (set by ``annotate_quality``).
    """
    if not results:
        return results
    qv = embed(query) if is_alive() else None
    texts = [r["title"] + ". " + r["content"][:300] for r in results]
    if qv:
        with ThreadPoolExecutor(max_workers=min(len(results), 4) or 1) as ex:
            vecs = list(ex.map(embed, texts))
    else:
        vecs = [None] * len(results)
    for r, v in zip(results, vecs, strict=True):
        sim = cosine(qv, v) if qv and v else 0.0
        quality = r.get("_quality")
        if quality is None:
            quality = source_quality_score(r.get("url", ""), r["title"], r["content"])
        r["_score"] = (1 - quality_weight) * sim + quality_weight * quality
        r["_v"] = v

    results.sort(key=lambda r: r["_score"], reverse=True)

    kept: list[dict] = []
    for r in results:
        if not any(cosine(r["_v"], k["_v"]) >= sim_cutoff for k in kept if r["_v"] and k.get("_v")):
            kept.append(r)

    for r in results:
        r.pop("_v", None)
        r.pop("_score", None)
    return kept


def annotate_quality(results: list[dict]) -> list[dict]:
    """Attach a ``_quality`` score to each result (domain authority + specificity)."""
    for r in results:
        r["_quality"] = source_quality_score(
            r.get("url", ""), r.get("title", ""), r.get("content", "")
        )
    return results
