"""The scout check — integrates the research loop with the heartbeat.

The scout is a Check that runs on a schedule, calls the research loop, and
surfaces results as a CheckResult. It follows the same pattern as every other
check: quiet by default, most runs produce nothing.

Key design decisions:
- The scout check wraps the research loop, adding schedule integration
- It uses the doctrine (from DOCTRINE.md or override) as the system prompt
- It tracks seen items to avoid repeats across runs
- It delivers even when empty — an empty run is information
- It persists per-item, not per-report — one malformed row must not discard
  the four good ones beside it
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..paths import STATE_DIR
from ..providers import Provider
from ..scout.doctrine import system_prompt
from ..scout.loop import ResearchLoopConfig, run_research_loop
from ..scout.overrides import effective_document
from ..scout.report import Finding, ScoutReport
from .checks import Check, CheckContext, CheckResult
from .inbox import NORMAL, QUIET

SEEN_ITEMS_PATH = STATE_DIR / "scout_seen.json"


@dataclass
class SeenItems:
    """Tracks which findings have been seen across runs.

    This is how the scout avoids repeating itself. The store is a JSON file
    with a list of seen item identifiers (URLs or titles).
    """

    items: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path = SEEN_ITEMS_PATH) -> "SeenItems":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return cls(items=raw.get("items", []))
        except (OSError, json.JSONDecodeError):
            return cls()

    def save(self, path: Path = SEEN_ITEMS_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"items": self.items}, indent=2), encoding="utf-8")

    def add(self, item: str) -> None:
        if item not in self.items:
            self.items.append(item)

    def __contains__(self, item: str) -> bool:
        return item in self.items


class ScoutCheck:
    """The scout as a heartbeat check.

    Runs the research loop on a schedule, surfaces results as a CheckResult.
    Quiet by default — most runs produce nothing.
    """

    name = "scout"

    def __init__(
        self,
        interval_seconds: float,
        settings: dict,
        provider: Provider,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.settings = settings
        self.provider = provider
        self.seen = SeenItems.load()

    def run(self, ctx: CheckContext) -> CheckResult:
        """Run the scout. Never raises; never stacks on an in-flight run."""
        query = self.settings.get("query", "competitor product news")
        max_iterations = int(self.settings.get("max_iterations", 12))
        timeout_s = float(self.settings.get("timeout_s", 120.0))

        config = ResearchLoopConfig(
            max_iterations=max_iterations,
            max_cost_usd=0.0,  # $0 = free tier only
            timeout_s=timeout_s,
        )

        # Load the doctrine (override or file)
        from ..scout.doctrine import DOCTRINE_PATH
        prompt = effective_document("scout_doctrine", DOCTRINE_PATH)

        # Run the research loop
        start = time.monotonic()
        try:
            report = run_research_loop(
                query=query,
                system_prompt=prompt,
                provider=self.provider,
                config=config,
            )
        except Exception as exc:  # noqa: BLE001 — a check must never crash
            return CheckResult(
                summary=f"scout error: {type(exc).__name__}: {exc}",
            )

        elapsed = time.monotonic() - start

        # Filter out seen items
        new_findings = [f for f in report.findings if f.source_url not in self.seen]

        # Persist per-item, not per-report
        persisted = 0
        for finding in new_findings:
            try:
                self.seen.add(finding.source_url)
                persisted += 1
            except Exception:  # noqa: BLE001 — one bad item must not stop the rest
                continue

        if persisted > 0:
            self.seen.save()

        # Build the result
        if report.stop_reason != "completed":
            # The run failed — surface it so the operator knows
            return CheckResult(
                surfaced=True,
                title=f"Scout run {report.stop_reason}",
                body=(
                    f"The scout run did not complete normally. "
                    f"Stop reason: {report.stop_reason}. "
                    f"Error: {report.error or 'none'}. "
                    f"Iterations: {report.iterations}, "
                    f"Cost: ${report.cost_usd:.4f}, "
                    f"Time: {report.wall_clock_s:.1f}s."
                ),
                level=NORMAL,
                summary=f"scout {report.stop_reason}",
            )

        if not new_findings:
            # Empty run — still report, but quietly
            return CheckResult(
                summary=(
                    f"scout: {len(report.findings)} found, "
                    f"{persisted} new, "
                    f"{len(report.findings) - persisted} already seen"
                ),
            )

        # Surface the new findings
        lines = []
        for f in new_findings[:5]:  # Cap at 5 to avoid overwhelming
            lines.append(f"• {f.title}")
            lines.append(f"  {f.summary[:100]}")
            lines.append(f"  Relevance: {f.relevance}/5, Novelty: {f.novelty}/5, Impact: {f.impact}/5")
            lines.append(f"  Kill: {f.kill_criterion}")
            lines.append(f"  {f.source_url}")
            lines.append("")

        body = "\n".join(lines).strip()
        if len(new_findings) > 5:
            body += f"\n\n…and {len(new_findings) - 5} more."

        return CheckResult(
            surfaced=True,
            title=f"Scout found {len(new_findings)} new item(s)",
            body=body,
            level=QUIET,
            summary=f"scout: {persisted} new finding(s)",
        )
