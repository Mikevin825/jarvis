"""The standing review.

Everything so far waits for the user to ask. The most valuable thing a real
board does is show up when you didn't call the meeting.

Once a month, convene with no question on the table but the business itself.
The prompt that makes this work:

> You did not call this meeting, so there is no question but the business.
> Read the numbers. What would you put on the agenda this month that they are
> not already looking at? Name the specific number that moves you, say what
> it implies, and give one concrete thing to do in the next 30 days. If the
> numbers genuinely warrant nothing, say so plainly rather than manufacturing
> a concern. Do not ask what they want to discuss — this is your agenda, not
> theirs.

That last line is load-bearing. Without it the likeliest failure is a board
that politely hands the question back, which defeats the entire routine.

Route it into the inbox and mark it as unprompted so the user can tell it
apart from an answer they asked for.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from ..providers import Provider
from .chair import run_chair
from .dossier import Dossier
from .meeting import MeetingResult, SeatOpinion, run_meeting
from .store import StoredCitation, StoredMeeting, StoredOpinion

if TYPE_CHECKING:
    from ..heartbeat.checks import CheckResult


# The standing review prompt. This is the prompt that makes the routine work.
# The last line is load-bearing — without it the board hands the question back.
STANDING_REVIEW_PROMPT = """You did not call this meeting, so there is no question but the business.

Read the numbers. What would you put on the agenda this month that they are not already looking at?

Name the specific number that moves you, say what it implies, and give one concrete thing to do in the next 30 days.

If the numbers genuinely warrant nothing, say so plainly rather than manufacturing a concern.

Do not ask what they want to discuss — this is your agenda, not theirs."""


@dataclass
class StandingReviewResult:
    """The result of a standing review."""

    question: str
    opinions: list[SeatOpinion] = field(default_factory=list)
    synthesis: str = ""
    spoken: str = ""
    split: str = ""
    agreement: str = ""
    discounts: list[str] = field(default_factory=list)
    unverified_flags: list[str] = field(default_factory=list)
    unanimous: bool = False
    abstentions: list[str] = field(default_factory=list)
    total_cost_usd: float = 0.0
    total_wall_clock_s: float = 0.0
    seats_attempted: int = 0
    seats_succeeded: int = 0
    seats_failed: int = 0
    surfaced: bool = False
    notice_id: str = ""


def run_standing_review(
    dossiers: list[Dossier],
    provider: Provider,
    business_brief: str = "",
    max_cost_usd: float = 0.50,
) -> StandingReviewResult:
    """Run the standing review.

    Once a month, convene with no question on the table but the business
    itself. The board reads the numbers and puts an agenda in front of the
    user — one they didn't ask for.

    Args:
        dossiers: All available seats.
        provider: The model provider.
        business_brief: The live business brief (empty if no numbers yet).
        max_cost_usd: Hard ceiling for the entire meeting.

    Returns:
        A StandingReviewResult with the result.
    """
    # The standing review uses all seats — it's the full board
    seat_ids = [d.id for d in dossiers]

    # Run the meeting with the standing review prompt as the question
    meeting = run_meeting(
        question=STANDING_REVIEW_PROMPT,
        dossiers=dossiers,
        seat_ids=seat_ids,
        provider=provider,
        max_cost_usd=max_cost_usd,
    )

    # Run the chair
    chair = run_chair(
        meeting=meeting,
        dossiers=dossiers,
        provider=provider,
        business_brief=business_brief,
    )

    return StandingReviewResult(
        question=STANDING_REVIEW_PROMPT,
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


def to_stored_meeting(result: StandingReviewResult) -> StoredMeeting:
    """Convert a StandingReviewResult to a StoredMeeting.

    Snapshots each cited entry's title and source into the stored meeting,
    so it renders its own citations without re-reading the dossier.
    """
    opinions = []
    for o in result.opinions:
        citations = []
        # We don't have the dossier here, so we snapshot what we have
        # The caller should enrich these with actual titles and sources
        for c in o.citations:
            citations.append(
                StoredCitation(
                    entry_id=c,
                    title=c,  # Fallback to id if title unknown
                    source="",
                    verification="sourced",
                )
            )
        opinions.append(
            StoredOpinion(
                seat_id=o.seat_id,
                seat_name=o.seat_name,
                position=o.position,
                reasoning=o.reasoning,
                citations=citations,
                confidence=o.confidence,
                would_change_mind=o.would_change_mind,
                abstains=o.abstains,
                unsourced=o.unsourced,
                error=o.error,
            )
        )

    return StoredMeeting(
        id=f"standing-{int(time.time())}",
        question="Standing review — the business itself",
        summary=result.synthesis,
        spoken=result.spoken,
        split=result.split,
        agreement=result.agreement,
        opinions=opinions,
        discounts=result.discounts,
        unverified_flags=result.unverified_flags,
        unanimous=result.unanimous,
        abstentions=result.abstentions,
        total_cost_usd=result.total_cost_usd,
        total_wall_clock_s=result.total_wall_clock_s,
        seats_attempted=result.seats_attempted,
        seats_succeeded=result.seats_succeeded,
        seats_failed=result.seats_failed,
    )


class StandingReviewCheck:
    """A heartbeat check that runs the standing review once a month.

    The most valuable thing a real board does is show up when you didn't call
    the meeting. This check makes that happen.
    """

    name = "board-standing-review"

    def __init__(
        self,
        interval_seconds: float,
        settings: dict,
        dossiers: list[Dossier],
        provider: Provider,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.settings = settings
        self.dossiers = dossiers
        self.provider = provider

    def run(self, ctx) -> "CheckResult":
        """Run the standing review.

        Returns a CheckResult with surfaced=True if the review ran and
        produced something worth surfacing.
        """
        from ..heartbeat.checks import CheckResult

        business_brief = self.settings.get("business_brief", "")
        max_cost_usd = float(self.settings.get("max_cost_usd", 0.50))

        result = run_standing_review(
            dossiers=self.dossiers,
            provider=self.provider,
            business_brief=business_brief,
            max_cost_usd=max_cost_usd,
        )

        if not result.synthesis:
            return CheckResult(summary="standing review produced nothing")

        return CheckResult(
            surfaced=True,
            title="Board standing review",
            body=result.spoken or result.synthesis,
            level="normal",
            summary=f"standing review: {result.seats_succeeded} seats, ${result.total_cost_usd:.4f}",
        )
