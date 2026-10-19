"""WhatsApp — a read-only window onto the real account.

How this works, and why it is shaped this way.

The WhatsApp connection itself already exists on this machine: a Baileys bridge
(`~/.hermes/hermes-agent/scripts/whatsapp-bridge/`) is paired to the account and
running on localhost:3000. Hermes's own gateway consumes it.

That bridge offers `GET /messages`, but that endpoint **drains** a queue — it is
a destructive read built for one consumer. Polling it from here would steal
messages out from under Hermes's gateway. So JARVIS does not touch it.

Instead, JARVIS reads the messages Hermes has already persisted, in SQLite
read-only mode:

    ~/.hermes/state.db
      sessions(session_key LIKE 'agent:%:whatsapp:%')
        └── messages(session_id = sessions.id)

`mode=ro` is the point: this connection physically cannot write, so a bug here
can never corrupt Hermes's session store. Nothing is consumed, nothing is
acknowledged, nothing races.

**There is no send.** Not gated, not disabled — absent. A real account means
real messages reach real people, and the strongest guarantee that JARVIS cannot
send one is that the code to do it does not exist. Replies are drafted to the
local outbox and the tool result says so in as many words.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .base import Tool, ToolError

# The Hermes state database. Read-only, always.
HERMES_STATE_DB = Path.home() / ".hermes" / "state.db"

# How many messages to pull before trimming to the caller's limit. The store
# interleaves tool traffic, so reading a window and filtering afterwards gives a
# better conversation view than LIMIT-ing the raw rows.
_SCAN_WINDOW = 400


@dataclass(frozen=True)
class ChatMessage:
    """One message, as read from Hermes's store."""

    session_key: str
    chat_id: str
    chat_name: str
    is_group: bool
    role: str
    content: str
    timestamp: float

    @property
    def when(self) -> str:
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc).astimezone().strftime(
            "%Y-%m-%d %H:%M"
        )

    @property
    def sender(self) -> str:
        """Who sent it.

        The stored `role` is the conversation role: 'user' is the person on the
        other end, 'assistant' is JARVIS/Hermes. We report that rather than
        inventing a display name we do not have.
        """
        return "them" if self.role == "user" else "me"


@dataclass(frozen=True)
class Chat:
    """A WhatsApp conversation."""

    session_key: str
    chat_id: str
    name: str
    is_group: bool
    message_count: int
    last_at: float

    @property
    def last_when(self) -> str:
        if not self.last_at:
            return "never"
        return datetime.fromtimestamp(self.last_at, tz=timezone.utc).astimezone().strftime(
            "%Y-%m-%d %H:%M"
        )


class WhatsAppUnavailable(ToolError):
    """The store is missing or unreadable, with a message that says what to do."""


def _connect(db_path: Path = HERMES_STATE_DB) -> sqlite3.Connection:
    """Open the Hermes state database read-only.

    `mode=ro` is enforced by SQLite itself, not by convention: if a future edit
    tries to write through this handle, SQLite refuses.
    """
    if not db_path.exists():
        raise WhatsAppUnavailable(
            f"No Hermes state database at {db_path}. WhatsApp is connected "
            f"through Hermes's bridge, so there is nothing to read until Hermes "
            f"has run at least once."
        )
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise WhatsAppUnavailable(f"Could not open the message store: {exc}") from exc
    con.row_factory = sqlite3.Row
    return con


def list_chats(limit: int = 20, db_path: Path = HERMES_STATE_DB) -> list[Chat]:
    """Every WhatsApp conversation Hermes knows about, most recent first."""
    con = _connect(db_path)
    try:
        rows = con.execute(
            """
            SELECT s.session_key  AS session_key,
                   s.chat_id      AS chat_id,
                   s.chat_type    AS chat_type,
                   s.display_name AS display_name,
                   s.message_count AS message_count,
                   COALESCE(s.last_activity_at, s.started_at, 0) AS last_at
            FROM sessions s
            WHERE s.session_key LIKE 'agent:%:whatsapp:%'
            ORDER BY last_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise WhatsAppUnavailable(f"Could not read the message store: {exc}") from exc
    finally:
        con.close()

    chats: list[Chat] = []
    for row in rows:
        key = row["session_key"] or ""
        # The human-readable half of the key is the fallback name; the session's
        # own display_name wins when it has one.
        key_tail = key.rsplit(":", 1)[-1]
        chat_id = row["chat_id"] or key_tail
        name = row["display_name"] or chat_id.split("@")[0]
        chats.append(
            Chat(
                session_key=key,
                chat_id=chat_id,
                name=name,
                is_group=(row["chat_type"] or "") == "group",
                message_count=row["message_count"] or 0,
                last_at=row["last_at"] or 0.0,
            )
        )
    return chats


def _session_keys_for(chat_id: str, con: sqlite3.Connection) -> list[str]:
    """Every session key that could belong to `chat_id`.

    A chat is reachable by its jid (`145024536850578@lid`), by a bare number, or
    by the key's own trailing segment, so all three are tried.
    """
    bare = chat_id.split("@")[0]
    patterns = [
        f"agent:%:whatsapp:%:{chat_id}",
        f"agent:%:whatsapp:%:{bare}",
        f"agent:%:whatsapp:%:{bare}%",
    ]
    found: list[str] = []
    for pattern in patterns:
        rows = con.execute(
            "SELECT session_key FROM sessions WHERE session_key LIKE ?",
            (pattern,),
        ).fetchall()
        for row in rows:
            key = row["session_key"]
            if key and key not in found:
                found.append(key)
    # Also match on the stored chat_id column, which holds the jid.
    rows = con.execute(
        "SELECT session_key FROM sessions WHERE chat_id = ? OR chat_id = ?",
        (chat_id, bare),
    ).fetchall()
    for row in rows:
        key = row["session_key"]
        if key and key not in found:
            found.append(key)
    return found


def _messages_for_keys(
    keys: list[str], limit: int, con: sqlite3.Connection
) -> list[ChatMessage]:
    """Recent conversational messages for the given session keys."""
    if not keys:
        return []

    placeholders = ",".join("?" for _ in keys)
    rows = con.execute(
        f"""
        SELECT s.session_key AS session_key,
               s.chat_id      AS chat_id,
               s.chat_type    AS chat_type,
               s.display_name AS display_name,
               m.role         AS role,
               m.content      AS content,
               m.timestamp    AS timestamp
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE s.session_key IN ({placeholders})
          AND m.content IS NOT NULL AND TRIM(m.content) != ''
          AND m.role IN ('user', 'assistant')
        ORDER BY m.timestamp DESC
        LIMIT ?
        """,
        (*keys, _SCAN_WINDOW),
    ).fetchall()

    out: list[ChatMessage] = []
    for row in reversed(rows):  # oldest first, so it reads like a conversation
        key = row["session_key"] or ""
        out.append(
            ChatMessage(
                session_key=key,
                chat_id=row["chat_id"] or key.rsplit(":", 1)[-1],
                chat_name=row["display_name"] or "",
                is_group=(row["chat_type"] or "") == "group",
                role=row["role"],
                content=row["content"] or "",
                timestamp=row["timestamp"] or 0.0,
            )
        )
    return out[-limit:] if limit > 0 else out


def read_chat(chat_id: str, limit: int = 20, db_path: Path = HERMES_STATE_DB) -> list[ChatMessage]:
    """The most recent messages in one conversation, oldest-first for reading."""
    if not (chat_id or "").strip():
        raise ToolError("Give me a chat id, or call list_whatsapp_chats first.")

    con = _connect(db_path)
    try:
        keys = _session_keys_for(str(chat_id).strip(), con)
        return _messages_for_keys(keys, limit, con)
    except sqlite3.Error as exc:
        raise WhatsAppUnavailable(f"Could not read the message store: {exc}") from exc
    finally:
        con.close()


def search_chats(query: str, limit: int = 20, db_path: Path = HERMES_STATE_DB) -> list[ChatMessage]:
    """Search WhatsApp message bodies for a string."""
    query = (query or "").strip()
    if not query:
        raise ToolError("Give me something to search for.")

    con = _connect(db_path)
    try:
        rows = con.execute(
            """
            SELECT s.session_key AS session_key,
                   s.chat_id      AS chat_id,
                   s.chat_type    AS chat_type,
                   s.display_name AS display_name,
                   m.role         AS role,
                   m.content      AS content,
                   m.timestamp    AS timestamp
            FROM messages m
            JOIN sessions s ON s.id = m.session_id
            WHERE s.session_key LIKE 'agent:%:whatsapp:%'
              AND m.content LIKE ?
              AND m.role IN ('user', 'assistant')
            ORDER BY m.timestamp DESC
            LIMIT ?
            """,
            (f"%{query}%", limit),
        ).fetchall()
    except sqlite3.Error as exc:
        raise WhatsAppUnavailable(f"Could not read the message store: {exc}") from exc
    finally:
        con.close()

    out: list[ChatMessage] = []
    for row in rows:
        key = row["session_key"] or ""
        out.append(
            ChatMessage(
                session_key=key,
                chat_id=row["chat_id"] or key.rsplit(":", 1)[-1],
                chat_name=row["display_name"] or "",
                is_group=(row["chat_type"] or "") == "group",
                role=row["role"],
                content=row["content"] or "",
                timestamp=row["timestamp"] or 0.0,
            )
        )
    return out


def bridge_health(timeout: float = 3.0) -> dict:
    """Whether the WhatsApp bridge is up, for an honest status line.

    Read-only and non-destructive: /health reports connection state without
    touching the message queue.
    """
    import httpx

    try:
        resp = httpx.get("http://localhost:3000/health", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001 — status must never raise
        return {"status": "unreachable", "error": str(exc)[:120]}


# -- tools -----------------------------------------------------------------

def _list_chats_tool(limit: int = 20) -> str:
    health = bridge_health()
    state = health.get("status", "unknown")
    try:
        chats = list_chats(limit=limit)
    except WhatsAppUnavailable as exc:
        raise ToolError(str(exc)) from exc

    if not chats:
        return (
            f"WhatsApp bridge: {state}. No WhatsApp conversations are stored yet. "
            "Nothing has come through the bridge, so there is nothing to show."
        )

    lines = [f"WhatsApp bridge: {state}", f"{len(chats)} conversation(s):", ""]
    for chat in chats:
        kind = "group" if chat.is_group else "direct"
        lines.append(
            f"  {chat.name}  ({kind})  chat_id: {chat.chat_id}  "
            f"{chat.message_count} stored  last: {chat.last_when}"
        )
    return "\n".join(lines)


def _read_chat_tool(chat_id: str, limit: int = 20) -> str:
    try:
        messages = read_chat(chat_id, limit=limit)
    except WhatsAppUnavailable as exc:
        raise ToolError(str(exc)) from exc

    if not messages:
        return f"No stored messages for chat '{chat_id}'."

    lines = [f"Chat {chat_id} — last {len(messages)} message(s):", ""]
    for m in messages:
        lines.append(f"[{m.when}] {m.sender}: {m.content}")
    return "\n".join(lines)


def _search_chats_tool(query: str, limit: int = 20) -> str:
    try:
        hits = search_chats(query, limit=limit)
    except WhatsAppUnavailable as exc:
        raise ToolError(str(exc)) from exc

    if not hits:
        return f"No WhatsApp messages matching '{query}'."
    lines = [f"{len(hits)} message(s) matching '{query}':", ""]
    for m in hits:
        lines.append(f"[{m.when}] {m.chat_id} — {m.sender}: {m.content[:160]}")
    return "\n".join(lines)


def _draft_reply_tool(chat_id: str, body: str) -> str:
    """Draft a reply to the local outbox.

    This does not send, and there is no tool that does. The result says so
    plainly, because a model that believes a message went out will tell the user
    it went out — and on a real account that is the worst possible failure.
    """
    from ..paths import MESSAGES_FILE, ensure_dirs

    if not (chat_id or "").strip():
        raise ToolError("Give me the chat id to reply to.")
    if not (body or "").strip():
        raise ToolError("Give me the reply text.")

    ensure_dirs()
    try:
        store = (
            json.loads(MESSAGES_FILE.read_text(encoding="utf-8"))
            if MESSAGES_FILE.exists()
            else {"inbox": [], "outbox": [], "drafts": [], "next_id": 1}
        )
    except json.JSONDecodeError:
        store = {"inbox": [], "outbox": [], "drafts": [], "next_id": 1}

    draft_id = f"d{store.get('next_id', 1)}"
    store["next_id"] = store.get("next_id", 1) + 1
    store.setdefault("drafts", []).append(
        {
            "id": draft_id,
            "to": f"whatsapp:{chat_id}",
            "channel": "whatsapp",
            "body": body,
            "created": datetime.now().isoformat(timespec="seconds"),
        }
    )
    MESSAGES_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")

    return (
        f"Drafted reply {draft_id} to WhatsApp chat {chat_id}. "
        "NOT SENT — JARVIS has no ability to send WhatsApp messages; the draft "
        "is saved locally only. Tell the user the draft is ready to copy and "
        "send themselves, and do not imply it was delivered."
    )


def build() -> list[Tool]:
    return [
        Tool(
            name="list_whatsapp_chats",
            description=(
                "Use this to list the WhatsApp conversations on the account, most "
                "recent first. These are real messages from the user's real "
                "WhatsApp, read from the local store. Call it when the user asks "
                "about their WhatsApp messages or who has been messaging them."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "limit": {
                        "type": "INTEGER",
                        "description": "How many conversations to list (default 20).",
                    }
                },
            },
            func=_list_chats_tool,
        ),
        Tool(
            name="read_whatsapp_chat",
            description=(
                "Use this to read the recent messages in one WhatsApp conversation. "
                "Get the chat_id from list_whatsapp_chats first. Reading never "
                "sends anything and never marks messages as read."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "chat_id": {
                        "type": "STRING",
                        "description": "The chat id from list_whatsapp_chats.",
                    },
                    "limit": {
                        "type": "INTEGER",
                        "description": "How many messages to read (default 20).",
                    },
                },
                "required": ["chat_id"],
            },
            func=_read_chat_tool,
        ),
        Tool(
            name="search_whatsapp",
            description=(
                "Use this to search the user's WhatsApp messages for a word or "
                "phrase — e.g. when they ask 'did anyone mention the invoice'. "
                "Searches message bodies only."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "query": {"type": "STRING", "description": "What to search for."},
                    "limit": {
                        "type": "INTEGER",
                        "description": "Maximum matches to return (default 20).",
                    },
                },
                "required": ["query"],
            },
            func=_search_chats_tool,
        ),
        Tool(
            name="draft_whatsapp_reply",
            description=(
                "Use this to write a reply to a WhatsApp conversation. IMPORTANT: "
                "this does NOT send. JARVIS has no ability to send WhatsApp "
                "messages at all — the draft is saved locally for the user to copy "
                "and send themselves. Always tell the user the draft is ready and "
                "not sent. Never imply a message was delivered."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "chat_id": {"type": "STRING", "description": "The chat to reply to."},
                    "body": {"type": "STRING", "description": "The reply text."},
                },
                "required": ["chat_id", "body"],
            },
            func=_draft_reply_tool,
        ),
    ]


__all__ = [
    "Chat",
    "ChatMessage",
    "HERMES_STATE_DB",
    "WhatsAppUnavailable",
    "bridge_health",
    "build",
    "list_chats",
    "read_chat",
    "search_chats",
]
