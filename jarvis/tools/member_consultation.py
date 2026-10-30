"""Member consultation tools — allow JARVIS to consult Beulah for an independent perspective.

These tools are read-only: they ask a member to provide their view on a topic,
but do not perform consequential actions themselves. The member's response
is returned to the user as information only.
"""

from __future__ import annotations

from datetime import datetime

from .base import Tool
from ..providers.base import Message

# Provider will be set when the tools module is imported with configuration
_PROVIDER = None


def set_provider(provider):
    """Set the model provider for member consultations."""
    global _PROVIDER
    _PROVIDER = provider


def build() -> list[Tool]:
    """Build the member consultation tools."""
    return [
        Tool(
            name="consult_beulah",
            description=(
                "Consult Beulah Racha for an independent perspective on a topic. "
                "Beulah provides her thoughtful analysis while respecting all "
                "safety controls and permission gates. Use when you want to see "
                "how Beulah would approach the question, or when her expertise "
                "would be valuable for comparison."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "question": {
                        "type": "STRING",
                        "description": "The question or topic to ask Beulah",
                    },
                    "context": {
                        "type": "STRING",
                        "description": "Optional context about the current situation, defaults to the question",
                    },
                },
                "required": ["question"],
            },
            func=_consult_beulah,
            consequential=False,  # Returns perspective only, no action
        ),
    ]


def _consult_beulah(question: str, context: str = "") -> str:
    """Delegate to Beulah for an independent perspective.

    Returns content that the model can naturally incorporate into its response,
    presenting Asif Racha's perspective to the user.
    """
    from ..members import get_member, build_member_system_prompt
    import re

    member = get_member("beulah")
    if member is None:
        return "No member named Beulah is registered."

    # Clean up the question - remove direct address to Beulah if present
    question = re.sub(r"^beulah[,:\s]+", "", question, flags=re.IGNORECASE).strip()

    # Load Beulah's memory
    member.memory.load()
    memory_facts = member.memory.render()

    # Build her system prompt
    system_prompt = build_member_system_prompt(member, memory_facts)

    # Build the conversation
    current_time = datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M %Z")

    # Construct the prompt for the model
    full_prompt = f"{system_prompt}\n\nCurrent time: {current_time}\n\nQuestion: {question}"

    if context:
        full_prompt += f"\n\nAdditional context: {context}"

    # If no provider is available, return a structured placeholder
    if _PROVIDER is None:
        return f"[Consultation with Beulah Racha — question: {question}]"

    # Invoke the model with Beulah's system prompt
    try:
        # Build Message objects for the provider (uses provider-neutral shape)
        user_content = f"Question: {question}"
        if context:
            user_content = f"Question: {question}\n\nContext: {context}"

        messages = [Message(role="user", content=user_content)]

        # Stream the response
        text_parts = []

        for event in _PROVIDER.stream(system_prompt, messages):
            if hasattr(event, 'text'):
                text_parts.append(event.text)

        response = "".join(text_parts)
        if response:
            # Strip any leading "I am... Beulah, Racha." identity statement
            # that would look like a system prompt in the model's response
            lines = response.split('\n')
            for i, line in enumerate(lines):
                if line.strip().startswith("I am") or "Beulah, Racha" in line:
                    # Keep the signature but skip the initial identity claim
                    if i == 0:
                        # Just take the rest
                        response = '\n'.join(lines[i+1:]).strip()
                        break
            return response

        return "[Beulah Racha]: [model returned no response]"

    except Exception as e:
        return f"[Beulah Racha consultation failed: {type(e).__name__}: {e}]"