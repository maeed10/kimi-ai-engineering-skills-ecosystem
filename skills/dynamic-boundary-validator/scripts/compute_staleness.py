#!/usr/bin/env python3
"""
compute_staleness.py — Diff runtime service graph against static architecture map.
Computes staleness score and boundary violation classification.

Usage:
  python compute_staleness.py \
    --runtime runtime_graph.json \
    --static domain_map.json \
    --output boundary_report.json

Input: runtime_graph.json (from extract_trace_graph.py)
       domain_map.json    (from boundary-enforcer skill)

Output: boundary_report.json
  {
    "meta": { "computed_at": "...", "staleness_score": 0.42 },
    "metrics": { "NER": 0.1, "MER": 0.2, "DMR": 0.0, "WDS": 0.5 },
    "violations": [
      {
        "code": "BV-H1",
        "severity": "HIGH",
        "title": "New context-to-context edge detected",
        "source_context": "Order",
        "target_context": "Inventory",
        "services": "order-service → inventory-service",
        "evidence": "8,320 calls in 24h window",
        "static_map_rule": "edge not present in allowed_crossings",
        "recommended_action": "Add to allowed_crossings or refactor through Warehouse context"
      }
    ],
    "staleness_score": 0.42,
    "reunderstand_triggered": false
  }
"""

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from typing import Any


def load_json(path: str) -> Any:
    with open(path, "r") as f:
        return json.load(f)


def sigmoid(t: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-t))
    except OverflowError:
        return 0.0 if t < 0 else 1.0


def collapse_to_contexts(services: list[str], edges: list[dict], service_to_context: dict[str, str]) -> dict:
    """Collapse service-level graph to context-level graph."""
    context_edges = {}  # (ctx_a, ctx_b) -> {"count": N, "services": []}
    contexts = set()

    for svc in services:
        ctx = service_to_context.get(svc)
        if ctx:
            contexts.add(ctx)

    for e in edges:
        src_ctx = service_to_context.get(e["source"])
        dst_ctx = service_to_context.get(e["target"])
        if not src_ctx or not dst_ctx:
            continue
        if src_ctx == dst_ctx:
            continue  # intra-context, ignore for boundary analysis
        key = (src_ctx, dst_ctx)
        if key not in context_edges:
            context_edges[key] = {"count": 0, "services": [], "latency_p99_ms": 0}
        context_edges[key]["count"] += e.get("count", 0)
        context_edges[key]["services"].append(f"{e['source']} → {e['target']}")

    return {"contexts": contexts, "edges": context_edges}


def compute_metrics(static_graph: dict, runtime_collapsed: dict) -> dict:
    """Compute NER, MER, DMR, WDS."""
    static_edges = set()
    static_edge_weights = {}  # (a,b) -> expected count

    for ctx_name, ctx_data in static_graph.get("bounded_contexts", {}).items():
        for dep in ctx_data.get("dependencies", []):
            edge = (ctx_name, dep["target_context"])
            static_edges.add(edge)
            static_edge_weights[edge] = dep.get("expected_calls_per_day", 0)

    # Also handle explicit allowed_crossings / forbidden_crossings if present
    for crossing in static_graph.get("allowed_crossings", []):
        edge = (crossing["source"], crossing["target"])
        static_edges.add(edge)
        static_edge_weights[edge] = crossing.get("expected_calls_per_day", 0)

    runtime_edges = set(runtime_collapsed["edges"].keys())
    runtime_edge_weights = {k: v["count"] for k, v in runtime_collapsed["edges"].items()}

    preserved = static_edges & runtime_edges
    missing = static_edges - runtime_edges
    new = runtime_edges - static_edges

    # Direction mismatch: (a→b) in static but (b→a) in runtime
    static_set = static_edges
    reversed_edges = set()
    for (a, b) in static_set:
        if (b, a) in runtime_edges:
            reversed_edges.add((a, b))

    static_count = max(len(static_edges), 1)

    NER = len(new) / static_count
    MER = len(missing) / static_count
    DMR = len(reversed_edges) / static_count

    # Weight deviation on preserved edges
    deviations = []
    for e in preserved:
        w_static = static_edge_weights.get(e, 0)
        w_runtime = runtime_edge_weights.get(e, 0)
        if w_static > 0:
            deviations.append(abs(w_runtime - w_static) / w_static)

    WDS = sum(deviations) / max(len(deviations), 1) if deviations else 0.0

    return {
        "NER": round(NER, 4),
        "MER": round(MER, 4),
        "DMR": round(DMR, 4),
        "WDS": round(WDS, 4),
        "preserved_count": len(preserved),
        "missing_count": len(missing),
        "new_count": len(new),
        "reversed_count": len(reversed_edges),
    }


def compute_staleness_score(metrics: dict) -> float:
    """Composite staleness score [0.0, 1.0]."""
    NER = metrics["NER"]
    MER = metrics["MER"]
    DMR = metrics["DMR"]
    WDS = metrics["WDS"]

    score = 0.40 * NER + 0.30 * MER + 0.20 * DMR + 0.10 * sigmoid(WDS - 1)
    return round(min(1.0, max(0.0, score)), 4)


def classify_violations(static_graph: dict, runtime_collapsed: dict, metrics: dict) -> list[dict]:
    """Classify each discrepancy into a severity tier."""
    violations = []

    forbidden = {
        (c["source"], c["target"]) for c in static_graph.get("forbidden_crossings", [])
    }
    static_allowed = {
        (c["source"], c["target"]) for c in static_graph.get("allowed_crossings", [])
    }
    # Also build from bounded_contexts.dependencies
    for ctx_name, ctx_data in static_graph.get("bounded_contexts", {}).items():
        for dep in ctx_data.get("dependencies", []):
            static_allowed.add((ctx_name, dep["target_context"]))

    runtime_edges = runtime_collapsed["edges"]

    # Check forbidden crossings (CRITICAL)
    for (src, dst), info in runtime_edges.items():
        if (src, dst) in forbidden:
            violations.append({
                "code": "BV-C1",
                "severity": "CRITICAL",
                "title": f"Forbidden crossing: {src} → {dst}",
                "source_context": src,
                "target_context": dst,
                "services": ", ".join(info["services"][:3]),
                "evidence": f"{info['count']} calls in trace window",
                "static_map_rule": f"forbidden_crossings: {src} → {dst}",
                "recommended_action": "Remove direct call or update forbidden_crossings after security review"
            })

    # Check new edges (HIGH)
    for (src, dst), info in runtime_edges.items():
        if (src, dst) not in static_allowed and (src, dst) not in forbidden:
            violations.append({
                "code": "BV-H1",
                "severity": "HIGH",
                "title": f"New context-to-context edge: {src} → {dst}",
                "source_context": src,
                "target_context": dst,
                "services": ", ".join(info["services"][:3]),
                "evidence": f"{info['count']} calls in trace window",
                "static_map_rule": "edge not present in allowed_crossings",
                "recommended_action": "Add to allowed_crossings or refactor through designated path"
            })

    # Check direction reversals (MEDIUM)
    for (src, dst) in static_allowed:
        if (dst, src) in runtime_edges:
            rev_info = runtime_edges[(dst, src)]
            violations.append({
                "code": "BV-M1",
                "severity": "MEDIUM",
                "title": f"Direction reversal: expected {src}→{dst}, found {dst}→{src}",
                "source_context": dst,
                "target_context": src,
                "services": ", ".join(rev_info["services"][:3]),
                "evidence": f"{rev_info['count']} reverse-direction calls",
                "static_map_rule": f"allowed_crossings: {src} → {dst}",
                "recommended_action": "Verify if callback pattern changed to direct coupling"
            })

    # Check weight deviations (MEDIUM)
    static_weights = {}
    for c in static_graph.get("allowed_crossings", []):
        static_weights[(c["source"], c["target"])] = c.get("expected_calls_per_day", 0)
    for ctx_name, ctx_data in static_graph.get("bounded_contexts", {}).items():
        for dep in ctx_data.get("dependencies", []):
            static_weights[(ctx_name, dep["target_context"])] = dep.get("expected_calls_per_day", 0)

    for (src, dst), info in runtime_edges.items():
        expected = static_weights.get((src, dst), 0)
        if expected > 0:
            ratio = info["count"] / expected
            if ratio > 3.0:  # >300% of expected
                violations.append({
                    "code": "BV-M2",
                    "severity": "MEDIUM",
                    "title": f"Weight deviation on {src}→{dst}: {ratio:.1f}x expected",
                    "source_context": src,
                    "target_context": dst,
                    "services": ", ".join(info["services"][:3]),
                    "evidence": f"Expected ~{expected}/day, observed {info['count']}",
                    "static_map_rule": f"expected_calls_per_day={expected}",
                    "recommended_action": "Investigate traffic spike or outdated baseline"
                })

    # Check orphan services (LOW)
    mapped_services = set()
    for ctx_data in static_graph.get("bounded_contexts", {}).values():
        for svc in ctx_data.get("services", []):
            mapped_services.add(svc)

    for svc in runtime_collapsed.get("_raw_services", []):
        if svc not in mapped_services:
            violations.append({
                "code": "BV-L2",
                "severity": "LOW",
                "title": f"Orphan service: {svc}",
                "source_context": "UNKNOWN",
                "target_context": "N/A",
                "services": svc,
                "evidence": "Service appears in traces but not in any bounded context",
                "static_map_rule": "service not in bounded_contexts[].services",
                "recommended_action": "Assign service to a bounded context in domain_map.json"
            })

    # Sort by severity
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    violations.sort(key=lambda v: severity_order.get(v["severity"], 99))

    return violations


def generate_markdown_report(report: dict) -> str:
    """Generate BOUNDARY_VIOLATIONS.md content."""
    lines = [
        "# Boundary Violations Report",
        f"Generated: {report['meta']['computed_at']}",
        f"Staleness Score: {report['staleness_score']}",
        f"Trace Window: {report['meta'].get('trace_window_start', 'N/A')} to {report['meta'].get('trace_window_end', 'N/A')}",
        f"Total Traces Analyzed: {report['meta'].get('total_traces', 'N/A')}",
        "",
        "## Summary",
        "| Severity | Count |",
        "|----------|-------|",
    ]

    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for v in report["violations"]:
        counts[v["severity"]] = counts.get(v["severity"], 0) + 1

    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        lines.append(f"| {sev} | {counts[sev]} |")

    lines.append("")
    lines.append("## Critical Findings")
    lines.append("")
    for v in report["violations"]:
        if v["severity"] == "CRITICAL":
            lines.append(f"### {v['code']}: {v['title']}")
            lines.append(f"- **Source Context**: {v['source_context']}")
            lines.append(f"- **Target Context**: {v['target_context']}")
            lines.append(f"- **Services**: {v['services']}")
            lines.append(f"- **Evidence**: {v['evidence']}")
            lines.append(f"- **Static Map Rule**: {v['static_map_rule']}")
            lines.append(f"- **Recommended Action**: {v['recommended_action']}")
            lines.append("")

    lines.append("## High Findings")
    lines.append("")
    for v in report["violations"]:
        if v["severity"] == "HIGH":
            lines.append(f"### {v['code']}: {v['title']}")
            lines.append(f"- **Source Context**: {v['source_context']}")
            lines.append(f"- **Target Context**: {v['target_context']}")
            lines.append(f"- **Services**: {v['services']}")
            lines.append(f"- **Evidence**: {v['evidence']}")
            lines.append(f"- **Static Map Rule**: {v['static_map_rule']}")
            lines.append(f"- **Recommended Action**: {v['recommended_action']}")
            lines.append("")

    lines.append("## Medium Findings")
    lines.append("")
    for v in report["violations"]:
        if v["severity"] == "MEDIUM":
            lines.append(f"### {v['code']}: {v['title']}")
            lines.append(f"- **Services**: {v['services']}")
            lines.append(f"- **Evidence**: {v['evidence']}")
            lines.append(f"- **Recommended Action**: {v['recommended_action']}")
            lines.append("")

    lines.append("## Low Findings")
    lines.append("")
    for v in report["violations"]:
        if v["severity"] == "LOW":
            lines.append(f"- **{v['code']}**: {v['title']} — {v['recommended_action']}")

    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    for k, v in report["metrics"].items():
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append(f"**Staleness Score**: {report['staleness_score']}")
    lines.append(f"**Re-understand Triggered**: {'YES' if report['reunderstand_triggered'] else 'NO'}")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Compute staleness and boundary violations")
    parser.add_argument("--runtime", required=True, help="Path to runtime_graph.json")
    parser.add_argument("--static", required=True, help="Path to domain_map.json (static architecture map)")
    parser.add_argument("--output", required=True, help="Output boundary_report.json path")
    parser.add_argument("--markdown", default="BOUNDARY_VIOLATIONS.md", help="Output markdown report path")
    args = parser.parse_args()

    runtime = load_json(args.runtime)
    static_map = load_json(args.static)

    # Build service → context mapping
    service_to_context = {}
    for ctx_name, ctx_data in static_map.get("bounded_contexts", {}).items():
        for svc in ctx_data.get("services", []):
            service_to_context[svc] = ctx_name

    runtime_collapsed = collapse_to_contexts(
        runtime.get("services", []),
        runtime.get("edges", []),
        service_to_context
    )
    runtime_collapsed["_raw_services"] = runtime.get("services", [])

    metrics = compute_metrics(static_map, runtime_collapsed)
    staleness = compute_staleness_score(metrics)

    # Forbidden crossing penalty
    forbidden_in_runtime = False
    forbidden_set = {
        (c["source"], c["target"]) for c in static_map.get("forbidden_crossings", [])
    }
    for edge_key in runtime_collapsed["edges"]:
        if edge_key in forbidden_set:
            forbidden_in_runtime = True
            break

    if forbidden_in_runtime:
        staleness = max(staleness, 0.8)

    violations = classify_violations(static_map, runtime_collapsed, metrics)
    reunderstand = staleness > 0.6 or any(v["code"] == "BV-C1" for v in violations)

    report = {
        "meta": {
            "computed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "staleness_score": staleness,
            "trace_window_start": runtime.get("meta", {}).get("trace_window_start"),
            "trace_window_end": runtime.get("meta", {}).get("trace_window_end"),
            "total_traces": runtime.get("meta", {}).get("total_traces_analyzed", "N/A"),
        },
        "metrics": metrics,
        "violations": violations,
        "staleness_score": staleness,
        "reunderstand_triggered": reunderstand,
    }

    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)

    md = generate_markdown_report(report)
    with open(args.markdown, "w") as f:
        f.write(md)

    print(f"Wrote {args.output} — staleness={staleness}, violations={len(violations)}, reunderstand={reunderstand}")


if __name__ == "__main__":
    main()
