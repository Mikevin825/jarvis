"""The mind map data contract.

Two JSON endpoints, verified with curl, before any 3D exists.

The backend is a pure assembly function, and every source is isolated. One
endpoint returns a "skeleton": a flat list of nodes and a flat list of edges,
plus a stats block. Each region is built inside its own try, so a broken
memory index or a failed database query empties that region only and records
"error" in the stats, instead of returning a 500 and giving a black page.

Write this as a plain function taking explicit arguments (the memory store,
the conversation repo, the tool registry) — not reaching into globals — so
it's testable without spinning up the server. Detail for a single node loads
lazily from a second endpoint when clicked; never ship every memory body in
the skeleton.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..memory import MemoryStore
    from ..tools import ToolRegistry

# Region colors from the spec
REGION_COLORS = {
    "core": "#2DD4A8",
    "memory": "#A78BFA",
    "working": "#67E8F9",
    "agents": "#E88FB3",
    "knowledge": "#F5A524",
    "rim": "#8B93A1",
}

# Similarity edge constants — these are load-bearing
SIMILARITY_TOP_K = 3
SIMILARITY_THRESHOLD = 0.3

# Freshness decay — exponential on age in days
FRESHNESS_HALFLIFE_DAYS = 30
FRESHNESS_FLOOR = 0.15


@dataclass
class MindNode:
    """One node in the mind map skeleton.

    Flat and self-describing. The frontend routes on the id prefix.
    """

    id: str
    type: str
    region: str
    label: str
    color: str
    size: float
    freshness: float
    extra: dict = field(default_factory=dict)


@dataclass
class MindEdge:
    """One edge in the mind map skeleton."""

    source: str
    target: str
    kind: str
    weight: float


@dataclass
class MindSkeleton:
    """The full mind map skeleton."""

    regions: list[str]
    nodes: list[MindNode]
    edges: list[MindEdge]
    stats: dict

    def to_dict(self) -> dict:
        return {
            "regions": self.regions,
            "nodes": [
                {
                    "id": n.id,
                    "type": n.type,
                    "region": n.region,
                    "label": n.label,
                    "color": n.color,
                    "size": n.size,
                    "freshness": n.freshness,
                    "extra": n.extra,
                }
                for n in self.nodes
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "kind": e.kind,
                    "weight": e.weight,
                }
                for e in self.edges
            ],
            "stats": self.stats,
        }


def _freshness(age_days: float) -> float:
    """Exponential decay on age, floored so nothing goes fully black."""
    import math

    return max(FRESHNESS_FLOOR, 0.5 ** (age_days / FRESHNESS_HALFLIFE_DAYS))


def _cooccurrence_edges(
    nodes: list[MindNode],
    top_k: int = SIMILARITY_TOP_K,
    threshold: float = SIMILARITY_THRESHOLD,
) -> list[MindEdge]:
    """Build co-occurrence edges between nodes.

    This is the fallback when no embeddings exist. Nodes are linked by
    shared words in their labels. The spec says to label these honestly as
    co-occurrence, not semantic similarity.

    For each node, link it to its top_k neighbors above the threshold.
    Canonicalize each pair by sorting the endpoints, and dedupe.
    """
    if len(nodes) < 2:
        return []

    # Extract words from each node's label
    word_sets: list[set[str]] = []
    for node in nodes:
        words = set(re.findall(r"[a-z0-9']+", node.label.lower()))
        word_sets.append(words)

    # Compute co-occurrence scores
    edges: list[MindEdge] = []
    seen_pairs: set[tuple[str, str]] = set()

    for i, node_a in enumerate(nodes):
        scores: list[tuple[float, int]] = []
        for j, node_b in enumerate(nodes):
            if i == j:
                continue
            # Jaccard similarity as a simple co-occurrence metric
            intersection = word_sets[i] & word_sets[j]
            union = word_sets[i] | word_sets[j]
            if not union:
                continue
            score = len(intersection) / len(union)
            if score >= threshold:
                scores.append((score, j))

        # Take top_k
        scores.sort(reverse=True)
        for score, j in scores[:top_k]:
            node_b = nodes[j]
            # Canonicalize the pair
            pair = tuple(sorted([node_a.id, node_b.id]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            edges.append(
                MindEdge(
                    source=pair[0],
                    target=pair[1],
                    kind="cooccurrence",
                    weight=score,
                )
            )

    return edges


def _build_core_region() -> tuple[list[MindNode], list[MindEdge]]:
    """The core region — JARVIS itself, plus its prompt blocks as orbiting rings."""
    nodes = [
        MindNode(
            id="core:jarvis",
            type="agent",
            region="core",
            label="JARVIS",
            color=REGION_COLORS["core"],
            size=1.5,
            freshness=1.0,
            extra={"name": "JARVIS", "accent": "#FFC247"},
        ),
    ]
    edges: list[MindEdge] = []
    return nodes, edges


def _build_memory_region(
    memory_store: "MemoryStore | None",
) -> tuple[list[MindNode], list[MindEdge], str]:
    """The memory region — long-term memories, wired by co-occurrence.

    Each region is built inside its own try, so a broken memory index empties
    that region only and records "error" in the stats.
    """
    if memory_store is None:
        return [], [], "no memory store"

    try:
        facts = memory_store.facts()
    except Exception:  # noqa: BLE001 — a broken memory index empties this region only
        return [], [], "error"

    if not facts:
        return [], [], "empty"

    nodes: list[MindNode] = []
    for fact in facts:
        # No timestamps in the current store, so freshness is the floor
        nodes.append(
            MindNode(
                id=f"mem:{fact.id}",
                type="memory",
                region="memory",
                label=fact.text[:80],
                color=REGION_COLORS["memory"],
                size=1.0,
                freshness=FRESHNESS_FLOOR,
                extra={
                    "fact_id": fact.id,
                    "text": fact.text,
                },
            )
        )

    # Build co-occurrence edges (no embeddings)
    edges = _cooccurrence_edges(nodes)

    return nodes, edges, "ok"


def _build_knowledge_region() -> tuple[list[MindNode], list[MindEdge], str]:
    """The knowledge region — always-loaded files feeding the system prompt."""
    knowledge_files = [
        ("AGENT.md", "AGENT.md"),
        ("personality.md", "personality.md"),
        ("jarvis/scout/DOCTRINE.md", "DOCTRINE.md"),
    ]

    nodes: list[MindNode] = []
    for path, label in knowledge_files:
        file_path = Path(__file__).resolve().parent.parent.parent / path
        if not file_path.exists():
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
            preview = content[:200].replace("\n", " ")
        except OSError:
            preview = ""

        nodes.append(
            MindNode(
                id=f"know:{path}",
                type="knowledge",
                region="knowledge",
                label=label,
                color=REGION_COLORS["knowledge"],
                size=1.5,
                freshness=1.0,
                extra={
                    "path": path,
                    "preview": preview,
                },
            )
        )

    edges: list[MindEdge] = []
    return nodes, edges, "ok" if nodes else "empty"


def _build_rim_region(
    tool_registry: "ToolRegistry | None",
) -> tuple[list[MindNode], list[MindEdge], str]:
    """The rim region — the whole tool inventory.

    Group by name prefix since no categories exist.
    """
    if tool_registry is None:
        return [], [], "no tool registry"

    try:
        tool_names = tool_registry.names()
    except Exception:  # noqa: BLE001
        return [], [], "error"

    if not tool_names:
        return [], [], "empty"

    # Group by name prefix (before the first underscore)
    groups: dict[str, list[str]] = {}
    for name in tool_names:
        prefix = name.split("_")[0] if "_" in name else name
        groups.setdefault(prefix, []).append(name)

    # Color palette for tool groups
    TOOL_COLORS = ["#E88FB3", "#67E8F9", "#A78BFA", "#F5A524", "#4ADE80", "#F87171", "#60A5FA", "#FBBF24", "#A3E635", "#E879F9"]

    nodes: list[MindNode] = []
    for idx, (prefix, tools) in enumerate(sorted(groups.items())):
        color = TOOL_COLORS[idx % len(TOOL_COLORS)]
        # Create a group node
        group_id = f"tool:group:{prefix}"
        nodes.append(
            MindNode(
                id=group_id,
                type="tool_group",
                region="rim",
                label=prefix,
                color=color,
                size=1.5,
                freshness=1.0,
                extra={"prefix": prefix, "tools": tools},
            )
        )
        # Create tool nodes
        for tool_name in tools:
            nodes.append(
                MindNode(
                    id=f"tool:{tool_name}",
                    type="tool",
                    region="rim",
                    label=tool_name,
                    color=color,
                    size=1.0,
                    freshness=1.0,
                    extra={"name": tool_name},
                )
            )

    # Edges from group to tools
    edges: list[MindEdge] = []
    for prefix, tools in sorted(groups.items()):
        group_id = f"tool:group:{prefix}"
        for tool_name in tools:
            edges.append(
                MindEdge(
                    source=group_id,
                    target=f"tool:{tool_name}",
                    kind="membership",
                    weight=1.0,
                )
            )

    return nodes, edges, "ok"


def build_mind_skeleton(
    memory_store: "MemoryStore | None" = None,
    tool_registry: "ToolRegistry | None" = None,
) -> MindSkeleton:
    """Assemble the full mind map skeleton.

    This is a pure function taking explicit arguments — not reaching into
    globals — so it's testable without spinning up the server.

    Each region is built inside its own try, so a broken source empties that
    region only and records "error" in the stats.
    """
    all_nodes: list[MindNode] = []
    all_edges: list[MindEdge] = []
    stats: dict = {}

    # Core
    try:
        nodes, edges = _build_core_region()
        all_nodes.extend(nodes)
        all_edges.extend(edges)
        stats["core"] = "ok"
    except Exception as exc:  # noqa: BLE001
        stats["core"] = f"error: {exc}"

    # Memory
    try:
        nodes, edges, status = _build_memory_region(memory_store)
        all_nodes.extend(nodes)
        all_edges.extend(edges)
        stats["memory"] = status
    except Exception as exc:  # noqa: BLE001
        stats["memory"] = f"error: {exc}"

    # Knowledge
    try:
        nodes, edges, status = _build_knowledge_region()
        all_nodes.extend(nodes)
        all_edges.extend(edges)
        stats["knowledge"] = status
    except Exception as exc:  # noqa: BLE001
        stats["knowledge"] = f"error: {exc}"

    # Rim
    try:
        nodes, edges, status = _build_rim_region(tool_registry)
        all_nodes.extend(nodes)
        all_edges.extend(edges)
        stats["rim"] = status
    except Exception as exc:  # noqa: BLE001
        stats["rim"] = f"error: {exc}"

    # Add cross-region edges: connect core to each region's nodes
    # This ensures the graph is fully connected
    core_node = next((n for n in all_nodes if n.region == "core"), None)
    if core_node:
        for region in ["memory", "knowledge"]:
            region_node = next((n for n in all_nodes if n.region == region), None)
            if region_node:
                all_edges.append(MindEdge(
                    source=core_node.id,
                    target=region_node.id,
                    kind="region",
                    weight=0.5,
                ))
        # Connect core to each rim group (not individual tools)
        rim_groups = [n for n in all_nodes if n.region == "rim" and n.type == "tool_group"]
        for group in rim_groups:
            all_edges.append(MindEdge(
                source=core_node.id,
                target=group.id,
                kind="region",
                weight=0.3,
            ))

    # Compute degree for each node and use it for size
    degree: dict[str, int] = {}
    for edge in all_edges:
        degree[edge.source] = degree.get(edge.source, 0) + 1
        degree[edge.target] = degree.get(edge.target, 0) + 1

    # Grow node size with degree
    for node in all_nodes:
        node.size = node.size * (1.0 + 0.1 * degree.get(node.id, 0))

    # Build the regions list
    regions = ["core", "memory", "knowledge", "rim"]

    # Stats
    stats["memory_total"] = len([n for n in all_nodes if n.region == "memory"])
    stats["memory_shown"] = stats["memory_total"]
    stats["sources"] = {
        "memory": "state/memory.txt",
        "knowledge": "AGENT.md, personality.md, DOCTRINE.md",
        "rim": "tool registry",
    }

    return MindSkeleton(
        regions=regions,
        nodes=all_nodes,
        edges=all_edges,
        stats=stats,
    )


def get_node_detail(node_id: str, memory_store: "MemoryStore | None" = None) -> dict | None:
    """Get the full detail for one node.

    For a memory, its body, type, source, timestamp, and nearest neighbors.
    For a knowledge file, a text preview — and only for paths in the manifest,
    never an arbitrary path. Return None for unknown ids.
    """
    # Parse the id prefix
    prefix, _, rest = node_id.partition(":")

    if prefix == "mem":
        # Memory node — look up the fact
        if memory_store is None:
            from ..memory import MemoryStore
            from ..paths import MEMORY_FILE

            memory_store = MemoryStore(MEMORY_FILE)
        memory_store.load()
        fact = memory_store.get(rest)
        if fact is None:
            return None

        # Find nearest neighbors by co-occurrence
        all_facts = memory_store.facts()
        neighbors = []
        fact_words = set(re.findall(r"[a-z0-9']+", fact.text.lower()))
        for other in all_facts:
            if other.id == fact.id:
                continue
            other_words = set(re.findall(r"[a-z0-9']+", other.text.lower()))
            intersection = fact_words & other_words
            union = fact_words | other_words
            if not union:
                continue
            score = len(intersection) / len(union)
            if score > 0:
                neighbors.append({"id": f"mem:{other.id}", "label": other.text[:80], "score": score})

        neighbors.sort(key=lambda x: x["score"], reverse=True)
        neighbors = neighbors[:3]

        return {
            "id": node_id,
            "type": "memory",
            "label": fact.text,
            "source": "state/memory.txt",
            "timestamp": None,
            "neighbors": neighbors,
        }

    if prefix == "know":
        # Knowledge node — return a text preview
        # Only for paths in the manifest, never an arbitrary path
        manifest = [
            "AGENT.md",
            "personality.md",
            "jarvis/scout/DOCTRINE.md",
        ]
        if rest not in manifest:
            return None

        file_path = Path(__file__).resolve().parent.parent.parent / rest
        if not file_path.exists():
            return None

        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            return None

        return {
            "id": node_id,
            "type": "knowledge",
            "label": rest,
            "preview": content[:1000],
        }

    if prefix == "tool":
        # Tool node — return the tool description
        from ..tools import build_registry

        registry = build_registry()
        tool = registry.get(rest)
        if tool is None:
            return None

        return {
            "id": node_id,
            "type": "tool",
            "label": rest,
            "description": tool.description,
        }

    return None
