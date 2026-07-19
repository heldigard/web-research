"""Output formatters for search results and research reports."""

from __future__ import annotations


def fmt_results(results: list[dict]) -> str:
    """Format search results as clean markdown."""
    if not results:
        return "_No results._"
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"### {i}. {r['title'] or '(no title)'}")
        lines.append(r["url"])
        meta = [x for x in (r.get("engine"), r.get("publishedDate"), r.get("source")) if x]
        if meta:
            lines.append("_" + " · ".join(dict.fromkeys(meta)) + "_")
        if r["content"]:
            lines.append(r["content"])
        lines.append("")
    return "\n".join(lines).strip()


def fmt_smart_results(
    results: list[dict],
    query: str,
    profile: dict | None = None,
    summary: str | None = None,
    meta: dict | None = None,
) -> str:
    """Format search results with query profile, optional synthesis, and quality badges.

    Args:
        results: scored/reranked result dicts (may carry ``_quality``).
        query: the original search query.
        profile: optional ``query_profile`` dict; its intent/recency/format are shown.
        summary: optional pre-synthesized answer block (``--summary``).
        meta: optional search escalation metadata (engine_used / escalated).
    """
    if not results:
        return "_No results._"
    lines = [f"# Smart search: {query}\n"]
    if profile:
        intent = profile.get("intent", "general")
        recency = "recency-sensitive" if profile.get("needs_recency") else "evergreen"
        fmt_hint = profile.get("expected_format", "snippet")
        lines.append(f"_Intent: {intent} · {recency} · expected: {fmt_hint}_")
    if meta and meta.get("escalated"):
        tried = ", ".join(meta.get("engines_tried") or [])
        lines.append(
            f"_Engine: escalated {meta.get('engine_requested')} → "
            f"{meta.get('engine_used')} (tried: {tried})_"
        )
    if profile or (meta and meta.get("escalated")):
        lines.append("")
    if summary:
        lines.append(summary.strip())
        lines.append("")
    for i, r in enumerate(results, 1):
        quality = r.get("_quality", 0.0)
        quality_badge = "⭐" if quality >= 0.7 else ""
        pub = r.get("_pub_date") or r.get("publishedDate") or ""
        date_bit = f" · {pub}" if pub else ""
        lines.append(f"{i}. {quality_badge} [{r['title']}]({r['url']}){date_bit}")
        snippet = r["content"][:160].replace("\n", " ")
        lines.append(f"   _{snippet}_")
    return "\n".join(lines)
