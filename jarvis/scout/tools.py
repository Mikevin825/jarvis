"""The scout's research tools.

All free, no API key. The scout uses these to hunt for competitor/product news.
Each tool follows the same pattern as the rest of JARVIS: typed inputs, plain
language errors, and results that are safe to show the model.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import quote_plus

import httpx

from .base import Tool, ToolError

_TIMEOUT = httpx.Timeout(15.0, connect=8.0)
_HEADERS = {"User-Agent": "JARVIS-Scout/1.0 (research bot)"}
# Search engines reject an obvious bot user-agent. A browser UA is what makes
# DuckDuckGo lite answer with results instead of an anti-bot page.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _decode_ddg_href(href: str) -> str:
    """Unwrap DuckDuckGo's redirect link into the real destination URL.

    DuckDuckGo lite returns links as /l/?uddg=<url-encoded>. Showing the model a
    redirect URL would put it in findings and then in citations, so unwrap it.
    """
    from urllib.parse import parse_qs, unquote, urlparse

    if "uddg=" not in href:
        return href
    try:
        query = urlparse(href).query
        target = parse_qs(query).get("uddg", [""])[0]
        return unquote(target) or href
    except Exception:  # noqa: BLE001 — a malformed link must not kill the search
        return href


def web_search(query: str, max_results: int = 5) -> str:
    """Search the web using DuckDuckGo's lite interface.

    Free, no API key. Returns a plain-text list of results.

    The lite endpoint is used rather than html.duckduckgo.com: the latter now
    answers automated requests with HTTP 202 and an anti-bot page instead of
    results, so the parser would silently return nothing.
    """
    query = (query or "").strip()
    if not query:
        raise ToolError("No search query was given.")

    try:
        resp = httpx.get(
            "https://lite.duckduckgo.com/lite/",
            params={"q": query},
            headers=_BROWSER_HEADERS,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ToolError("The search service did not respond in time.") from exc
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not reach the search service: {exc}") from exc

    # DuckDuckGo lite marks each result anchor with class='result-link' and uses
    # single quotes. The href may be a /l/?uddg= redirect; unwrap it so findings
    # cite the real URL.
    results = []
    pattern = re.compile(
        r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*class=[\"']result-link[\"'][^>]*>(.*?)</a>",
        re.DOTALL | re.IGNORECASE,
    )
    for match in pattern.finditer(resp.text):
        url = _decode_ddg_href(match.group(1))
        title = re.sub(r"<[^>]+>", "", match.group(2))
        title = title.replace("&#x27;", "'").replace("&amp;", "&").strip()
        if title and url:
            results.append(f"- {title}\n  {url}")
        if len(results) >= max_results:
            break

    if not results:
        return f"No results found for '{query}'."
    return f"Search results for '{query}':\n" + "\n".join(results)


def fetch_rss(url: str, max_items: int = 10) -> str:
    """Fetch and parse an RSS/Atom feed.

    Free, no API key. Returns a plain-text list of recent items.
    """
    url = (url or "").strip()
    if not url:
        raise ToolError("No feed URL was given.")

    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ToolError(f"The feed at {url} did not respond in time.") from exc
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not reach the feed at {url}: {exc}") from exc

    # Parse RSS/Atom items. Look for <item> or <entry> elements.
    items = []
    for match in re.finditer(
        r"<(?:item|entry)>(.*?)</(?:item|entry)>",
        resp.text,
        re.DOTALL | re.IGNORECASE,
    ):
        body = match.group(1)
        title = re.search(r"<title[^>]*>(.*?)</title>", body, re.DOTALL | re.IGNORECASE)
        link = re.search(r"<link[^>]*>(.*?)</link>", body, re.DOTALL | re.IGNORECASE)
        if not link:
            link = re.search(r'<link[^>]*href="([^"]+)"', body, re.IGNORECASE)
        desc = re.search(
            r"<(?:description|summary)[^>]*>(.*?)</(?:description|summary)>",
            body,
            re.DOTALL | re.IGNORECASE,
        )

        title_text = re.sub(r"<[^>]+>", "", title.group(1)).strip() if title else "(no title)"
        link_text = link.group(1).strip() if link else ""
        desc_text = re.sub(r"<[^>]+>", "", desc.group(1)).strip()[:200] if desc else ""

        items.append(f"- {title_text}\n  {link_text}\n  {desc_text}")
        if len(items) >= max_items:
            break

    if not items:
        return f"No items found in the feed at {url}."
    return f"Recent items from {url}:\n" + "\n".join(items)


class _TextExtractor(HTMLParser):
    """Extract visible text from HTML, skipping script/style."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip > 0:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            text = data.strip()
            if text:
                self._parts.append(text)

    def text(self) -> str:
        return " ".join(self._parts)


def fetch_url(url: str, max_chars: int = 5000) -> str:
    """Fetch a web page and extract its visible text.

    Free, no API key. Returns plain text, truncated to max_chars.
    """
    url = (url or "").strip()
    if not url:
        raise ToolError("No URL was given.")

    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ToolError(f"The page at {url} did not respond in time.") from exc
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not reach the page at {url}: {exc}") from exc

    extractor = _TextExtractor()
    try:
        extractor.feed(resp.text)
    except Exception:  # noqa: BLE001 - malformed HTML must not crash the tool
        pass

    text = extractor.text()
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return text or f"No visible text found at {url}."


def build() -> list[Tool]:
    """Assemble the scout's research tools."""
    return [
        Tool(
            name="web_search",
            description=(
                "Use this to search the web for competitor and product news. "
                "Returns a list of results with titles and URLs. "
                "Call it when you need to find recent information about a topic."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": "The search query, e.g. 'OpenAI new product launch 2026'.",
                    },
                    "max_results": {
                        "type": "INTEGER",
                        "description": "Maximum number of results to return (default 5).",
                    },
                },
                "required": ["query"],
            },
            func=web_search,
        ),
        Tool(
            name="fetch_rss",
            description=(
                "Use this to fetch and parse an RSS or Atom feed. "
                "Returns recent items with titles, links, and descriptions. "
                "Call it when you need to check a blog, news site, or changelog."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "url": {
                        "type": "STRING",
                        "description": "The feed URL, e.g. 'https://blog.example.com/feed.xml'.",
                    },
                    "max_items": {
                        "type": "INTEGER",
                        "description": "Maximum number of items to return (default 10).",
                    },
                },
                "required": ["url"],
            },
            func=fetch_rss,
        ),
        Tool(
            name="fetch_url",
            description=(
                "Use this to fetch a web page and extract its visible text. "
                "Returns plain text, truncated to a reasonable length. "
                "Call it when you need to read the content of a specific page."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "url": {
                        "type": "STRING",
                        "description": "The page URL to fetch.",
                    },
                    "max_chars": {
                        "type": "INTEGER",
                        "description": "Maximum characters to return (default 5000).",
                    },
                },
                "required": ["url"],
            },
            func=fetch_url,
        ),
    ]
