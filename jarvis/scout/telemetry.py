"""Telemetry that compounds.

Every run leaves behind a record that makes later runs smarter for free.

Record every entity the scout examined — not just the ones it surfaced — with
a timestamp and whatever cheap metrics your sources already return. On the
next run, the delta between snapshots is a signal you didn't pay for: something
growing fast, something gone stale, something that changed direction.

Also worth capturing: when a paid data source would have changed a score. Have
the scout say so in its report. That sentence is how the operator decides
whether a subscription is worth buying, instead of guessing.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..paths import STATE_DIR

TELEMETRY_PATH = STATE_DIR / "scout_telemetry.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass
class EntitySnapshot:
    """One entity examined during a run, with cheap metrics."""

    identifier: str  # URL or title
    source: str  # Which tool found it
    examined_at: datetime = field(default_factory=_now)
    # Cheap metrics — whatever the source already returns.
    metrics: dict = field(default_factory=dict)
    # Whether this entity was surfaced as a finding.
    surfaced: bool = False
    # Score if surfaced (composite of relevance, novelty, impact).
    score: float | None = None

    def to_dict(self) -> dict:
        return {
            "identifier": self.identifier,
            "source": self.source,
            "examined_at": _iso(self.examined_at),
            "metrics": self.metrics,
            "surfaced": self.surfaced,
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "EntitySnapshot":
        examined = raw.get("examined_at", "")
        try:
            when = datetime.fromisoformat(examined) if examined else _now()
        except (TypeError, ValueError):
            when = _now()
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return cls(
            identifier=raw.get("identifier", ""),
            source=raw.get("source", ""),
            examined_at=when,
            metrics=raw.get("metrics", {}),
            surfaced=bool(raw.get("surfaced", False)),
            score=raw.get("score"),
        )


@dataclass
class RunTelemetry:
    """One run's telemetry record."""

    run_id: str
    started_at: datetime = field(default_factory=_now)
    finished_at: datetime | None = None
    entities: list[EntitySnapshot] = field(default_factory=list)
    # What was searched (queries, URLs).
    searched: list[str] = field(default_factory=list)
    # Cost and performance.
    cost_usd: float = 0.0
    iterations: int = 0
    wall_clock_s: float = 0.0
    stop_reason: str = "completed"
    # When a paid source would have changed a score.
    paid_source_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at) if self.finished_at else None,
            "entities": [e.to_dict() for e in self.entities],
            "searched": self.searched,
            "cost_usd": self.cost_usd,
            "iterations": self.iterations,
            "wall_clock_s": self.wall_clock_s,
            "stop_reason": self.stop_reason,
            "paid_source_notes": self.paid_source_notes,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "RunTelemetry":
        started = raw.get("started_at", "")
        try:
            started_when = datetime.fromisoformat(started) if started else _now()
        except (TypeError, ValueError):
            started_when = _now()
        if started_when.tzinfo is None:
            started_when = started_when.replace(tzinfo=timezone.utc)

        finished = raw.get("finished_at")
        finished_when = None
        if finished:
            try:
                finished_when = datetime.fromisoformat(finished)
            except (TypeError, ValueError):
                finished_when = None
            if finished_when and finished_when.tzinfo is None:
                finished_when = finished_when.replace(tzinfo=timezone.utc)

        return cls(
            run_id=raw.get("run_id", ""),
            started_at=started_when,
            finished_at=finished_when,
            entities=[EntitySnapshot.from_dict(e) for e in raw.get("entities", [])],
            searched=raw.get("searched", []),
            cost_usd=float(raw.get("cost_usd", 0)),
            iterations=int(raw.get("iterations", 0)),
            wall_clock_s=float(raw.get("wall_clock_s", 0)),
            stop_reason=raw.get("stop_reason", "completed"),
            paid_source_notes=raw.get("paid_source_notes", []),
        )


@dataclass
class Delta:
    """The delta between two snapshots of the same entity."""

    identifier: str
    previous: EntitySnapshot
    current: EntitySnapshot
    # What changed.
    metrics_changed: dict = field(default_factory=dict)
    score_changed: bool = False
    score_delta: float = 0.0
    # How many runs apart.
    runs_apart: int = 1

    def describe(self) -> str:
        parts = [f"{self.identifier}:"]
        if self.metrics_changed:
            for key, (old, new) in self.metrics_changed.items():
                parts.append(f"  {key}: {old} → {new}")
        if self.score_changed:
            parts.append(f"  score: {self.score_delta:+.1f}")
        return "\n".join(parts)


class TelemetryStore:
    """A durable store of run telemetry.

    Records every entity examined — not just the ones surfaced — with a
    timestamp and cheap metrics. On the next run, the delta between snapshots
    is a signal you didn't pay for.
    """

    def __init__(self, path: Path = TELEMETRY_PATH) -> None:
        self.path = path
        self._runs: list[RunTelemetry] = []
        self._loaded = False

    def load(self) -> "TelemetryStore":
        if not self.path.exists():
            self._loaded = True
            return self
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._loaded = True
            return self
        self._runs = [RunTelemetry.from_dict(r) for r in raw.get("runs", [])]
        self._loaded = True
        return self

    def _save(self) -> None:
        payload = {
            "runs": [r.to_dict() for r in self._runs],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    def record_run(self, run: RunTelemetry) -> None:
        """Record one run's telemetry."""
        if not self._loaded:
            self.load()
        self._runs.append(run)
        self._save()

    def last_run(self) -> RunTelemetry | None:
        """The most recent run, or None if no runs recorded."""
        if not self._loaded:
            self.load()
        return self._runs[-1] if self._runs else None

    def previous_run(self) -> RunTelemetry | None:
        """The run before the last, or None if fewer than two runs."""
        if not self._loaded:
            self.load()
        return self._runs[-2] if len(self._runs) >= 2 else None

    def compute_deltas(self) -> list[Delta]:
        """Compute deltas between the last two runs.

        The delta between snapshots is a signal you didn't pay for: something
        growing fast, something gone stale, something that changed direction.
        """
        last = self.last_run()
        prev = self.previous_run()
        if last is None or prev is None:
            return []

        # Index previous entities by identifier.
        prev_by_id = {e.identifier: e for e in prev.entities}

        deltas: list[Delta] = []
        for entity in last.entities:
            previous = prev_by_id.get(entity.identifier)
            if previous is None:
                continue

            # Compare metrics.
            metrics_changed = {}
            for key in set(previous.metrics) | set(entity.metrics):
                old_val = previous.metrics.get(key)
                new_val = entity.metrics.get(key)
                if old_val != new_val:
                    metrics_changed[key] = (old_val, new_val)

            # Compare scores.
            score_changed = False
            score_delta = 0.0
            if entity.score is not None and previous.score is not None:
                score_delta = entity.score - previous.score
                if abs(score_delta) > 0.01:
                    score_changed = True

            if metrics_changed or score_changed:
                deltas.append(
                    Delta(
                        identifier=entity.identifier,
                        previous=previous,
                        current=entity,
                        metrics_changed=metrics_changed,
                        score_changed=score_changed,
                        score_delta=score_delta,
                    )
                )

        return deltas

    def entities_examined(self) -> int:
        """Total entities examined across all runs."""
        if not self._loaded:
            self.load()
        return sum(len(r.entities) for r in self._runs)

    def entities_surfaced(self) -> int:
        """Total entities surfaced across all runs."""
        if not self._loaded:
            self.load()
        return sum(sum(1 for e in r.entities if e.surfaced) for r in self._runs)

    def total_cost(self) -> float:
        """Total cost across all runs."""
        if not self._loaded:
            self.load()
        return sum(r.cost_usd for r in self._runs)

    def paid_source_notes(self) -> list[str]:
        """All paid-source notes across all runs."""
        if not self._loaded:
            self.load()
        notes = []
        for run in self._runs:
            notes.extend(run.paid_source_notes)
        return notes
