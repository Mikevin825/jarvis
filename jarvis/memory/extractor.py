"""Automatic memory extractor — runs when a session ends.

A cheap model call reads the transcript, proposes durable facts, checks each
against what's already stored to avoid duplicates, and skips anything that
looks like testing or idle chatter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..providers import Provider, ProviderError

if TYPE_CHECKING:
    from ..memory import MemoryStore


@dataclass
class ExtractedMemory:
    """A memory proposed by the extractor."""

    fact: str
    type: str = "general"
    hook: str = ""


def extract_memories(
    transcript: list[dict],
    store: "MemoryStore",
    provider: Provider,
    max_memories: int = 5,
) -> list[ExtractedMemory]:
    """Extract durable memories from a conversation transcript.

    Args:
        transcript: List of {"role": "user"/"assistant", "content": "..."} dicts
        store: The memory store (for dedup checking)
        provider: The model provider (for the extraction call)
        max_memories: Maximum number of memories to extract

    Returns:
        List of extracted memories (empty if extraction fails)
    """
    if not transcript:
        return []

    # Build a compact transcript for the model
    lines = []
    for msg in transcript[-50:]:  # Last 50 messages
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if content:
            lines.append(f"{role}: {content}")
    conversation = "\n".join(lines)

    if not conversation.strip():
        return []

    system = """You are a memory extractor. Your job is to read a conversation and extract durable facts worth remembering.

Rules:
- Only extract facts that are durable and useful across sessions
- Skip transient task state, current conversation details, small talk
- Skip anything already in the "already known" list
- Each fact should be one short plain statement
- Types: user (about the user), preference (how they want things), project (active projects), resource (external pointers), general
- Hook: one-line searchable summary
- Return JSON: [{"fact": "...", "type": "...", "hook": "..."}]

Already known:
"""

    # Add existing facts for dedup
    existing = store.facts()
    for f in existing:
        system += f"- {f.text}\n"

    system += f"\nExtract up to {max_memories} new memories. Return only JSON."

    try:
        from ..providers import Message, TextDelta, TurnEnd

        response_text = ""
        for event in provider.stream(system, [Message(role="user", content=conversation)]):
            if isinstance(event, TextDelta):
                response_text += event.text
            elif isinstance(event, TurnEnd):
                break

        # Parse JSON from response
        json_start = response_text.find("[")
        json_end = response_text.rfind("]") + 1
        if json_start >= 0 and json_end > json_start:
            data = json.loads(response_text[json_start:json_end])
        else:
            return []

        memories = []
        for item in data[:max_memories]:
            fact = item.get("fact", "").strip()
            if not fact:
                continue
            # Dedup check
            existing_texts = {f.text.lower() for f in existing}
            if fact.lower() in existing_texts:
                continue
            memories.append(ExtractedMemory(
                fact=fact,
                type=item.get("type", "general"),
                hook=item.get("hook", fact[:80]),
            ))

        return memories

    except (ProviderError, json.JSONDecodeError, Exception):
        return []
