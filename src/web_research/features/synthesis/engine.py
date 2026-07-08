"""Synthesis: structured, cited answers via Ollama or cheap cloud fallback."""

from __future__ import annotations

import json
import re
from functools import partial

from web_research.shared.compat import cheap_complete
from web_research.shared.config import (
    OLLAMA_SYNTH_MODEL,
    WEB_SYNTH_CLOUD_MODEL,
    WEB_SYNTH_MAX_CONTEXT_CHARS,
)
from web_research.shared.http import _warn
from web_research.shared.ollama_api import generate


def _synthesize_local(prompt: str, system: str) -> str | None:
    # Final cited answer → use the synthesis-tuned model (OLLAMA_SYNTH_MODEL =
    # aratan/gemma-4-E4B-it-heretic:Q6_K, web_synth #1 in the 2026-07-08
    # canonical refactor bench), not the universal qwen3.5:4b anchor.
    return generate(prompt, system=system, temperature=0.2, model=OLLAMA_SYNTH_MODEL)


_STRUCTURED_SCHEMA = [
    "answer",
    "facts[].claim",
    "facts[].source",
    "facts[].confidence",
    "contradictions[].claim_a",
    "contradictions[].claim_b",
    "contradictions[].sources",
    "unknowns[]",
]


def _synthesize_cloud(prompt: str, system: str, structured: bool = False) -> str | None:
    if cheap_complete is None:
        return None
    try:
        out = cheap_complete(
            system=system,
            prompt=prompt,
            schema_hint=_STRUCTURED_SCHEMA if structured else None,
            timeout_total=30.0,
            require_json=structured,
            cloud_model=WEB_SYNTH_CLOUD_MODEL,
        )
        return (out.get("text") or "").strip() or None
    except Exception as e:  # noqa: BLE001
        _warn("cheap_llm", str(e))
        return None


def synthesize(
    query: str,
    docs: list[dict],
    answer_mode: bool = False,
    structured: bool = False,
) -> str | None:
    """Generate cited synthesis using Ollama, falling back to cheap cloud LLM.

    If structured=True, attempts to return a JSON object that is then rendered
    as clean markdown.
    """
    ctx_parts = []
    remaining = WEB_SYNTH_MAX_CONTEXT_CHARS
    for i, d in enumerate(docs, 1):
        text = d.get("extracted") or d["text"]
        if remaining <= 0:
            text = "[context budget exhausted]"
        else:
            source_slots_left = max(len(docs) - i + 1, 1)
            budget = min(remaining, max(800, remaining // source_slots_left))
            text = _compact_source_text(text, budget)
        remaining = max(0, remaining - len(text))
        ctx_parts.append(f"[{i}] {d['title']}\nURL: {d['url']}\n{text}")
    context = "\n\n---\n\n".join(ctx_parts)

    base_system = (
        "You are a precise research analyst. Be factual, cite sources, no filler. "
        "Use only the provided sources."
    )

    if structured:
        style = (
            "Reply ONLY with a JSON object matching this schema:\n"
            '{"answer": "...", "facts": [{"claim": "...", "source": n, "confidence": "high|medium|low"}], '
            '"contradictions": [{"claim_a": "...", "claim_b": "...", "sources": [n, m]}], '
            '"unknowns": ["..."], "recommended_next_search": "..."}\n'
            "Confidence rules: high=official docs/multiple agreeing sources, "
            "medium=single reputable source, low=unclear/conflicting."
        )
    elif answer_mode:
        style = (
            "Answer the user's question directly and concisely using ONLY the sources. "
            "Cite as [n] matching source numbers. If sources are insufficient, say so."
        )
    else:
        style = (
            "Write a concise, well-organized synthesis of the sources answering the research query. "
            "Use bullet points and cite facts as [n] matching source numbers. "
            "Ignore marketing fluff. Note contradictions. "
            "Do NOT include a Sources section at the end; it will be appended automatically."
        )

    prompt = f"QUERY: {query}\n\nSOURCES:\n{context}\n\n{style}"

    # Cloud backend is mode-aware (prose → require_json=False; structured →
    # JSON schema + render). partial binds `structured` so both backends share
    # the (prompt, system) call signature.
    cloud_fn = partial(_synthesize_cloud, structured=structured)
    for fn, label in ((_synthesize_local, "ollama"), (cloud_fn, "cloud")):
        answer = _try_synthesize(fn, label, prompt, base_system)
        if answer:
            return _format_answer(answer, structured)
    return None


def _compact_source_text(text: str, max_chars: int) -> str:
    """Trim source text for synthesis while preserving readable paragraphs."""
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(text) <= max_chars:
        return text

    marker = "\n\n[content truncated]"
    clipped = text[: max(0, max_chars - len(marker))].rstrip()
    last_para = clipped.rfind("\n\n")
    if last_para >= max_chars // 2:
        clipped = clipped[:last_para].rstrip()
    return clipped + marker


def _try_synthesize(fn, label: str, prompt: str, system: str) -> str | None:
    """Call a synthesis backend, swallowing exceptions."""
    try:
        answer = fn(prompt, system)
        return answer if answer else None
    except Exception as e:  # noqa: BLE001
        _warn(label, f"synthesis failed: {e}")
        return None


def _format_answer(answer: str, structured: bool) -> str | None:
    """Render a structured answer or return the prose answer as-is."""
    if structured:
        return _render_structured(answer)
    return answer


def _render_structured(answer: str) -> str:
    """Parse structured JSON and render it as clean markdown."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", answer.strip(), flags=re.MULTILINE)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return answer

    sections: list[str] = []
    _render_answer(data, sections)
    _render_facts(data, sections)
    _render_contradictions(data, sections)
    _render_unknowns(data, sections)
    _render_next_search(data, sections)
    return "\n".join(sections).strip() or answer


def _render_answer(data: dict, lines: list[str]) -> None:
    if data.get("answer"):
        lines.append(data["answer"])
        lines.append("")


def _render_facts(data: dict, lines: list[str]) -> None:
    facts = data.get("facts") or []
    if not facts:
        return
    lines.append("### Key facts")
    for f in facts:
        src = f.get("source")
        cite = f" [{src}]" if isinstance(src, int) else ""
        lines.append(f"- ({f.get('confidence', 'medium')}) {f.get('claim', '')}{cite}")
    lines.append("")


def _render_contradictions(data: dict, lines: list[str]) -> None:
    contradictions = data.get("contradictions") or []
    if not contradictions:
        return
    lines.append("### Contradictions")
    for c in contradictions:
        srcs = c.get("sources") or []
        cite = " [" + ", ".join(str(s) for s in srcs) + "]" if srcs else ""
        lines.append(f"- {c.get('claim_a')} vs {c.get('claim_b')}{cite}")
    lines.append("")


def _render_unknowns(data: dict, lines: list[str]) -> None:
    unknowns = data.get("unknowns") or []
    if not unknowns:
        return
    lines.append("### Unknowns / gaps")
    for u in unknowns:
        lines.append(f"- {u}")
    lines.append("")


def _render_next_search(data: dict, lines: list[str]) -> None:
    if data.get("recommended_next_search"):
        lines.append(f"### Suggested next search\n- {data['recommended_next_search']}\n")
