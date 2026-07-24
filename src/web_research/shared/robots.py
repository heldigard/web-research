"""robots.txt compliance for the reader (stdlib only, fail-open).

The reader consults this before fetching a page so the engine respects crawl
directives. Parsing results are cached per host (5 min) to avoid a robots
round-trip on every scrape. Network, server, and parse failures are treated as
*allow* (fail-open); ``RobotFileParser`` semantics are retained for HTTP
responses, so 401/403 deny crawling and ordinary 4xx responses allow it.
"""

from __future__ import annotations

import time
import urllib.error
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from web_research.shared.config import get_settings
from web_research.shared.http import default_client

_CACHE: dict[str, tuple[float, RobotFileParser | None]] = {}
_TTL_SECONDS = 300.0


def _host_root(url: str) -> str | None:
    """Return the HTTP(S) ``scheme://netloc``, or ``None`` if unsupported."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _load_parser(host_root: str) -> RobotFileParser | None:
    """Fetch+parse ``robots.txt`` with the shared bounded HTTP client."""
    now = time.time()
    cached = _CACHE.get(host_root)
    if cached and now - cached[0] < _TTL_SECONDS:
        return cached[1]
    parser = RobotFileParser()
    robots_url = f"{host_root}/robots.txt"
    parser.set_url(robots_url)
    try:
        raw = default_client().get_bytes(robots_url, timeout=get_settings().timeout)
    except urllib.error.HTTPError as exc:
        # Match RobotFileParser.read(): authorization failures deny crawling,
        # while an absent robots file permits it. Other failures remain the
        # project's documented fail-open behavior.
        if exc.code in (401, 403):
            parser.parse(["User-agent: *", "Disallow: /"])
            result: RobotFileParser | None = parser
        elif 400 <= exc.code < 500:
            parser.parse([])
            result = parser
        else:
            result = None
        exc.close()
    except Exception:  # noqa: BLE001 — unreachable/malformed → fail open
        result = None
    else:
        try:
            parser.parse(raw.decode("utf-8", "surrogateescape").splitlines())
        except Exception:  # noqa: BLE001 — malformed content → fail open
            result = None
        else:
            result = parser
    _CACHE[host_root] = (now, result)
    return result


def is_allowed(url: str, user_agent: str = "*") -> bool:
    """True if robots.txt permits fetching ``url``; fail open on fetch/parse errors."""
    root = _host_root(url)
    if root is None:
        return False
    parser = _load_parser(root)
    if parser is None:
        return True
    try:
        return parser.can_fetch(user_agent, url)
    except Exception:  # noqa: BLE001 — malformed entry → allow rather than block
        return True


def bust_cache() -> None:
    """Clear the in-memory robots cache (test hook)."""
    _CACHE.clear()
