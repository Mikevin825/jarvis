"""The meeting: fan out, in isolation.

For each selected seat, one call. Its system prompt contains that seat's
dossier and nothing else. It doesn't know who else is in the room.

Things that cost real money if you skip them:

- Set a generous output limit. A truncated response means you paid for a
  meeting and got nothing. If a seat gets cut off mid-JSON, the whole call
  is wasted — and the chair's limit needs to be larger than the seats',
  because it consumes all of them.

- Budget per call, chair included, so no single seat can eat the whole
  ceiling. And make a ceiling of zero actually mean zero — if the cost
  check only happens after a call returns, "spend nothing" spends a full
  fan-out before anything notices.

- De-duplicate seats before calling. A router naming one advisor twice
  must not buy two calls to the same dossier — and must never produce two
  identical opinions, because the unanimity guard in Tier 5 counts voices
  and one advisor duplicated would clear the bar by agreeing with himself.

- Let a seat fail without failing the meeting. Gather results tolerantly.
  Three good opinions and one timeout is a partial meeting, not a dead one.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..providers import Provider, ProviderError

if TYPE_CHECKING:
    from .dossier import Dossier


# The structured output schema for each seat. The model must conform to this
# or the call is wasted.
_SEAT_OUTPUT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "position": {
            "type": "STRING",
            "description": "The seat's position on the question, in 2-3 sentences.",
        },
        "reasoning": {
            "type": "STRING",
            "description": "The reasoning behind the position, in 3-5 sentences.",
        },
        "citations": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "Doctrine ids cited from the dossier (e.g. ['D1', 'D3']).",
        },
        "confidence": {
            "type": "INTEGER",
            "minimum": 1,
            "maximum": 5,
            "description": "Confidence in this position, 1-5.",
        },
        "would_change_mind": {
            "type": "STRING",
            "description": "What would change this seat's mind, in 1-2 sentences.",
        },
        "abstains": {
            "type": "BOOLEAN",
            "description": "Whether this seat abstains from answering.",
        },
    },
    "required": ["position", "reasoning", "citations", "confidence", "would_change_mind", "abstains"],
}


@dataclass
class SeatOpinion:
    """One seat's opinion on a question."""

    seat_id: str
    seat_name: str
    position: str
    reasoning: str
    citations: list[str] = field(default_factory=list)
    confidence: int = 3
    would_change_mind: str = ""
    abstains: bool = False
    unsourced: bool = False
    error: str | None = None
    cost_usd: float = 0.0
    wall_clock_s: float = 0.0


@dataclass
class MeetingResult:
    """The result of a full meeting."""

    question: str
    opinions: list[SeatOpinion] = field(default_factory=list)
    total_cost_usd: float = 0.0
    total_wall_clock_s: float = 0.0
    seats_attempted: int = 0
    seats_succeeded: int = 0
    seats_failed: int = 0

    @property
    def non_abstaining(self) -> list[SeatOpinion]:
        """Opinions from seats that didn't abstain."""
        return [o for o in self.opinions if not o.abstains and o.error is None]

    @property
    def abstentions(self) -> list[SeatOpinion]:
        """Opinions from seats that abstained."""
        return [o for o in self.opinions if o.abstains]


def _parse_seat_response(text: str) -> dict | None:
    """Parse a seat's JSON response, tolerantly.

    Returns None if the response can't be parsed. A truncated response
    usually contains the first part of the JSON — try to extract what we can.
    """
    if not text:
        return None

    # Try to find JSON in the response
    json_start = text.find("{")
    json_end = text.rfind("}") + 1

    if json_start < 0 or json_end <= json_start:
        return None

    try:
        return json.loads(text[json_start:json_end])
    except json.JSONDecodeError:
        # Try to fix common truncation issues
        # If the JSON is truncated, try to close it
        truncated = text[json_start:]
        # Count open braces
        open_count = truncated.count("{") - truncated.count("}")
        if open_count > 0:
            try:
                return json.loads(truncated + "}" * open_count)
            except json.JSONDecodeError:
                pass
        return None


def _coerce_seat_output(data: dict) -> dict:
    """Coerce a parsed seat output to the correct types.

    Treat every field the model returns as hostile input. A schema-declared
    boolean can come back as the string "false", and in most languages that
    is truthy. Check identity, not truthiness. Coerce every scalar. Drop
    anything structural where a sentence belonged.
    """
    result = {}

    # Position: must be a string
    position = data.get("position", "")
    result["position"] = str(position) if position else ""

    # Reasoning: must be a string
    reasoning = data.get("reasoning", "")
    result["reasoning"] = str(reasoning) if reasoning else ""

    # Citations: must be a list of strings — drop non-strings entirely
    citations = data.get("citations", [])
    if isinstance(citations, list):
        result["citations"] = [c for c in citations if isinstance(c, str) and c]
    else:
        result["citations"] = []

    # Confidence: must be an integer 1-5
    try:
        confidence = int(data.get("confidence", 3))
        result["confidence"] = max(1, min(5, confidence))
    except (TypeError, ValueError):
        result["confidence"] = 3

    # Would change mind: must be a string
    would_change = data.get("would_change_mind", "")
    result["would_change_mind"] = str(would_change) if would_change else ""

    # Abstains: must be a boolean — check identity, not truthiness
    abstains = data.get("abstains", False)
    if isinstance(abstains, bool):
        result["abstains"] = abstains
    elif isinstance(abstains, str):
        result["abstains"] = abstains.lower() in ("true", "yes", "1")
    else:
        result["abstains"] = bool(abstains)

    return result


def run_meeting(
    question: str,
    dossiers: list["Dossier"],
    seat_ids: list[str],
    provider: Provider,
    max_cost_usd: float = 0.50,
    max_output_tokens: int = 4096,
) -> MeetingResult:
    """Run a full meeting: fan out to each seat in isolation.

    For each selected seat, one call. Its system prompt contains that seat's
    dossier and nothing else. It doesn't know who else is in the room.

    Args:
        question: The user's question.
        dossiers: All available seats.
        seat_ids: The selected seat ids (from the router).
        provider: The model provider.
        max_cost_usd: Hard ceiling for the entire meeting.
        max_output_tokens: Output limit per seat call.

    Returns:
        A MeetingResult with all opinions.
    """
    start_time = time.monotonic()
    total_cost = 0.0

    # De-duplicate seats before calling. A router naming one advisor twice
    # must not buy two calls to the same dossier.
    seen_ids: set[str] = set()
    unique_seat_ids: list[str] = []
    for seat_id in seat_ids:
        if seat_id not in seen_ids:
            seen_ids.add(seat_id)
            unique_seat_ids.append(seat_id)

    # Build a lookup from id to dossier
    dossier_map = {d.id: d for d in dossiers}

    opinions: list[SeatOpinion] = []
    seats_attempted = 0
    seats_succeeded = 0
    seats_failed = 0

    for seat_id in unique_seat_ids:
        # Check cost ceiling before each call. A ceiling of zero means zero.
        if max_cost_usd >= 0 and total_cost >= max_cost_usd:
            break

        dossier = dossier_map.get(seat_id)
        if dossier is None:
            continue

        seats_attempted += 1
        seat_start = time.monotonic()

        try:
            # Build the system prompt: the dossier and nothing else
            system = dossier.to_prompt()

            # Build the user message
            user_message = f"Question: {question}\n\nProvide your position, reasoning, citations, confidence, what would change your mind, and whether you abstain."

            # Make the call
            from ..providers import Message

            messages = [Message(role="user", content=user_message)]
            response_text = ""
            usage = None

            for event in provider.stream(system, messages):
                from ..providers import TextDelta, TurnEnd

                if isinstance(event, TextDelta):
                    response_text += event.text
                elif isinstance(event, TurnEnd):
                    usage = event.usage

            # Track cost
            seat_cost = 0.0
            if usage:
                seat_cost = float(
                    usage.get("cost_usd", 0)
                    or usage.get("total_cost", 0)
                    or 0
                )
            total_cost += seat_cost

            # Parse the response
            parsed = _parse_seat_response(response_text)
            if parsed is None:
                seats_failed += 1
                opinions.append(
                    SeatOpinion(
                        seat_id=seat_id,
                        seat_name=dossier.name,
                        position="",
                        reasoning="",
                        error="could not parse response",
                        cost_usd=seat_cost,
                        wall_clock_s=time.monotonic() - seat_start,
                    )
                )
                continue

            # Coerce the output
            coerced = _coerce_seat_output(parsed)

            # Check citations against the dossier
            from .gate import CitationGate

            gate = CitationGate(dossier.doctrine_ids)
            valid_citations = gate.check(coerced["citations"], coerced["abstains"])

            seats_succeeded += 1
            opinions.append(
                SeatOpinion(
                    seat_id=seat_id,
                    seat_name=dossier.name,
                    position=coerced["position"],
                    reasoning=coerced["reasoning"],
                    citations=valid_citations,
                    confidence=coerced["confidence"],
                    would_change_mind=coerced["would_change_mind"],
                    abstains=coerced["abstains"],
                    unsourced=gate.unsourced,
                    cost_usd=seat_cost,
                    wall_clock_s=time.monotonic() - seat_start,
                )
            )

        except ProviderError as exc:
            seats_failed += 1
            opinions.append(
                SeatOpinion(
                    seat_id=seat_id,
                    seat_name=dossier.name,
                    position="",
                    reasoning="",
                    error=str(exc),
                    wall_clock_s=time.monotonic() - seat_start,
                )
            )
        except Exception as exc:  # noqa: BLE001 — a seat must not fail the meeting
            seats_failed += 1
            opinions.append(
                SeatOpinion(
                    seat_id=seat_id,
                    seat_name=dossier.name,
                    position="",
                    reasoning="",
                    error=f"{type(exc).__name__}: {exc}",
                    wall_clock_s=time.monotonic() - seat_start,
                )
            )

    return MeetingResult(
        question=question,
        opinions=opinions,
        total_cost_usd=total_cost,
        total_wall_clock_s=time.monotonic() - start_time,
        seats_attempted=seats_attempted,
        seats_succeeded=seats_succeeded,
        seats_failed=seats_failed,
    )
