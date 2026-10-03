"""The citation gate.

A pure function: given whatever the model returned as citations and the set
of ids that seat was actually shown, return only the valid ones.

The gate can prove a citation exists in the file. It can never prove the file
is true. That is why the research process has two stages and why the second
stage is adversarial.

Two details that are easy to get wrong and expensive to miss:

- The valid set is what the seat was shown, not everything in the file. When
  retirement is added later these diverge, and the gap is a seat citing
  something withheld from it.

- A seat that cites nothing and didn't abstain is unsourced. Track that as
  its own flag and show it to the user. It's not an error, but it's the seat
  talking without support and the user should be able to see that at a glance.
"""

from __future__ import annotations

import re


def filter_citations(
    returned: list[str] | tuple[str, ...] | None,
    valid_ids: set[str] | list[str] | tuple[str, ...],
) -> list[str]:
    """Filter citations to only those that exist in the seat's dossier.

    Uppercase-normalize, de-duplicate, preserve order, discard everything
    else.

    Args:
        returned: Whatever the model returned as citations. Can be a list,
            tuple, or None. Each item can be a string like "D1" or a
            longer string containing a citation like "as I said in D3".
        valid_ids: The set of ids the seat was actually shown. Only these
            are valid.

    Returns:
        A list of valid citation ids, in the order they first appeared,
        de-duplicated.
    """
    if not returned:
        return []

    valid = set(valid_ids)
    seen: set[str] = set()
    result: list[str] = []

    for item in returned:
        if not isinstance(item, str):
            continue
        # Find all citation patterns in the string
        for match in re.finditer(r"\bD\d+\b", item, re.IGNORECASE):
            citation = match.group(0).upper()
            if citation in valid and citation not in seen:
                seen.add(citation)
                result.append(citation)

    return result


class CitationGate:
    """Tracks citation state for a seat's response.

    A seat that cites nothing and didn't abstain is unsourced. That's not an
    error, but it's the seat talking without support and the user should be
    able to see that at a glance.
    """

    def __init__(self, valid_ids: set[str] | list[str] | tuple[str, ...]) -> None:
        self.valid_ids = set(valid_ids)
        self.returned: list[str] = []
        self.valid: list[str] = []
        self.abstained: bool = False

    def check(self, returned: list[str] | tuple[str, ...] | None, abstained: bool = False) -> list[str]:
        """Check a seat's citations and return the valid ones.

        Args:
            returned: The citations the model returned.
            abstained: Whether the seat abstained from answering.

        Returns:
            The filtered list of valid citations.
        """
        self.returned = list(returned) if returned else []
        self.abstained = abstained
        self.valid = filter_citations(self.returned, self.valid_ids)
        return self.valid

    @property
    def unsourced(self) -> bool:
        """Whether the seat cited nothing and didn't abstain.

        This is the seat talking without support. Not an error, but the
        user should be able to see it at a glance.
        """
        return not self.valid and not self.abstained

    @property
    def fabricated(self) -> list[str]:
        """Citations the model returned that aren't in the dossier.

        These were stripped by the gate. Tracking them makes fabrication
        visible rather than silent.
        """
        if not self.returned:
            return []
        valid = set(self.valid)
        seen: set[str] = set()
        result: list[str] = []
        for item in self.returned:
            if not isinstance(item, str):
                continue
            for match in re.finditer(r"\bD\d+\b", item, re.IGNORECASE):
                citation = match.group(0).upper()
                if citation not in valid and citation not in seen:
                    seen.add(citation)
                    result.append(citation)
        return result
