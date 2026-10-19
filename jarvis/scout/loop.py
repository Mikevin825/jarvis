"""The scout's research loop.

One function you can call by hand that hunts and returns a typed report.

The loop gives the model real research tools plus one terminal tool —
emit_report — whose call ends the loop and whose input IS the result. This
beats asking for JSON in prose: the schema is enforced at the tool-call layer,
so the model retries on a mismatch instead of handing back unparseable text.

Four things that bite here, all worth writing down:

- max_tokens is a silent killer. A full scorecard with evidence and arithmetic
  does not fit a small default. The first truncated run validates to nothing and
  looks like "the model found nothing." Size it deliberately and say in a
  comment that the cost cap — not the token limit — is the real guardrail.

- Salvage, don't discard. A truncated response usually contains the summary and
  the first item or two. Hand the partial payload to a coercion function that
  keeps what parses and drops what doesn't, rather than throwing away a run
  the operator just paid for.

- Distinguish failure modes in the logs. truncated, loop_detected, exhausted,
  and completed should not all produce the same message. When this thing
  quietly stops working months from now, those log lines are the entire
  investigation.

- A salvage message must not read like a finding. If your coercion path returns
  something like "partial result — nothing cleared the bar," an operator
  glancing at a briefing cannot tell a broken run from an honest empty one.
  Make the fallback text unmistakably a failure, or carry a status field
  alongside it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..providers import (
    Message,
    Provider,
    ProviderError,
    TextDelta,
    ToolOutput,
    TurnEnd,
)
from ..tools import Tool, ToolRegistry
from .report import Finding, ScoutReport
from .tools import build as build_research_tools

# The emit_report tool's input schema. This IS the report schema — the model
# must conform to it or the tool call fails.
_EMIT_REPORT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "findings": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "summary": {"type": "STRING"},
                    "source_url": {"type": "STRING"},
                    "relevance": {"type": "INTEGER", "minimum": 1, "maximum": 5},
                    "novelty": {"type": "INTEGER", "minimum": 1, "maximum": 5},
                    "impact": {"type": "INTEGER", "minimum": 1, "maximum": 5},
                    "kill_criterion": {"type": "STRING"},
                    "seen_before": {"type": "BOOLEAN"},
                },
                "required": [
                    "title", "summary", "source_url",
                    "relevance", "novelty", "impact", "kill_criterion",
                ],
            },
        },
    },
    "required": ["findings"],
}


@dataclass
class ResearchLoopConfig:
    """Guards for the research loop.

    cost_usd is the hard ceiling — the real guardrail. max_tokens is sized for
    a FULL report, not the default. A truncated run salvages what it can.
    """

    max_iterations: int = 12
    max_cost_usd: float = 0.0  # $0 = free tier only
    timeout_s: float = 120.0
    max_tokens: int = 8192  # Sized for a full scorecard, not the default


def _coerce_finding(raw: object) -> Finding | None:
    """Coerce a raw dict into a Finding, or None if it doesn't parse.

    This is the salvage path. A truncated response usually contains the first
    item or two — keep what parses, drop what doesn't.

    Required fields must be present and have the right type. If any are
    missing or wrong, the finding is dropped rather than coerced with defaults.
    """
    if not isinstance(raw, dict):
        return None
    try:
        # Let the try/except handle missing keys, None values, and bad types.
        # int(None) raises TypeError, int("abc") raises ValueError — both caught.
        return Finding(
            title=str(raw["title"]),
            summary=str(raw["summary"]),
            source_url=str(raw["source_url"]),
            relevance=max(1, min(5, int(raw["relevance"]))),
            novelty=max(1, min(5, int(raw["novelty"]))),
            impact=max(1, min(5, int(raw["impact"]))),
            kill_criterion=str(raw["kill_criterion"]),
            seen_before=bool(raw.get("seen_before", False)),
        )
    except (TypeError, ValueError, KeyError):
        return None


def _salvage_report(raw_args: dict | None) -> tuple[list[Finding], str]:
    """Salvage a truncated or partial report.

    Returns (findings, note). The note is set when something was dropped, so
    the operator can tell a partial run from a complete one.
    """
    if raw_args is None:
        return [], "no report was emitted"

    raw_findings = raw_args.get("findings")
    if not isinstance(raw_findings, list):
        return [], "report had no findings array"

    findings: list[Finding] = []
    dropped = 0
    for raw in raw_findings:
        finding = _coerce_finding(raw) if isinstance(raw, dict) else None
        if finding is not None:
            findings.append(finding)
        else:
            dropped += 1

    note = f" ({dropped} finding(s) dropped — truncated)" if dropped else ""
    return findings, note


def run_research_loop(
    query: str,
    system_prompt: str,
    provider: Provider,
    config: ResearchLoopConfig | None = None,
) -> ScoutReport:
    """Run one research loop and return a validated report.

    This is the function you call by hand. It hunts using the research tools,
    and ends when the model calls emit_report (the terminal tool) or when a
    guard is hit.

    The loop enforces cost, iteration, and wall-clock ceilings. A truncated or
    failed run salvages what it can — the stop_reason in the report tells you
    what happened.
    """
    cfg = config or ResearchLoopConfig()
    start_time = time.monotonic()
    total_cost = 0.0
    iterations = 0
    searched: list[str] = []

    # Build the tool registry: research tools + the terminal emit_report tool.
    registry = ToolRegistry()
    for tool in build_research_tools():
        registry.register(tool)

    # The terminal tool. When the model calls this, the loop ends and its
    # arguments become the report. We capture the args and return a success
    # result so the model knows the report was received.
    captured_args: dict | None = None

    def _emit_report(findings: list[dict]) -> str:
        nonlocal captured_args
        captured_args = {"findings": findings}
        return "Report emitted."

    registry.register(
        Tool(
            name="emit_report",
            description=(
                "Emit the final scored report. Call once, at the end, "
                "with all findings. Each finding must have title, summary, "
                "source_url, relevance (1-5), novelty (1-5), impact (1-5), "
                "and kill_criterion."
            ),
            parameters=_EMIT_REPORT_SCHEMA,
            func=_emit_report,
        )
    )

    # Run the loop using the brain's provider directly.
    #
    # The query goes in a user message, not only in the system prompt: the
    # provider requires at least one content turn, and starting from an empty
    # list makes every request fail with "contents is not specified".
    messages: list[Message] = [Message(role="user", content=query)]
    stop_reason = "completed"
    error: str | None = None
    # The loop must keep going until the model calls the terminal tool, so the
    # break has to key off an explicit flag. Keying off stop_reason ==
    # "completed" broke out after the first tool round, because that is also its
    # initial value — the scout did one search and gave up.
    terminal_called = False

    try:
        for iteration in range(cfg.max_iterations + 1):
            iterations = iteration + 1

            # Check wall-clock timeout.
            elapsed = time.monotonic() - start_time
            if elapsed > cfg.timeout_s:
                stop_reason = "timeout"
                break

            # Check cost ceiling.
            if total_cost > cfg.max_cost_usd and cfg.max_cost_usd > 0:
                stop_reason = "cost_exceeded"
                break

            # Stream one turn. The doctrine is the system prompt; the query is
            # already the opening user message.
            end: TurnEnd | None = None
            for event in provider.stream(system_prompt, messages, registry.declarations()):
                if isinstance(event, TextDelta):
                    pass  # We don't need the text for the report
                elif isinstance(event, TurnEnd):
                    end = event
                    # Track cost from usage.
                    if event.usage:
                        # Usage format varies by provider; try common keys.
                        cost = (
                            event.usage.get("cost_usd", 0)
                            or event.usage.get("total_cost", 0)
                            or 0
                        )
                        total_cost += float(cost)

            if end is None:
                stop_reason = "error"
                error = "the model returned nothing at all"
                break

            # Check for truncation.
            raw = end.raw
            if isinstance(raw, dict) and raw.get("finish_reason") == "length":
                stop_reason = "truncated"
                break

            # If no tool calls, the model is done — but did it call emit_report?
            if not end.calls:
                if captured_args is not None:
                    stop_reason = "completed"
                else:
                    stop_reason = "no_terminal_call"
                    error = "the model returned without calling emit_report"
                break

            # Run tool calls.
            outputs: list[ToolOutput] = []
            for call in end.calls:
                result = registry.run(call.name, call.args)
                outputs.append(
                    ToolOutput(
                        name=call.name,
                        content=result.content,
                        ok=result.ok,
                    )
                )
                # Record what was actually looked up. Without this the report's
                # `searched` list is always empty and the run cannot be audited.
                if call.name in ("web_search", "fetch_rss", "fetch_url"):
                    target = call.args.get("query") or call.args.get("url")
                    if target:
                        searched.append(f"{call.name}: {target}")
                if call.name == "emit_report":
                    # The terminal tool was called — end the loop.
                    stop_reason = "completed"
                    terminal_called = True
                    break

            messages.append(
                Message(
                    role="assistant",
                    content=end.text,
                    calls=end.calls,
                    raw=end.raw,
                )
            )
            messages.append(Message(role="tool", outputs=outputs))

            if terminal_called:
                break

    except ProviderError as exc:
        stop_reason = "error"
        error = str(exc)
    except Exception as exc:  # noqa: BLE001 — a research loop must not crash
        stop_reason = "error"
        error = f"{type(exc).__name__}: {exc}"

    # Build the report.
    wall_clock = time.monotonic() - start_time

    if captured_args is not None:
        findings, note = _salvage_report(captured_args)
        if note and stop_reason == "completed":
            stop_reason = "truncated"
            error = note
    else:
        findings = []
        if stop_reason == "completed":
            stop_reason = "no_terminal_call"

    return ScoutReport(
        findings=findings,
        searched=searched,
        cost_usd=total_cost,
        iterations=iterations,
        wall_clock_s=wall_clock,
        stop_reason=stop_reason,
        error=error,
    )
