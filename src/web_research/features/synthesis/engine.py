"""Synthesis: structured, cited answers via Ollama or cheap cloud fallback."""

from __future__ import annotations

import hashlib
import re
from functools import partial

from web_research.shared.cache import get as cache_get
from web_research.shared.cache import set as cache_set
from web_research.shared.compat import cheap_complete
from web_research.shared.config import (
    OLLAMA_SYNTH_MODEL,
    WEB_SYNTH_CLOUD_MODEL,
    WEB_SYNTH_MAX_CONTEXT_CHARS,
    Settings,
    get_settings,
)
from web_research.shared.http import _warn
from web_research.shared.json_utils import extract_json_object as _extract_json_object
from web_research.shared.ollama_api import generate


def _synthesize_local(prompt: str, system: str, model: str | None = None) -> str | None:
    # Final cited answer: PRIMARY is the synthesis-tuned model (TeichAI/Fable-5-v1,
    # web_synth combined #1 per ~/ollama-bench/RANKING.md 2026-07-09 validation).
    # `model` overrides the default PRIMARY so synthesize() can chain PRIMARY →
    # FALLBACK without re-importing the constants here.
    return generate(prompt, system=system, temperature=0.2, model=model or OLLAMA_SYNTH_MODEL)


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
            max_output_tokens=2048,  # cited synthesis can exceed the 1024 default
        )
        return (out.get("text") or "").strip() or None
    except Exception as e:  # noqa: BLE001
        _warn("cheap_llm", str(e))
        return None


def _synth_cache_params(
    query: str, docs: list[dict], answer_mode: bool, structured: bool, max_ctx: int
) -> dict:
    """Deterministic cache key for a synthesis result.

    Captures every input that changes the output: query, the source set
    (URLs + a content fingerprint so an updated page invalidates even at the
    same URL), the two rendering modes, and the context-truncation budget
    (``WEB_SYNTH_MAX_CONTEXT_CHARS`` — a wider budget yields a different
    answer from the same sources, so it must invalidate). The model is stamped
    via ``engine_tag`` at the call site (a model bump forces a miss without a
    full schema bump — see ``shared/cache.py``).
    """
    material = sorted(
        (str(d.get("url", "")), (d.get("extracted") or d.get("text", ""))[:2000]) for d in docs
    )
    docs_hash = hashlib.sha256(
        "\n".join(f"{url}\n{txt}" for url, txt in material).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "q": query,
        "docs_hash": docs_hash,
        "n_docs": len(docs),
        "answer_mode": answer_mode,
        "structured": structured,
        "max_ctx": max_ctx,
    }


def synthesize(
    query: str,
    docs: list[dict],
    answer_mode: bool = False,
    structured: bool = False,
    no_cache: bool = False,
) -> str | None:
    """Generate cited synthesis using Ollama, falling back to cheap cloud LLM.

    Back-compat wrapper over :func:`synthesize_result` (returns only the
    rendered answer string). Prefer ``synthesize_result`` when the caller
    needs structured fields such as ``recommended_next_search`` for multi-hop.
    """
    return synthesize_result(
        query, docs, answer_mode=answer_mode, structured=structured, no_cache=no_cache
    )["answer"]


def synthesize_result(
    query: str,
    docs: list[dict],
    answer_mode: bool = False,
    structured: bool = False,
    no_cache: bool = False,
) -> dict:
    """Like :func:`synthesize` but also returns structured meta when available.

    Return shape::

        {"answer": str | None, "structured": dict | None}

    ``structured`` is the grounded JSON object (facts/unknowns/next search)
    when ``structured=True`` and the model produced parseable JSON; else None.
    Research uses this to decide a single follow-up hop without re-parsing
    markdown.
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
        "You are a precise research analyst for LLM controller agents. "
        "Be factual, cite sources, no filler. Use ONLY the provided sources. "
        "Never invent URLs, versions, dates, or claims not supported by a source. "
        "If evidence is thin, say what is unknown rather than guessing. "
        "When sources disagree on dates, deadlines, availability windows, or version "
        "status, build an explicit timeline and treat the most recent dated source as "
        "authoritative unless an official primary source contradicts it."
    )

    if structured:
        style = (
            "Reply ONLY with a JSON object matching this schema:\n"
            '{"answer": "...", "facts": [{"claim": "...", "source": n, "confidence": "high|medium|low"}], '
            '"contradictions": [{"claim_a": "...", "claim_b": "...", "sources": [n, m]}], '
            '"unknowns": ["..."], "recommended_next_search": "..."}\n'
            "Rules:\n"
            "- Every fact.claim MUST be directly supported by the numbered source body; "
            "source is the 1-based index of that source.\n"
            "- Confidence: high=official docs or ≥2 agreeing sources; "
            "medium=single reputable source; low=unclear/conflicting/inferred.\n"
            "- If sources mention different dates/deadlines for the same event "
            "(e.g. 'until July 12' vs 'until July 19'), put both in contradictions "
            "or facts with dates, and state the latest date in answer.\n"
            "- Put open questions in unknowns; put a concrete follow-up query in "
            "recommended_next_search when gaps remain "
            "(date timelines, prior extensions, official primary sources)."
        )
    elif answer_mode:
        style = (
            "Answer the user's question directly and concisely using ONLY the sources. "
            "Cite as [n] matching source numbers. Prefer short, decision-ready answers. "
            "If sources give conflicting dates/deadlines, list the timeline and use the "
            "most recent date. If sources are insufficient, say so and list what is missing."
        )
    else:
        style = (
            "Write a concise, well-organized synthesis of the sources answering the research query. "
            "Use bullet points and cite facts as [n] matching source numbers. "
            "Ignore marketing fluff. Note contradictions and gaps explicitly. "
            "When dates or availability windows conflict across sources, open with a short "
            "timeline (oldest → newest) and state which date is current. "
            "Do NOT include a Sources section at the end; it will be appended automatically."
        )

    prompt = f"QUERY: {query}\n\nSOURCES:\n{context}\n\n{style}"

    # Synthesis backend chain: local Ollama (PRIMARY → FALLBACK) → cloud.
    settings = get_settings()

    cache_params = _synth_cache_params(
        query, docs, answer_mode, structured, WEB_SYNTH_MAX_CONTEXT_CHARS
    )
    if not no_cache:
        cached = cache_get("synth", cache_params, engine_tag=settings.ollama_synth_model)
        if cached:
            return {
                "answer": cached.get("answer"),
                "structured": cached.get("structured"),
            }

    answer, structured_data = _run_synth_chain(prompt, base_system, structured, settings, docs=docs)

    if answer and not no_cache:
        cache_set(
            "synth",
            cache_params,
            {"answer": answer, "structured": structured_data},
            engine_tag=settings.ollama_synth_model,
        )
    return {"answer": answer, "structured": structured_data}


def _run_synth_chain(
    prompt: str,
    base_system: str,
    structured: bool,
    settings: Settings,
    docs: list[dict] | None = None,
) -> tuple[str | None, dict | None]:
    """Run the local→fallback→cloud backend chain.

    Returns ``(rendered_answer, structured_data)``. Structured data is only
    populated when ``structured=True`` and JSON parsed cleanly.
    """
    local_attempts: list[tuple[str, str]] = [
        (settings.ollama_synth_model, "ollama"),
    ]
    fb = settings.ollama_synth_fallback_model
    if fb and fb != settings.ollama_synth_model:
        local_attempts.append((fb, "ollama-fallback"))
    for model, label in local_attempts:
        fn = partial(_synthesize_local, model=model)
        answer = _try_synthesize(fn, label, prompt, base_system)
        if answer:
            return _format_answer(answer, structured, docs=docs)
    cloud_fn = partial(_synthesize_cloud, structured=structured)
    answer = _try_synthesize(cloud_fn, "cloud", prompt, base_system)
    if not answer:
        return None, None
    return _format_answer(answer, structured, docs=docs)


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


def _format_answer(
    answer: str, structured: bool, docs: list[dict] | None = None
) -> tuple[str | None, dict | None]:
    """Render a structured answer or return the prose answer as-is.

    Returns ``(rendered, structured_data)``.
    """
    if structured:
        return _render_structured(answer, docs=docs)
    return answer, None


# Content tokens used for lightweight claim↔source grounding. Small stopword
# set keeps false negatives low without depending on ranking.engine.
_GROUND_STOP: frozenset[str] = frozenset(
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
        "as",
        "at",
        "from",
        "that",
        "this",
        "it",
        "its",
        "el",
        "la",
        "los",
        "las",
        "de",
        "del",
        "en",
        "un",
        "una",
        "y",
        "o",
        "que",
        "por",
        "con",
        "para",
        "se",
        "es",
        "al",
    }
)
_GROUND_WORD_RE = re.compile(r"[a-z0-9áéíóúüñ]{2,}", re.IGNORECASE)
# Fraction of claim content-tokens that must appear in the cited source.
_GROUND_OVERLAP_MIN = 0.35


def _content_tokens(text: str) -> set[str]:
    """Lowercase content tokens for grounding overlap (stopwords dropped)."""
    return {
        tok
        for tok in _GROUND_WORD_RE.findall(text.lower())
        if tok not in _GROUND_STOP and not tok.isdigit()
    }


def _source_text(docs: list[dict], index: int) -> str:
    """Return the best available text for 1-based source index."""
    if index < 1 or index > len(docs):
        return ""
    doc = docs[index - 1]
    return str(doc.get("extracted") or doc.get("text") or doc.get("content") or "")


def _claim_supported(claim: str, source_text: str) -> bool:
    """True when enough claim content tokens appear in the cited source body."""
    claim_toks = _content_tokens(claim)
    if len(claim_toks) < 2:
        # Too short to judge — do not demote (avoid over-flagging booleans).
        return True
    if not source_text:
        return False
    src_toks = _content_tokens(source_text)
    if not src_toks:
        return False
    overlap = len(claim_toks & src_toks) / len(claim_toks)
    return overlap >= _GROUND_OVERLAP_MIN


def ground_structured_facts(data: dict, docs: list[dict]) -> dict:
    """Demote / flag structured facts whose claims lack support in cited sources.

    Controllers trust ``[n]`` citations. Local synthesis models sometimes
    invent a plausible claim and attach a source number. This pure post-pass
    checks lexical support and:
      * sets ``confidence`` to ``low`` when unsupported
      * sets ``grounding`` to ``supported`` / ``unsupported`` / ``invalid_source``
      * appends an ``unknowns`` note listing ungrounded claims

    Does not drop claims (agents still see them) — demotion is the honest
    signal. Mutates and returns ``data``.
    """
    if not isinstance(data, dict) or not docs:
        return data

    facts = data.get("facts")
    if not isinstance(facts, list) or not facts:
        return data

    ungrounded: list[str] = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        claim = str(fact.get("claim") or "").strip()
        src = fact.get("source")
        if not isinstance(src, int):
            fact["confidence"] = "low"
            fact["grounding"] = "invalid_source"
            if claim:
                ungrounded.append(claim)
            continue
        body = _source_text(docs, src)
        if not body or src < 1 or src > len(docs):
            fact["confidence"] = "low"
            fact["grounding"] = "invalid_source"
            if claim:
                ungrounded.append(claim)
            continue
        if _claim_supported(claim, body):
            fact.setdefault("grounding", "supported")
        else:
            fact["confidence"] = "low"
            fact["grounding"] = "unsupported"
            if claim:
                ungrounded.append(claim)

    if ungrounded:
        unknowns = data.get("unknowns")
        if not isinstance(unknowns, list):
            unknowns = []
            data["unknowns"] = unknowns
        note = (
            f"{len(ungrounded)} claim(s) lack lexical support in the cited source(s) "
            "and were demoted to low confidence"
        )
        if note not in unknowns:
            unknowns.append(note)
    return data


def _render_structured(answer: str, docs: list[dict] | None = None) -> tuple[str, dict | None]:
    """Parse structured JSON (tolerating fences/prose) and render as clean markdown.

    Returns ``(rendered_markdown, grounded_data_or_None)``.
    """
    data = _extract_json_object(answer)
    if data is None:
        return answer, None

    if docs:
        data = ground_structured_facts(data, docs)

    sections: list[str] = []
    _render_answer(data, sections)
    _render_facts(data, sections)
    _render_contradictions(data, sections)
    _render_unknowns(data, sections)
    _render_next_search(data, sections)
    rendered = "\n".join(sections).strip() or answer
    return rendered, data


def next_search_query(structured: dict | None) -> str | None:
    """Extract a usable follow-up search query from structured synthesis meta."""
    if not isinstance(structured, dict):
        return None
    raw = structured.get("recommended_next_search")
    if not isinstance(raw, str):
        return None
    q = raw.strip().strip('"').strip("'")
    if len(q) < 8 or len(q) > 200:
        return None
    # Reject placeholder / non-query noise.
    low = q.lower()
    if low in {"none", "n/a", "na", "null", "no further search", "no"}:
        return None
    return q


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
        if not isinstance(f, dict):
            continue
        src = f.get("source")
        cite = f" [{src}]" if isinstance(src, int) else ""
        conf = f.get("confidence", "medium")
        grounding = f.get("grounding")
        flag = " ⚠ ungrounded" if grounding in ("unsupported", "invalid_source") else ""
        lines.append(f"- ({conf}) {f.get('claim', '')}{cite}{flag}")
    lines.append("")


def _render_contradictions(data: dict, lines: list[str]) -> None:
    contradictions = data.get("contradictions") or []
    if not contradictions:
        return
    lines.append("### Contradictions")
    for c in contradictions:
        if not isinstance(c, dict):
            continue
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
