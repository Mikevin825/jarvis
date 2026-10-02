"""The scout's report schema.

The report is the typed object the research loop returns. It is enforced at the
tool-call layer: the emit_report tool's parameters define the schema, and the
model must conform to it or the tool call fails. This beats asking for JSON in
prose — the schema is enforced by the tool-call layer, so the model retries on
a mismatch instead of handing back unparseable text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Finding:
    """One scored finding from the scout.

    Each finding carries a kill criterion — a pre-committed bar that says when
    to abandon it later. This is what makes the scout's output actionable
    rather than just informative.
    """

    title: str
    summary: str
    source_url: str
    relevance: int  # 1-5: how relevant is this to the operator's interests
    novelty: int    # 1-5: how new is this information
    impact: int     # 1-5: how much could this affect the operator
    kill_criterion: str  # When to abandon this find
    seen_before: bool = False  # Whether this was seen in a previous run


@dataclass
class ScoutReport:
    """The final report from a scout run.

    The stop_reason distinguishes failure modes in the logs. When this thing
    quietly stops working months from now, those log lines are the entire
    investigation.
    """

    findings: list[Finding]
    searched: list[str]  # What was searched (queries, URLs)
    cost_usd: float
    iterations: int
    wall_clock_s: float
    stop_reason: Literal[
        "completed",      # emit_report was called successfully
        "truncated",      # the model's response was truncated
        "exhausted",      # hit the iteration cap
        "loop_detected",  # the model is looping
        "cost_exceeded",  # hit the cost ceiling
        "timeout",        # hit the wall-clock timeout
        "error",          # an exception occurred
        "no_terminal_call",  # the model returned without calling emit_report
    ]
    error: str | None = None  # Set when stop_reason indicates a problem
