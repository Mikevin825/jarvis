"""Tests for the telemetry store.

Telemetry that compounds: every run leaves behind a record that makes later
runs smarter for free. The delta between snapshots is a signal you didn't pay
for.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jarvis.scout.telemetry import (
    TELEMETRY_PATH,
    Delta,
    EntitySnapshot,
    RunTelemetry,
    TelemetryStore,
)


def _make_entity(
    identifier: str,
    source: str = "web_search",
    metrics: dict | None = None,
    surfaced: bool = False,
    score: float | None = None,
    examined_at: datetime | None = None,
) -> EntitySnapshot:
    return EntitySnapshot(
        identifier=identifier,
        source=source,
        examined_at=examined_at or datetime.now(timezone.utc),
        metrics=metrics or {},
        surfaced=surfaced,
        score=score,
    )


def _make_run(
    run_id: str,
    entities: list[EntitySnapshot] | None = None,
    searched: list[str] | None = None,
    cost_usd: float = 0.0,
    iterations: int = 5,
    wall_clock_s: float = 10.0,
    stop_reason: str = "completed",
    paid_source_notes: list[str] | None = None,
    started_at: datetime | None = None,
) -> RunTelemetry:
    return RunTelemetry(
        run_id=run_id,
        started_at=started_at or datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        entities=entities or [],
        searched=searched or [],
        cost_usd=cost_usd,
        iterations=iterations,
        wall_clock_s=wall_clock_s,
        stop_reason=stop_reason,
        paid_source_notes=paid_source_notes or [],
    )


class TestEntitySnapshot:
    def test_to_dict_round_trip(self) -> None:
        entity = _make_entity(
            "https://example.com/article1",
            metrics={"views": 100},
            surfaced=True,
            score=4.5,
        )
        raw = entity.to_dict()
        restored = EntitySnapshot.from_dict(raw)
        assert restored.identifier == entity.identifier
        assert restored.source == entity.source
        assert restored.metrics == entity.metrics
        assert restored.surfaced == entity.surfaced
        assert restored.score == entity.score

    def test_from_dict_handles_missing_fields(self) -> None:
        raw = {"identifier": "https://example.com"}
        entity = EntitySnapshot.from_dict(raw)
        assert entity.identifier == "https://example.com"
        assert entity.source == ""
        assert entity.metrics == {}
        assert entity.surfaced is False
        assert entity.score is None


class TestRunTelemetry:
    def test_to_dict_round_trip(self) -> None:
        run = _make_run(
            "run-1",
            entities=[_make_entity("https://example.com")],
            searched=["query1"],
            cost_usd=0.01,
        )
        raw = run.to_dict()
        restored = RunTelemetry.from_dict(raw)
        assert restored.run_id == run.run_id
        assert len(restored.entities) == 1
        assert restored.searched == run.searched
        assert restored.cost_usd == run.cost_usd

    def test_from_dict_handles_missing_fields(self) -> None:
        raw = {"run_id": "run-1"}
        run = RunTelemetry.from_dict(raw)
        assert run.run_id == "run-1"
        assert run.entities == []
        assert run.searched == []
        assert run.cost_usd == 0.0


class TestTelemetryStore:
    def test_loads_empty_when_no_file(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "telemetry.json")
        store.load()
        assert store.last_run() is None
        assert store.previous_run() is None

    def test_records_and_retrieves_runs(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "telemetry.json")
        run1 = _make_run("run-1")
        run2 = _make_run("run-2")
        store.record_run(run1)
        store.record_run(run2)
        last = store.last_run()
        assert last is not None
        assert last.run_id == "run-2"
        prev = store.previous_run()
        assert prev is not None
        assert prev.run_id == "run-1"

    def test_persists_to_disk(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "telemetry.json")
        store.record_run(_make_run("run-1"))
        # Create a new store instance and load
        store2 = TelemetryStore(tmp_path / "telemetry.json")
        store2.load()
        last = store2.last_run()
        assert last is not None
        assert last.run_id == "run-1"

    def test_compute_deltas_empty_with_one_run(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "telemetry.json")
        store.record_run(_make_run("run-1"))
        assert store.compute_deltas() == []

    def test_compute_deltas_empty_with_no_runs(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "telemetry.json")
        assert store.compute_deltas() == []

    def test_compute_detects_metric_changes(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "telemetry.json")
        run1 = _make_run(
            "run-1",
            entities=[_make_entity("https://example.com", metrics={"views": 100})],
        )
        run2 = _make_run(
            "run-2",
            entities=[_make_entity("https://example.com", metrics={"views": 150})],
        )
        store.record_run(run1)
        store.record_run(run2)
        deltas = store.compute_deltas()
        assert len(deltas) == 1
        assert deltas[0].identifier == "https://example.com"
        assert "views" in deltas[0].metrics_changed
        assert deltas[0].metrics_changed["views"] == (100, 150)

    def test_compute_detects_score_changes(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "telemetry.json")
        run1 = _make_run(
            "run-1",
            entities=[_make_entity("https://example.com", score=3.0)],
        )
        run2 = _make_run(
            "run-2",
            entities=[_make_entity("https://example.com", score=4.5)],
        )
        store.record_run(run1)
        store.record_run(run2)
        deltas = store.compute_deltas()
        assert len(deltas) == 1
        assert deltas[0].score_changed is True
        assert deltas[0].score_delta == 1.5

    def test_compute_ignores_new_entities(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "telemetry.json")
        run1 = _make_run(
            "run-1",
            entities=[_make_entity("https://example.com/old")],
        )
        run2 = _make_run(
            "run-2",
            entities=[_make_entity("https://example.com/new")],
        )
        store.record_run(run1)
        store.record_run(run2)
        # New entity in run2 has no previous snapshot, so no delta.
        assert store.compute_deltas() == []

    def test_compute_ignores_unchanged_entities(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "telemetry.json")
        run1 = _make_run(
            "run-1",
            entities=[_make_entity("https://example.com", metrics={"views": 100})],
        )
        run2 = _make_run(
            "run-2",
            entities=[_make_entity("https://example.com", metrics={"views": 100})],
        )
        store.record_run(run1)
        store.record_run(run2)
        assert store.compute_deltas() == []

    def test_entities_examined_counts_all(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "telemetry.json")
        run1 = _make_run(
            "run-1",
            entities=[
                _make_entity("https://a.com"),
                _make_entity("https://b.com"),
            ],
        )
        run2 = _make_run(
            "run-2",
            entities=[_make_entity("https://c.com")],
        )
        store.record_run(run1)
        store.record_run(run2)
        assert store.entities_examined() == 3

    def test_entities_surfaced_counts_only_surfaced(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "telemetry.json")
        run = _make_run(
            "run-1",
            entities=[
                _make_entity("https://a.com", surfaced=True),
                _make_entity("https://b.com", surfaced=False),
                _make_entity("https://c.com", surfaced=True),
            ],
        )
        store.record_run(run)
        assert store.entities_surfaced() == 2

    def test_total_cost_sums_all_runs(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "telemetry.json")
        store.record_run(_make_run("run-1", cost_usd=0.01))
        store.record_run(_make_run("run-2", cost_usd=0.02))
        assert store.total_cost() == pytest.approx(0.03)

    def test_paid_source_notes_collects_all(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "telemetry.json")
        store.record_run(
            _make_run("run-1", paid_source_notes=["Paid source A would have changed score"])
        )
        store.record_run(
            _make_run("run-2", paid_source_notes=["Paid source B would have changed score"])
        )
        notes = store.paid_source_notes()
        assert len(notes) == 2
        assert "Paid source A" in notes[0]
        assert "Paid source B" in notes[1]

    def test_delta_describe_includes_changes(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "telemetry.json")
        run1 = _make_run(
            "run-1",
            entities=[_make_entity("https://example.com", metrics={"views": 100}, score=3.0)],
        )
        run2 = _make_run(
            "run-2",
            entities=[_make_entity("https://example.com", metrics={"views": 150}, score=4.5)],
        )
        store.record_run(run1)
        store.record_run(run2)
        deltas = store.compute_deltas()
        assert len(deltas) == 1
        description = deltas[0].describe()
        assert "https://example.com" in description
        assert "views" in description
        assert "score" in description
