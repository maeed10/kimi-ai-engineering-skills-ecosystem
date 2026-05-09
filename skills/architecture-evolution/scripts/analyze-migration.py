#!/usr/bin/env python3
"""
analyze-migration.py

Template script for analyzing dependency graphs and suggesting modularization /
extraction candidates. Intended to be invoked by the Architecture Evolution skill
after loading dependency data from Graphify / Brownfield Intelligence.

Inputs (file paths or stdin JSON):
  --deps    Dependency graph JSON: { "nodes": [...], "edges": [...] }
  --metrics Module metrics JSON:   { "modules": { "name": { "lines": ..., "complexity": ... } } }
  --config  Config JSON with thresholds (optional)

Outputs (stdout JSON):
  { "candidates": [...], "clusters": [...], "risk_flags": [...] }
"""

import argparse
import json
import sys
from collections import defaultdict
from typing import Any


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_adjacency(nodes: list[str], edges: list[dict]) -> tuple[dict, dict]:
    """Build inbound and outbound adjacency maps."""
    out_map: dict[str, set[str]] = defaultdict(set)
    in_map: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        src = e.get("source") or e.get("from")
        dst = e.get("target") or e.get("to")
        if src and dst:
            out_map[src].add(dst)
            in_map[dst].add(src)
    return dict(out_map), dict(in_map)


def compute_coupling_score(name: str, out_map: dict, in_map: dict, total_nodes: int) -> float:
    """
    Coupling score: combines fan-out and fan-in normalized by graph size.
    Higher = more entangled, worse extraction candidate.
    """
    fan_out = len(out_map.get(name, set()))
    fan_in = len(in_map.get(name, set()))
    # Normalize; penalize high fan-in more because downstream consumers complicate extraction
    return (fan_out + 2.0 * fan_in) / max(total_nodes, 1)


def cluster_by_weak_edges(nodes: list[str], edges: list[dict], out_map: dict, in_map: dict) -> list[dict]:
    """
    Greedy clustering: start with high-fan-out nodes as seeds,
    absorb nearby nodes that share strong bidirectional links.
    """
    visited: set[str] = set()
    clusters: list[dict] = []
    sorted_by_out = sorted(nodes, key=lambda n: len(out_map.get(n, set())), reverse=True)

    for seed in sorted_by_out:
        if seed in visited:
            continue
        cluster = {seed}
        frontier = {seed}
        while frontier:
            current = frontier.pop()
            # Bidirectional neighbors
            neighbors = (out_map.get(current, set()) | in_map.get(current, set())) - visited
            for n in neighbors:
                # Strong tie: both directions exist or shared consumers/providers
                if n in out_map.get(current, set()) and current in out_map.get(n, set()):
                    cluster.add(n)
                    frontier.add(n)
                elif len(out_map.get(current, set()) & out_map.get(n, set())) > 0:
                    cluster.add(n)
                    frontier.add(n)
        visited |= cluster
        clusters.append({
            "nodes": sorted(cluster),
            "size": len(cluster),
            "internal_edges": sum(
                1 for e in edges
                if (e.get("source") or e.get("from")) in cluster
                and (e.get("target") or e.get("to")) in cluster
            ),
        })

    return clusters


def score_extraction_candidate(
    node: str,
    cluster: set[str],
    out_map: dict,
    in_map: dict,
    metrics: dict,
    thresholds: dict,
) -> dict[str, Any]:
    """
    Score a candidate module for extraction.
    Returns a dict with score, risk flags, and reasoning.
    """
    external_deps = out_map.get(node, set()) - cluster
    external_consumers = in_map.get(node, set()) - cluster
    total_deps = len(out_map.get(node, set()) | in_map.get(node, set()))
    internal_deps = total_deps - len(external_deps) - len(external_consumers)

    # Cohesion ratio: internal / total
    cohesion = internal_deps / max(total_deps, 1)

    # Size metric from input
    mod_metrics = metrics.get("modules", {}).get(node, {})
    lines = mod_metrics.get("lines", 0)
    complexity = mod_metrics.get("complexity", 0)

    # Extraction score: higher cohesion, lower external coupling, moderate size
    size_penalty = 0.0
    max_lines = thresholds.get("max_lines", 5000)
    if lines > max_lines:
        size_penalty = (lines - max_lines) / max_lines

    score = cohesion * 10.0 - len(external_deps) * 2.0 - len(external_consumers) * 3.0 - size_penalty * 2.0

    risk_flags = []
    if len(external_consumers) > 1:
        risk_flags.append("MULTIPLE_DOWNSTREAM_CONSUMERS")
    if len(external_deps) > thresholds.get("max_external_deps", 5):
        risk_flags.append("HIGH_EXTERNAL_DEPENDENCIES")
    if complexity > thresholds.get("max_complexity", 50):
        risk_flags.append("HIGH_COMPLEXITY")
    if lines > max_lines:
        risk_flags.append("OVERSIZED_MODULE")

    return {
        "module": node,
        "score": round(score, 2),
        "cohesion": round(cohesion, 2),
        "external_deps": sorted(external_deps),
        "external_consumers": sorted(external_consumers),
        "lines": lines,
        "complexity": complexity,
        "risk_flags": risk_flags,
        "extractable": len(risk_flags) <= 1 and score > 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze dependency graph for migration candidates")
    parser.add_argument("--deps", required=True, help="Path to dependency graph JSON")
    parser.add_argument("--metrics", required=True, help="Path to module metrics JSON")
    parser.add_argument("--config", help="Optional path to config JSON with thresholds")
    args = parser.parse_args()

    deps = load_json(args.deps)
    metrics = load_json(args.metrics)
    config = load_json(args.config) if args.config else {}
    thresholds = config.get("thresholds", {})

    nodes = deps.get("nodes", [])
    if not nodes and "modules" in deps:
        nodes = list(deps["modules"].keys())
    edges = deps.get("edges", [])

    out_map, in_map = build_adjacency(nodes, edges)
    total_nodes = len(nodes)

    clusters = cluster_by_weak_edges(nodes, edges, out_map, in_map)

    candidates = []
    for cluster_info in clusters:
        cluster_set = set(cluster_info["nodes"])
        for node in cluster_info["nodes"]:
            cand = score_extraction_candidate(
                node, cluster_set, out_map, in_map, metrics, thresholds
            )
            candidates.append(cand)

    # Sort by score descending
    candidates.sort(key=lambda c: c["score"], reverse=True)

    # Global risk flags
    risk_flags = []
    if any(len(c["nodes"]) > total_nodes * 0.5 for c in clusters):
        risk_flags.append("DOMINANT_CLUSTER")
    if len(candidates) == 0:
        risk_flags.append("NO_EXTRACTABLE_CANDIDATES")

    output = {
        "candidates": candidates,
        "clusters": clusters,
        "risk_flags": risk_flags,
        "summary": {
            "total_modules": total_nodes,
            "total_clusters": len(clusters),
            "extractable_candidates": sum(1 for c in candidates if c["extractable"]),
        },
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
