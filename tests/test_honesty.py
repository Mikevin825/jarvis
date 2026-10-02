"""Tools must not claim more than they do.

The messaging tool does not send anything — there is no mail account connected.
If it says "sent", the model tells the user it was sent, and the user believes
something happened that did not. These tests pin that honesty down.
"""

from __future__ import annotations

import json

import pytest


def test_send_message_does_not_claim_delivery(registry):
    from jarvis.gate import AutoApproveGate

    registry.gate = AutoApproveGate()
    result = registry.run("send_message", {"to": "mum", "body": "hello"})

    lowered = result.content.lower()
    assert "not delivered" in lowered, "the tool must not imply it was sent"
    assert "outbox" in lowered


def test_send_message_tool_description_is_honest(registry):
    tool = registry.get("send_message")
    description = tool.description.lower()
    assert "no mail or messaging account" in description or "not deliver" in description
    assert "outbox" in description


def test_confirm_prompt_is_honest(registry):
    """The user is told what will actually happen before approving."""
    tool = registry.get("send_message")
    prompt = tool.confirm_prompt.lower()
    assert "nothing will actually be delivered" in prompt or "no mail" in prompt


def test_outbox_entry_is_marked_undelivered(registry, state_dir):
    from jarvis.gate import AutoApproveGate

    registry.gate = AutoApproveGate()
    registry.run("send_message", {"to": "mum", "body": "hello"})

    store = json.loads((state_dir / "messages.json").read_text())
    entry = store["outbox"][0]
    assert entry["delivered"] is False
    assert "queued" in entry, "the field name must not imply it was sent"


def test_list_messages_description_is_honest(registry):
    tool = registry.get("list_messages")
    description = tool.description.lower()
    assert "not" in description and ("real email" in description or "local" in description)


def test_drafting_is_still_safe_and_ungated(registry):
    """Drafting never leaves the machine, so it needs no confirmation."""
    assert "draft_message" not in registry.consequential_names()
    result = registry.run("draft_message", {"to": "mum", "body": "hi"})
    assert result.ok is True
    assert "not been sent" in result.content.lower()
