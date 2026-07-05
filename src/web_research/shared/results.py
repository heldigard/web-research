"""Result-dict transforms shared across the search/research commands.

Pure dict reshaping — no feature dependencies (keeps ``shared`` from importing
``features``, per the vertical-slice low-coupling rule).
"""

from __future__ import annotations


def strip_internal(results: list[dict]) -> list[dict]:
    """Drop internal scoring keys (``_v``/``_score``/``_quality``) before output."""
    for r in results:
        for k in ("_v", "_score", "_quality"):
            r.pop(k, None)
    return results


def snippets_to_docs(results: list[dict]) -> list[dict]:
    """Adapt search snippets into the doc shape expected by :func:`synthesize`."""
    return [
        {
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "text": r.get("content", ""),
        }
        for r in results
    ]
