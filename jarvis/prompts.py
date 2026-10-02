"""The system prompt.

One place that describes who the assistant is, so the text path, the voice path,
and the heartbeat all introduce the same assistant. Keep this consistent
everywhere — see AGENT.md.
"""

from __future__ import annotations

from .config import AssistantConfig

SYSTEM_PROMPT = """\
You are {name}.

{purpose}

Tone — follow this exactly:
{tone}

Rules:
- Your replies are often read aloud. Keep them short and speakable: plain
  sentences, no markdown, no bullet lists, no code blocks unless I ask for them.
- If you don't know something, say so plainly rather than guessing.
- Never claim to have done something you did not actually do.
"""


def build_system_prompt(assistant: AssistantConfig) -> str:
    return SYSTEM_PROMPT.format(
        name=assistant.name,
        purpose=assistant.purpose.strip(),
        tone=assistant.tone.strip(),
    )
