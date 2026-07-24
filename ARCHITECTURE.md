# Architecture

Vertical-slice CLI engine. One responsibility per slice; backends live in
per-file modules so adding a new source is one file + one registry entry.

```
src/web_research/
├── cli.py               # entrypoint: build_parser + dispatch (handlers injected)
├── cli_parser.py        # argparse construction (separated for cycle-free injection)
└── features/
    ├── search/
    │   ├── command.py
    │   ├── engine.py               # dispatcher: fan-out, dedup, dict projection
    │   └── backends/
    │       ├── base.py             # SearchResult dataclass + URL helpers
    │       ├── searxng.py
    │       ├── minimax.py
    │       └── zai.py
    ├── read/
    │   ├── command.py
    │   ├── engine.py               # dispatcher: engine + Firecrawl→Z.AI fallback
    │   └── backends/
    │       ├── base.py             # Page dataclass
    │       ├── firecrawl.py
    │       └── zai_reader.py
    ├── research/
    │   └── command.py              # orchestrates search → scrape → synth
    ├── ranking/engine.py           # rerank + source-quality scoring
    ├── intelligence/engine.py      # query profile, expansion, focused extract
    └── synthesis/engine.py         # cited synthesis (Ollama + opt-in cheap cloud)

shared/
├── config.py             # typed Settings (frozen dataclass) + env loader
├── http.py               # HttpClient port + UrllibHttpClient impl
├── cache.py              # versioned on-disk cache (auto-invalidate on schema bump)
├── ollama_api.py         # embed / generate / is_alive (TTL-cache)
├── cli_helpers.py        # apply_common — push CLI flags into settings
├── formatters.py         # markdown output for search + smart
├── results.py            # pure dict transforms (strip_internal, snippets_to_docs)
└── compat.py             # optional harness import bootstrap (ollama_client, cheap_llm)
```

## Adding a new search backend

1. Write `features/search/backends/<name>.py` with a class exposing:
   ```python
   class MyBackend:
       name = "my"  # the --engine value
       def __init__(self, api_key=None, base_url=None) -> None: ...
       def search(self, query: str, num: int, **opts) -> list[SearchResult]: ...
   ```
2. Register in `features/search/backends/__init__.py::BUILTIN_BACKENDS`.
3. The CLI plumbs `--engine my` → `engine="my"` → `build_backend("my")()` automatically.

## Adding a new reader

Same pattern under `features/read/backends/`. Each reader has a `read(url, **opts) -> str` method
returning markdown.

## Swapping the HTTP transport

`shared/http.py` ships `UrllibHttpClient` (stdlib-only) wired as the module
singleton (`_client`). To swap to `httpx`, add a new `HttpClient` impl and
re-point the singleton:

```python
# shared/http_httpx.py
class HttpxClient:
    def get_json(self, url, *, timeout=None, headers=None): ...
    def post_json(self, url, payload, *, timeout=None, headers=None): ...
    def get_bytes(self, url, *, timeout=None, headers=None): ...

# in shared/http.py — replace the singleton assignment, or reintroduce a
# set_default_client() setter at that point if a runtime flag is needed:
#   _client: HttpClient = HttpxClient() if config.USE_HTTPX else UrllibHttpClient()
```

No edits to backends or the dispatcher — they all resolve via `default_client()`.

## Cache invalidation on model / prompt change

`shared/cache.py` stamps every entry with `SCHEMA_VERSION` from `shared/config.py`.
Bump the version (already at `1`) whenever a config field, prompt template,
or backend response shape changes incompatible with prior entries; old
entries are deleted on read and treated as a miss.

`cache.set/get` also accept an `engine_tag=` argument (e.g. the synthesis
model name) so changing the model forces a per-tag refresh without a
schema bump.
