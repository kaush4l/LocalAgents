"""
Web Search Agent — searches the web via DuckDuckGo.

Module-level ``web_search_agent`` is ready at import.
"""

from __future__ import annotations

import warnings
from typing import Any

from core.engine import ReActAgent

warnings.filterwarnings(
    "ignore",
    message=r"This package .* has been renamed to `ddgs`!.*",
    category=RuntimeWarning,
)


_DDGS_CLASS: type | None = None
_DDGS_IMPORT_ERROR: str | None = None


def _get_ddgs_class() -> type | None:
    global _DDGS_CLASS, _DDGS_IMPORT_ERROR
    if _DDGS_CLASS is not None:
        return _DDGS_CLASS
    if _DDGS_IMPORT_ERROR:
        return None

    try:
        from ddgs import DDGS as _DDGS  # type: ignore[import-not-found]
    except ImportError:
        try:
            from duckduckgo_search import DDGS as _DDGS
        except ImportError:
            _DDGS_IMPORT_ERROR = "missing ddgs/duckduckgo-search package"
            return None

    _DDGS_CLASS = _DDGS
    return _DDGS_CLASS


def _resolve_query(inputs: dict[str, Any]) -> str:
    for key in ("query", "key", "q", "keywords", "text", "prompt"):
        value = inputs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    # Last-resort fallback: first non-empty string value.
    for value in inputs.values():
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _resolve_max_results(inputs: dict[str, Any], default: int = 5) -> int:
    raw = inputs.get("max_results", default)
    try:
        value = int(raw)
    except TypeError, ValueError:
        value = default
    return min(max(1, value), 10)


def _resolve_region(inputs: dict[str, Any], default: str = "us-en") -> str:
    value = inputs.get("region", default)
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return default


def _resolve_safesearch(inputs: dict[str, Any], default: str = "moderate") -> str:
    value = inputs.get("safesearch", default)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"on", "moderate", "off"}:
            return normalized
    return default


def _resolve_timelimit(inputs: dict[str, Any]) -> str | None:
    value = inputs.get("timelimit")
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"d", "w", "m", "y"}:
            return normalized
    return None


def _build_results(hits: list[dict[str, Any]]) -> str:
    results: list[str] = []
    for i, hit in enumerate(hits, 1):
        title = str(hit.get("title") or "No title")
        url = str(hit.get("href") or hit.get("url") or "No URL")
        snippet = str(hit.get("body") or hit.get("snippet") or "No snippet")[:200]
        results.append(f"{i}. {title}\n   URL: {url}\n   {snippet}")
    return "Search Results:\n\n" + "\n\n".join(results)


def web_search(inputs: dict[str, Any]) -> str:
    """Search the web using DuckDuckGo.

    Args:
        inputs: Dict with keys:
            - query (str): Search query (required)
            - key/q/keywords/text (str): Accepted aliases for query
            - max_results (int, optional): 1-10, default 5
            - region (str, optional): DDG region code (default: us-en)
            - safesearch (str, optional): on|moderate|off (default: moderate)
            - timelimit (str, optional): d|w|m|y

    Returns:
        Formatted search results or error message.
    """
    query = _resolve_query(inputs)
    if not query:
        return "Error: search query is required (use 'query' or 'key')."

    max_results = _resolve_max_results(inputs)
    region = _resolve_region(inputs)
    safesearch = _resolve_safesearch(inputs)
    timelimit = _resolve_timelimit(inputs)
    backends = ("auto", "html", "lite")
    backend_errors: list[str] = []
    ddgs_class = _get_ddgs_class()
    if ddgs_class is None:
        return "Error: search backend package not installed (install 'ddgs' or 'duckduckgo-search')."

    for backend in backends:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with ddgs_class() as ddgs:
                    hits = ddgs.text(
                        query,
                        region=region,
                        safesearch=safesearch,
                        timelimit=timelimit,
                        backend=backend,
                        max_results=max_results,
                    )
            if not hits:
                continue
            return _build_results(hits)
        except Exception as exc:
            backend_errors.append(f"{backend}: {exc}")

    if backend_errors:
        return (
            f"No results found for: {query}. "
            f"Backends attempted: {', '.join(backends)}. "
            f"Last errors: {' | '.join(backend_errors[:2])}"
        )
    return f"No results found for: {query}"


tools = [web_search]

web_search_agent = ReActAgent(
    name="web_search_agent",
    description=(
        "Internet research agent using DuckDuckGo.\n"
        "\n"
        "Best for:\n"
        "- Time-sensitive facts (versions, news, pricing)\n"
        "- Finding official docs and primary sources\n"
        "- Quick comparisons with URLs/snippets\n"
        "\n"
        'Primary tool: web_search({"query": "...", "max_results": 5})'
    ),
    system_instructions="web_search_agent",
    tools=tools,
)
