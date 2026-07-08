"""Optional stage-2 reranker: self-hosted HuggingFace TEI ``/rerank`` cross-encoder.

The default ranker (:func:`ranking.engine.rerank_results`) is a bi-encoder:
embed query + docs once, cosine-similarity. That is cheap but coarse. A
cross-encoder (e.g. ``BAAI/bge-reranker-v2-m3`` served by TEI) scores each
``(query, doc)`` pair jointly and orders the top-N noticeably better.

Enabled only when ``TEI_RERANK_URL`` is set (e.g. ``http://localhost:8081``,
the appliance form from ``ghcr.io/huggingface/text-embeddings-inference``).
When disabled or unreachable, every function here degrades to ``None``/``False``
so the caller transparently falls back to the bi-encoder — no feature flag,
no crash.

Request shape (TEI native)::

    POST {tei_rerank_url}/rerank
    {"query": "...", "texts": ["...", "..."], "raw_scores": false}

Response shape::  ``[{"index": 1, "score": 0.93}, ...]``
"""

from __future__ import annotations

from web_research.shared.config import get_settings
from web_research.shared.http import debug, default_client, warn


def tei_enabled() -> bool:
    """True when a TEI rerank endpoint is configured."""
    return bool(get_settings().tei_rerank_url)


def rerank(query: str, texts: list[str]) -> list[tuple[int, float]] | None:
    """Cross-encoder rerank ``texts`` for ``query`` via TEI.

    Returns ``(original_index, score)`` tuples sorted by score descending, or
    ``None`` when TEI is disabled, unreachable, or returned nothing usable.
    """
    base = get_settings().tei_rerank_url
    if not base or not texts:
        return None
    endpoint = base.rstrip("/") + "/rerank"
    try:
        data = default_client().post_json(
            endpoint,
            {"query": query, "texts": texts, "raw_scores": False},
            timeout=20,
        )
    except Exception as e:  # noqa: BLE001 — TEI down -> fall back to bi-encoder
        warn("tei", str(e))
        return None
    return _parse_tei_scores(data)


def _parse_tei_scores(data: dict) -> list[tuple[int, float]] | None:
    """Normalize TEI's ``[{index, score}, ...]`` response into sorted pairs."""
    raw = data.get("results")
    if not isinstance(raw, list) or not raw:
        return None
    scored: list[tuple[int, float]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        index = row.get("index")
        score = row.get("score")
        if index is None or score is None:
            continue
        try:
            scored.append((int(index), float(score)))
        except (TypeError, ValueError):
            continue
    if not scored:
        return None
    scored.sort(key=lambda item: item[1], reverse=True)
    debug("tei", f"reranked {len(scored)} docs via cross-encoder")
    return scored
