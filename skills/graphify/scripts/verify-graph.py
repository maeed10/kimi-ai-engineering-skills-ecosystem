#!/usr/bin/env python3
"""
verify-graph.py - Validate a Graphify-generated knowledge graph JSON file.

Usage:
    python verify-graph.py <graph.json> [options]

Options:
    --fix       Remove orphaned nodes and invalid edges, write cleaned graph back
    --verbose   Show detailed validation output
    --help      Show this help message and exit

Safety: This script only reads (and optionally writes to) the specified graph.json
file. It never modifies source code. When --fix is used, the original file is
preserved as graph.json.bak before writing the cleaned version.

Exit codes:
    0 - Graph is valid (or successfully fixed)
    1 - Validation errors found (or fix failed)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_NODE_TYPES = {"file", "function", "class", "import", "module"}
ALLOWED_EDGE_TYPES = {"calls", "imports", "contains", "inherits", "semantic_related"}
REQUIRED_TOP_KEYS = {"nodes", "edges", "metadata"}
REQUIRED_METADATA_KEYS = {"graph_version", "build_timestamp"}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ValidationIssue:
    severity: str  # "error" | "warning"
    message: str
    location: str = ""


@dataclass
class GraphStats:
    node_count: int = 0
    edge_count: int = 0
    node_type_counts: Counter = field(default_factory=Counter)
    edge_type_counts: Counter = field(default_factory=Counter)
    orphaned_nodes: list[str] = field(default_factory=list)
    invalid_edges: list[str] = field(default_factory=list)
    diameter_estimate: int = 0


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------

class GraphValidator:
    """Validates a Graphify knowledge graph JSON structure."""

    def __init__(self, graph_data: dict[str, Any], verbose: bool = False) -> None:
        self.graph = graph_data
        self.verbose = verbose
        self.issues: list[ValidationIssue] = []
        self.stats = GraphStats()
        self._node_ids: set[str] = set()

    def _add(self, severity: str, message: str, location: str = "") -> None:
        self.issues.append(ValidationIssue(severity, message, location))
        if self.verbose:
            prefix = "[ERROR]" if severity == "error" else "[WARN]"
            loc = f" {location}" if location else ""
            print(f"{prefix}{loc}: {message}", file=sys.stderr)

    def validate_structure(self) -> bool:
        """Validate top-level JSON structure."""
        ok = True
        for key in REQUIRED_TOP_KEYS:
            if key not in self.graph:
                self._add("error", f"Missing required top-level key: '{key}'")
                ok = False

        if not isinstance(self.graph.get("nodes"), list):
            self._add("error", "'nodes' must be a list")
            ok = False
        if not isinstance(self.graph.get("edges"), list):
            self._add("error", "'edges' must be a list")
            ok = False
        if not isinstance(self.graph.get("metadata"), dict):
            self._add("error", "'metadata' must be an object")
            ok = False
        else:
            for key in REQUIRED_METADATA_KEYS:
                if key not in self.graph["metadata"]:
                    self._add("warning", f"Missing metadata key: '{key}'")
        return ok

    def validate_nodes(self) -> bool:
        """Validate each node has required fields and allowed types."""
        nodes = self.graph.get("nodes", [])
        self.stats.node_count = len(nodes)
        ok = True
        seen_ids: set[str] = set()

        for idx, node in enumerate(nodes):
            loc = f"nodes[{idx}]"
            if not isinstance(node, dict):
                self._add("error", "Node must be an object", loc)
                ok = False
                continue

            node_id = node.get("id")
            if not node_id:
                self._add("error", "Node missing 'id' field", loc)
                ok = False
                continue

            if node_id in seen_ids:
                self._add("error", f"Duplicate node id: '{node_id}'", loc)
                ok = False
            seen_ids.add(node_id)

            node_type = node.get("type")
            if not node_type:
                self._add("error", f"Node '{node_id}' missing 'type' field", loc)
                ok = False
            elif node_type not in ALLOWED_NODE_TYPES:
                self._add(
                    "error",
                    f"Invalid node type '{node_type}' for node '{node_id}'. "
                    f"Allowed: {sorted(ALLOWED_NODE_TYPES)}",
                    loc,
                )
                ok = False
            else:
                self.stats.node_type_counts[node_type] += 1

            # Optional: validate label exists
            if "label" not in node:
                self._add("warning", f"Node '{node_id}' missing 'label' field", loc)

        self._node_ids = seen_ids
        return ok

    def validate_edges(self) -> bool:
        """Validate each edge references existing nodes and has allowed type."""
        edges = self.graph.get("edges", [])
        self.stats.edge_count = len(edges)
        ok = True
        invalid_edges: list[dict] = []

        for idx, edge in enumerate(edges):
            loc = f"edges[{idx}]"
            if not isinstance(edge, dict):
                self._add("error", "Edge must be an object", loc)
                ok = False
                continue

            source = edge.get("source")
            target = edge.get("target")
            edge_type = edge.get("type")

            if not source or not target:
                self._add("error", "Edge missing 'source' or 'target'", loc)
                invalid_edges.append(edge)
                ok = False
                continue

            if edge_type not in ALLOWED_EDGE_TYPES:
                self._add(
                    "error",
                    f"Invalid edge type '{edge_type}'. "
                    f"Allowed: {sorted(ALLOWED_EDGE_TYPES)}",
                    loc,
                )
                ok = False
            else:
                self.stats.edge_type_counts[edge_type] += 1

            missing_nodes = []
            if source not in self._node_ids:
                missing_nodes.append(f"source='{source}'")
            if target not in self._node_ids:
                missing_nodes.append(f"target='{target}'")
            if missing_nodes:
                self._add(
                    "error",
                    f"Edge references non-existent node(s): {', '.join(missing_nodes)}",
                    loc,
                )
                invalid_edges.append(edge)
                ok = False

        self.stats.invalid_edges = invalid_edges
        return ok

    def compute_stats(self) -> None:
        """Compute derived statistics: orphans, diameter estimate."""
        edges = self.graph.get("edges", [])
        nodes = self.graph.get("nodes", [])

        # Orphaned nodes: no incoming or outgoing edges
        connected: set[str] = set()
        adjacency: dict[str, list[str]] = {}

        for edge in edges:
            if not isinstance(edge, dict):
                continue
            src = edge.get("source")
            tgt = edge.get("target")
            if src and tgt:
                connected.add(src)
                connected.add(tgt)
                adjacency.setdefault(src, []).append(tgt)

        all_node_ids = {n.get("id") for n in nodes if isinstance(n, dict) and n.get("id")}
        self.stats.orphaned_nodes = sorted(all_node_ids - connected)

        # Diameter estimate: longest shortest path via BFS from each node
        max_dist = 0
        for start in all_node_ids:
            if start not in adjacency:
                continue
            visited: dict[str, int] = {start: 0}
            queue: deque[str] = deque([start])
            while queue:
                current = queue.popleft()
                for neighbor in adjacency.get(current, []):
                    if neighbor not in visited:
                        visited[neighbor] = visited[current] + 1
                        queue.append(neighbor)
                        if visited[neighbor] > max_dist:
                            max_dist = visited[neighbor]
        self.stats.diameter_estimate = max_dist

    def validate(self) -> bool:
        """Run full validation pipeline. Returns True if no errors."""
        self.validate_structure()
        self.validate_nodes()
        self.validate_edges()
        self.compute_stats()
        return not any(i.severity == "error" for i in self.issues)

    def report(self) -> None:
        """Print a validation report to stdout."""
        errors = [i for i in self.issues if i.severity == "error"]
        warnings = [i for i in self.issues if i.severity == "warning"]

        print("\n" + "=" * 60)
        print("Graphify Graph Validation Report")
        print("=" * 60)

        print(f"\n--- Statistics ---")
        print(f"  Nodes:            {self.stats.node_count}")
        for nt, count in sorted(self.stats.node_type_counts.items()):
            print(f"    - {nt}: {count}")
        print(f"  Edges:            {self.stats.edge_count}")
        for et, count in sorted(self.stats.edge_type_counts.items()):
            print(f"    - {et}: {count}")
        print(f"  Orphaned nodes:   {len(self.stats.orphaned_nodes)}")
        if self.stats.orphaned_nodes:
            for oid in self.stats.orphaned_nodes[:10]:
                print(f"    - {oid}")
            if len(self.stats.orphaned_nodes) > 10:
                print(f"    ... and {len(self.stats.orphaned_nodes) - 10} more")
        print(f"  Invalid edges:    {len(self.stats.invalid_edges)}")
        print(f"  Diameter estimate: {self.stats.diameter_estimate}")

        print(f"\n--- Issues ---")
        print(f"  Errors:   {len(errors)}")
        print(f"  Warnings: {len(warnings)}")

        if errors:
            print("\n--- Errors ---")
            for issue in errors[:20]:
                loc = f" [{issue.location}]" if issue.location else ""
                print(f"  {loc} {issue.message}")
            if len(errors) > 20:
                print(f"  ... and {len(errors) - 20} more errors")

        if warnings:
            print("\n--- Warnings ---")
            for issue in warnings[:10]:
                loc = f" [{issue.location}]" if issue.location else ""
                print(f"  {loc} {issue.message}")
            if len(warnings) > 10:
                print(f"  ... and {len(warnings) - 10} more warnings")

        print("=" * 60)


# ---------------------------------------------------------------------------
# Fix / clean
# ---------------------------------------------------------------------------

def clean_graph(graph_data: dict[str, Any]) -> dict[str, Any]:
    """Remove orphaned nodes and invalid edges from the graph."""
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    # Collect valid node IDs
    valid_node_ids: set[str] = set()
    for node in nodes:
        if isinstance(node, dict) and node.get("id") and node.get("type") in ALLOWED_NODE_TYPES:
            valid_node_ids.add(node["id"])

    # Filter to valid edges (both endpoints exist, valid type)
    valid_edges = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src = edge.get("source")
        tgt = edge.get("target")
        etype = edge.get("type")
        if src in valid_node_ids and tgt in valid_node_ids and etype in ALLOWED_EDGE_TYPES:
            valid_edges.append(edge)

    # Find connected node IDs
    connected: set[str] = set()
    for edge in valid_edges:
        connected.add(edge["source"])
        connected.add(edge["target"])

    # Keep only connected nodes
    valid_nodes = [n for n in nodes if isinstance(n, dict) and n.get("id") in connected]

    return {
        "nodes": valid_nodes,
        "edges": valid_edges,
        "metadata": {
            **graph_data.get("metadata", {}),
            "cleaned": True,
            "original_node_count": len(nodes),
            "original_edge_count": len(edges),
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Graphify knowledge graph JSON file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Safety: This script only reads the graph.json file. "
            "With --fix, it creates a .bak backup before writing changes. "
            "Source code is never modified."
        ),
    )
    parser.add_argument("graph_file", help="Path to the graph.json file to validate")
    parser.add_argument("--fix", action="store_true", help="Remove orphaned nodes and invalid edges")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed validation output")
    parser.add_argument("--version", action="version", version="%(prog)s 1.0")

    args = parser.parse_args()

    graph_path = Path(args.graph_file)
    if not graph_path.exists():
        print(f"Error: File not found: {graph_path}", file=sys.stderr)
        return 1

    # Load JSON
    try:
        with open(graph_path, "r", encoding="utf-8") as f:
            graph_data = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"Error: Invalid JSON in {graph_path}: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Error: Cannot read {graph_path}: {exc}", file=sys.stderr)
        return 1

    if not isinstance(graph_data, dict):
        print("Error: Graph JSON must be a top-level object", file=sys.stderr)
        return 1

    # Validate
    validator = GraphValidator(graph_data, verbose=args.verbose)
    is_valid = validator.validate()
    validator.report()

    # Optionally fix
    if args.fix:
        if is_valid and not validator.stats.orphaned_nodes:
            print("\nGraph is already valid. No fixes needed.")
            return 0

        backup_path = graph_path.with_suffix(graph_path.suffix + ".bak")
        cleaned = clean_graph(graph_data)

        # Preserve original
        try:
            shutil.copy2(graph_path, backup_path)
        except OSError as exc:
            print(f"Error: Cannot create backup: {exc}", file=sys.stderr)
            return 1

        try:
            with open(graph_path, "w", encoding="utf-8") as f:
                json.dump(cleaned, f, indent=2, ensure_ascii=False)
        except OSError as exc:
            print(f"Error: Cannot write fixed graph: {exc}", file=sys.stderr)
            return 1

        removed_nodes = cleaned["metadata"]["original_node_count"] - len(cleaned["nodes"])
        removed_edges = cleaned["metadata"]["original_edge_count"] - len(cleaned["edges"])
        print(f"\nFixed graph written to {graph_path}")
        print(f"  Backup:        {backup_path}")
        print(f"  Nodes removed: {removed_nodes}")
        print(f"  Edges removed: {removed_edges}")
        print(f"  Nodes:         {len(cleaned['nodes'])}")
        print(f"  Edges:         {len(cleaned['edges'])}")

        return 0

    return 0 if is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
