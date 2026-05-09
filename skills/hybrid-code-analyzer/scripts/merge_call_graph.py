#!/usr/bin/env python3
"""
merge_call_graph.py

Merge static and dynamic call graphs into a unified graph with edge tags,
confidence scores, and anomaly flags.

Usage:
    # Collect dynamic trace (Python example)
    python merge_call_graph.py --collect --lang python -- pytest tests/

    # Merge static + dynamic graphs
    python merge_call_graph.py \
        --static .brownfield/call_graph.json \
        --dynamic .hybrid/traces/py_trace.jsonl \
        --output .hybrid/merged_graph.json \
        --lang python

    # Validate existing merged graph
    python merge_call_graph.py --validate .hybrid/merged_graph.json
"""

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
MAX_SURPRISING_RATIO = 0.15
MIN_COVERAGE_WARN = 0.60
MIN_COVERAGE_FATAL = 0.30
MIN_BOTH_RATIO = 0.20
MAX_NORM_FAILURE = 0.10


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Edge:
    source: str
    target: str
    tag: str  # STATIC | DYNAMIC | BOTH
    confidence: float
    dynamic_hits: int
    flags: List[str] = field(default_factory=list)


@dataclass
class Node:
    id: str
    type: str = "function"


@dataclass
class Diagnostics:
    surprising_edge_count: int = 0
    dead_static_edge_count: int = 0
    dead_subgraph_nodes: List[str] = field(default_factory=list)
    norm_failures: int = 0
    warnings: List[str] = field(default_factory=list)


@dataclass
class MergedGraph:
    meta: dict
    nodes: List[dict]
    edges: List[dict]
    diagnostics: dict


# ---------------------------------------------------------------------------
# Node normalization
# ---------------------------------------------------------------------------

def normalize_node(raw: str, lang: str) -> str:
    """Canonicalize a node identifier for cross-graph comparison."""
    raw = raw.strip()
    if lang == "python":
        # /path/to/pkg/module.py:func -> pkg.module.func
        if ".py:" in raw:
            parts = raw.split(":", 1)
            file_part = parts[0]
            func_part = parts[1] if len(parts) > 1 else ""
            # Strip .py and map path -> module (simplified)
            mod = file_part.replace("/", ".").replace("\\", ".")
            if mod.endswith(".py"):
                mod = mod[:-3]
            return f"{mod}.{func_part}" if func_part else mod
        return raw
    elif lang in ("javascript", "typescript", "js", "ts"):
        # Resolve source-mapped names pre-merge via external tool
        return raw
    elif lang == "go":
        return raw
    elif lang == "java":
        return raw
    return raw


def normalize_edges(edges: List[dict], lang: str) -> Set[Tuple[str, str]]:
    """Normalize a list of edge dicts to canonical (src, tgt) tuples."""
    result = set()
    for e in edges:
        src = normalize_node(e.get("source", e.get("caller", "")), lang)
        tgt = normalize_node(e.get("target", e.get("callee", "")), lang)
        result.add((src, tgt))
    return result


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_static_graph(path: str) -> Tuple[List[dict], List[dict]]:
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("nodes", []), data.get("edges", [])
    return [], data if isinstance(data, list) else []


def load_dynamic_traces(path: str) -> List[dict]:
    """Load JSON Lines file of dynamic trace events."""
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def build_dynamic_edges(events: List[dict]) -> Dict[Tuple[str, str], int]:
    """Aggregate trace events into edge -> hit_count map."""
    edges: Dict[Tuple[str, str], int] = defaultdict(int)
    for ev in events:
        src = ev.get("caller", ev.get("source", ""))
        tgt = ev.get("callee", ev.get("target", ""))
        hits = ev.get("hits", 1)
        if src and tgt:
            edges[(src, tgt)] += hits
    return edges


# ---------------------------------------------------------------------------
# Merge core
# ---------------------------------------------------------------------------

def merge_graphs(
    static_nodes: List[dict],
    static_edges: List[dict],
    dynamic_events: List[dict],
    lang: str,
    test_coverage: float = 0.0,
) -> MergedGraph:
    # Normalize static edges
    static_set = normalize_edges(static_edges, lang)

    # Build dynamic edge map (raw keys)
    dynamic_raw = build_dynamic_edges(dynamic_events)

    # Normalize dynamic keys and track failures
    dynamic_norm: Dict[Tuple[str, str], int] = defaultdict(int)
    norm_failures = 0
    for (src_raw, tgt_raw), hits in dynamic_raw.items():
        src = normalize_node(src_raw, lang)
        tgt = normalize_node(tgt_raw, lang)
        if src == "" or tgt == "" or src == "?" or tgt == "?":
            norm_failures += 1
        dynamic_norm[(src, tgt)] += hits

    # Node universe
    node_ids = {n.get("id", n.get("name", "")) for n in static_nodes}
    for (src, tgt) in static_set:
        node_ids.add(src)
        node_ids.add(tgt)
    for (src, tgt) in dynamic_norm:
        node_ids.add(src)
        node_ids.add(tgt)
    node_ids.discard("")

    nodes = [Node(id=nid) for nid in sorted(node_ids)]

    # Edge merge
    all_pairs = static_set | set(dynamic_norm.keys())
    edges: List[Edge] = []
    diag = Diagnostics()
    diag.norm_failures = norm_failures

    # Build set of executed nodes (have any dynamic outgoing edge)
    executed_nodes = {src for (src, _) in dynamic_norm}

    for pair in sorted(all_pairs):
        src, tgt = pair
        in_static = pair in static_set
        in_dynamic = pair in dynamic_norm
        hits = dynamic_norm.get(pair, 0)

        if in_static and in_dynamic:
            tag = "BOTH"
            confidence = 1.0
            flags = []
        elif in_static and not in_dynamic:
            tag = "STATIC"
            # If caller was executed but this edge never taken
            if src in executed_nodes:
                confidence = 0.6
                flags = ["DEAD_STATIC_EDGE"]
            else:
                confidence = 0.3
                flags = []
        else:
            tag = "DYNAMIC"
            confidence = min(1.0, hits / 10.0) if hits > 0 else 0.4
            flags = ["SURPRISING_RUNTIME_EDGE"]

        edges.append(Edge(src, tgt, tag, round(confidence, 2), hits, flags))

        if "SURPRISING_RUNTIME_EDGE" in flags:
            diag.surprising_edge_count += 1
        if "DEAD_STATIC_EDGE" in flags:
            diag.dead_static_edge_count += 1

    # Dead subgraph detection
    for node in sorted(node_ids):
        static_out = {e for e in static_set if e[0] == node}
        dynamic_out = {e for e in dynamic_norm if e[0] == node}
        if static_out and not dynamic_out and node in executed_nodes:
            diag.dead_subgraph_nodes.append(node)

    # Validation
    total_edges = len(edges)
    both_ratio = sum(1 for e in edges if e.tag == "BOTH") / total_edges if total_edges else 0
    surprising_ratio = diag.surprising_edge_count / total_edges if total_edges else 0
    norm_fail_ratio = diag.norm_failures / len(dynamic_raw) if dynamic_raw else 0

    if test_coverage < MIN_COVERAGE_FATAL:
        diag.warnings.append(
            f"FATAL: test coverage {test_coverage:.0%} < {MIN_COVERAGE_FATAL:.0%}; "
            "merge aborted. Run broader integration tests."
        )
    elif test_coverage < MIN_COVERAGE_WARN:
        diag.warnings.append(
            f"WARN: test coverage {test_coverage:.0%} < {MIN_COVERAGE_WARN:.0%}; "
            "dynamic edges may be incomplete."
        )
    if surprising_ratio > MAX_SURPRISING_RATIO:
        diag.warnings.append(
            f"WARN: {surprising_ratio:.1%} edges are DYNAMIC-only (threshold {MAX_SURPRISING_RATIO:.0%}); "
            "investigate reflection/DI/conditional loading."
        )
    if both_ratio < MIN_BOTH_RATIO:
        diag.warnings.append(
            f"WARN: only {both_ratio:.1%} edges are BOTH (threshold {MIN_BOTH_RATIO:.0%}); "
            "low cross-validation confidence."
        )
    if norm_fail_ratio > MAX_NORM_FAILURE:
        diag.warnings.append(
            f"WARN: {norm_fail_ratio:.1%} dynamic edges failed normalization; "
            "check path mapping or source maps."
        )

    meta = {
        "static_source": "brownfield-intelligence",
        "dynamic_source": lang,
        "test_coverage": round(test_coverage, 2),
        "total_edges": total_edges,
        "both_ratio": round(both_ratio, 2),
        "surprising_ratio": round(surprising_ratio, 2),
    }

    return MergedGraph(
        meta=meta,
        nodes=[asdict(n) for n in nodes],
        edges=[asdict(e) for e in edges],
        diagnostics=asdict(diag),
    )


# ---------------------------------------------------------------------------
# Collect mode
# ---------------------------------------------------------------------------

def collect_trace(lang: str, command: List[str]) -> str:
    """Run tests with the appropriate profiler injected."""
    trace_dir = Path(".hybrid/traces")
    trace_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HYBRID_COLLECT"] = "1"

    if lang in ("python", "py"):
        trace_file = trace_dir / "py_trace.jsonl"
        env["PYTHONPATH"] = str(Path(".hybrid").absolute()) + ":" + env.get("PYTHONPATH", "")
        # Write a conftest-style auto-loader
        loader = Path(".hybrid") / "_hybrid_autoimport.py"
        loader.write_text(
            "import sys, os\n"
            "if os.environ.get('HYBRID_COLLECT'):\n"
            "    try:\n"
            "        exec(open('.hybrid/hybrid_tracer.py').read())\n"
            "    except FileNotFoundError:\n"
            "        import warnings; warnings.warn('hybrid_tracer.py not found')\n"
        )
        env["PYTHONPATH"] = str(loader.parent.absolute()) + ":" + env.get("PYTHONPATH", "")
    elif lang == "java":
        trace_file = trace_dir / "java_trace.jsonl"
    elif lang in ("javascript", "typescript", "js", "ts"):
        trace_file = trace_dir / "js_trace.jsonl"
    elif lang == "go":
        trace_file = trace_dir / "go_trace.jsonl"
    else:
        raise ValueError(f"Unsupported language: {lang}")

    print(f"[hybrid] Running profiler for {lang}: {' '.join(command)}")
    subprocess.run(command, env=env, check=False)
    return str(trace_file)


# ---------------------------------------------------------------------------
# Validate mode
# ---------------------------------------------------------------------------

def validate_merged_graph(path: str) -> bool:
    with open(path) as f:
        data = json.load(f)
    diag = data.get("diagnostics", {})
    warnings = diag.get("warnings", [])
    for w in warnings:
        if w.startswith("FATAL"):
            print(f"[hybrid] VALIDATE FAIL: {w}")
            return False
    if warnings:
        for w in warnings:
            print(f"[hybrid] VALIDATE WARN: {w}")
    else:
        print("[hybrid] VALIDATE PASS")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Hybrid static+dynamic call graph merger")
    parser.add_argument("--static", help="Path to static call graph JSON")
    parser.add_argument("--dynamic", help="Path to dynamic trace JSONL")
    parser.add_argument("--output", default=".hybrid/merged_graph.json", help="Output path")
    parser.add_argument("--lang", default="auto", help="Language: python|java|js|ts|go")
    parser.add_argument("--coverage", type=float, default=0.0, help="Test coverage ratio 0-1")
    parser.add_argument("--collect", action="store_true", help="Run profiler during tests")
    parser.add_argument("--validate", help="Validate an existing merged graph")
    args, rest = parser.parse_known_args()

    if args.validate:
        return 0 if validate_merged_graph(args.validate) else 1

    if args.collect:
        if not rest:
            print("[hybrid] Error: provide test command after --", file=sys.stderr)
            return 1
        trace_path = collect_trace(args.lang, rest)
        print(f"[hybrid] Trace written to: {trace_path}")
        return 0

    if not args.static or not args.dynamic:
        parser.print_help()
        return 1

    # Auto-detect language
    lang = args.lang
    if lang == "auto":
        if Path(args.static).suffix == ".json":
            # Heuristic: inspect first few dynamic events
            events = load_dynamic_traces(args.dynamic)
            sample = events[0] if events else {}
            caller = sample.get("caller", "")
            if ".py:" in caller or caller.count(".") > 1:
                lang = "python"
            elif ".js:" in caller or ".ts:" in caller:
                lang = "javascript"
            else:
                lang = "java"
        else:
            lang = "python"

    static_nodes, static_edges = load_static_graph(args.static)
    dynamic_events = load_dynamic_traces(args.dynamic)

    print(f"[hybrid] Static:  {len(static_nodes)} nodes, {len(static_edges)} edges")
    print(f"[hybrid] Dynamic: {len(dynamic_events)} trace events")
    print(f"[hybrid] Lang:    {lang}")

    merged = merge_graphs(static_nodes, static_edges, dynamic_events, lang, args.coverage)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Fail on FATAL coverage
    has_fatal = any(w.startswith("FATAL") for w in merged.diagnostics.get("warnings", []))
    if has_fatal:
        # Write diagnostics-only file
        diag_only = {
            "meta": merged.meta,
            "diagnostics": merged.diagnostics,
            "error": "Merge aborted due to fatal validation failure."
        }
        with open(out_path) as f:  # type: ignore
            pass
        with open(out_path.with_suffix(".diag.json"), "w") as f:
            json.dump(diag_only, f, indent=2)
        print(f"[hybrid] FATAL: merge aborted. Diagnostics in {out_path.with_suffix('.diag.json')}")
        for w in merged.diagnostics["warnings"]:
            print(f"  - {w}")
        return 1

    with open(out_path, "w") as f:
        json.dump(asdict(merged), f, indent=2)
    print(f"[hybrid] Merged graph written to: {out_path}")
    print(f"[hybrid] Edges: {merged.meta['total_edges']} | "
          f"BOTH: {merged.meta['both_ratio']:.0%} | "
          f"Surprising: {merged.diagnostics['surprising_edge_count']}")
    for w in merged.diagnostics.get("warnings", []):
        print(f"[hybrid] WARN: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
