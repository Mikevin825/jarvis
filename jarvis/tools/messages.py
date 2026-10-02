"""Messaging — the "answer my messages" capability.

Honest scope: this is backed by a **local** store (`state/messages.json`), not by
a live mail or SMS account. That keeps the capability real and testable now;
connecting it to an actual provider is a credential-and-API task for later, and
the tool shape will not change when that happens.

Sending is consequential and gated. Drafting and reading are safe.
"""

from __future__ import annotations

import json
from datetime import datetime

from ..paths import MESSAGES_FILE, ensure_dirs
from .base import Tool, ToolError

_PARAMS_LIST = {
    "type": "OBJECT",
    "properties": {
        "unread_only": {
            "type": "BOOLEAN",
            "description": "Set true to list only unread messages.",
        }
    },
}

_PARAMS_DRAFT = {
    "type": "OBJECT",
    "properties": {
        "to": {"type": "STRING", "description": "Who the message is for."},
        "body": {"type": "STRING", "description": "The text of the message."},
        "subject": {"type": "STRING", "description": "Optional subject line."},
    },
    "required": ["to", "body"],
}

_PARAMS_SEND = {
    "type": "OBJECT",
    "properties": {
        "draft_id": {
            "type": "STRING",
            "description": "The id of a draft to send, from draft_message.",
        },
        "to": {"type": "STRING", "description": "Recipient, if not using a draft."},
        "body": {"type": "STRING", "description": "Message body, if not using a draft."},
    },
}


def _load() -> dict:
    ensure_dirs()
    if not MESSAGES_FILE.exists():
        return {"inbox": [], "outbox": [], "drafts": [], "next_id": 1}
    try:
        return json.loads(MESSAGES_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolError(
            "The local message store is unreadable (corrupt JSON). "
            f"It is at {MESSAGES_FILE}."
        ) from exc


def _save(store: dict) -> None:
    ensure_dirs()
    MESSAGES_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")


def list_messages(unread_only: bool = False) -> str:
    """List inbox messages.

    The inbox is a local file. There is no connected mail account, so this is
    whatever has been placed there — not the user's real email.
    """
    store = _load()
    inbox = store.get("inbox", [])
    if unread_only:
        inbox = [m for m in inbox if not m.get("read")]
    if not inbox:
        return "The inbox is empty." if not unread_only else "No unread messages."
    lines = []
    for m in inbox:
        flag = "" if m.get("read") else "[unread] "
        subject = f" — {m['subject']}" if m.get("subject") else ""
        lines.append(
            f"{flag}#{m['id']} from {m.get('from', 'unknown')}{subject}: "
            f"{(m.get('body') or '')[:80]}"
        )
    return f"{len(inbox)} message(s):\n" + "\n".join(lines)


def read_message(message_id: str) -> str:
    store = _load()
    for m in store.get("inbox", []):
        if str(m.get("id")) == str(message_id):
            m["read"] = True
            _save(store)
            return (
                f"From {m.get('from', 'unknown')}"
                + (f"\nSubject: {m['subject']}" if m.get("subject") else "")
                + f"\n\n{m.get('body', '')}"
            )
    raise ToolError(f"There is no message #{message_id} in the inbox.")


def draft_message(to: str, body: str, subject: str | None = None) -> str:
    """Write a draft. Safe: nothing leaves the machine."""
    store = _load()
    draft_id = f"d{store['next_id']}"
    store["next_id"] += 1
    store.setdefault("drafts", []).append(
        {
            "id": draft_id,
            "to": to,
            "subject": subject,
            "body": body,
            "created": datetime.now().isoformat(timespec="seconds"),
        }
    )
    _save(store)
    return (
        f"Drafted message {draft_id} to {to}. It has NOT been sent. "
        "Show the user the draft and ask whether to send it."
    )


def list_drafts() -> str:
    store = _load()
    drafts = store.get("drafts", [])
    if not drafts:
        return "There are no drafts."
    return "\n".join(
        f"{d['id']} to {d['to']}: {(d.get('body') or '')[:70]}" for d in drafts
    )


def send_message(draft_id: str | None = None, to: str | None = None, body: str | None = None) -> str:
    """Send a message. Consequential — never runs without confirmation.

    IMPORTANT — this does not actually send anything. It moves a draft into the
    local outbox file. The tool result says so in as many words, because a model
    that believes a message went out will tell the user it went out. Overstating
    what happened is worse than the missing capability.
    """
    store = _load()

    if draft_id:
        draft = next(
            (d for d in store.get("drafts", []) if str(d["id"]) == str(draft_id)), None
        )
        if draft is None:
            raise ToolError(f"There is no draft called '{draft_id}'.")
        to = draft["to"]
        body = draft["body"]
        subject = draft.get("subject")
        store["drafts"] = [d for d in store["drafts"] if d["id"] != draft_id]
    elif to and body:
        subject = None
    else:
        raise ToolError("Give me either a draft_id, or both a recipient and a body.")

    store.setdefault("outbox", []).append(
        {
            "to": to,
            "subject": subject,
            "body": body,
            "queued": datetime.now().isoformat(timespec="seconds"),
            "delivered": False,
        }
    )
    _save(store)
    return (
        f"Queued in the local outbox: to {to}. "
        "NOT DELIVERED — this build has no mail or messaging account connected, "
        "so nothing left this machine. Tell the user it is sitting in the outbox "
        "and has not been sent to anyone."
    )


def build() -> list[Tool]:
    return [
        Tool(
            name="list_messages",
            description=(
                "Use this to see messages in the local inbox file. NOTE: no mail "
                "or messaging account is connected in this build, so this is NOT "
                "the user's real email — it is a local store. Call it when the "
                "user asks what messages they have, and be clear about that."
            ),
            parameters=_PARAMS_LIST,
            func=list_messages,
        ),
        Tool(
            name="read_message",
            description=(
                "Use this to read one message in full by its id, and mark it read."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "message_id": {"type": "STRING", "description": "The message id."}
                },
                "required": ["message_id"],
            },
            func=read_message,
        ),
        Tool(
            name="draft_message",
            description=(
                "Use this to compose a message without sending it. This is the "
                "safe way to write something for the user — it never sends."
            ),
            parameters=_PARAMS_DRAFT,
            func=draft_message,
        ),
        Tool(
            name="list_drafts",
            description="Use this to list the messages the user has drafted but not sent.",
            parameters={"type": "OBJECT", "properties": {}},
            func=list_drafts,
        ),
        Tool(
            name="send_message",
            description=(
                "Use this to move a drafted message into the outbox. NOTE: this "
                "build has NO mail or messaging account connected, so this does "
                "not deliver anything to anyone — it only writes the message to "
                "the local outbox file. Always tell the user it was queued and "
                "not sent. Requires the user's explicit confirmation first."
            ),
            parameters=_PARAMS_SEND,
            func=send_message,
            consequential=True,
            confirm_prompt=(
                "queues a message in the local outbox. This build has no mail or "
                "messaging account connected, so nothing will actually be "
                "delivered to anyone"
            ),
        ),
    ]
