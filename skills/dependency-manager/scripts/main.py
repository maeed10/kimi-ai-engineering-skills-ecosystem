#!/usr/bin/env python3
"""Dependency Manager — analyze package manifests for outdated deps, CVEs, license conflicts."""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Analyze package manifests for vulnerabilities, licenses, and outdated dependencies."
    )
    parser.add_argument("--manifest", required=True, help="Path to package manifest")
    parser.add_argument("--output", help="Path to write JSON report")
    parser.add_argument("--check-cves", action="store_true", help="Flag to check CVEs")
    parser.add_argument("--check-licenses", action="store_true", help="Flag to check licenses")
    parser.add_argument(
        "--allow-licenses",
        default="MIT,Apache-2.0,BSD-2-Clause,BSD-3-Clause,ISC",
        help="Comma-separated allowed SPDX license identifiers",
    )
    parser.add_argument(
        "--block-licenses",
        default="GPL-2.0,GPL-3.0,AGPL-3.0,SSPL-1.0",
        help="Comma-separated blocked SPDX license identifiers",
    )
    return parser.parse_args()


def parse_manifest(manifest_path: str) -> dict[str, Any]:
    """Parse a package manifest and return dependency metadata."""
    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    name = path.name.lower()
    text = path.read_text(encoding="utf-8", errors="ignore")

    if name == "package.json":
        return _parse_package_json(text, manifest_path)
    elif name == "requirements.txt":
        return _parse_requirements_txt(text, manifest_path)
    elif name == "cargo.toml":
        return _parse_cargo_toml(text, manifest_path)
    elif name == "go.mod":
        return _parse_go_mod(text, manifest_path)
    elif name == "pipfile":
        return _parse_pipfile(text, manifest_path)
    elif name == "gemfile":
        return _parse_gemfile(text, manifest_path)
    else:
        raise ValueError(f"Unsupported manifest: {name}")


def _parse_package_json(text: str, path: str) -> dict[str, Any]:
    import json as _json
    data = _json.loads(text)
    deps = {}
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        for pkg, ver in data.get(section, {}).items():
            deps[pkg] = {"declared_version": ver, "section": section, "ecosystem": "npm"}
    return {"format": "package.json", "path": path, "dependencies": deps}


def _parse_requirements_txt(text: str, path: str) -> dict[str, Any]:
    deps = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Handle extras and markers loosely
        match = re.match(r"^([a-zA-Z0-9_.-]+)\s*(.*)", line)
        if match:
            pkg = match.group(1)
            ver = match.group(2).strip()
            deps[pkg] = {"declared_version": ver or "*", "section": "main", "ecosystem": "pypi"}
    return {"format": "requirements.txt", "path": path, "dependencies": deps}


def _parse_cargo_toml(text: str, path: str) -> dict[str, Any]:
    import tomllib
    data = tomllib.loads(text)
    deps = {}
    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
        for pkg, spec in data.get(section, {}).items():
            ver = spec if isinstance(spec, str) else spec.get("version", "*")
            deps[pkg] = {"declared_version": ver, "section": section, "ecosystem": "cargo"}
    return {"format": "Cargo.toml", "path": path, "dependencies": deps}


def _parse_go_mod(text: str, path: str) -> dict[str, Any]:
    deps = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("require "):
            parts = line[len("require "):].strip().split()
            if len(parts) >= 2:
                deps[parts[0]] = {"declared_version": parts[1], "section": "require", "ecosystem": "go"}
        elif not line.startswith(("module ", "go ", "replace ", "(", ")", "//")) and line:
            parts = line.split()
            if len(parts) >= 2:
                deps[parts[0]] = {"declared_version": parts[1], "section": "require", "ecosystem": "go"}
    return {"format": "go.mod", "path": path, "dependencies": deps}


def _parse_pipfile(text: str, path: str) -> dict[str, Any]:
    import tomllib
    data = tomllib.loads(text)
    deps = {}
    for section in ("packages", "dev-packages"):
        for pkg, spec in data.get(section, {}).items():
            ver = spec if isinstance(spec, str) else spec.get("version", "*")
            deps[pkg] = {"declared_version": ver, "section": section, "ecosystem": "pypi"}
    return {"format": "Pipfile", "path": path, "dependencies": deps}


def _parse_gemfile(text: str, path: str) -> dict[str, Any]:
    deps = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("gem "):
            parts = line[len("gem "):].strip().split(",")
            pkg = parts[0].strip().strip("'\"")
            ver = parts[1].strip().strip("'\"") if len(parts) > 1 else "*"
            deps[pkg] = {"declared_version": ver, "section": "main", "ecosystem": "rubygems"}
    return {"format": "Gemfile", "path": path, "dependencies": deps}


def check_licenses(deps: dict[str, Any], allowed: set[str], blocked: set[str]) -> list[dict[str, Any]]:
    """Check dependency licenses against allow/block lists."""
    findings = []
    # Simulated license lookup; in production, query registry APIs or SBOM tools
    simulated = {
        "react": "MIT",
        "lodash": "MIT",
        "express": "MIT",
        "django": "BSD-3-Clause",
        "requests": "Apache-2.0",
        "numpy": "BSD-3-Clause",
        "pandas": "BSD-3-Clause",
        "serde": "MIT",
        "tokio": "MIT",
        "gin": "MIT",
        "rails": "MIT",
        "sidekiq": "LGPL-3.0",
    }
    for pkg, meta in deps.items():
        lic = simulated.get(pkg, "Unknown")
        meta["license"] = lic
        if lic in blocked:
            findings.append({
                "package": pkg,
                "license": lic,
                "severity": "BLOCKING",
                "message": f"Blocked license '{lic}' detected",
            })
        elif lic == "Unknown":
            findings.append({
                "package": pkg,
                "license": lic,
                "severity": "WARNING",
                "message": "License metadata missing — manual review required",
            })
        elif lic not in allowed:
            findings.append({
                "package": pkg,
                "license": lic,
                "severity": "WARNING",
                "message": f"License '{lic}' not in allow-list",
            })
    return findings


def check_cves(deps: dict[str, Any]) -> list[dict[str, Any]]:
    """Simulate CVE scanning against a static advisory set."""
    findings = []
    # Static simulation of known CVEs for demonstration
    known = {
        "lodash": [{"cve": "CVE-2021-23337", "cvss": 7.4, "fixed_in": "4.17.21"}],
        "express": [{"cve": "CVE-2022-24999", "cvss": 7.5, "fixed_in": "4.18.0"}],
        "django": [{"cve": "CVE-2023-31047", "cvss": 9.8, "fixed_in": "4.2.1"}],
    }
    for pkg, meta in deps.items():
        if pkg in known:
            for adv in known[pkg]:
                findings.append({
                    "package": pkg,
                    "version": meta["declared_version"],
                    "cve": adv["cve"],
                    "cvss": adv["cvss"],
                    "severity": "CRITICAL" if adv["cvss"] >= 9.0 else "HIGH",
                    "fixed_in": adv["fixed_in"],
                    "message": f"{adv['cve']} (CVSS {adv['cvss']}) affects {pkg}@{meta['declared_version']}",
                })
    return findings


def compute_risk_score(deps: dict[str, Any], cves: list[dict[str, Any]], license_issues: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute a composite risk score."""
    max_cvss = max((c["cvss"] for c in cves), default=0.0)
    blocking_license = any(l["severity"] == "BLOCKING" for l in license_issues)
    critical_cve = any(c["severity"] == "CRITICAL" for c in cves)
    high_cve = any(c["severity"] == "HIGH" for c in cves)

    gate = "PASS"
    if blocking_license or critical_cve:
        gate = "BLOCK"
    elif high_cve or len(license_issues) > 0:
        gate = "WARN"

    return {
        "aggregate_score": round(min(10.0, max_cvss + len(cves) * 0.5 + len(license_issues) * 0.3), 2),
        "gate": gate,
        "max_cvss": max_cvss,
        "cve_count": len(cves),
        "license_issue_count": len(license_issues),
    }


def generate_sbom(manifest_info: dict[str, Any]) -> dict[str, Any]:
    """Generate a basic CycloneDX-style SBOM skeleton."""
    components = []
    for pkg, meta in manifest_info["dependencies"].items():
        components.append({
            "type": "library",
            "name": pkg,
            "version": meta["declared_version"],
            "purl": f"pkg:{meta['ecosystem']}/{pkg}@{meta['declared_version']}",
            "licenses": [{"license": {"id": meta.get("license", "Unknown")}}],
        })
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "components": components,
    }


def main() -> int:
    """Main entry point."""
    args = parse_args()
    allowed = {s.strip() for s in args.allow_licenses.split(",") if s.strip()}
    blocked = {s.strip() for s in args.block_licenses.split(",") if s.strip()}

    try:
        manifest_info = parse_manifest(args.manifest)
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}), file=sys.stderr)
        return 1

    license_findings = []
    cve_findings = []

    if args.check_licenses:
        license_findings = check_licenses(manifest_info["dependencies"], allowed, blocked)

    if args.check_cves:
        cve_findings = check_cves(manifest_info["dependencies"])

    risk = compute_risk_score(manifest_info["dependencies"], cve_findings, license_findings)
    sbom = generate_sbom(manifest_info)

    report = {
        "success": True,
        "manifest": manifest_info["path"],
        "format": manifest_info["format"],
        "dependency_count": len(manifest_info["dependencies"]),
        "sbom": sbom,
        "license_findings": license_findings,
        "cve_findings": cve_findings,
        "risk_score": risk,
    }

    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if risk["gate"] != "BLOCK" else 1


if __name__ == "__main__":
    sys.exit(main())
