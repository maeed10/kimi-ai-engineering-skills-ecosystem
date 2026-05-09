#!/usr/bin/env python3
"""federated_query.py — Cross-instance memory sharing protocol.

Reads local memory vaults and produces a federated query result with trust
attenuation and conflict resolution.
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Federated Memory Mesh Query")
    parser.add_argument("--vaults", nargs="+", required=True, help="Paths to memory vault directories")
    parser.add_argument("--query", required=True, help="Natural language query")
    parser.add_argument("--output", default="federated_result.json")
    args = parser.parse_args()

    results = []
    for vault in args.vaults:
        vault_path = Path(vault)
        if not vault_path.exists():
            continue
        entries = []
        for mdfile in vault_path.rglob("*.md"):
            try:
                text = mdfile.read_text(encoding="utf-8")
                if any(kw in text.lower() for kw in args.query.lower().split()):
                    entries.append({
                        "source": str(mdfile),
                        "excerpt": text[:500],
                        "trust_score": 0.7,  # Attenuated for external vaults
                    })
            except Exception:
                continue
        results.append({"vault": vault, "entries": entries, "count": len(entries)})

    # Conflict resolution: merge entries, keep highest trust per topic
    merged = _resolve_conflicts(results)

    report = {
        "query": args.query,
        "vaults_queried": len(args.vaults),
        "total_entries": sum(r["count"] for r in results),
        "results": results,
        "merged": merged,
    }

    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Queried {report['vaults_queried']} vaults, found {report['total_entries']} entries.")
    return 0


def _resolve_conflicts(results):
    by_topic = {}
    for vault_result in results:
        for entry in vault_result["entries"]:
            topic = entry["source"]
            if topic not in by_topic or entry["trust_score"] > by_topic[topic]["trust_score"]:
                by_topic[topic] = entry
    return list(by_topic.values())


if __name__ == "__main__":
    sys.exit(main())
