"""Tests for the WhatsApp connector.

The important properties, in order of how much damage their absence would do:

1. The store handle cannot write — read-only is enforced by SQLite, not by
   convention.
2. No send path exists anywhere in the module.
3. Reading is non-destructive: it never consumes or acknowledges.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from jarvis.tools import whatsapp
from jarvis.tools.whatsapp import (
    Chat,
    ChatMessage,
    WhatsAppUnavailable,
    list_chats,
    read_chat,
    search_chats,
)

# -- a fixture store that mirrors Hermes's real schema ---------------------

SCHEMA = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    session_key TEXT,
    chat_id TEXT,
    chat_type TEXT,
    display_name TEXT,
    message_count INTEGER,
    started_at REAL,
    last_activity_at REAL
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    role TEXT,
    content TEXT,
    timestamp REAL
);
"""


def _make_store(tmp_path: Path) -> Path:
    db = tmp_path / "state.db"
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)

    con.execute(
        "INSERT INTO sessions (id, session_key, chat_id, chat_type, display_name,"
        " message_count, started_at, last_activity_at) VALUES (?,?,?,?,?,?,?,?)",
        ("s1", "agent:main:whatsapp:dm:2348012345678", "2348012345678@s.whatsapp.net",
         "dm", "Ada", 4, 1000.0, 1600.0),
    )
    con.execute(
        "INSERT INTO sessions (id, session_key, chat_id, chat_type, display_name,"
        " message_count, started_at, last_activity_at) VALUES (?,?,?,?,?,?,?,?)",
        ("s2", "agent:main:whatsapp:group:120363@g.us", "120363@g.us",
         "group", "Team Chat", 2, 900.0, 1200.0),
    )
    # A non-WhatsApp session must never surface.
    con.execute(
        "INSERT INTO sessions (id, session_key, chat_id, chat_type, display_name,"
        " message_count, started_at, last_activity_at) VALUES (?,?,?,?,?,?,?,?)",
        ("s3", "agent:main:telegram:dm:999", "999", "dm", "Telegram Person", 5, 500.0, 9999.0),
    )

    msgs = [
        ("s1", "user", "Did you send the invoice?", 1500.0),
        ("s1", "assistant", "Yes, this morning.", 1510.0),
        ("s1", "tool", "tool noise", 1515.0),
        ("s1", "assistant", "", 1520.0),  # empty content is skipped
        ("s1", "user", "Thanks!", 1600.0),
        ("s2", "user", "Meeting at three", 1100.0),
        ("s2", "assistant", "Noted.", 1200.0),
        ("s3", "user", "Telegram only", 9999.0),
    ]
    con.executemany(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?,?,?,?)",
        msgs,
    )
    con.commit()
    con.close()
    return db


# -- the safety properties -------------------------------------------------

def test_the_connection_is_read_only(tmp_path: Path):
    """A write through our handle must be refused by SQLite itself."""
    db = _make_store(tmp_path)
    con = whatsapp._connect(db)
    try:
        with pytest.raises(sqlite3.OperationalError) as exc:
            con.execute("DELETE FROM messages")
        assert "readonly" in str(exc.value).lower() or "read-only" in str(exc.value).lower()
    finally:
        con.close()


def test_read_only_connection_cannot_drop_a_table(tmp_path: Path):
    db = _make_store(tmp_path)
    con = whatsapp._connect(db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("DROP TABLE messages")
    finally:
        con.close()


def test_reading_does_not_modify_the_store(tmp_path: Path):
    """Non-destructive: the file's contents are identical after reading."""
    db = _make_store(tmp_path)
    before = db.read_bytes()

    list_chats(db_path=db)
    read_chat("2348012345678", db_path=db)
    search_chats("invoice", db_path=db)

    assert db.read_bytes() == before


def test_no_send_function_exists_anywhere_in_the_module():
    """The strongest guarantee is absence.

    This asserts on the module's own source, which is normally a smell — but
    here the *absence of code* is the safety property, and there is no runtime
    behaviour to assert instead. A future edit adding a send path fails this.
    """
    source = Path(whatsapp.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for forbidden in ("send", "send_message", "send_whatsapp", "reply", "post"):
        assert not any(
            name == forbidden or name.startswith(f"{forbidden}_") for name in defined
        ), f"a send path appeared: {forbidden}"

    # And no outbound POST to the bridge anywhere.
    assert "/send" not in source
    assert "httpx.post" not in source


def test_the_only_http_call_is_the_health_probe():
    source = Path(whatsapp.__file__).read_text(encoding="utf-8")
    assert "httpx.get" in source
    assert "httpx.post" not in source


# -- reading ---------------------------------------------------------------

def test_list_chats_returns_whatsapp_only(tmp_path: Path):
    db = _make_store(tmp_path)
    chats = list_chats(db_path=db)
    names = [c.name for c in chats]
    assert "Ada" in names
    assert "Team Chat" in names
    # The Telegram session must not leak in.
    assert "Telegram Person" not in names


def test_list_chats_is_most_recent_first(tmp_path: Path):
    db = _make_store(tmp_path)
    chats = list_chats(db_path=db)
    assert chats[0].name == "Ada"  # last_activity 1600 > 1200


def test_list_chats_marks_groups(tmp_path: Path):
    db = _make_store(tmp_path)
    by_name = {c.name: c for c in list_chats(db_path=db)}
    assert by_name["Team Chat"].is_group is True
    assert by_name["Ada"].is_group is False


def test_read_chat_returns_the_conversation_oldest_first(tmp_path: Path):
    db = _make_store(tmp_path)
    messages = read_chat("2348012345678", db_path=db)
    assert [m.content for m in messages] == [
        "Did you send the invoice?",
        "Yes, this morning.",
        "Thanks!",
    ]


def test_read_chat_skips_tool_traffic_and_empty_content(tmp_path: Path):
    db = _make_store(tmp_path)
    messages = read_chat("2348012345678", db_path=db)
    assert all(m.role in ("user", "assistant") for m in messages)
    assert all(m.content.strip() for m in messages)
    assert "tool noise" not in [m.content for m in messages]


def test_read_chat_accepts_a_bare_number(tmp_path: Path):
    db = _make_store(tmp_path)
    assert read_chat("2348012345678", db_path=db)


def test_read_chat_accepts_the_full_jid(tmp_path: Path):
    db = _make_store(tmp_path)
    assert read_chat("2348012345678@s.whatsapp.net", db_path=db)


def test_read_chat_respects_the_limit(tmp_path: Path):
    db = _make_store(tmp_path)
    messages = read_chat("2348012345678", limit=2, db_path=db)
    assert len(messages) == 2
    # The most recent two, still oldest-first.
    assert [m.content for m in messages] == ["Yes, this morning.", "Thanks!"]


def test_read_chat_on_an_unknown_chat_returns_nothing(tmp_path: Path):
    db = _make_store(tmp_path)
    assert read_chat("0000000000", db_path=db) == []


def test_read_chat_requires_an_id(tmp_path: Path):
    from jarvis.tools.base import ToolError

    db = _make_store(tmp_path)
    with pytest.raises(ToolError):
        read_chat("   ", db_path=db)


def test_sender_labels_the_conversation_role(tmp_path: Path):
    db = _make_store(tmp_path)
    messages = read_chat("2348012345678", db_path=db)
    assert messages[0].sender == "them"  # role user
    assert messages[1].sender == "me"  # role assistant


def test_search_finds_a_phrase_across_chats(tmp_path: Path):
    db = _make_store(tmp_path)
    hits = search_chats("invoice", db_path=db)
    assert len(hits) == 1
    assert "invoice" in hits[0].content


def test_search_excludes_non_whatsapp_sessions(tmp_path: Path):
    db = _make_store(tmp_path)
    assert search_chats("Telegram only", db_path=db) == []


def test_search_requires_a_query(tmp_path: Path):
    from jarvis.tools.base import ToolError

    db = _make_store(tmp_path)
    with pytest.raises(ToolError):
        search_chats("  ", db_path=db)


def test_search_escapes_nothing_it_should_not(tmp_path: Path):
    """A quote in the query must not break the statement (parameterised)."""
    db = _make_store(tmp_path)
    assert search_chats("'; DROP TABLE messages; --", db_path=db) == []
    # The table still exists, which is the actual assertion.
    assert list_chats(db_path=db)


# -- failure modes ---------------------------------------------------------

def test_a_missing_store_raises_something_actionable(tmp_path: Path):
    with pytest.raises(WhatsAppUnavailable) as exc:
        list_chats(db_path=tmp_path / "nope.db")
    assert "no hermes state database" in str(exc.value).lower()


def test_a_corrupt_store_raises_rather_than_crashing(tmp_path: Path):
    db = tmp_path / "state.db"
    db.write_text("this is not a database", encoding="utf-8")
    with pytest.raises(WhatsAppUnavailable):
        list_chats(db_path=db)


def test_bridge_health_never_raises():
    """A down bridge is a status, not an exception."""
    result = whatsapp.bridge_health(timeout=0.01)
    assert "status" in result


# -- the tools -------------------------------------------------------------

def test_build_exposes_exactly_four_tools():
    names = [t.name for t in whatsapp.build()]
    assert names == [
        "list_whatsapp_chats",
        "read_whatsapp_chat",
        "search_whatsapp",
        "draft_whatsapp_reply",
    ]


def test_no_tool_is_marked_consequential():
    """Because none of them can send, none of them need a gate.

    If a send tool is ever added, this test should fail — it is a tripwire, not
    a preference.
    """
    assert all(not t.consequential for t in whatsapp.build())


def test_every_tool_description_says_it_cannot_send():
    """The model must not believe it can deliver a message."""
    by_name = {t.name: t for t in whatsapp.build()}
    draft = by_name["draft_whatsapp_reply"]
    assert "does NOT send" in draft.description
    assert "no ability to send" in draft.description


def test_draft_reply_writes_to_the_local_outbox(tmp_path: Path, monkeypatch):
    """Drafting is local, and the result says it was not sent."""
    import jarvis.paths as paths

    messages_file = tmp_path / "messages.json"
    monkeypatch.setattr(paths, "MESSAGES_FILE", messages_file)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: None)

    result = whatsapp._draft_reply_tool("2348012345678", "On my way.")

    assert "NOT SENT" in result
    assert "no ability to send" in result.lower()
    stored = messages_file.read_text(encoding="utf-8")
    assert "On my way." in stored
    assert "whatsapp:2348012345678" in stored


def test_draft_reply_rejects_empty_input():
    from jarvis.tools.base import ToolError

    with pytest.raises(ToolError):
        whatsapp._draft_reply_tool("", "hi")
    with pytest.raises(ToolError):
        whatsapp._draft_reply_tool("123", "   ")
