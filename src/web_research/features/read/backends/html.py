"""Stdlib HTML reader — zero-dependency last-resort fallback.

When Firecrawl (JS-rendered, self-hosted) and the Z.AI reader (subscription)
are both unavailable, this reader does a plain ``GET`` and extracts visible
text + ``<title>`` with the standard-library ``html.parser``. No JavaScript
rendering, so SPA shells yield little — but a static article page still
returns usable markdown. It exists so ``read_with_fallback`` never returns
an empty string just because the two server-side readers are down.
"""

from __future__ import annotations

import urllib.error
from html.parser import HTMLParser

from web_research.shared.http import default_client, warn

# vs-soft-allow  — see backends/base.py; HTTP-semantic reader contract.


class _TextExtractor(HTMLParser):
    """Collect visible text + ``<title>``, skipping script/style/nav noise.

    Inserts a newline at block-element boundaries so the collapsed output keeps
    paragraph-ish structure instead of one glued-together line.
    """

    _BLOCK_TAGS = frozenset(
        {
            "p",
            "div",
            "section",
            "article",
            "li",
            "br",
            "tr",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "pre",
            "blockquote",
            "td",
        }
    )
    # ``head`` is intentionally NOT skipped: ``<title>`` lives there and is the
    # one useful piece of text in the head. ``<style>``/``<script>`` inside head
    # are still skipped by their own entries below.
    _SKIP_TAGS = frozenset({"script", "style", "noscript", "nav", "footer", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._body: list[str] = []
        self._title: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        _ = attrs
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in self._BLOCK_TAGS:
            self._body.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in self._BLOCK_TAGS:
            self._body.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title.append(data)
        else:
            self._body.append(data)

    def result(self) -> tuple[str, str]:
        """Return ``(title, body_text)`` with whitespace collapsed per line."""
        body_lines = [" ".join(line.split()) for line in "".join(self._body).splitlines()]
        body = "\n".join(line for line in body_lines if line)
        title = " ".join("".join(self._title).split())
        return title, body


class HtmlReader:
    """``GET <url>`` → text via ``html.parser``. Zero deps, no JS rendering."""

    name = "html"

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        # Interface parity with the other readers (base_url/api_key ignored).
        _ = base_url, api_key

    def read(self, url: str, *, timeout: int = 30) -> str:
        """Return lightweight markdown (``# title`` + visible text) or empty string."""
        try:
            raw = default_client().get_bytes(url, timeout=timeout)
        except urllib.error.URLError as e:
            warn("html", f"{url} -> {e}")
            return ""
        except Exception as e:  # noqa: BLE001
            warn("html", f"{url} -> {type(e).__name__}: {e}")
            return ""
        html_text = raw.decode("utf-8", errors="replace")
        return _html_to_markdown(html_text)


def _html_to_markdown(html_text: str) -> str:
    """Parse ``html_text`` into ``# title\\n\\nbody`` (best-effort, never raises)."""
    parser = _TextExtractor()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:  # noqa: BLE001 — malformed HTML; keep whatever was parsed
        pass
    title, body = parser.result()
    if not body:
        return ""
    if title:
        return f"# {title}\n\n{body}"
    return body
