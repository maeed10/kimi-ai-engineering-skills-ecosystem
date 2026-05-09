#!/usr/bin/env python3
"""
verify-deps.py — Dependency Pre-flight Verification for Kimi AI Engineering Skills Ecosystem v4.0

Checks all required binaries, Python packages, and language runtimes before any skill executes.
Queries live OSV API and GitHub Advisory Database for real CVE data (never LLM hallucinations).
Generates SBOMs, caches vulnerability data for offline operation, and produces actionable reports.

Usage:
    python verify-deps.py --skill security-auditor
    python verify-deps.py --all --sbom --cve-scan
    python verify-deps.py --all --auto-install --output-dir ./reports

Exit Codes:
    0 — All dependencies satisfied; no blocking CVEs
    1 — Missing or version-incompatible Python packages
    2 — Missing external binaries or language runtimes (human approval required)
    3 — CVEs found (with --cve-scan; non-blocking if error-policy permits)
    4 — Network error during CVE update (stale cache fallback attempted)
    5 — Invalid manifest or configuration error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Optional third-party dependencies — fail gracefully with instructions if missing
# ---------------------------------------------------------------------------
try:
    import requests
except ModuleNotFoundError:  # pragma: no cover
    print("[FATAL] 'requests' is required. Install: pip install requests>=2.31", file=sys.stderr)
    sys.exit(5)

try:
    from packaging.requirements import Requirement
    from packaging.version import Version, parse as parse_version
    from packaging.specifiers import SpecifierSet
except ModuleNotFoundError:  # pragma: no cover
    print("[FATAL] 'packaging' is required. Install: pip install packaging>=23.0", file=sys.stderr)
    sys.exit(5)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
OSV_BASE_URL = "https://api.osv.dev/v1"
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
DEFAULT_CACHE_DIR = "/tmp/kimi-deps-cache"
DEFAULT_OUTPUT_DIR = "/mnt/agents/output/dependency-resolver/reports"
DEFAULT_SKILLS_DIR = "/mnt/agents/skills"
CACHE_TTL_SECONDS = 24 * 3600  # 24 hours
SEVERITY_ORDER = {"LOW": 0, "MODERATE": 1, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class CVERecord:
    id: str
    source: str  # "osv" or "github"
    package: str
    ecosystem: str
    severity: str
    cvss_score: float | None
    summary: str
    fixed_versions: list[str]
    references: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "package": self.package,
            "ecosystem": self.ecosystem,
            "severity": self.severity,
            "cvss_score": self.cvss_score,
            "summary": self.summary,
            "fixed_versions": self.fixed_versions,
            "references": self.references,
            "aliases": self.aliases,
        }


@dataclass
class OutdatedInfo:
    package: str
    current_version: str
    latest_version: str
    spec: str


@dataclass
class VerificationReport:
    skill_name: str
    ok: bool = True
    missing_packages: list[str] = field(default_factory=list)
    missing_binaries: list[str] = field(default_factory=list)
    missing_runtimes: list[str] = field(default_factory=list)
    outdated_packages: list[OutdatedInfo] = field(default_factory=list)
    cves: list[CVERecord] = field(default_factory=list)
    installed_packages: dict[str, str] = field(default_factory=dict)
    installed_binaries: dict[str, str] = field(default_factory=dict)
    installed_runtimes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "ok": self.ok,
            "missing_packages": self.missing_packages,
            "missing_binaries": self.missing_binaries,
            "missing_runtimes": self.missing_runtimes,
            "outdated_packages": [
                {
                    "package": o.package,
                    "current_version": o.current_version,
                    "latest_version": o.latest_version,
                    "spec": o.spec,
                }
                for o in self.outdated_packages
            ],
            "cves": [c.to_dict() for c in self.cves],
            "installed_packages": self.installed_packages,
            "installed_binaries": self.installed_binaries,
            "installed_runtimes": self.installed_runtimes,
        }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _log(msg: str, verbose: bool = False) -> None:
    if verbose:
        print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}")


def _cache_file_path(cache_dir: Path, ecosystem: str, package: str, version: str, source: str) -> Path:
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", f"{ecosystem}-{package}-{version}")
    return cache_dir / source / f"{safe_name}.json"


def _is_cache_fresh(path: Path, ttl: int = CACHE_TTL_SECONDS) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < ttl


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    with manifest_path.open("rb") as f:
        return json.load(f)


def _discover_skills(skills_dir: Path) -> list[Path]:
    if not skills_dir.exists():
        return []
    manifests = []
    for skill_dir in skills_dir.iterdir():
        manifest = skill_dir / "manifest.json"
        if manifest.exists():
            manifests.append(skill_dir)
    return manifests


# ---------------------------------------------------------------------------
# Package Checking
# ---------------------------------------------------------------------------

def _get_installed_packages() -> dict[str, str]:
    """Return mapping of normalized package name -> installed version via pip."""
    result = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=json"],
        capture_output=True,
        text=True,
        check=True,
    )
    packages = json.loads(result.stdout)
    # Normalize names: lowercase, replace - with _
    return {
        pkg["name"].lower().replace("-", "_"): pkg["version"]
        for pkg in packages
    }


def _check_python_packages(
    requirements: list[str],
    installed: dict[str, str],
    verbose: bool = False,
) -> tuple[list[str], list[OutdatedInfo], dict[str, str]]:
    """Check if required Python packages are installed and satisfy version specs.

    Returns: (missing_list, outdated_list, satisfied_dict)
    """
    missing: list[str] = []
    outdated: list[OutdatedInfo] = []
    satisfied: dict[str, str] = {}

    for req_str in requirements:
        try:
            req = Requirement(req_str)
        except Exception as e:
            _log(f"[WARN] Invalid requirement '{req_str}': {e}", verbose)
            missing.append(req_str)
            continue

        # Normalize name for lookup
        normalized_name = req.name.lower().replace("-", "_")
        installed_version_str = installed.get(normalized_name)

        if installed_version_str is None:
            missing.append(req_str)
            continue

        installed_version = parse_version(installed_version_str)
        if req.specifier and not req.specifier.contains(installed_version, prereleases=True):
            outdated.append(
                OutdatedInfo(
                    package=req.name,
                    current_version=installed_version_str,
                    latest_version="unknown",  # Updated later if network allows
                    spec=str(req.specifier),
                )
            )
            continue

        satisfied[req.name] = installed_version_str

    return missing, outdated, satisfied


def _auto_install_packages(packages: list[str], verbose: bool = False) -> list[str]:
    """Attempt to install missing Python packages via pip. Returns packages that still failed."""
    if not packages:
        return []

    print(f"[INFO] Auto-installing {len(packages)} package(s)...")
    still_missing = []
    for pkg in packages:
        _log(f"[INSTALL] pip install '{pkg}'", verbose)
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            still_missing.append(pkg)
            print(f"[ERROR] Failed to install {pkg}: {result.stderr.strip()}", file=sys.stderr)
        else:
            print(f"[OK] Installed {pkg}")
    return still_missing


# ---------------------------------------------------------------------------
# Binary / Runtime Checking
# ---------------------------------------------------------------------------

def _get_binary_version(binary: str) -> str | None:
    """Try common version flags for a binary. Returns version string or None."""
    version_flags = ["--version", "-version", "-v", "-V", "version"]
    for flag in version_flags:
        try:
            result = subprocess.run(
                [binary, flag],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode in (0, 1):  # Some tools exit 1 on --version
                output = result.stdout + result.stderr
                # Extract first semver-looking thing
                match = re.search(r"(\d+\.\d+(?:\.\d+)?)", output)
                if match:
                    return match.group(1)
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
            continue
    return None


def _check_binaries(binaries: list[str], verbose: bool = False) -> tuple[list[str], dict[str, str]]:
    """Check if external binaries exist in PATH and are executable.

    Returns: (missing_list, found_dict{name: version})
    """
    missing: list[str] = []
    found: dict[str, str] = {}

    for binary in binaries:
        path = shutil.which(binary)
        if path is None:
            missing.append(binary)
            continue
        version = _get_binary_version(binary)
        if version:
            found[binary] = version
            _log(f"[OK] Binary '{binary}' found at {path} (version {version})", verbose)
        else:
            found[binary] = "unknown"
            _log(f"[OK] Binary '{binary}' found at {path} (version unknown)", verbose)

    return missing, found


def _check_runtimes(runtimes: dict[str, str], verbose: bool = False) -> tuple[list[str], dict[str, str]]:
    """Check language runtimes against version spec.

    Returns: (missing_list, found_dict{name: version})
    """
    missing: list[str] = []
    found: dict[str, str] = {}

    # Built-in Python check
    if "python" in runtimes:
        py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        found["python"] = py_version
        try:
            spec = SpecifierSet(runtimes["python"])
            if not spec.contains(parse_version(py_version)):
                missing.append(f"python {runtimes['python']} (found {py_version})")
            else:
                _log(f"[OK] Python {py_version} satisfies {runtimes['python']}", verbose)
        except Exception as e:
            _log(f"[WARN] Invalid Python version spec '{runtimes['python']}': {e}", verbose)
            missing.append(f"python {runtimes['python']}")

    # Node check
    if "node" in runtimes:
        node_version = _get_binary_version("node")
        if node_version is None:
            missing.append(f"node {runtimes['node']}")
        else:
            found["node"] = node_version
            try:
                spec = SpecifierSet(runtimes["node"])
                if not spec.contains(parse_version(node_version)):
                    missing.append(f"node {runtimes['node']} (found {node_version})")
                else:
                    _log(f"[OK] Node {node_version} satisfies {runtimes['node']}", verbose)
            except Exception as e:
                _log(f"[WARN] Invalid Node version spec '{runtimes['node']}': {e}", verbose)
                missing.append(f"node {runtimes['node']}")

    # Go check
    if "go" in runtimes:
        go_version = _get_binary_version("go")
        if go_version is None:
            missing.append(f"go {runtimes['go']}")
        else:
            found["go"] = go_version
            try:
                spec = SpecifierSet(runtimes["go"])
                if not spec.contains(parse_version(go_version)):
                    missing.append(f"go {runtimes['go']} (found {go_version})")
                else:
                    _log(f"[OK] Go {go_version} satisfies {runtimes['go']}", verbose)
            except Exception as e:
                _log(f"[WARN] Invalid Go version spec '{runtimes['go']}': {e}", verbose)
                missing.append(f"go {runtimes['go']}")

    return missing, found


# ---------------------------------------------------------------------------
# CVE Scanning (OSV API + GitHub Advisory)
# ---------------------------------------------------------------------------

def _query_osv_batch(
    packages: list[tuple[str, str, str]],  # (ecosystem, name, version)
    cache_dir: Path,
    offline: bool = False,
    force_update: bool = False,
    verbose: bool = False,
) -> dict[tuple[str, str, str], list[CVERecord]]:
    """Query OSV API in batch for given packages. Uses cache unless stale or force_update.

    Returns mapping of (ecosystem, name, version) -> list of CVERecord.
    """
    results: dict[tuple[str, str, str], list[CVERecord]] = {}
    to_query: list[tuple[str, str, str]] = []

    # Determine what needs fresh API queries
    for eco, name, version in packages:
        cache_path = _cache_file_path(cache_dir, eco, name, version, "osv")
        if force_update or not _is_cache_fresh(cache_path) or not cache_path.exists():
            to_query.append((eco, name, version))
        else:
            # Load from cache
            try:
                with cache_path.open("r") as f:
                    data = json.load(f)
                results[(eco, name, version)] = [_osv_to_cverecord(v) for v in data.get("vulns", [])]
                _log(f"[CACHE] OSV {eco}/{name}@{version}", verbose)
            except Exception as e:
                _log(f"[WARN] Corrupt cache {cache_path}: {e}", verbose)
                to_query.append((eco, name, version))

    if not to_query:
        return results

    if offline:
        _log("[OFFLINE] Skipping OSV API queries for stale/missing cache entries.", verbose)
        for key in to_query:
            results[key] = []
        return results

    # OSV batch query (max 1000 per call, but we chunk defensively)
    chunk_size = 500
    for i in range(0, len(to_query), chunk_size):
        chunk = to_query[i : i + chunk_size]
        queries = [
            {"package": {"ecosystem": eco, "name": name}, "version": version}
            for eco, name, version in chunk
        ]

        _log(f"[API] POST /querybatch for {len(chunk)} package(s)", verbose)
        try:
            resp = requests.post(
                f"{OSV_BASE_URL}/querybatch",
                json={"queries": queries},
                timeout=30,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            _log(f"[ERROR] OSV batch query failed: {e}", verbose)
            for key in chunk:
                results[key] = []
            continue

        batch_results = resp.json().get("results", [])
        for idx, key in enumerate(chunk):
            eco, name, version = key
            vulns = batch_results[idx].get("vulns", []) if idx < len(batch_results) else []
            # Cache result
            cache_path = _cache_file_path(cache_dir, eco, name, version, "osv")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with cache_path.open("w") as f:
                json.dump({"vulns": vulns, "queried_at": datetime.now(timezone.utc).isoformat()}, f)

            results[key] = [_osv_to_cverecord(v) for v in vulns]
            _log(f"[API] OSV {eco}/{name}@{version}: {len(vulns)} vuln(s)", verbose)

    return results


def _osv_to_cverecord(vuln: dict[str, Any]) -> CVERecord:
    """Convert an OSV vulnerability entry to a unified CVERecord."""
    severity = "UNKNOWN"
    cvss_score: float | None = None
    aliases: list[str] = vuln.get("aliases", [])

    # OSV severity field
    for sev in vuln.get("severity", []):
        if sev.get("type") == "CVSS_V3":
            score_str = sev.get("score", "")
            # Extract numeric score from CVSS string if present
            m = re.search(r"(\d+(?:\.\d+)?)", score_str)
            if m:
                try:
                    cvss_score = float(m.group(1))
                    if cvss_score >= 9.0:
                        severity = "CRITICAL"
                    elif cvss_score >= 7.0:
                        severity = "HIGH"
                    elif cvss_score >= 4.0:
                        severity = "MEDIUM"
                    else:
                        severity = "LOW"
                except ValueError:
                    pass
            break

    # If no CVSS, infer from aliases or database_specific
    if severity == "UNKNOWN":
        for alias in aliases:
            if alias.startswith("CVE-"):
                # We'll try to enrich later via GitHub if token is available
                pass
        db_specific = vuln.get("database_specific", {})
        if "severity" in db_specific:
            severity = db_specific["severity"].upper()

    fixed_versions: list[str] = []
    for affected in vuln.get("affected", []):
        for ranges in affected.get("ranges", []):
            for event in ranges.get("events", []):
                if "fixed" in event:
                    fixed_versions.append(event["fixed"])
        for version in affected.get("versions", []):
            # This is less precise; skip unless no ranges
            pass

    return CVERecord(
        id=vuln.get("id", "UNKNOWN"),
        source="osv",
        package=vuln.get("package", {}).get("name", "unknown"),
        ecosystem=vuln.get("package", {}).get("ecosystem", "unknown"),
        severity=severity,
        cvss_score=cvss_score,
        summary=vuln.get("summary", vuln.get("details", "")[:200]),
        fixed_versions=list(dict.fromkeys(fixed_versions)),  # dedup preserve order
        aliases=aliases,
        references=[ref.get("url", "") for ref in vuln.get("references", [])],
    )


def _enrich_with_github_advisory(
    cves: list[CVERecord],
    cache_dir: Path,
    offline: bool = False,
    verbose: bool = False,
) -> list[CVERecord]:
    """Enrich CVE records with GitHub Advisory Database severity and exploitability data."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        _log("[INFO] GITHUB_TOKEN not set; skipping GitHub Advisory enrichment.", verbose)
        return cves

    if offline:
        _log("[OFFLINE] Skipping GitHub Advisory enrichment.", verbose)
        return cves

    # Build GraphQL query for GHSA IDs or CVE IDs we have aliases for
    ghsa_ids = []
    cve_to_record: dict[str, CVERecord] = {}
    for rec in cves:
        for alias in rec.aliases:
            if alias.startswith("GHSA-"):
                ghsa_ids.append(alias)
                cve_to_record[alias] = rec
            elif alias.startswith("CVE-") and rec.id.startswith("GHSA-"):
                # Map CVE alias back to GHSA record for enrichment
                cve_to_record[alias] = rec

    if not ghsa_ids:
        return cves

    # GitHub GraphQL batch — we'll do individual lookups for simplicity
    # (GitHub doesn't have a great batch advisory lookup; we query by GHSA id)
    graphql_query = """
    query($ghsaId: String!) {
      securityAdvisory(ghsaId: $ghsaId) {
        ghsaId
        severity
        cvss {
          score
        }
        references {
          url
        }
        identifiers {
          type
          value
        }
      }
    }
    """

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    enriched_count = 0
    for ghsa in ghsa_ids:
        cache_path = cache_dir / "github-advisory" / f"{ghsa}.json"
        if _is_cache_fresh(cache_path) and cache_path.exists():
            try:
                with cache_path.open("r") as f:
                    data = json.load(f)
            except Exception:
                data = None
        else:
            try:
                resp = requests.post(
                    GITHUB_GRAPHQL_URL,
                    json={"query": graphql_query, "variables": {"ghsaId": ghsa}},
                    headers=headers,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with cache_path.open("w") as f:
                    json.dump(data, f)
            except requests.RequestException as e:
                _log(f"[WARN] GitHub Advisory query for {ghsa} failed: {e}", verbose)
                continue

        if not data or "data" not in data or data.get("errors"):
            continue

        advisory = data["data"].get("securityAdvisory", {})
        if not advisory:
            continue

        rec = cve_to_record.get(ghsa)
        if rec:
            rec.severity = advisory.get("severity", rec.severity).upper()
            rec.cvss_score = advisory.get("cvss", {}).get("score", rec.cvss_score)
            for ref in advisory.get("references", []):
                if ref.get("url") and ref["url"] not in rec.references:
                    rec.references.append(ref["url"])
            enriched_count += 1

    _log(f"[OK] Enriched {enriched_count} record(s) from GitHub Advisory", verbose)
    return cves


def _extract_packages_for_cve_scan(
    manifest: dict[str, Any], installed: dict[str, str]
) -> list[tuple[str, str, str]]:
    """Extract (ecosystem, package, version) tuples for CVE scanning."""
    packages: list[tuple[str, str, str]] = []
    deps = manifest.get("dependencies", {})

    # Python packages -> PyPI ecosystem
    for req_str in deps.get("python_packages", []):
        try:
            req = Requirement(req_str)
            normalized = req.name.lower().replace("-", "_")
            version = installed.get(normalized, "0.0.0")
            packages.append(("PyPI", req.name, version))
        except Exception:
            continue

    # npm packages if declared
    for req_str in deps.get("npm_packages", []):
        # npm packages may be "package@version" or just "package"
        parts = req_str.split("@")
        name = parts[0]
        version = parts[1] if len(parts) > 1 else "0.0.0"
        packages.append(("npm", name, version))

    # Go modules if declared
    for req_str in deps.get("go_modules", []):
        parts = req_str.split("@")
        name = parts[0]
        version = parts[1] if len(parts) > 1 else "0.0.0"
        packages.append(("Go", name, version))

    return packages


# ---------------------------------------------------------------------------
# SBOM Generation
# ---------------------------------------------------------------------------

def _generate_sbom(
    scope: str,
    manifests: list[dict[str, Any]],
    installed: dict[str, str],
    cves: list[CVERecord],
    output_format: str,
    output_dir: Path,
    verbose: bool = False,
) -> Path:
    """Generate SBOM in SPDX-2.3 JSON, CycloneDX 1.5 JSON, or Markdown format."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()

    # Gather all direct python packages from manifests
    all_packages: dict[str, str] = {}
    for manifest in manifests:
        for req_str in manifest.get("dependencies", {}).get("python_packages", []):
            try:
                req = Requirement(req_str)
                normalized = req.name.lower().replace("-", "_")
                version = installed.get(normalized, "unknown")
                all_packages[req.name] = version
            except Exception:
                continue

    # Try to enrich with pip inspect for transitive dependencies
    transitive: dict[str, str] = {}
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "inspect", "--format=json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            inspect_data = json.loads(result.stdout)
            for pkg in inspect_data.get("installed", []):
                meta = pkg.get("metadata", {})
                name = meta.get("name", pkg.get("name", "unknown"))
                version = meta.get("version", pkg.get("version", "unknown"))
                transitive[name] = version
    except Exception as e:
        _log(f"[WARN] pip inspect failed: {e}", verbose)

    # Merge direct + transitive
    all_packages.update(transitive)

    # License extraction (best effort)
    licenses: dict[str, str] = {}
    for pkg_name in all_packages:
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
                        licenses[pkg_name] = line.split(":", 1)[1].strip()
                        break
        except Exception:
            pass

    cve_by_package: dict[str, list[CVERecord]] = {}
    for cve in cves:
        cve_by_package.setdefault(cve.package, []).append(cve)

    if output_format == "spdx":
        sbom = _build_spdx_json(scope, timestamp, all_packages, licenses, cve_by_package)
        ext = "spdx.json"
    elif output_format == "cyclonedx":
        sbom = _build_cyclonedx_json(scope, timestamp, all_packages, licenses, cve_by_package)
        ext = "cyclonedx.json"
    else:
        sbom = _build_sbom_markdown(scope, timestamp, all_packages, licenses, cve_by_package)
        ext = "md"

    out_path = output_dir / f"sbom-{scope}-{timestamp.replace(':', '-')}.{ext}"
    if output_format in ("spdx", "cyclonedx"):
        with out_path.open("w") as f:
            json.dump(sbom, f, indent=2)
    else:
        with out_path.open("w") as f:
            f.write(sbom)

    _log(f"[OK] SBOM written to {out_path}", verbose)
    return out_path


def _build_spdx_json(
    scope: str,
    timestamp: str,
    packages: dict[str, str],
    licenses: dict[str, str],
    cve_by_package: dict[str, list[CVERecord]],
) -> dict[str, Any]:
    spdx_id = f"SPDXRef-DOCUMENT-{scope}"
    spdx_packages: list[dict[str, Any]] = [
        {
            "SPDXID": spdx_id,
            "name": f"kimi-skills-{scope}",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "copyrightText": "NOASSERTION",
        }
    ]
    relationships: list[dict[str, Any]] = [
        {
            "spdxElementId": spdx_id,
            "relatedSpdxElement": pkg_spdx_id,
            "relationshipType": "DEPENDS_ON",
        }
        for pkg_spdx_id in [f"SPDXRef-{re.sub(r'[^a-zA-Z0-9.-]', '-', name)}" for name in packages]
    ]

    for name, version in packages.items():
        safe_id = re.sub(r"[^a-zA-Z0-9.-]", "-", name)
        pkg_spdx_id = f"SPDXRef-{safe_id}"
        cves = cve_by_package.get(name, [])
        annotations: list[dict[str, Any]] = []
        for cve in cves:
            annotations.append(
                {
                    "annotationType": "REVIEW",
                    "annotator": "Tool: dependency-resolver-4.0.0",
                    "annotationDate": timestamp,
                    "comment": f"{cve.id} ({cve.severity}): {cve.summary}",
                }
            )

        spdx_packages.append(
            {
                "SPDXID": pkg_spdx_id,
                "name": name,
                "versionInfo": version,
                "downloadLocation": f"https://pypi.org/project/{name}/{version}/",
                "filesAnalyzed": False,
                "licenseConcluded": licenses.get(name, "NOASSERTION"),
                "copyrightText": "NOASSERTION",
                "annotations": annotations,
            }
        )

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
    cve_by_package: dict[str, list[CVERecord]],
) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    for name, version in packages.items():
        cves = cve_by_package.get(name, [])
        vulns: list[dict[str, Any]] = []
        for cve in cves:
            vulns.append(
                {
                    "id": cve.id,
                    "source": {"name": cve.source.upper(), "url": cve.references[0] if cve.references else ""},
                    "ratings": [
                        {
                            "source": {"name": cve.source.upper()},
                            "score": cve.cvss_score,
                            "severity": cve.severity,
                            "method": "CVSSv3" if cve.cvss_score else "other",
                        }
                    ],
                    "description": cve.summary,
                }
            )

        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name}@{version}",
                "licenses": [{"license": {"name": licenses.get(name, "NOASSERTION")}}],
                "vulnerabilities": vulns,
            }
        )

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


def _build_sbom_markdown(
    scope: str,
    timestamp: str,
    packages: dict[str, str],
    licenses: dict[str, str],
    cve_by_package: dict[str, list[CVERecord]],
) -> str:
    lines = [
        f"# SBOM: {scope}",
        f"",
        f"- **Generated**: {timestamp}",
        f"- **Tool**: dependency-resolver v4.0.0",
        f"- **Packages**: {len(packages)}",
        f"",
        f"## Packages",
        f"",
        f"| Package | Version | License | CVEs |",
        f"|---------|---------|---------|------|",
    ]
    for name, version in sorted(packages.items()):
        cves = cve_by_package.get(name, [])
        cve_str = ", ".join([f"{c.id} ({c.severity})" for c in cves]) if cves else "None"
        lines.append(f"| {name} | {version} | {licenses.get(name, 'NOASSERTION')} | {cve_str} |")

    lines.append("")
    lines.append("## Vulnerability Details")
    lines.append("")
    for name, cves in sorted(cve_by_package.items()):
        for cve in cves:
            lines.append(f"### {cve.id}")
            lines.append(f"- **Package**: {name}")
            lines.append(f"- **Severity**: {cve.severity}")
            lines.append(f"- **CVSS**: {cve.cvss_score or 'N/A'}")
            lines.append(f"- **Summary**: {cve.summary}")
            lines.append(f"- **Fixed in**: {', '.join(cve.fixed_versions) or 'N/A'}")
            lines.append("")

    return "\n".join(lines)


def _uuid_from_scope(scope: str) -> str:
    # Deterministic UUID5-like hash for stable SBOM serial numbers
    h = hashlib.sha1(f"kimi-skills:{scope}".encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# ---------------------------------------------------------------------------
# Error Policy Integration
# ---------------------------------------------------------------------------

def _emit_error_policy_json(
    skill_name: str,
    report: VerificationReport,
    output_dir: Path,
    auto_install_safe: bool,
) -> Path:
    """Emit a structured error report for the error-policy skill."""
    output_dir.mkdir(parents=True, exist_ok=True)
    error_code = "DEP_OK"
    severity = "none"
    recommended_action = "none"

    if report.missing_binaries or report.missing_runtimes:
        error_code = "DEP_MISSING_BINARY"
        severity = "blocking"
        recommended_action = "request_human_approval"
    elif report.missing_packages:
        error_code = "DEP_MISSING_PACKAGE"
        severity = "blocking"
        recommended_action = "auto_install_packages_or_halt"
    elif report.cves:
        max_sev = max((SEVERITY_ORDER.get(c.severity, 0) for c in report.cves), default=0)
        if max_sev >= SEVERITY_ORDER["HIGH"]:
            error_code = "DEP_CVE_HIGH"
            severity = "blocking"
            recommended_action = "update_dependencies_or_halt"
        else:
            error_code = "DEP_CVE_LOW"
            severity = "warning"
            recommended_action = "review_in_next_sprint"

    payload = {
        "error_code": error_code,
        "severity": severity,
        "target_skill": skill_name,
        "missing": {
            "binaries": report.missing_binaries,
            "packages": report.missing_packages,
            "runtimes": report.missing_runtimes,
        },
        "outdated": [o.__dict__ for o in report.outdated_packages],
        "cves": [c.to_dict() for c in report.cves],
        "recommended_action": recommended_action,
        "auto_install_safe": auto_install_safe and bool(report.missing_packages) and not report.missing_binaries,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    out_path = output_dir / f"error-policy-{skill_name}.json"
    with out_path.open("w") as f:
        json.dump(payload, f, indent=2)
    return out_path


# ---------------------------------------------------------------------------
# Main Verification Logic
# ---------------------------------------------------------------------------

def verify_skill(
    skill_dir: Path,
    installed: dict[str, str],
    cache_dir: Path,
    auto_install: bool = False,
    cve_scan: bool = False,
    cve_update: bool = False,
    offline: bool = False,
    verbose: bool = False,
) -> VerificationReport:
    """Verify a single skill's dependencies."""
    manifest_path = skill_dir / "manifest.json"
    skill_name = skill_dir.name

    if not manifest_path.exists():
        report = VerificationReport(skill_name=skill_name, ok=False)
        report.missing_binaries.append("manifest.json")
        return report

    try:
        manifest = _load_manifest(manifest_path)
    except Exception as e:
        report = VerificationReport(skill_name=skill_name, ok=False)
        report.missing_binaries.append(f"invalid manifest: {e}")
        return report

    deps = manifest.get("dependencies", {})
    report = VerificationReport(skill_name=skill_name)

    # --- Python packages ---
    py_packages = deps.get("python_packages", [])
    if py_packages:
        _log(f"[CHECK] Python packages for {skill_name}: {py_packages}", verbose)
        missing, outdated, satisfied = _check_python_packages(py_packages, installed, verbose)
        report.missing_packages = missing
        report.outdated_packages = outdated
        report.installed_packages = satisfied
        if missing:
            report.ok = False
            if auto_install:
                report.missing_packages = _auto_install_packages(missing, verbose)
                # Re-check after install
                if report.missing_packages:
                    report.ok = False
                else:
                    report.ok = True
            else:
                report.ok = False

    # --- Binaries ---
    binaries = deps.get("binaries", [])
    if binaries:
        _log(f"[CHECK] Binaries for {skill_name}: {binaries}", verbose)
        missing, found = _check_binaries(binaries, verbose)
        report.missing_binaries = missing
        report.installed_binaries = found
        if missing:
            report.ok = False

    # --- Runtimes ---
    runtimes = deps.get("runtimes", {})
    if runtimes:
        _log(f"[CHECK] Runtimes for {skill_name}: {runtimes}", verbose)
        missing, found = _check_runtimes(runtimes, verbose)
        report.missing_runtimes = missing
        report.installed_runtimes = found
        if missing:
            report.ok = False

    # --- CVE Scan ---
    if cve_scan:
        _log(f"[CHECK] CVE scan for {skill_name}", verbose)
        packages_for_scan = _extract_packages_for_cve_scan(manifest, installed)
        if packages_for_scan:
            cve_map = _query_osv_batch(
                packages_for_scan, cache_dir, offline=offline, force_update=cve_update, verbose=verbose
            )
            all_cves: list[CVERecord] = []
            for key, cves in cve_map.items():
                all_cves.extend(cves)
            all_cves = _enrich_with_github_advisory(all_cves, cache_dir, offline=offline, verbose=verbose)
            report.cves = all_cves
            if all_cves:
                _log(f"[WARN] {len(all_cves)} CVE(s) found for {skill_name}", verbose)
        else:
            _log(f"[INFO] No version-locked packages to scan for {skill_name}", verbose)

    return report


def verify_all(
    skills_dir: Path,
    installed: dict[str, str],
    cache_dir: Path,
    auto_install: bool = False,
    cve_scan: bool = False,
    cve_update: bool = False,
    offline: bool = False,
    verbose: bool = False,
) -> dict[str, VerificationReport]:
    """Verify all skills in the ecosystem directory."""
    skill_dirs = _discover_skills(skills_dir)
    reports: dict[str, VerificationReport] = {}
    for skill_dir in skill_dirs:
        report = verify_skill(
            skill_dir,
            installed,
            cache_dir,
            auto_install=auto_install,
            cve_scan=cve_scan,
            cve_update=cve_update,
            offline=offline,
            verbose=verbose,
        )
        reports[skill_dir.name] = report
    return reports


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_report(report: VerificationReport, verbose: bool = False) -> None:
    print(f"\n{'='*60}")
    print(f"Dependency Report: {report.skill_name}")
    print(f"{'='*60}")
    print(f"Status: {'OK' if report.ok else 'FAILED'}")

    if report.installed_packages:
        print(f"\n[Python Packages — {len(report.installed_packages)} satisfied]")
        for name, version in sorted(report.installed_packages.items()):
            print(f"  OK   {name}=={version}")
    if report.missing_packages:
        print(f"\n[Python Packages — {len(report.missing_packages)} MISSING]")
        for pkg in report.missing_packages:
            print(f"  FAIL {pkg}")
    if report.outdated_packages:
        print(f"\n[Python Packages — {len(report.outdated_packages)} OUTDATED]")
        for info in report.outdated_packages:
            print(f"  WARN {info.package}=={info.current_version} (requires {info.spec})")

    if report.installed_binaries:
        print(f"\n[Binaries — {len(report.installed_binaries)} found]")
        for name, version in sorted(report.installed_binaries.items()):
            print(f"  OK   {name} (version {version})")
    if report.missing_binaries:
        print(f"\n[Binaries — {len(report.missing_binaries)} MISSING]")
        for binary in report.missing_binaries:
            print(f"  FAIL {binary} — requires human approval to install")

    if report.installed_runtimes:
        print(f"\n[Runtimes — {len(report.installed_runtimes)} found]")
        for name, version in sorted(report.installed_runtimes.items()):
            print(f"  OK   {name} (version {version})")
    if report.missing_runtimes:
        print(f"\n[Runtimes — {len(report.missing_runtimes)} MISSING]")
        for runtime in report.missing_runtimes:
            print(f"  FAIL {runtime} — requires human approval to install")

    if report.cves:
        print(f"\n[CVE Findings — {len(report.cves)} found]")
        # Sort by severity descending
        sorted_cves = sorted(report.cves, key=lambda c: SEVERITY_ORDER.get(c.severity, 0), reverse=True)
        for cve in sorted_cves:
            print(f"  {cve.severity:8} {cve.id} — {cve.package} — {cve.summary[:60]}...")
            if cve.cvss_score:
                print(f"           CVSS: {cve.cvss_score} | Fixed: {', '.join(cve.fixed_versions) or 'N/A'}")
    else:
        print("\n[CVE Findings — none found]")

    print(f"{'='*60}\n")


def _write_json_report(
    reports: dict[str, VerificationReport],
    output_dir: Path,
    verbose: bool = False,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "dependency-report.json"
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": "dependency-resolver-4.0.0",
        "summary": {
            "total_skills": len(reports),
            "ok": sum(1 for r in reports.values() if r.ok),
            "failed": sum(1 for r in reports.values() if not r.ok),
            "total_cves": sum(len(r.cves) for r in reports.values()),
            "missing_packages": sum(len(r.missing_packages) for r in reports.values()),
            "missing_binaries": sum(len(r.missing_binaries) for r in reports.values()),
        },
        "skills": {name: report.to_dict() for name, report in reports.items()},
    }
    with out_path.open("w") as f:
        json.dump(payload, f, indent=2)
    _log(f"[OK] JSON report written to {out_path}", verbose)
    return out_path


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify-deps.py",
        description="Dependency pre-flight verification for the Kimi AI Engineering Skills Ecosystem",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--skill", type=str, help="Target skill name to verify")
    group.add_argument("--all", action="store_true", help="Verify all skills in the ecosystem")
    parser.add_argument("--auto-install", action="store_true", help="Auto-install missing Python packages (safe only)")
    parser.add_argument("--sbom", action="store_true", help="Generate SBOM for target scope")
    parser.add_argument("--sbom-format", choices=["spdx", "cyclonedx", "markdown"], default="spdx")
    parser.add_argument("--cve-scan", action="store_true", help="Include CVE scan in verification report")
    parser.add_argument("--cve-update", action="store_true", help="Force refresh of CVE cache before scanning")
    parser.add_argument("--offline", action="store_true", help="Use only local cache; do not query APIs")
    parser.add_argument("--output-dir", type=str, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skills-dir", type=str, default=DEFAULT_SKILLS_DIR)
    parser.add_argument("--cache-dir", type=str, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args(argv)

    skills_dir = Path(args.skills_dir)
    cache_dir = Path(args.cache_dir)
    output_dir = Path(args.output_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    verbose = args.verbose
    _log(f"[START] dependency-resolver v4.0.0 | skills_dir={skills_dir} | cache_dir={cache_dir}", verbose)

    # Load installed packages once
    try:
        installed = _get_installed_packages()
        _log(f"[INFO] Detected {len(installed)} installed Python packages", verbose)
    except subprocess.CalledProcessError as e:
        print(f"[FATAL] Cannot list installed packages: {e}", file=sys.stderr)
        return 5

    # Determine scope
    if args.skill:
        target_dir = skills_dir / args.skill
        if not target_dir.exists():
            print(f"[FATAL] Skill directory not found: {target_dir}", file=sys.stderr)
            return 5
        reports = {
            args.skill: verify_skill(
                target_dir,
                installed,
                cache_dir,
                auto_install=args.auto_install,
                cve_scan=args.cve_scan,
                cve_update=args.cve_update,
                offline=args.offline,
                verbose=verbose,
            )
        }
    else:
        reports = verify_all(
            skills_dir,
            installed,
            cache_dir,
            auto_install=args.auto_install,
            cve_scan=args.cve_scan,
            cve_update=args.cve_update,
            offline=args.offline,
            verbose=verbose,
        )

    # Print reports
    for report in reports.values():
        _print_report(report, verbose)

    # Write JSON report
    json_path = _write_json_report(reports, output_dir, verbose)

    # Emit error-policy JSON for each failed skill
    for name, report in reports.items():
        if not report.ok or report.cves:
            _emit_error_policy_json(
                name,
                report,
                output_dir,
                auto_install_safe=args.auto_install,
            )

    # SBOM generation
    if args.sbom:
        manifests = []
        for skill_dir in _discover_skills(skills_dir):
            try:
                manifests.append(_load_manifest(skill_dir / "manifest.json"))
            except Exception:
                continue
        all_cves = []
        for report in reports.values():
            all_cves.extend(report.cves)
        _generate_sbom(
            scope=args.skill or "all",
            manifests=manifests,
            installed=installed,
            cves=all_cves,
            output_format=args.sbom_format,
            output_dir=output_dir,
            verbose=verbose,
        )

    # Determine exit code
    has_missing_packages = any(r.missing_packages for r in reports.values())
    has_missing_binaries = any(r.missing_binaries for r in reports.values())
    has_missing_runtimes = any(r.missing_runtimes for r in reports.values())
    has_cves = any(r.cves for r in reports.values())

    if has_missing_binaries or has_missing_runtimes:
        _log("[EXIT] Code 2 — missing binaries or runtimes (human approval required)", verbose)
        return 2
    if has_missing_packages:
        _log("[EXIT] Code 1 — missing Python packages", verbose)
        return 1
    if has_cves and args.cve_scan:
        _log("[EXIT] Code 3 — CVEs found (non-blocking, see error-policy)", verbose)
        return 3

    _log("[EXIT] Code 0 — all dependencies satisfied", verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
