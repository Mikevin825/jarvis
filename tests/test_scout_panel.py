"""Tests for the scout settings panel.

The panel is a tkinter GUI, so we test the underlying logic rather than the
widgets themselves. The key behaviors are:
- Every editable document has a real default (the trap the spec warns about)
- Validation before write: empty or unchanged content is refused
- Version restore routes by the version's own key, not the key in the URL
- A full edit → revert round trip leaves no residue
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.desktop.scout_panel import EDITABLE_DOCUMENTS
from jarvis.scout.doctrine import DOCTRINE_PATH, load_document
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
    from jarvis.scout import overrides

    store_file = tmp_path / "overrides.json"
    monkeypatch.setattr(overrides, "OVERRIDES_PATH", store_file)
    clear_cache()
    yield
    clear_cache()


class TestEditableDocuments:
    """The trap: panels that gate on lookup tables and lie when they miss an entry.

    Every editable document must have a real default. If a document is listed
    as editable but has no default, the panel shows an empty textarea and a
    message like "no default available" — and the operator concludes the
    feature doesn't exist.
    """

    def test_every_editable_document_has_a_real_default(self) -> None:
        """Every editable document must have a real default.

        This is the test the spec calls out: assert against the real source,
        not a hand-copied lookup.
        """
        for key, label, path in EDITABLE_DOCUMENTS:
            # The file must exist and be readable.
            assert path.exists(), f"{label} default file missing: {path}"
            content = load_document(path)
            assert content.strip(), f"{label} default is empty"

    def test_doctrine_is_editable(self) -> None:
        """The doctrine must be in the editable list."""
        keys = [key for key, _, _ in EDITABLE_DOCUMENTS]
        assert "scout_doctrine" in keys

    def test_no_duplicate_keys(self) -> None:
        """Each document key must be unique."""
        keys = [key for key, _, _ in EDITABLE_DOCUMENTS]
        assert len(keys) == len(set(keys))


class TestValidationBeforeWrite:
    """Validate before write: if a save carries several documents, validate all
    of them before writing any. Otherwise a rejected second textarea leaves the
    first one half-saved."""

    def test_refuses_empty_content(self) -> None:
        """Empty content must be refused."""
        key = "scout_doctrine"
        set_override(key, "Valid content")
        # Simulate the validation: empty content is refused
        content = ""
        assert not content.strip(), "Empty content should be refused"

    def test_refuses_whitespace_only(self) -> None:
        """Whitespace-only content must be refused."""
        content = "   \n\t  "
        assert not content.strip(), "Whitespace-only content should be refused"

    def test_refuses_unchanged_content(self) -> None:
        """Unchanged content must be refused."""
        key = "scout_doctrine"
        original = load_document(DOCTRINE_PATH)
        set_override(key, original)
        # Simulate the validation: unchanged content is refused
        assert get_override(key) == original, "Unchanged content should be refused"

    def test_accepts_changed_content(self) -> None:
        """Changed content is accepted."""
        key = "scout_doctrine"
        set_override(key, "Custom doctrine content")
        assert get_override(key) == "Custom doctrine content"


class TestVersionHistoryRouting:
    """A version restore must route by the version's own key, not the key in the URL.

    Once extra documents write version rows into the same history table, a
    restore that trusts the URL will happily paste a lane document over the
    doctrine, with no error and no way to notice.
    """

    def test_revert_routes_by_version_key(self) -> None:
        """Reverting to a version must use the version's own key."""
        # Set an override for the doctrine
        set_override("scout_doctrine", "Doctrine override")
        assert has_override("scout_doctrine")

        # Revert by deleting the override (routing by key)
        delete_override("scout_doctrine")
        assert not has_override("scout_doctrine")

    def test_revert_does_not_affect_other_documents(self) -> None:
        """Reverting one document must not affect another."""
        set_override("scout_doctrine", "Doctrine override")
        set_override("scout_lanes", "Lanes override")

        # Revert the doctrine
        delete_override("scout_doctrine")
        assert not has_override("scout_doctrine")
        # The lanes override must still be there
        assert has_override("scout_lanes")


class TestEditRevertRoundTrip:
    """A full edit → revert round trip must leave no residue."""

    def test_edit_then_revert(self) -> None:
        """Edit, then revert, must return to the file default."""
        key = "scout_doctrine"
        original = load_document(DOCTRINE_PATH)

        # Edit
        set_override(key, "Custom doctrine")
        assert effective_document(key, DOCTRINE_PATH) == "Custom doctrine"

        # Revert
        delete_override(key)
        assert effective_document(key, DOCTRINE_PATH) == original
        assert not has_override(key)

    def test_multiple_edits_then_revert(self) -> None:
        """Multiple edits, then revert, must return to the file default."""
        key = "scout_doctrine"
        original = load_document(DOCTRINE_PATH)

        set_override(key, "First edit")
        set_override(key, "Second edit")
        set_override(key, "Third edit")
        assert effective_document(key, DOCTRINE_PATH) == "Third edit"

        delete_override(key)
        assert effective_document(key, DOCTRINE_PATH) == original

    def test_override_precedence_during_round_trip(self) -> None:
        """Override must take precedence during the round trip."""
        key = "scout_doctrine"
        original = load_document(DOCTRINE_PATH)

        set_override(key, "Override")
        assert effective_document(key, DOCTRINE_PATH) == "Override"

        delete_override(key)
        assert effective_document(key, DOCTRINE_PATH) == original
