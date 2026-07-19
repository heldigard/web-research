"""``status`` subcommand: render the health envelope for humans or agents."""

from __future__ import annotations

import argparse
import json

from web_research.features.status.engine import status_payload
from web_research.shared.cli_helpers import apply_common


def _yes_no(ok: bool) -> str:
    return "OK" if ok else "FAIL"


def _render_services(services: dict) -> list[str]:
    lines = ["## Services"]
    for name in ("searxng", "firecrawl", "ollama"):
        s = services[name]
        head = f"- [{_yes_no(s['ok'])}] {name:<10} {s['latency_ms']:>5} ms  {s['url']}"
        if s["ok"]:
            lines.append(head)
            continue
        # Detail carries the error reason; show it so the operator sees *why*.
        lines.append(f"{head}\n         {s['detail']}")
    lines.append("")
    return lines


def _render_models(models: dict) -> list[str]:
    if not models:
        return []
    lines = ["## Ollama models (configured vs installed)"]
    for key, info in models.items():
        mark = "present" if info["installed"] else "MISSING"
        lines.append(f"- [{mark}] {key:<14} {info['configured']}")
    lines.append("")
    return lines


def _render_keys(keys: dict) -> list[str]:
    lines = ["## API keys"]
    lines.append(
        f"- minimax: {'set' if keys['minimax'] else 'unset'} · "
        f"zai: {'set' if keys['zai'] else 'unset'} · "
        f"firecrawl: {'set' if keys['firecrawl'] else 'unset'}"
    )
    if keys.get("firecrawl_is_default_placeholder"):
        lines.append(
            "  note: firecrawl key is the built-in local placeholder — set FC_API_KEY for non-local use."
        )
    lines.append("")
    return lines


def _render_cloud(cloud: dict) -> list[str]:
    state = "available" if cloud["available"] else "absent (cheap_llm.py not on path)"
    return [f"## Cloud fallback\n- {state} · model: {cloud['model']}\n"]


def _render_cache(cache: dict) -> list[str]:
    kib = cache["bytes"] / 1024
    return [f"## Cache\n- {cache['entries']} entries · {kib:.0f} KiB · {cache['dir']}\n"]


def _render_human(payload: dict) -> str:
    verdict = "ALL SERVICES OK" if payload["overall_ok"] else "ONE OR MORE SERVICES DOWN"
    parts: list[str] = [f"# web-research status — {verdict}\n"]
    parts += _render_services(payload["services"])
    parts += _render_models(payload["models"])
    parts += _render_keys(payload["keys"])
    parts += _render_cloud(payload["cloud_fallback"])
    parts += _render_cache(payload["cache"])
    return "\n".join(parts).rstrip() + "\n"


def mode_status(args: argparse.Namespace) -> int:
    """Probe the local stack and print a human or JSON status report."""
    apply_common(args)
    payload = status_payload()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_render_human(payload), end="")
    # Non-zero exit when something is down, so scripts/agents can gate on it.
    return 0 if payload["overall_ok"] else 1
