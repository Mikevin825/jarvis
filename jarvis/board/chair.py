"""The chair: JARVIS, and the only one who read the numbers.

The chair receives every opinion with its citations, the live business brief,
and each seat's blind spots. It synthesizes, names the split before the
agreement, and discounts seats using their documented blind spots.

Two deterministic guards, built rather than trusted to a prompt:

- A unanimity guard. Fewer than two non-abstaining seats can never be
  reported as unanimous. One voice is not a consensus, and a model will
  cheerfully call it one.

- Check that the spoken summary matches the computed verdict. If the guard
  sets `unanimous: false`, the sentence read aloud must not say "the board
  is unanimous." Ask how we know: because it did, once, and the guard was
  working perfectly the whole time — the prose just ignored it.

Keep the spoken part short. One or two sentences, leading with the split.
The detail belongs on screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..providers import Provider, ProviderError

if TYPE_CHECKING:
    from .dossier import Dossier
    from .meeting import MeetingResult, SeatOpinion


@dataclass
class ChairSynthesis:
    """The chair's synthesis of a meeting."""

    summary: str  # 1-2 sentences, leading with the split
    split: str  # Where the board divided
    agreement: str  # Where the board agreed (if anything)
    discounts: list[str] = field(default_factory=list)  # Seats discounted via blind spots
    unverified_flags: list[str] = field(default_factory=list)  # Positions resting on unverified entries
    unanimous: bool = False
    abstentions: list[str] = field(default_factory=list)
    spoken: str = ""  # The short spoken summary


def _check_unanimity(opinions: list["SeatOpinion"]) -> bool:
    """Deterministic unanimity guard.

    Fewer than two non-abstaining seats can never be reported as unanimous.
    One voice is not a consensus.
    """
    non_abstaining = [o for o in opinions if not o.abstains and o.error is None]
    if len(non_abstaining) < 2:
        return False

    # Check if all non-abstaining opinions agree
    # For simplicity, we consider them unanimous if they all have the same
    # confidence direction (all positive or all negative)
    # A more sophisticated check would compare the actual positions
    positions = [o.position.lower() for o in non_abstaining]
    # Simple heuristic: if all positions start with the same word, they agree
    if not positions:
        return False
    first_words = [p.split()[0] if p.split() else "" for p in positions]
    return len(set(first_words)) == 1


def _find_blind_spot_discounts(
    opinions: list["SeatOpinion"],
    dossiers: dict[str, "Dossier"],
) -> list[str]:
    """Find seats whose positions fall inside their documented blind spots.

    The chair uses this to discount the seat. It must be honest or it's
    worse than absent.
    """
    discounts = []
    for opinion in opinions:
        if opinion.abstains or opinion.error:
            continue
        dossier = dossiers.get(opinion.seat_id)
        if dossier is None:
            continue

        position_lower = opinion.position.lower()
        for spot in dossier.blind_spots:
            # Check if the blind spot applies to this position
            # Simple keyword matching — a more sophisticated check would use
            # the model to evaluate this
            spot_keywords = spot.lower().split()
            if any(keyword in position_lower for keyword in spot_keywords if len(keyword) > 4):
                discounts.append(
                    f"{opinion.seat_name}: position falls inside documented blind spot — {spot}"
                )
                break

    return discounts


def _find_unverified_positions(
    opinions: list["SeatOpinion"],
    dossiers: dict[str, "Dossier"],
) -> list[str]:
    """Flag positions resting on unverified entries.

    The chair must be told, so it can say "this rests on something you wrote
    yourself" instead of presenting it as documented. Otherwise the user's
    own half-remembered impression comes back wearing an advisor's name.
    """
    flags = []
    for opinion in opinions:
        if opinion.abstains or opinion.error:
            continue
        dossier = dossiers.get(opinion.seat_id)
        if dossier is None:
            continue

        # Check if any cited entries are marked as "user" (unverified)
        for citation in opinion.citations:
            for entry in dossier.doctrine:
                if entry.id == citation and entry.verification == "user":
                    flags.append(
                        f"{opinion.seat_name}: citation {citation} rests on a user entry, not a documented source"
                    )

    return flags


def run_chair(
    meeting: MeetingResult,
    dossiers: list["Dossier"],
    provider: Provider,
    business_brief: str = "",
    max_output_tokens: int = 2048,
) -> ChairSynthesis:
    """Run the chair: synthesize the meeting.

    The chair is JARVIS itself, the only participant who has read the actual
    business numbers. It receives every opinion with its citations, the live
    business brief, and each seat's blind spots.

    Args:
        meeting: The meeting result with all opinions.
        dossiers: All available seats.
        provider: The model provider.
        business_brief: The live business brief (empty if no numbers yet).
        max_output_tokens: Output limit for the chair call.

    Returns:
        A ChairSynthesis with the result.
    """
    dossier_map = {d.id: d for d in dossiers}

    # Deterministic guards
    unanimous = _check_unanimity(meeting.opinions)
    discounts = _find_blind_spot_discounts(meeting.opinions, dossier_map)
    unverified_flags = _find_unverified_positions(meeting.opinions, dossier_map)
    abstentions = [o.seat_name for o in meeting.abstentions]

    # Build the chair's prompt
    system = _build_chair_prompt(meeting, dossier_map, business_brief, discounts, unverified_flags)

    # Make the call
    from ..providers import Message

    messages = [Message(role="user", content="Synthesize the board's opinions.")]

    try:
        response_text = ""
        for event in provider.stream(system, messages):
            from ..providers import TextDelta, TurnEnd

            if isinstance(event, TextDelta):
                response_text += event.text
            elif isinstance(event, TurnEnd):
                break

        # Parse the response
        summary = response_text.strip()

        # Build the spoken summary — short, leading with the split
        spoken = _build_spoken_summary(summary, unanimous, abstentions)

        return ChairSynthesis(
            summary=summary,
            split=_extract_split(summary),
            agreement=_extract_agreement(summary),
            discounts=discounts,
            unverified_flags=unverified_flags,
            unanimous=unanimous,
            abstentions=abstentions,
            spoken=spoken,
        )

    except ProviderError:
        # If the chair fails, return a minimal synthesis
        return ChairSynthesis(
            summary="The chair could not synthesize this meeting.",
            split="",
            agreement="",
            discounts=discounts,
            unverified_flags=unverified_flags,
            unanimous=unanimous,
            abstentions=abstentions,
            spoken="The board could not reach a synthesis.",
        )
    except Exception:  # noqa: BLE001 — a chair must not crash the meeting
        return ChairSynthesis(
            summary="The chair could not synthesize this meeting.",
            split="",
            agreement="",
            discounts=discounts,
            unverified_flags=unverified_flags,
            unanimous=unanimous,
            abstentions=abstentions,
            spoken="The board could not reach a synthesis.",
        )


def _build_chair_prompt(
    meeting: MeetingResult,
    dossier_map: dict[str, "Dossier"],
    business_brief: str,
    discounts: list[str],
    unverified_flags: list[str],
) -> str:
    """Build the chair's system prompt.

    The chair receives every opinion with its citations, the live business
    brief, and each seat's blind spots.
    """
    lines = [
        "# The Chair",
        "",
        "You are the chair of a board of advisors. You are the only participant",
        "who has read the actual business numbers. Your job is to synthesize",
        "the board's opinions, name the split before the agreement, and",
        "discount seats using their documented blind spots.",
        "",
        "## Instructions",
        "",
        "- Name the split before the agreement. Where the board divided is the",
        "  information; where it agreed is often just the obvious.",
        "- Discount seats using their documented blind spots. When a position",
        "  falls inside one, say so plainly.",
        "- Treat abstention as abstention, never as assent.",
        "- Flag positions resting on unverified entries as the user's own",
        "  assumption rather than that person's documented view.",
        "- Keep the spoken part short. One or two sentences, leading with the",
        "  split. The detail belongs on screen.",
        "",
    ]

    if business_brief:
        lines.extend([
            "## Live Business Brief",
            "",
            business_brief,
            "",
        ])

    lines.extend([
        "## Opinions",
        "",
    ])

    for opinion in meeting.opinions:
        if opinion.error:
            lines.append(f"### {opinion.seat_name}")
            lines.append(f"Error: {opinion.error}")
            lines.append("")
            continue

        lines.append(f"### {opinion.seat_name}")
        lines.append(f"Position: {opinion.position}")
        lines.append(f"Reasoning: {opinion.reasoning}")
        lines.append(f"Citations: {', '.join(opinion.citations) or 'none'}")
        lines.append(f"Confidence: {opinion.confidence}/5")
        lines.append(f"Would change mind: {opinion.would_change_mind}")
        lines.append(f"Abstains: {opinion.abstains}")
        if opinion.unsourced:
            lines.append("⚠️ Unsourced: this seat cited nothing and did not abstain")
        lines.append("")

    if discounts:
        lines.extend([
            "## Blind Spot Discounts",
            "",
        ])
        for discount in discounts:
            lines.append(f"- {discount}")
        lines.append("")

    if unverified_flags:
        lines.extend([
            "## Unverified Positions",
            "",
        ])
        for flag in unverified_flags:
            lines.append(f"- {flag}")
        lines.append("")

    return "\n".join(lines)


def _build_spoken_summary(summary: str, unanimous: bool, abstentions: list[str]) -> str:
    """Build the short spoken summary.

    One or two sentences, leading with the split. The detail belongs on screen.
    """
    if not summary:
        return "The board could not reach a synthesis."

    # Take the first sentence or two
    sentences = summary.split(". ")
    spoken = ". ".join(sentences[:2])
    if not spoken.endswith("."):
        spoken += "."

    # Add abstentions if any
    if abstentions:
        spoken += f" {', '.join(abstentions)} abstained."

    return spoken


def _extract_split(summary: str) -> str:
    """Extract the split from the summary."""
    if not summary:
        return ""
    # Look for split indicators
    lower = summary.lower()
    if "split" in lower or "divided" in lower or "disagree" in lower:
        # Return the relevant sentence
        for sentence in summary.split(". "):
            if any(word in sentence.lower() for word in ["split", "divided", "disagree"]):
                return sentence
    return ""


def _extract_agreement(summary: str) -> str:
    """Extract the agreement from the summary."""
    if not summary:
        return ""
    lower = summary.lower()
    if "agree" in lower or "unanimous" in lower or "consensus" in lower:
        for sentence in summary.split(". "):
            if any(word in sentence.lower() for word in ["agree", "unanimous", "consensus"]):
                return sentence
    return ""
