#!/usr/bin/env python3
"""
sbom-generator.py — SBOM generator for dependency-resolver v4.0.0

Generates SPDX-2.3 JSON, CycloneDX 1.5 JSON, or Markdown SBOMs for a skill or the entire ecosystem.

Usage:
    python sbom-generator.py --skill security-auditor --format spdx
    python sbom-generator.py --all --format cyclonedx --output-dir ./sboms
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# In production this imports from a shared internal module; standalone helpers below.


def _uuid_from_scope(scope: str) -> str:
    h = hashlib.sha1(f"kimi-skills:{scope}".encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _get_installed_packages() -> dict[str, str]:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=json"],
        capture_output=True,
        text=True,
        check=True,
    )
    packages = json.loads(result.stdout)
    return {pkg["name"].lower().replace("-", "_"): pkg["version"] for pkg in packages}


def _get_transitive_packages() -> dict[str, str]:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "inspect", "--format=json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            inspect_data = json.loads(result.stdout)
            out = {}
            for pkg in inspect_data.get("installed", []):
                meta = pkg.get("metadata", {})
                name = meta.get("name", pkg.get("name", "unknown"))
                version = meta.get("version", pkg.get("version", "unknown"))
                out[name] = version
            return out
    except Exception:
        pass
    return {}


def _get_license(pkg_name: str) -> str:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", pkg_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("License:"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return "NOASSERTION"


def _build_spdx_json(
    scope: str,
    timestamp: str,
    packages: dict[str, str],
    licenses: dict[str, str],
    cve_by_package: dict[str, list[Any]],
) -> dict[str, Any]:
    spdx_id = f"SPDXRef-DOCUMENT-{scope}"
    spdx_packages = [
        {
            "SPDXID": spdx_id,
            "name": f"kimi-skills-{scope}",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "copyrightText": "NOASSERTION",
        }
    ]
    relationships = []
    for name in packages:
        safe_id = re.sub(r"[^a-zA-Z0-9.-]", "-", name)
        pkg_spdx_id = f"SPDXRef-{safe_id}"
        relationships.append({
            "spdxElementId": spdx_id,
            "relatedSpdxElement": pkg_spdx_id,
            "relationshipType": "DEPENDS_ON",
        })
        cves = cve_by_package.get(name, [])
        annotations = []
        for cve in cves:
            annotations.append({
                "annotationType": "REVIEW",
                "annotator": "Tool: dependency-resolver-4.0.0",
                "annotationDate": timestamp,
                "comment": f"{cve.get('id')} ({cve.get('severity')}): {cve.get('summary', '')}",
            })
        spdx_packages.append({
            "SPDXID": pkg_spdx_id,
            "name": name,
            "versionInfo": packages[name],
            "downloadLocation": f"https://pypi.org/project/{name}/{packages[name]}/",
            "filesAnalyzed": False,
            "licenseConcluded": licenses.get(name, "NOASSERTION"),
            "copyrightText": "NOASSERTION",
            "annotations": annotations,
        })
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": spdx_id,
        "name": f"kimi-skills-{scope}",
        "documentNamespace": f"https://kimi-ai.io/skills/{scope}/{timestamp}",
        "creationInfo": {
            "created": timestamp,
            "creators": ["Tool: dependency-resolver-4.0.0"],
        },
        "packages": spdx_packages,
        "relationships": relationships,
    }


def _build_cyclonedx_json(
    scope: str,
    timestamp: str,
    packages: dict[str, str],
    licenses: dict[str, str],
    cve_by_package: dict[str, list[Any]],
) -> dict[str, Any]:
    components = []
    for name, version in packages.items():
        cves = cve_by_package.get(name, [])
        vulns = []
        for cve in cves:
            vulns.append({
                "id": cve.get("id"),
                "source": {
                    "name": cve.get("source", "UNKNOWN").upper(),
                    "url": cve.get("references", [""])[0],
                },
                "ratings": [{
                    "source": {"name": cve.get("source", "UNKNOWN").upper()},
                    "score": cve.get("cvss_score"),
                    "severity": cve.get("severity"),
                    "method": "CVSSv3" if cve.get("cvss_score") else "other",
                }],
                "description": cve.get("summary", ""),
            })
        components.append({
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name}@{version}",
            "licenses": [{"license": {"name": licenses.get(name, "NOASSERTION")}}],
            "vulnerabilities": vulns,
        })
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{_uuid_from_scope(scope)}",
        "version": 1,
        "metadata": {
            "timestamp": timestamp,
            "tools": [{"name": "dependency-resolver", "version": "4.0.0"}],
        },
        "components": components,
    }


def _build_markdown(
    scope: str,
    timestamp: str,
    packages: dict[str, str],
    licenses: dict[str, str],
    cve_by_package: dict[str, list[Any]],
) -> str:
    lines = [
        f"# SBOM: {scope}",
        "",
        f"- **Generated**: {timestamp}",
        "- **Tool**: dependency-resolver v4.0.0",
        f"- **Packages**: {len(packages)}",
        "",
        "## Packages",
        "",
        "| Package | Version | License | CVEs |",
        "|---------|---------|---------|------|",
    ]
    for name, version in sorted(packages.items()):
        cves = cve_by_package.get(name, [])
        cve_str = ", ".join([f"{c.get('id')} ({c.get('severity')})" for c in cves]) if cves else "None"
        lines.append(f"| {name} | {version} | {licenses.get(name, 'NOASSERTION')} | {cve_str} |")
    lines += ["", "## Vulnerability Details", ""]
    for name, cves in sorted(cve_by_package.items()):
        for cve in cves:
            lines += [
                f"### {cve.get('id')}",
                f"- **Package**: {name}",
                f"- **Severity**: {cve.get('severity')}",
                f"- **CVSS**: {cve.get('cvss_score') or 'N/A'}",
                f"- **Summary**: {cve.get('summary', '')}",
                f"- **Fixed in**: {', '.join(cve.get('fixed_versions', [])) or 'N/A'}",
                "",
            ]
    return "\n".join(lines)


def generate_sbom(
    scope: str,
    packages: dict[str, str],
    transitive: dict[str, str],
    cve_by_package: dict[str, list[Any]],
    output_format: str,
    output_dir: Path,
) -> Path:
    all_packages = dict(packages)
    all_packages.update(transitive)
    licenses = {name: _get_license(name) for name in all_packages}
    timestamp = datetime.now(timezone.utc).isoformat()

    if output_format == "spdx":
        sbom = _build_spdx_json(scope, timestamp, all_packages, licenses, cve_by_package)
        ext = "spdx.json"
    elif output_format == "cyclonedx":
        sbom = _build_cyclonedx_json(scope, timestamp, all_packages, licenses, cve_by_package)
        ext = "cyclonedx.json"
    else:
        sbom = _build_markdown(scope, timestamp, all_packages, licenses, cve_by_package)
        ext = "md"

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"sbom-{scope}-{timestamp.replace(':', '-')}.{ext}"
    if output_format in ("spdx", "cyclonedx"):
        with out_path.open("w") as f:
            json.dump(sbom, f, indent=2)
    else:
        with out_path.open("w") as f:
            f.write(sbom)
    print(f"[OK] SBOM written to {out_path}")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill", type=str, help="Target skill name")
    parser.add_argument("--all", action="store_true", help="Generate for entire ecosystem")
    parser.add_argument("--format", choices=["spdx", "cyclonedx", "markdown"], default="spdx")
    parser.add_argument("--output-dir", type=str, default="/mnt/agents/output/dependency-resolver/reports")
    parser.add_argument("--skills-dir", type=str, default="/mnt/agents/skills")
    args = parser.parse_args(argv)

    if not args.skill and not args.all:
        print("[ERROR] Must specify --skill or --all", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    installed = _get_installed_packages()
    transitive = _get_transitive_packages()

    # Load CVEs from cache if available (simplified)
    cve_by_package: dict[str, list[Any]] = {}
    cache_dir = Path("/tmp/kimi-deps-cache")
    if cache_dir.exists():
        for osv_file in (cache_dir / "osv").glob("*.json"):
            try:
                with osv_file.open("r") as f:
                    data = json.load(f)
                for vuln in data.get("vulns", []):
                    pkg_name = vuln.get("package", {}).get("name", "unknown")
                    cve_by_package.setdefault(pkg_name, []).append({
                        "id": vuln.get("id"),
                        "source": "osv",
                        "severity": "UNKNOWN",
                        "summary": vuln.get("summary", "")[:200],
                        "cvss_score": None,
                        "fixed_versions": [],
                        "references": [ref.get("url", "") for ref in vuln.get("references", [])],
                    })
            except Exception:
                continue

    scope = args.skill or "all"
    generate_sbom(scope, installed, transitive, cve_by_package, args.format, output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
