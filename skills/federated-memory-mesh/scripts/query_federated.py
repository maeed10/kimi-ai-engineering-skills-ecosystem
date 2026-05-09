#!/usr/bin/env python3
"""query_federated.py — Cross-instance memory sharing query.

Reads from multiple memory vaults and merges results with trust attenuation
and conflict resolution.
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Federated Memory Mesh Query")
    parser.add_argument("--vaults", nargs="+", required=True, help="Paths to vault directories")
    parser.add_argument("--query", required=True, help="Search query string")
    parser.add_argument("--output", default="federated_result.json")
    args = parser.parse_args()

    all_memories = []
    for vault in args.vaults:
        vpath = Path(vault)
        if not vpath.exists():
            continue
        for memfile in vpath.rglob("*.md"):
            try:
                text = memfile.read_text(encoding="utf-8")
                trust = _compute_trust(text, memfile)
                all_memories.append({
                    "source": str(memfile),
                    "vault": str(vpath),
                    "content": text[:500],
                    "trust_score": trust,
                    "relevance": _relevance(text, args.query),
                })
            except Exception:
                continue

    # Sort by relevance then trust
    all_memories.sort(key=lambda m: (m["relevance"], m["trust_score"]), reverse=True)

    # Conflict resolution: if same topic has conflicting memories, prefer higher trust
    resolved = _resolve_conflicts(all_memories)

    report = {
        "query": args.query,
        "vaults_queried": len(args.vaults),
        "memories_found": len(all_memories),
        "memories_returned": len(resolved),
        "results": resolved[:10],
    }

    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Queried {report['vaults_queried']} vaults, found {report['memories_found']} memories.")
    return 0


def _compute_trust(text, path):
    score = 0.5
    if "verified" in text.lower():
        score += 0.2
    if "automated" in text.lower():
        score += 0.1
    if path.stat().st_mtime > 0:
        age_days = (Path(__file__).stat().st_mtime - path.stat().st_mtime) / 86400
        if age_days < 7:
            score += 0.2
    return min(score, 1.0)


def _relevance(text, query):
    qwords = set(query.lower().split())
    twords = set(text.lower().split())
    if not qwords:
        return 0.0
    return len(qwords & twords) / len(qwords)


def _resolve_conflicts(memories):
    # Simple deduplication by content hash prefix
    seen = {}
    for m in memories:
        key = m["content"][:50]
        if key not in seen or seen[key]["trust_score"] < m["trust_score"]:
            seen[key] = m
    return list(seen.values())


if __name__ == "__main__":
    sys.exit(main())
