"""Surface the meeting in the inbox.

A meeting that finishes into a log file nobody reads is a meeting that didn't
happen. Surface it the way JARVIS already surfaces things — the inbox.

When you surface the meeting card, snapshot each cited entry's title and
source into it. Then a stored meeting renders its own citations without
re-reading the dossier, and stays readable after the file changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .store import StoredCitation, StoredMeeting, StoredOpinion

if TYPE_CHECKING:
    from ..heartbeat.inbox import Inbox


def surface_meeting(inbox: "Inbox", meeting: StoredMeeting) -> str:
    """Surface a meeting in the inbox.

    Creates a notice with the meeting's summary, split, and cost. The notice
    body includes the key opinions and citations so the user can see what
    happened without opening the full meeting.

    Args:
        inbox: The heartbeat inbox.
        meeting: The stored meeting to surface.

    Returns:
        The notice id.
    """
    # Build the notice body
    lines = [
        f"Question: {meeting.question}",
        "",
        meeting.spoken or meeting.summary,
        "",
    ]

    if meeting.split:
        lines.append(f"Split: {meeting.split}")
        lines.append("")

    # Add opinions
    for opinion in meeting.opinions:
        if opinion.error:
            lines.append(f"• {opinion.seat_name}: error — {opinion.error}")
        elif opinion.abstains:
            lines.append(f"• {opinion.seat_name}: abstained")
        else:
            lines.append(f"• {opinion.seat_name}: {opinion.position}")
            if opinion.citations:
                cites = ", ".join(
                    f"{c.entry_id} ({c.verification})" for c in opinion.citations
                )
                lines.append(f"  Citations: {cites}")
        lines.append("")

    # Add discounts and flags
    if meeting.discounts:
        lines.append("Blind spot discounts:")
        for d in meeting.discounts:
            lines.append(f"  - {d}")
        lines.append("")

    if meeting.unverified_flags:
        lines.append("Unverified positions:")
        for f in meeting.unverified_flags:
            lines.append(f"  - {f}")
        lines.append("")

    lines.append(f"Cost: ${meeting.total_cost_usd:.4f}")
    lines.append(f"Time: {meeting.total_wall_clock_s:.1f}s")

    body = "\n".join(lines)

    # Create the notice
    notice = inbox.add(
        source="board",
        title=f"Board meeting: {meeting.question[:50]}",
        body=body,
        level="normal",
    )

    return notice.id


def surface_meeting_card(inbox: "Inbox | None", meeting: StoredMeeting) -> dict:
    """Build a meeting card for display.

    The card includes the meeting's summary, split, opinions with citations,
    discounts, and cost. This is what the user sees when they open the meeting.

    Args:
        inbox: The heartbeat inbox (unused, but kept for API consistency).
        meeting: The stored meeting.

    Returns:
        A dict with the meeting card data.
    """
    return {
        "id": meeting.id,
        "question": meeting.question,
        "summary": meeting.summary,
        "spoken": meeting.spoken,
        "split": meeting.split,
        "agreement": meeting.agreement,
        "opinions": [
            {
                "seat_id": o.seat_id,
                "seat_name": o.seat_name,
                "position": o.position,
                "reasoning": o.reasoning,
                "citations": [
                    {
                        "entry_id": c.entry_id,
                        "title": c.title,
                        "source": c.source,
                        "verification": c.verification,
                    }
                    for c in o.citations
                ],
                "confidence": o.confidence,
                "abstains": o.abstains,
                "unsourced": o.unsourced,
                "error": o.error,
            }
            for o in meeting.opinions
        ],
        "discounts": meeting.discounts,
        "unverified_flags": meeting.unverified_flags,
        "unanimous": meeting.unanimous,
        "abstentions": meeting.abstentions,
        "total_cost_usd": meeting.total_cost_usd,
        "total_wall_clock_s": meeting.total_wall_clock_s,
    }
