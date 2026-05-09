#!/usr/bin/env python3
"""
verify-deps.py — Pre-flight dependency verification for Kimi Skill Ecosystem v4.0

Checks that all required binaries and Python packages are available before
running the skill pipeline. Exits with non-zero status if critical deps missing.

Usage:
    python verify-deps.py [--critical-only] [--json]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Literal, Optional


@dataclass
class DepResult:
    name: str
    category: str
    status: Literal["OK", "MISSING", "VERSION_MISMATCH", "ERROR"]
    path: Optional[str] = None
    version: Optional[str] = None
    message: str = ""


DEPENDENCIES: List[Dict] = [
    # Critical system binaries
    {"name": "python", "category": "critical", "type": "binary", "min_version": "3.10"},
    {"name": "docker", "category": "critical", "type": "binary", "min_version": None},
    {"name": "git", "category": "critical", "type": "binary", "min_version": "2.30"},
    # Security tools
    {"name": "semgrep", "category": "security", "type": "binary", "min_version": "1.0"},
    {"name": "bandit", "category": "security", "type": "python", "module": "bandit"},
    # Performance tools
    {"name": "k6", "category": "performance", "type": "binary", "min_version": None},
    # Python packages
    {"name": "pyyaml", "category": "critical", "type": "python", "module": "yaml"},
    {"name": "requests", "category": "critical", "type": "python", "module": "requests"},
    {"name": "numpy", "category": "performance", "type": "python", "module": "numpy"},
    {
        "name": "sentence-transformers",
        "category": "ipi",
        "type": "python",
        "module": "sentence_transformers",
    },
    {"name": "cryptography", "category": "memory", "type": "python", "module": "cryptography"},
]


def check_binary(name: str, min_version: Optional[str]) -> DepResult:
    path = shutil.which(name)
    if not path:
        return DepResult(name=name, category="", status="MISSING", message=f"{name} not found in PATH")

    version: Optional[str] = None
    if min_version:
        try:
            result = subprocess.run(
                [name, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            version = result.stdout.strip().split()[0] if result.stdout else None
        except Exception as exc:
            return DepResult(
                name=name, category="", status="ERROR", path=path, message=str(exc)
            )

    return DepResult(name=name, category="", status="OK", path=path, version=version)


def check_python_module(name: str, module: str) -> DepResult:
    spec = importlib.util.find_spec(module)
    if spec is None:
        return DepResult(
            name=name, category="", status="MISSING", message=f"pip install {name}"
        )

    version: Optional[str] = None
    try:
        mod = importlib.import_module(module)
        version = getattr(mod, "__version__", None)
    except Exception as exc:
        return DepResult(
            name=name, category="", status="ERROR", message=f"Import error: {exc}"
        )

    return DepResult(name=name, category="", status="OK", version=version)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Kimi Skill Ecosystem dependencies")
    parser.add_argument("--critical-only", action="store_true", help="Check only critical deps")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    results: List[DepResult] = []
    for dep in DEPENDENCIES:
        if args.critical_only and dep["category"] != "critical":
            continue

        if dep["type"] == "binary":
            result = check_binary(dep["name"], dep.get("min_version"))
        elif dep["type"] == "python":
            result = check_python_module(dep["name"], dep["module"])
        else:
            result = DepResult(
                name=dep["name"],
                category=dep["category"],
                status="ERROR",
                message=f"Unknown dep type: {dep['type']}",
            )

        result.category = dep["category"]
        results.append(result)

    critical_missing = [r for r in results if r.category == "critical" and r.status != "OK"]
    any_missing = [r for r in results if r.status != "OK"]

    if args.json:
        output = {
            "summary": {
                "total": len(results),
                "ok": len([r for r in results if r.status == "OK"]),
                "missing": len(any_missing),
                "critical_missing": len(critical_missing),
                "pass": len(critical_missing) == 0,
            },
            "results": [asdict(r) for r in results],
        }
        print(json.dumps(output, indent=2))
    else:
        print("=" * 60)
        print("Kimi Skill Ecosystem v4.0 — Dependency Verification")
        print("=" * 60)
        for r in results:
            icon = "OK" if r.status == "OK" else "XX"
            print(f"[{icon}] {r.name:30s} [{r.category:12s}] {r.status}")
            if r.path:
                print(f"   Path: {r.path}")
            if r.version:
                print(f"   Version: {r.version}")
            if r.message:
                print(f"   Note: {r.message}")
        print("=" * 60)
        print(f"Total: {len(results)} | OK: {len([r for r in results if r.status == 'OK'])} | Missing: {len(any_missing)}")
        if critical_missing:
            print(f"CRITICAL MISSING: {', '.join(r.name for r in critical_missing)}")
            print("Install: pip install -e \".[all]\"")
        else:
            print("All critical dependencies satisfied.")

    return 0 if not critical_missing else 1


if __name__ == "__main__":
    sys.exit(main())
