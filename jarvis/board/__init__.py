"""The board of advisors.

A standing council of well-documented operators that JARVIS can convene on a
real decision. Each seat is one markdown file — a dossier of numbered, sourced
principles that a model reads and reasons from.

Two failure modes this design exists to prevent:

- **Consensus theater.** One model asked to voice five people produces five
  hats on one head. The defense is structural: each seat gets its own isolated
  model call containing exactly one dossier.

- **Confident fabrication.** A persona will happily invent a position the real
  person has never taken. The defense is a citation gate: every dossier holds
  numbered doctrine entries, a seat may only cite the ids in its own dossier,
  and any other citation is stripped server-side before the user ever sees it.

The gate can prove a citation exists in the file. It can never prove the file
is true. That is why the research process has two stages and why the second
stage is adversarial.
"""

from .dossier import Dossier, DoctrineEntry, parse_dossier
from .gate import CitationGate, filter_citations

__all__ = [
    "CitationGate",
    "Dossier",
    "DoctrineEntry",
    "filter_citations",
    "parse_dossier",
]
