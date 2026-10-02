"""The override store.

An operator-set value in the database shadows the file default, and takes
effect on the next run without a restart.

The store is a JSON file in state/. It is keyed by an arbitrary string, not
a foreign key to the agent list. Extra documents belong to an agent but are
not the agent, so the key is "<agent>_doctrine", not "<agent>".

The cache is in-process. When an override is written, the cache is cleared
(full refresh). Full refresh over per-key invalidation: caches this small
aren't worth the bug surface of partial updates.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from ..paths import STATE_DIR

OVERRIDES_PATH = STATE_DIR / "scout_overrides.json"

# In-process cache: key -> (content, mtime). Loaded at startup, cleared on write.
_cache: dict[str, tuple[str, float]] = {}

# Callbacks to notify when an override is written. Each callback takes no
# arguments and returns nothing. Used to clear caches in other processes.
_listeners: list[Callable[[], None]] = []


def _read_store() -> dict:
    """Read the override store, returning an empty dict if missing."""
    try:
        return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_store(data: dict) -> None:
    """Write the override store, creating the directory if needed."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_override(key: str) -> str | None:
    """Get the override for a key, or None if not set.

    Checks the cache first. If not cached, reads from the store and caches.
    """
    if key in _cache:
        return _cache[key][0]

    store = _read_store()
    entry = store.get(key)
    if entry is None:
        return None

    content = entry.get("content", "")
    updated_at = entry.get("updated_at", 0.0)
    _cache[key] = (content, updated_at)
    return content


def set_override(key: str, content: str) -> None:
    """Set an override for a key.

    Writes to the store, updates the cache, and notifies all listeners.
    The next run will use this override instead of the file default.
    """
    store = _read_store()
    store[key] = {
        "content": content,
        "updated_at": time.time(),
    }
    _write_store(store)

    # Update the cache.
    _cache[key] = (content, store[key]["updated_at"])

    # Notify all listeners (full refresh).
    for listener in _listeners:
        try:
            listener()
        except Exception:  # noqa: BLE001 — a broken listener must not stop the write
            pass


def delete_override(key: str) -> bool:
    """Delete an override for a key. Returns True if one existed."""
    store = _read_store()
    if key not in store:
        return False

    del store[key]
    _write_store(store)

    # Remove from cache.
    _cache.pop(key, None)

    # Notify all listeners.
    for listener in _listeners:
        try:
            listener()
        except Exception:  # noqa: BLE001
            pass

    return True


def has_override(key: str) -> bool:
    """Whether an override exists for a key."""
    return get_override(key) is not None


def clear_cache() -> None:
    """Clear the entire cache.

    Called when an override is written, so the next read picks up the new value.
    Full refresh over per-key invalidation.
    """
    _cache.clear()


def add_listener(callback: Callable[[], None]) -> None:
    """Register a callback to be notified when an override is written."""
    _listeners.append(callback)


def remove_listener(callback: Callable[[], None]) -> None:
    """Remove a previously registered callback."""
    try:
        _listeners.remove(callback)
    except ValueError:
        pass


def effective_document(key: str, path: Path) -> str:
    """The effective document: override or file.

    This is the read that doesn't care. Callers never branch on which one they
    got. If an override exists, it is used. Otherwise, the file is loaded.
    """
    override = get_override(key)
    if override is not None:
        return override

    # Import here to avoid a circular import.
    from .doctrine import load_document

    return load_document(path)
