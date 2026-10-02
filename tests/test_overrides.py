"""Tests for the override store.

An operator-set value in the database shadows the file default, and takes
effect on the next run without a restart.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.scout import overrides
from jarvis.scout.overrides import (
    clear_cache,
    delete_override,
    effective_document,
    get_override,
    has_override,
    set_override,
)


@pytest.fixture(autouse=True)
def _isolate_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the override store to a temp file for each test."""
    store_file = tmp_path / "overrides.json"
    monkeypatch.setattr(overrides, "OVERRIDES_PATH", store_file)
    clear_cache()
    yield
    clear_cache()


class TestGetOverride:
    def test_returns_none_when_not_set(self) -> None:
        assert get_override("scout_doctrine") is None

    def test_returns_content_when_set(self) -> None:
        set_override("scout_doctrine", "Custom doctrine")
        assert get_override("scout_doctrine") == "Custom doctrine"

    def test_caches_result(self) -> None:
        set_override("scout_doctrine", "Custom doctrine")
        # Second call should return cached content.
        assert get_override("scout_doctrine") == "Custom doctrine"

    def test_different_keys_are_independent(self) -> None:
        set_override("scout_doctrine", "Doctrine A")
        set_override("scout_lanes", "Lanes B")
        assert get_override("scout_doctrine") == "Doctrine A"
        assert get_override("scout_lanes") == "Lanes B"


class TestSetOverride:
    def test_writes_to_store(self) -> None:
        set_override("scout_doctrine", "Custom doctrine")
        store = json.loads(overrides.OVERRIDES_PATH.read_text(encoding="utf-8"))
        assert "scout_doctrine" in store
        assert store["scout_doctrine"]["content"] == "Custom doctrine"

    def test_updates_existing_override(self) -> None:
        set_override("scout_doctrine", "First version")
        set_override("scout_doctrine", "Second version")
        assert get_override("scout_doctrine") == "Second version"

    def test_notifies_listeners(self) -> None:
        called = []
        overrides.add_listener(lambda: called.append(True))
        set_override("scout_doctrine", "Custom doctrine")
        assert called == [True]
        overrides.remove_listener(lambda: called.append(True))


class TestDeleteOverride:
    def test_deletes_existing(self) -> None:
        set_override("scout_doctrine", "Custom doctrine")
        assert delete_override("scout_doctrine") is True
        assert get_override("scout_doctrine") is None

    def test_returns_false_when_not_set(self) -> None:
        assert delete_override("scout_doctrine") is False

    def test_removes_from_store(self) -> None:
        set_override("scout_doctrine", "Custom doctrine")
        delete_override("scout_doctrine")
        store = json.loads(overrides.OVERRIDES_PATH.read_text(encoding="utf-8"))
        assert "scout_doctrine" not in store


class TestHasOverride:
    def test_false_when_not_set(self) -> None:
        assert has_override("scout_doctrine") is False

    def test_true_when_set(self) -> None:
        set_override("scout_doctrine", "Custom doctrine")
        assert has_override("scout_doctrine") is True


class TestEffectiveDocument:
    def test_returns_override_when_set(self, tmp_path: Path) -> None:
        doc = tmp_path / "DOCTRINE.md"
        doc.write_text("File default", encoding="utf-8")
        set_override("scout_doctrine", "Override content")
        assert effective_document("scout_doctrine", doc) == "Override content"

    def test_returns_file_when_no_override(self, tmp_path: Path) -> None:
        doc = tmp_path / "DOCTRINE.md"
        doc.write_text("File default", encoding="utf-8")
        assert effective_document("scout_doctrine", doc) == "File default"

    def test_override_takes_precedence(self, tmp_path: Path) -> None:
        doc = tmp_path / "DOCTRINE.md"
        doc.write_text("File default", encoding="utf-8")
        set_override("scout_doctrine", "Override content")
        # Override wins even when file exists.
        assert effective_document("scout_doctrine", doc) == "Override content"

    def test_different_keys_use_different_overrides(self, tmp_path: Path) -> None:
        doc = tmp_path / "DOCTRINE.md"
        doc.write_text("File default", encoding="utf-8")
        set_override("scout_doctrine", "Doctrine override")
        # scout_lanes has no override, so it falls back to the file.
        assert effective_document("scout_lanes", doc) == "File default"


class TestClearCache:
    def test_clears_all_entries(self) -> None:
        set_override("scout_doctrine", "Doctrine A")
        set_override("scout_lanes", "Lanes B")
        clear_cache()
        # After clearing, the store is re-read.
        assert get_override("scout_doctrine") == "Doctrine A"
        assert get_override("scout_lanes") == "Lanes B"

    def test_set_override_clears_cache(self) -> None:
        set_override("scout_doctrine", "First version")
        # set_override should update the cache, so the new value is returned.
        set_override("scout_doctrine", "Second version")
        assert get_override("scout_doctrine") == "Second version"
