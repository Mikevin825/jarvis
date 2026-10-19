"""The board tool — lets JARVIS convene the board.

This is the missing piece. The board exists as code, but JARVIS doesn't know
how to convene it. This tool adds that capability to the registry.

The tool:
1. Routes the question to the board
2. Runs the meeting (fan out in isolation)
3. Runs the chair (synthesis)
4. Stores the meeting
5. Surfaces it in the inbox
6. Returns a summary

Usage: ask JARVIS "ask the board about X" or "convene the board on X".
"""

from __future__ import annotations

from pathlib import Path

from ..tools.base import Tool, ToolError
from .chair import run_chair
from .dossier import parse_dossier
from .meeting import run_meeting
from .router import route_question
from .standing import to_stored_meeting
from .store import MeetingStore
from .surface import surface_meeting

DOSSIERS_DIR = Path(__file__).parent / "dossiers"


def _load_dossiers() -> list:
    """Load all dossiers from the dossiers directory."""
    if not DOSSIERS_DIR.exists():
        return []
    result = []
    for path in sorted(DOSSIERS_DIR.glob("*.md")):
        dossier = parse_dossier(path)
        if dossier is not None:
            result.append(dossier)
    return result


def convene_board(
    question: str,
    provider=None,
    business_brief: str = "",
    max_cost_usd: float = 0.50,
    max_output_tokens: int = 8192,
    chair_max_output_tokens: int = 4096,
) -> str:
    """Convene the board on a question.

    Routes the question, runs the meeting in isolation, runs the chair,
    stores the meeting, and surfaces it in the inbox.

    Args:
        question: The question to put to the board.
        provider: The model provider. Required.
        business_brief: The live business brief (empty if no numbers yet).
        max_cost_usd: Hard ceiling for the entire meeting.
        max_output_tokens: Output limit per seat. Generous on purpose — a seat
            that runs out of room is cut mid-reasoning and reads as broken.
        chair_max_output_tokens: Output limit for the chair's synthesis.

    Returns:
        A summary of the meeting result.

    Raises:
        ToolError: If no provider is given or no dossiers are found.
    """
    if provider is None:
        raise ToolError("No provider available. The board needs a model to reason.")

    dossiers = _load_dossiers()
    if not dossiers:
        raise ToolError("No dossiers found. The board has no seats.")

    # Route the question
    routing = route_question(question, dossiers)
    if routing.declined:
        return f"The board declined this question: {routing.decline_reason}"
    if not routing.should_route:
        return f"No seats have standing on this question: {routing.reason}"

    # Run the meeting
    meeting = run_meeting(
        question=question,
        dossiers=dossiers,
        seat_ids=routing.seat_ids,
        provider=provider,
        max_cost_usd=max_cost_usd,
        max_output_tokens=max_output_tokens,
    )

    # Run the chair
    chair = run_chair(
        meeting=meeting,
        dossiers=dossiers,
        provider=provider,
        business_brief=business_brief,
        max_output_tokens=chair_max_output_tokens,
    )

    # Store the meeting
    from .standing import StandingReviewResult

    result = StandingReviewResult(
        question=question,
        opinions=meeting.opinions,
        synthesis=chair.summary,
        spoken=chair.spoken,
        split=chair.split,
        agreement=chair.agreement,
        discounts=chair.discounts,
        unverified_flags=chair.unverified_flags,
        unanimous=chair.unanimous,
        abstentions=chair.abstentions,
        total_cost_usd=meeting.total_cost_usd,
        total_wall_clock_s=meeting.total_wall_clock_s,
        seats_attempted=meeting.seats_attempted,
        seats_succeeded=meeting.seats_succeeded,
        seats_failed=meeting.seats_failed,
    )
    stored = to_stored_meeting(result)

    # Surface in the inbox
    from ..heartbeat.inbox import Inbox
    from ..paths import INBOX_FILE

    inbox = Inbox(INBOX_FILE).load()
    surface_meeting(inbox, stored)

    # Build the summary
    lines = [
        f"Board meeting on: {question}",
        "",
        chair.spoken or chair.summary,
        "",
    ]

    if chair.split:
        lines.append(f"Split: {chair.split}")
        lines.append("")

    for opinion in meeting.opinions:
        if opinion.error:
            lines.append(f"• {opinion.seat_name}: error — {opinion.error}")
        elif opinion.abstains:
            lines.append(f"• {opinion.seat_name}: abstained")
        else:
            lines.append(f"• {opinion.seat_name}: {opinion.position}")
        lines.append("")

    lines.append(f"Cost: ${meeting.total_cost_usd:.4f}")
    lines.append(f"Time: {meeting.total_wall_clock_s:.1f}s")

    return "\n".join(lines)


def build(provider=None) -> list[Tool]:
    """Assemble the board tools.

    The provider is captured in a closure so the tool function can pass it
    to convene_board when the model calls it. The token budgets come from
    config.yaml (`board:`), so they are tunable without a code change.
    """
    from ..config import load_config, load_dotenv

    def _board_settings() -> dict:
        """Read the board's budgets, falling back to safe defaults.

        Read per call, not once at import, so editing config.yaml takes effect
        without restarting JARVIS.
        """
        try:
            load_dotenv()
            cfg = load_config()
            return {
                "max_output_tokens": cfg.board.max_output_tokens,
                "chair_max_output_tokens": cfg.board.chair_max_output_tokens,
                "max_cost_usd": cfg.board.max_cost_usd,
            }
        except Exception:  # noqa: BLE001 - a config problem must not kill the tool
            return {
                "max_output_tokens": 8192,
                "chair_max_output_tokens": 4096,
                "max_cost_usd": 0.50,
            }

    def _convene_board_tool(question: str) -> str:
        return convene_board(question, provider=provider, **_board_settings())

    def _list_board_tool() -> str:
        dossiers = _load_dossiers()
        if not dossiers:
            return "The board has no seats."
        lines = ["Board of Advisors — current roster:", ""]
        for d in dossiers:
            lines.append(f"• {d.name} — {d.seat_title}")
            lines.append(f"  Domains: {', '.join(d.domains)}")
            lines.append(f"  Doctrine entries: {len(d.doctrine)}")
            lines.append("")
        return "\n".join(lines)

    return [
        Tool(
            name="convene_board",
            description=(
                "Use this to convene the board of advisors on a question. "
                "The board has 7 seats: Seth Godin (Growth & Marketing), "
                "Paul Arden (Creative Strategy), Marty Neumeier (Brand & Position), "
                "Jason Fried (Operations), Eric Ries (Lean Startup), "
                "Marty Cagan (Product Discovery), Peter Thiel (Zero to One). "
                "The board routes the question to the right seats, runs a "
                "meeting in isolation, synthesizes the result, and surfaces "
                "it in the inbox. Call it when the user asks to 'ask the "
                "board' or 'convene the board'."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "question": {
                        "type": "STRING",
                        "description": "The question to put to the board.",
                    },
                },
                "required": ["question"],
            },
            func=_convene_board_tool,
        ),
        Tool(
            name="list_board",
            description=(
                "List all board members with their seat titles, domains, and "
                "doctrine entry counts. Use this to see who is on the board."
            ),
            parameters={"type": "OBJECT", "properties": {}},
            func=_list_board_tool,
        ),
    ]
