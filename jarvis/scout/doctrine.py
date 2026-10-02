"""The doctrine loader.

Loads DOCTRINE.md at run time with mtime-based caching. Edit the file and the
next run picks up the change — no restart required.

The doctrine is the scout's instruction set. It is data, not code. The loader
caches on mtime so that a hand edit to the file is picked up on the next run
without restarting the process.
"""

from __future__ import annotations

from pathlib import Path

DOCTRINE_PATH = Path(__file__).parent / "DOCTRINE.md"

# Cache: (mtime, content). Loaded once, refreshed when the file changes.
_cache: tuple[float, str] | None = None


def load_document(path: Path = DOCTRINE_PATH) -> str:
    """Load a document, caching on mtime.

    If the file has not changed since the last load, return the cached content.
    If it has changed (or was never loaded), read it and update the cache.

    This is what makes the doctrine editable without a restart: the next call
    after an edit sees the new mtime and reloads.
    """
    global _cache

    try:
        mtime = path.stat().st_mtime
    except OSError:
        # File missing or unreadable — return a generic fallback, never raise.
        # A missing doctrine must not crash the scout.
        return (
            "You are a research scout. You hunt for competitor and product news, "
            "score what you find, and hand the results to a human who decides. "
            "You never act on a find. You recommend; the human decides."
        )

    if _cache is not None and _cache[0] == mtime:
        return _cache[1]

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return (
            "You are a research scout. You hunt for competitor and product news, "
            "score what you find, and hand the results to a human who decides. "
            "You never act on a find. You recommend; the human decides."
        )

    _cache = (mtime, content)
    return content


def system_prompt() -> str:
    """The scout's system prompt, loaded from DOCTRINE.md.

    This is the function the research loop calls. It returns the current
    doctrine, reloading if the file has changed.
    """
    return load_document()


def invalidate_cache() -> None:
    """Force a reload on the next call.

    Useful for tests, or when you know the file has changed but the mtime
    granularity is too coarse to detect it.
    """
    global _cache
    _cache = None
