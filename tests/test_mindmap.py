"""Tests for the mind map data contract.

Two JSON endpoints, verified with curl, before any 3D exists. The backend is
a pure assembly function, and every source is isolated.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.mindmap import (
    FRESHNESS_FLOOR,
    SIMILARITY_THRESHOLD,
    SIMILARITY_TOP_K,
    MindEdge,
    MindNode,
    MindSkeleton,
    _build_core_region,
    _build_knowledge_region,
    _build_memory_region,
    _build_rim_region,
    _cooccurrence_edges,
    _freshness,
    build_mind_skeleton,
    get_node_detail,
)
from jarvis.memory import MemoryStore
from jarvis.tools import build_registry


class TestFreshness:
    def test_exponential_decay(self) -> None:
        assert _freshness(0) == 1.0
        assert _freshness(30) == pytest.approx(0.5)
        assert _freshness(60) == pytest.approx(0.25)

    def test_floored_at_minimum(self) -> None:
        assert _freshness(365) >= FRESHNESS_FLOOR


class TestCooccurrenceEdges:
    def test_no_edges_for_single_node(self) -> None:
        nodes = [MindNode(id="a", type="memory", region="memory", label="test", color="#fff", size=1.0, freshness=1.0)]
        assert _cooccurrence_edges(nodes) == []

    def test_links_nodes_with_shared_words(self) -> None:
        nodes = [
            MindNode(id="a", type="memory", region="memory", label="coffee milk", color="#fff", size=1.0, freshness=1.0),
            MindNode(id="b", type="memory", region="memory", label="coffee sugar", color="#fff", size=1.0, freshness=1.0),
        ]
        edges = _cooccurrence_edges(nodes)
        assert len(edges) > 0
        assert edges[0].kind == "cooccurrence"

    def test_no_edges_for_unrelated_nodes(self) -> None:
        nodes = [
            MindNode(id="a", type="memory", region="memory", label="coffee milk", color="#fff", size=1.0, freshness=1.0),
            MindNode(id="b", type="memory", region="memory", label="quantum physics", color="#fff", size=1.0, freshness=1.0),
        ]
        edges = _cooccurrence_edges(nodes)
        assert edges == []

    def test_respects_top_k(self) -> None:
        nodes = [
            MindNode(id=f"n{i}", type="memory", region="memory", label="coffee milk sugar", color="#fff", size=1.0, freshness=1.0)
            for i in range(10)
        ]
        edges = _cooccurrence_edges(nodes, top_k=2)
        # Each node initiates at most top_k edges (as source)
        out_degree: dict[str, int] = {}
        for e in edges:
            out_degree[e.source] = out_degree.get(e.source, 0) + 1
        assert all(d <= 2 for d in out_degree.values())


class TestBuildRegions:
    def test_core_region(self) -> None:
        nodes, edges = _build_core_region()
        assert len(nodes) == 1
        assert nodes[0].id == "core:jarvis"
        assert nodes[0].region == "core"

    def test_memory_region_empty(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "memory.txt")
        nodes, edges, status = _build_memory_region(store)
        assert nodes == []
        assert status == "empty"

    def test_memory_region_with_facts(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "memory.txt")
        store.add("The user likes coffee")
        store.add("The user likes tea")
        nodes, edges, status = _build_memory_region(store)
        assert len(nodes) == 2
        assert status == "ok"
        assert nodes[0].id.startswith("mem:")

    def test_knowledge_region(self) -> None:
        nodes, edges, status = _build_knowledge_region()
        assert len(nodes) >= 1
        assert status == "ok"

    def test_rim_region(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "memory.txt")
        registry = build_registry(store)
        nodes, edges, status = _build_rim_region(registry)
        assert len(nodes) > 0
        assert status == "ok"


class TestBuildMindSkeleton:
    def test_builds_skeleton(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "memory.txt")
        store.add("The user likes coffee")
        registry = build_registry(store)

        skeleton = build_mind_skeleton(memory_store=store, tool_registry=registry)

        assert isinstance(skeleton, MindSkeleton)
        assert "core" in skeleton.regions
        assert "memory" in skeleton.regions
        assert "knowledge" in skeleton.regions
        assert "rim" in skeleton.regions
        assert len(skeleton.nodes) > 0
        assert skeleton.stats["memory_total"] == 1

    def test_skeleton_to_dict(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "memory.txt")
        registry = build_registry(store)

        skeleton = build_mind_skeleton(memory_store=store, tool_registry=registry)
        data = skeleton.to_dict()

        assert "regions" in data
        assert "nodes" in data
        assert "edges" in data
        assert "stats" in data
        assert isinstance(data["nodes"], list)
        assert isinstance(data["edges"], list)

    def test_empty_skeleton(self) -> None:
        skeleton = build_mind_skeleton(memory_store=None, tool_registry=None)
        assert skeleton.stats["memory"] == "no memory store"
        assert skeleton.stats["rim"] == "no tool registry"


class TestGetNodeDetail:
    def test_returns_none_for_unknown_id(self) -> None:
        assert get_node_detail("unknown:id") is None

    def test_returns_none_for_invalid_prefix(self) -> None:
        assert get_node_detail("invalid:id") is None

    def test_memory_node_detail(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "memory.txt")
        fact = store.add("The user likes coffee with milk")

        detail = get_node_detail(f"mem:{fact.id}", memory_store=store)
        assert detail is not None
        assert detail["type"] == "memory"
        assert detail["label"] == "The user likes coffee with milk"
        assert "neighbors" in detail

    def test_knowledge_node_detail(self) -> None:
        detail = get_node_detail("know:AGENT.md")
        assert detail is not None
        assert detail["type"] == "knowledge"
        assert "preview" in detail

    def test_knowledge_node_rejects_arbitrary_path(self) -> None:
        assert get_node_detail("know:../../etc/passwd") is None

    def test_tool_node_detail(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "memory.txt")
        registry = build_registry(store)

        detail = get_node_detail("tool:get_weather")
        assert detail is not None
        assert detail["type"] == "tool"
        assert detail["label"] == "get_weather"
