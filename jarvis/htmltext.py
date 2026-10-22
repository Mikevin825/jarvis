"""HTML → readable text.

Lives at the package root on purpose: both `jarvis.tools.web` (the `fetch_web`
tool) and `jarvis.presence.website` (the business status report) need it, and
neither should import the other's package. `jarvis.tools.__init__` imports the
presence tools, so a presence module importing from `jarvis.tools` creates a
cycle — putting this in its own module with no JARVIS imports is what avoids it.
"""

from __future__ import annotations

import re

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


def extract_text(html: str) -> str:
    """Strip HTML tags and return readable text.

    Script and style blocks go entirely; block-level elements become newlines
    so paragraphs stay separate; remaining tags are dropped. Entity decoding
    covers the handful that appear in real pages.
    """
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


def extract_title(html: str) -> str:
    """The `<title>` text, whitespace-collapsed, or an empty string."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return " ".join(match.group(1).split())
