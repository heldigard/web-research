"""Ranking: semantic rerank, source-quality scoring, deduplication."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files  # nosemgrep: python37-compatibility-importlib2
from urllib.parse import urlparse

from web_research.shared.ollama_api import cosine, embed, is_alive

from . import tei_rerank

# A small English stopword set — enough to stop "the/for/how" from dominating
# the title↔content overlap signal. Kept inline (not a data file) because it is
# a fixed linguistic constant, not a user-editable list like authority domains.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "by",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "as",
        "at",
        "from",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "how",
        "what",
        "when",
        "where",
        "why",
        "which",
        "who",
        "do",
        "does",
        "did",
        "can",
        "your",
        "you",
        "vs",
        "versus",
    }
)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    """Lowercase, strip punctuation, drop stopwords + single chars.

    Replaces the old ``set(text.lower().split())`` which kept punctuation
    tokens and stopwords, diluting the overlap signal (``"rust?"`` and
    ``"rust"`` counted as different tokens).
    """
    return {
        tok for tok in _WORD_RE.findall(text.lower()) if len(tok) >= 2 and tok not in _STOPWORDS
    }


def _load_authority_domains() -> frozenset[str]:
    """Load authority domains from the packaged data file (cached on the function).

    Falls back to an empty set if the resource is missing (e.g. an exotic
    install layout) so the score degrades gracefully instead of crashing.
    """
    cached = getattr(_load_authority_domains, "_cache", None)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    try:
        raw = (
            files("web_research.features.ranking.data")
            .joinpath("authority_domains.txt")
            .read_text(encoding="utf-8")
        )
        domains = frozenset(
            line.strip().lower()
            for line in raw.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    except Exception:  # noqa: BLE001 — resource missing; degrade, don't crash
        domains = frozenset()
    _load_authority_domains._cache = domains  # type: ignore[attr-defined]
    return domains


def source_quality_score(url: str, title: str, content: str) -> float:
    """Score a source by domain authority and content specificity.

    Returns a value between 0 and 1.
    """
    if not url:
        return 0.0
    domain = urlparse(url).netloc.lower()
    authority_domains = _load_authority_domains()
    score = 0.0
    if any(domain == d or domain.endswith("." + d) for d in authority_domains):
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
    """Token-overlap relevance heuristic (punctuation- and stopword-aware)."""
    title_words = _tokenize(title)
    content_words = _tokenize(content)
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

    # Optional stage-2: a TEI cross-encoder re-orders the survivors. Disabled
    # (TEI_RERANK_URL unset) or unreachable -> no-op, bi-encoder order stands.
    kept = _maybe_tei_rerank(query, kept)

    for r in results:
        r.pop("_v", None)
        r.pop("_score", None)
    return kept


def _maybe_tei_rerank(query: str, kept: list[dict]) -> list[dict]:
    """Apply TEI cross-encoder rerank to ``kept`` when enabled; else pass-through.

    TEI scores ``(query, doc)`` pairs jointly and returns ``[{index, score}]``
    over the same list order it received. Docs it did not score are appended at
    the end in their prior bi-encoder order so none are dropped.
    """
    if len(kept) <= 1 or not tei_rerank.tei_enabled():
        return kept
    texts = [r["title"] + ". " + r["content"][:300] for r in kept]
    scored = tei_rerank.rerank(query, texts)
    if not scored:
        return kept
    returned = {idx for idx, _ in scored}
    ordered = [kept[idx] for idx, _ in scored if 0 <= idx < len(kept)]
    for idx, r in enumerate(kept):
        if idx not in returned:
            ordered.append(r)
    return ordered


def annotate_quality(results: list[dict]) -> list[dict]:
    """Attach a ``_quality`` score to each result (domain authority + specificity)."""
    for r in results:
        r["_quality"] = source_quality_score(
            r.get("url", ""), r.get("title", ""), r.get("content", "")
        )
    return results
