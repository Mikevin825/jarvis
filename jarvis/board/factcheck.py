"""The adversarial fact-check.

Stage two of the research process. A separate pass, without access to the
researcher's reasoning, instructed to try to refute each entry. For every
claim: does the cited source exist, does it actually say this, is it this
person's idea or one they credited to someone else, and is the framing honest.

The fact-check can prove a citation exists in the file. It can never prove
the file is true. That is why this stage exists.

Mark each entry's verification state — "sourced" when it survived the
adversarial pass, "user" when the user typed it in themselves later. Seats
may cite the user's own entries; the user's knowledge is legitimate input.
But the chair must be told, so it can say "this rests on something you wrote
yourself" instead of presenting it as documented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .dossier import Dossier, DoctrineEntry


@dataclass
class FactCheckResult:
    """The result of fact-checking one doctrine entry."""

    entry_id: str
    title: str
    source: str
    status: str  # "sourced", "user", "rejected"
    notes: str = ""


@dataclass
class FactCheckReport:
    """The full fact-check report for one seat."""

    seat_id: str
    seat_name: str
    results: list[FactCheckResult] = field(default_factory=list)

    @property
    def confirmed(self) -> int:
        return sum(1 for r in self.results if r.status == "sourced")

    @property
    def rejected(self) -> int:
        return sum(1 for r in self.results if r.status == "rejected")

    @property
    def user_entries(self) -> int:
        return sum(1 for r in self.results if r.status == "user")

    def summary(self) -> str:
        return (
            f"{self.seat_name}: {self.confirmed} confirmed, "
            f"{self.rejected} rejected, {self.user_entries} user entries"
        )


def fact_check_dossier(
    dossier: "Dossier",
    provider=None,
) -> FactCheckReport:
    """Run the adversarial fact-check on a dossier.

    This is a separate pass, without access to the researcher's reasoning,
    instructed to try to refute each entry. For every claim: does the cited
    source exist, does it actually say this, is it this person's idea or one
    they credited to someone else, and is the framing honest.

    If no provider is given, returns a report with all entries marked as
    "user" — the conservative default when no fact-check has been run.

    Args:
        dossier: The dossier to fact-check.
        provider: An optional provider to use for the adversarial pass.
            If None, all entries are marked as "user".

    Returns:
        A FactCheckReport with the results for each entry.
    """
    report = FactCheckReport(
        seat_id=dossier.id,
        seat_name=dossier.name,
    )

    for entry in dossier.doctrine:
        if provider is None:
            # No fact-check run — mark as user (conservative default)
            report.results.append(
                FactCheckResult(
                    entry_id=entry.id,
                    title=entry.text[:60] + "..." if len(entry.text) > 60 else entry.text,
                    source=entry.source,
                    status="user",
                    notes="No fact-check run — marked as user entry",
                )
            )
        else:
            # Run the adversarial fact-check
            result = _fact_check_entry(entry, provider)
            report.results.append(result)

    return report


def _fact_check_entry(
    entry: "DoctrineEntry",
    provider,
) -> FactCheckResult:
    """Fact-check one doctrine entry.

    The fact-check asks:
    1. Does the cited source exist?
    2. Does it actually say this?
    3. Is it this person's idea or one they credited to someone else?
    4. Is the framing honest — a narrow finding presented as a general law
       is a defect even when every word is true.
    """
    # Build the fact-check prompt
    prompt = f"""You are an adversarial fact-checker. Your job is to try to REFUTE the following claim.

Claim: {entry.text}
Source: {entry.source}

For this claim, check:
1. Does the cited source exist?
2. Does it actually say this?
3. Is it this person's idea or one they credited to someone else?
4. Is the framing honest — a narrow finding presented as a general law is a defect even when every word is true.

Be skeptical. Assume the claim is wrong until proven otherwise. If you cannot verify it, mark it as "user" (unverified).

Return JSON:
{{
  "status": "sourced" | "user" | "rejected",
  "notes": "your reasoning"
}}
"""

    try:
        # Use the provider to run the fact-check
        from ..providers import Message

        messages = [Message(role="user", content=prompt)]
        response = ""
        for event in provider.stream("You are a fact-checker.", messages):
            from ..providers import TextDelta, TurnEnd

            if isinstance(event, TextDelta):
                response += event.text
            elif isinstance(event, TurnEnd):
                break

        # Parse the response
        import json

        # Try to extract JSON from the response
        json_start = response.find("{")
        json_end = response.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            data = json.loads(response[json_start:json_end])
            return FactCheckResult(
                entry_id=entry.id,
                title=entry.text[:60] + "..." if len(entry.text) > 60 else entry.text,
                source=entry.source,
                status=data.get("status", "user"),
                notes=data.get("notes", ""),
            )
    except Exception:  # noqa: BLE001 — a failed fact-check must not crash
        pass

    # If anything fails, mark as user (conservative default)
    return FactCheckResult(
        entry_id=entry.id,
        title=entry.text[:60] + "..." if len(entry.text) > 60 else entry.text,
        source=entry.source,
        status="user",
        notes="Fact-check failed — marked as user entry",
    )
