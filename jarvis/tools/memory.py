"""Tools that let JARVIS manage its own memory.

Recording and correcting are safe — they add or amend a single legible line.
Forgetting deletes data, so it is flagged consequential and fails closed until
Tier 6 builds the confirmation gate.

Note what is deliberately *absent*: no tool can read the store as instructions,
and nothing here lets a fact widen the assistant's permissions. Memory is
background knowledge, never a way around the safety gate.
"""

from __future__ import annotations

from ..memory import MemoryError, MemoryStore
from .base import Tool, ToolError

_PARAMS_REMEMBER = {
    "type": "OBJECT",
    "properties": {
        "fact": {
            "type": "STRING",
            "description": (
                "The fact to remember, as one short plain statement, e.g. "
                "'The user's name is Mike.' or 'The user prefers morning meetings.'"
            ),
        }
    },
    "required": ["fact"],
}


def build(store: MemoryStore) -> list[Tool]:
    def remember_fact(fact: str) -> str:
        try:
            saved = store.add(fact)
        except MemoryError as exc:
            raise ToolError(str(exc)) from exc
        return f"Remembered ({saved.id}): {saved.text}"

    def save_memory(fact: str, type: str = "general", hook: str = "") -> str:
        """Save a memory with type and hook. JARVIS decides when to call this."""
        try:
            saved = store.add(fact, type=type, hook=hook)
        except MemoryError as exc:
            raise ToolError(str(exc)) from exc
        return f"Saved ({saved.id}, {saved.type}): {saved.text}"

    def recall_memory(query: str) -> str:
        """Search memories by keyword. Returns matching facts."""
        results = store.search(query, limit=5)
        if not results:
            return f"No memories found matching '{query}'."
        lines = [f"{r.id} | {r.type} | {r.text}" for r in results]
        return "\n".join(lines)

    def list_facts() -> str:
        facts = store.facts()
        if not facts:
            return "I have not remembered anything yet."
        return "\n".join(f"{f.id} | {f.text}" for f in facts)

    def update_fact(fact_id: str, fact: str) -> str:
        try:
            updated = store.update(fact_id, fact)
        except MemoryError as exc:
            raise ToolError(str(exc)) from exc
        return f"Updated {updated.id} to: {updated.text}"

    def forget_fact(fact_id: str) -> str:
        try:
            removed = store.remove(fact_id)
        except MemoryError as exc:
            raise ToolError(str(exc)) from exc
        return f"Forgot {removed.id}: {removed.text}"

    return [
        Tool(
            name="remember_fact",
            description=(
                "Use this to remember something durable about the user — their "
                "name, a preference, a decision, or a stable fact about their "
                "world. Call it when the user says to remember something, or "
                "when they state a lasting preference. Do not use it for "
                "passing details of the current conversation."
            ),
            parameters=_PARAMS_REMEMBER,
            func=remember_fact,
        ),
        Tool(
            name="save_memory",
            description=(
                "Use this to save a memory with a type and hook. "
                "Call it when you decide something is worth remembering — "
                "a fact about the user, a preference, a project decision, "
                "or a resource pointer. "
                "Types: user, preference, project, resource, general. "
                "Hook: one-line searchable summary."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "fact": {
                        "type": "STRING",
                        "description": "The fact to save, as one short plain statement.",
                    },
                    "type": {
                        "type": "STRING",
                        "description": "Memory type: user, preference, project, resource, or general.",
                        "enum": ["user", "preference", "project", "resource", "general"],
                    },
                    "hook": {
                        "type": "STRING",
                        "description": "Optional: one-line searchable summary for recall.",
                    },
                },
                "required": ["fact"],
            },
            func=save_memory,
        ),
        Tool(
            name="recall_memory",
            description=(
                "Use this to search your memories by keyword. "
                "Call it when you need to recall something from a previous session, "
                "or when the user asks if you remember something. "
                "Returns matching facts with their ids and types."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": "What to search for, e.g. 'coffee' or 'project'.",
                    },
                },
                "required": ["query"],
            },
            func=recall_memory,
        ),
        Tool(
            name="list_facts",
            description=(
                "Use this to see everything currently remembered about the user. "
                "Call it before updating or forgetting something, so you use the "
                "right id."
            ),
            parameters={"type": "OBJECT", "properties": {}},
            func=list_facts,
        ),
        Tool(
            name="update_fact",
            description=(
                "Use this to correct a remembered fact that has changed or was "
                "wrong. Give the fact's id from list_facts."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "fact_id": {"type": "STRING", "description": "The id, e.g. 'm3'."},
                    "fact": {"type": "STRING", "description": "The corrected statement."},
                },
                "required": ["fact_id", "fact"],
            },
            func=update_fact,
        ),
        Tool(
            name="forget_fact",
            description=(
                "Use this to delete a remembered fact permanently. This destroys "
                "data, so it requires the user's explicit confirmation first."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "fact_id": {"type": "STRING", "description": "The id to forget."},
                },
                "required": ["fact_id"],
            },
            func=forget_fact,
            consequential=True,
            confirm_prompt="permanently deletes a remembered fact",
        ),
    ]
