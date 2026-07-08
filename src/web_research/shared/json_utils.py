"""Tolerant JSON-object extraction from free-form LLM output (stdlib only).

Shared by ``synthesis`` (structured answers) and ``intelligence`` (query
profile). Lives in ``shared/`` so neither feature imports the other — the
vertical-slice low-coupling rule forbids ``features/* → features/*``.

Handles the common model-output failure modes: leading prose, trailing
commentary, and/or ```` ```json ```` code fences. Returns ``None`` when no
complete object parses so the caller can fall back to the raw text.
"""

from __future__ import annotations

import json
import re


def strip_fences(text: str) -> str:
    """Trim whitespace + a single pair of ```` ```json ... ``` ```` fences."""
    s = text.strip()
    s = re.sub(r"^\s*```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def try_parse_dict(s: str) -> dict | None:
    """``json.loads`` that returns ``None`` on failure or non-object results."""
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


# vs-soft-allow  — first_balanced_json is a single-responsibility brace/quote
# state-machine scanner; its apparent depth is a flat sequence of guard branches
# (for > if-string-mode > if-escape/quote), not nested business logic. Splitting
# it would scatter the state vars (depth/in_str/escaped) across helpers for no
# cohesion gain.
def first_balanced_json(s: str) -> dict | None:
    """Scan for the first brace-balanced, string-aware span and try to parse it.

    Rescues responses shaped ``"prose { ...json... } trailing prose"`` where the
    object is not the whole string. Uses guard clauses + early ``continue`` to
    keep nesting shallow (escape/quote state is tracked linearly, not nested).
    """
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escaped = False
    for offset, ch in enumerate(s[start:], start):
        # String-literal scanning: braces inside strings don't affect depth.
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if depth == 0 and ch == "}":
            return try_parse_dict(s[start : offset + 1])
    return None


def extract_json_object(text: str) -> dict | None:
    """Extract the first balanced JSON object from ``text`` (fence/prose-tolerant)."""
    s = strip_fences(text)
    direct = try_parse_dict(s)
    if direct is not None:
        return direct
    return first_balanced_json(s)
