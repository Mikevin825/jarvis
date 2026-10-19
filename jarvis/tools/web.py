"""Web access — fetch and extract content from URLs.

Read-only. Uses httpx for fetching and html.parser for extraction.
No API key needed. Handles timeouts, errors, and non-HTML content.
"""

from __future__ import annotations

import re
import httpx

from .base import Tool, ToolError

_TIMEOUT = httpx.Timeout(15.0, connect=8.0)
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Tags to strip entirely (with content)
_STRIP_TAGS = re.compile(
    r"<(script|style|nav|footer|header|aside|form|iframe|noscript|svg)[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
# Block-level tags → newline
_BLOCK_TAGS = re.compile(
    r"</?(p|div|br|li|h[1-6]|tr|section|article|blockquote|pre)[^>]*>",
    re.IGNORECASE,
)
# All remaining tags
_ALL_TAGS = re.compile(r"<[^>]+>")
# Whitespace collapse
_WS = re.compile(r"\n{3,}")


def _extract_text(html: str) -> str:
    """Strip HTML tags and return readable text."""
    # Remove script/style/etc with their content
    text = _STRIP_TAGS.sub("", html)
    # Replace block tags with newlines
    text = _BLOCK_TAGS.sub("\n", text)
    # Remove all remaining tags
    text = _ALL_TAGS.sub("", text)
    # Decode common HTML entities
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
    )
    # Collapse whitespace
    text = _WS.sub("\n\n", text)
    # Strip each line and drop empty ones
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines)


def fetch_web(url: str, query: str = "") -> str:
    url = (url or "").strip()
    if not url:
        raise ToolError("No URL was given. Ask the user which page they mean.")

    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ToolError(f"The page at {url} did not respond in time.") from exc
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not reach {url}: {exc}") from exc

    content_type = resp.headers.get("content-type", "")
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        raise ToolError(
            f"The URL returned {content_type or 'unknown content type'}, not a web page. "
            "I can only read HTML pages."
        )

    text = _extract_text(resp.text)

    if not text:
        raise ToolError(f"The page at {url} had no readable text content.")

    lines = text.split("\n")

    # If query given, try to find relevant sections
    if query:
        query_lower = query.lower()
        relevant = [line for line in lines if query_lower in line.lower()]
        if relevant:
            return "\n".join(relevant[:20])
        # Fallback: return first 50 lines
        return "\n".join(lines[:50])

    # General fetch: return first 100 lines
    return "\n".join(lines[:100])


_PARAMS = {
    "type": "OBJECT",
    "properties": {
        "url": {
            "type": "STRING",
            "description": "The URL to fetch, e.g. 'https://example.com' or 'https://news.ycombinator.com'.",
        },
        "query": {
            "type": "STRING",
            "description": "Optional: what to look for on the page. If given, returns only relevant sections. If omitted, returns the main content.",
        },
    },
    "required": ["url"],
}


def build() -> list[Tool]:
    return [
        Tool(
            name="fetch_web",
            description=(
                "Use this to fetch and read content from a web page. "
                "Call it when the user asks you to LOOK UP, READ, or GET INFORMATION "
                "from a URL — when they want you to tell them what's on the page. "
                "Returns the text content so you can summarize or answer questions about it. "
                "Do NOT use this when the user wants to open a link in the browser — "
                "use open_url for that."
            ),
            parameters=_PARAMS,
            func=fetch_web,
        )
    ]
