#!/usr/bin/env python3
"""
dev-dependency-manager: analyze_dependencies.py

Scans project dependencies across multiple ecosystems and generates a unified
update and vulnerability report.

Supports:
  - Node.js (package.json, package-lock.json, yarn.lock, pnpm-lock.yaml)
  - Python (requirements.txt, pyproject.toml, poetry.lock, uv.lock)
  - Rust (Cargo.toml, Cargo.lock)
  - Go (go.mod, go.sum)
  - Ruby (Gemfile, Gemfile.lock)
  - PHP (composer.json, composer.lock)
  - Java (pom.xml, build.gradle, gradle.lockfile)

Usage:
  python analyze_dependencies.py [--root .] [--format json|markdown|sarif]
                                 [--severity low|moderate|high|critical]
                                 [--check-vulns] [--check-outdated] [--check-bloat]
                                 [--output report.json]

Examples:
  python analyze_dependencies.py --format markdown --output DEPENDENCY_REPORT.md
  python analyze_dependencies.py --check-vulns --severity high --format sarif
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.request import urlopen, Request
from urllib.error import HTTPError
import xml.etree.ElementTree as ET


@dataclass
class Dependency:
    name: str
    version: str
    ecosystem: str
    source_file: str
    is_direct: bool = True
    is_dev: bool = False
    declared_range: Optional[str] = None
    latest_version: Optional[str] = None
    license: Optional[str] = None
    size_kb: Optional[int] = None


@dataclass
class Vulnerability:
    id: str
    dependency: str
    ecosystem: str
    severity: str
    score: Optional[float] = None
    fixed_version: Optional[str] = None
    description: Optional[str] = None
    references: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)


@dataclass
class UpdateRecommendation:
    dependency: str
    ecosystem: str
    current: str
    target: str
    type: str
    breaking_risk: str
    reason: str = ""


@dataclass
class Report:
    project_root: str
    scan_time: str
    ecosystems: List[str] = field(default_factory=list)
    dependencies: List[Dependency] = field(default_factory=list)
    vulnerabilities: List[Vulnerability] = field(default_factory=list)
    recommendations: List[UpdateRecommendation] = field(default_factory=list)
    license_conflicts: List[Dict[str, Any]] = field(default_factory=list)
    bloat_flags: List[Dict[str, Any]] = field(default_factory=list)
    lock_file_issues: List[str] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)


def _extract_version(raw: str) -> str:
    """Strip prefix characters (^, ~, >=, ==, etc.) to get bare version."""
    cleaned = re.sub(r"^[\^~>=<!]*\s*", "", raw)
    cleaned = cleaned.lstrip("vV")
    return cleaned if cleaned else raw

# ──────────────────────────────────────────────────────────────────────────────
# Parsers per ecosystem
# ──────────────────────────────────────────────────────────────────────────────

class NodeParser:
    ECOSYSTEM = "npm"

    @staticmethod
    def parse(root: Path) -> List[Dependency]:
        deps: List[Dependency] = []
        pkg_json = root / "package.json"
        if not pkg_json.exists():
            return deps
        data = json.loads(pkg_json.read_text(encoding="utf-8"))
        for section, is_dev in [
            ("dependencies", False),
            ("devDependencies", True),
            ("optionalDependencies", False),
            ("peerDependencies", False),
        ]:
            for name, version in data.get(section, {}).items():
                deps.append(Dependency(
                    name=name,
                    version=_extract_version(version),
                    ecosystem=NodeParser.ECOSYSTEM,
                    source_file=str(pkg_json),
                    is_direct=True,
                    is_dev=is_dev,
                    declared_range=version,
                ))
        lock = root / "package-lock.json"
        if lock.exists():
            NodeParser._enrich_from_npm_lock(deps, lock)
        yarn = root / "yarn.lock"
        if yarn.exists():
            NodeParser._enrich_from_yarn_lock(deps, yarn)
        pnpm = root / "pnpm-lock.yaml"
        if pnpm.exists():
            NodeParser._enrich_from_pnpm_lock(deps, pnpm)
        return deps

    @staticmethod
    def _enrich_from_npm_lock(deps: List[Dependency], lock: Path):
        try:
            data = json.loads(lock.read_text(encoding="utf-8"))
            packages = data.get("packages", {})
            if not packages:
                packages = data.get("dependencies", {})
            for dep in deps:
                key = f"node_modules/{dep.name}"
                entry = packages.get(key) or packages.get(dep.name)
                if entry:
                    dep.version = entry.get("version", dep.version)
        except Exception:
            pass

    @staticmethod
    def _enrich_from_yarn_lock(deps: List[Dependency], lock: Path):
        text = lock.read_text(encoding="utf-8")
        for dep in deps:
            esc = re.escape(dep.name)
            pattern = re.compile(r'^' + esc + r'@.*?:\n\s+version\s+"([^"]+)"', re.MULTILINE)
            m = pattern.search(text)
            if m:
                dep.version = m.group(1)

    @staticmethod
    def _enrich_from_pnpm_lock(deps: List[Dependency], lock: Path):
        text = lock.read_text(encoding="utf-8")
        for dep in deps:
            esc = re.escape(dep.name)
            pattern = re.compile(r'/ ' + esc + r'@([^\s:]+)')
            m = pattern.search(text)
            if m:
                dep.version = m.group(1)

class PythonParser:
    ECOSYSTEM = "PyPI"

    @staticmethod
    def parse(root: Path) -> List[Dependency]:
        deps: List[Dependency] = []
        req_files = list(root.glob("requirements*.txt")) + list(root.glob("requirements/**/*.txt"))
        for req in req_files:
            deps.extend(PythonParser._parse_requirements(req))
        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            deps.extend(PythonParser._parse_pyproject(pyproject))
        poetry_lock = root / "poetry.lock"
        if poetry_lock.exists():
            PythonParser._enrich_from_poetry_lock(deps, poetry_lock)
        uv_lock = root / "uv.lock"
        if uv_lock.exists():
            PythonParser._enrich_from_uv_lock(deps, uv_lock)
        return deps

    @staticmethod
    def _parse_requirements(path: Path) -> List[Dependency]:
        deps = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            m = re.match(r'^([A-Za-z0-9_.\-]+)\s*([<>=!~]+)\s*([A-Za-z0-9_.+\-]+)', line)
            if m:
                deps.append(Dependency(
                    name=m.group(1),
                    version=m.group(3),
                    ecosystem=PythonParser.ECOSYSTEM,
                    source_file=str(path),
                    declared_range=m.group(2) + m.group(3),
                ))
            else:
                m2 = re.match(r'^([A-Za-z0-9_.\-]+)', line)
                if m2:
                    deps.append(Dependency(
                        name=m2.group(1),
                        version="?",
                        ecosystem=PythonParser.ECOSYSTEM,
                        source_file=str(path),
                        declared_range="*",
                    ))
        return deps

    @staticmethod
    def _parse_pyproject(path: Path) -> List[Dependency]:
        deps = []
        text = path.read_text(encoding="utf-8")
        dep_section = re.search(r'\[project\.dependencies\](.*?)(?=\[|$)', text, re.DOTALL)
        if dep_section:
            for line in dep_section.group(1).splitlines():
                line = line.strip().strip(",").strip('"').strip("'")
                if not line or line.startswith("#"):
                    continue
                m = re.match(r'^([A-Za-z0-9_.\-]+)\s*([<>=!~]+)?\s*([A-Za-z0-9_.+\-]+)?', line)
                if m:
                    deps.append(Dependency(
                        name=m.group(1),
                        version=m.group(3) or "?",
                        ecosystem=PythonParser.ECOSYSTEM,
                        source_file=str(path),
                        declared_range=(m.group(2) or "") + (m.group(3) or ""),
                    ))
        return deps

    @staticmethod
    def _enrich_from_poetry_lock(deps: List[Dependency], lock: Path):
        text = lock.read_text(encoding="utf-8")
        for dep in deps:
            esc = re.escape(dep.name)
            pattern = re.compile(r'^\[\[package\]\]\nname = "' + esc + r'"\nversion = "([^"]+)"', re.MULTILINE)
            m = pattern.search(text)
            if m:
                dep.version = m.group(1)

    @staticmethod
    def _enrich_from_uv_lock(deps: List[Dependency], lock: Path):
        text = lock.read_text(encoding="utf-8")
        for dep in deps:
            esc = re.escape(dep.name)
            pattern = re.compile(r'name = "' + esc + r'"\s*\nversion = "([^"]+)"')
            m = pattern.search(text)
            if m:
                dep.version = m.group(1)

class RustParser:
    ECOSYSTEM = "crates.io"

    @staticmethod
    def parse(root: Path) -> List[Dependency]:
        deps: List[Dependency] = []
        cargo_toml = root / "Cargo.toml"
        if not cargo_toml.exists():
            return deps
        text = cargo_toml.read_text(encoding="utf-8")
        for section_name, is_dev in [("dependencies", False), ("dev-dependencies", True)]:
            section = re.search(r'\[' + section_name + r'\](.*?)(?=\[|$)', text, re.DOTALL)
            if not section:
                continue
            for line in section.group(1).splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                inline = re.match(r'^([A-Za-z0-9_\-]+)\s*=\s*\{(.*?)\}', line)
                if inline:
                    name = inline.group(1)
                    ver_match = re.search(r'version\s*=\s*"([^"]+)"', inline.group(2))
                    version = ver_match.group(1) if ver_match else "?"
                else:
                    simple = re.match(r'^([A-Za-z0-9_\-]+)\s*=\s*"([^"]+)"', line)
                    if simple:
                        name, version = simple.group(1), simple.group(2)
                    else:
                        continue
                deps.append(Dependency(
                    name=name,
                    version=version,
                    ecosystem=RustParser.ECOSYSTEM,
                    source_file=str(cargo_toml),
                    is_dev=is_dev,
                    declared_range=version,
                ))
        cargo_lock = root / "Cargo.lock"
        if cargo_lock.exists():
            RustParser._enrich_from_lock(deps, cargo_lock)
        return deps

    @staticmethod
    def _enrich_from_lock(deps: List[Dependency], lock: Path):
        text = lock.read_text(encoding="utf-8")
        for dep in deps:
            esc = re.escape(dep.name)
            pattern = re.compile(r'^\[\[package\]\]\s*\nname = "' + esc + r'"\s*\nversion = "([^"]+)"', re.MULTILINE)
            m = pattern.search(text)
            if m:
                dep.version = m.group(1)


class GoParser:
    ECOSYSTEM = "Go"

    @staticmethod
    def parse(root: Path) -> List[Dependency]:
        deps: List[Dependency] = []
        go_mod = root / "go.mod"
        if not go_mod.exists():
            return deps
        text = go_mod.read_text(encoding="utf-8")
        require_section = re.search(r'require\s*\((.*?)\)', text, re.DOTALL)
        if require_section:
            for line in require_section.group(1).splitlines():
                line = line.strip()
                if not line or line.startswith("//"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    deps.append(Dependency(
                        name=parts[0],
                        version=parts[1],
                        ecosystem=GoParser.ECOSYSTEM,
                        source_file=str(go_mod),
                        declared_range=parts[1],
                    ))
        else:
            single = re.search(r'^require\s+(\S+)\s+(\S+)', text, re.MULTILINE)
            if single:
                deps.append(Dependency(
                    name=single.group(1),
                    version=single.group(2),
                    ecosystem=GoParser.ECOSYSTEM,
                    source_file=str(go_mod),
                    declared_range=single.group(2),
                ))
        return deps


class RubyParser:
    ECOSYSTEM = "RubyGems"

    @staticmethod
    def parse(root: Path) -> List[Dependency]:
        deps: List[Dependency] = []
        gemfile = root / "Gemfile"
        if not gemfile.exists():
            return deps
        text = gemfile.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("gem "):
                continue
            m = re.search(r"gem\s+['\"]([^'\"]+)['\"](?:\s*,\s*['\"]([^'\"]+)['\"])?", line)
            if m:
                deps.append(Dependency(
                    name=m.group(1),
                    version=m.group(2) or "?",
                    ecosystem=RubyParser.ECOSYSTEM,
                    source_file=str(gemfile),
                    declared_range=m.group(2) or "*",
                ))
        lock = root / "Gemfile.lock"
        if lock.exists():
            RubyParser._enrich_from_lock(deps, lock)
        return deps

    @staticmethod
    def _enrich_from_lock(deps: List[Dependency], lock: Path):
        text = lock.read_text(encoding="utf-8")
        in_specs = False
        for line in text.splitlines():
            if line.strip() == "specs:":
                in_specs = True
                continue
            if in_specs and line.startswith("    "):
                m = re.match(r'^\s+([A-Za-z0-9_\-.]+)\s+\(([^)]+)\)', line)
                if m:
                    name, version = m.group(1), m.group(2)
                    for dep in deps:
                        if dep.name == name:
                            dep.version = version
        return deps


class PHPParser:
    ECOSYSTEM = "Packagist"

    @staticmethod
    def parse(root: Path) -> List[Dependency]:
        deps: List[Dependency] = []
        composer = root / "composer.json"
        if not composer.exists():
            return deps
        data = json.loads(composer.read_text(encoding="utf-8"))
        for section, is_dev in [("require", False), ("require-dev", True)]:
            for name, version in data.get(section, {}).items():
                if name == "php" or name.startswith("ext-"):
                    continue
                deps.append(Dependency(
                    name=name,
                    version=_extract_version(version),
                    ecosystem=PHPParser.ECOSYSTEM,
                    source_file=str(composer),
                    is_dev=is_dev,
                    declared_range=version,
                ))
        lock = root / "composer.lock"
        if lock.exists():
            PHPParser._enrich_from_lock(deps, lock)
        return deps

    @staticmethod
    def _enrich_from_lock(deps: List[Dependency], lock: Path):
        try:
            data = json.loads(lock.read_text(encoding="utf-8"))
            for pkg in data.get("packages", []) + data.get("packages-dev", []):
                for dep in deps:
                    if dep.name == pkg.get("name"):
                        dep.version = pkg.get("version", dep.version)
        except Exception:
            pass


class JavaParser:
    ECOSYSTEM = "Maven"

    @staticmethod
    def parse(root: Path) -> List[Dependency]:
        deps: List[Dependency] = []
        pom = root / "pom.xml"
        if pom.exists():
            deps.extend(JavaParser._parse_pom(pom))
        gradle = root / "build.gradle"
        gradle_kts = root / "build.gradle.kts"
        for g in (gradle, gradle_kts):
            if g.exists():
                deps.extend(JavaParser._parse_gradle(g))
        return deps

    @staticmethod
    def _parse_pom(path: Path) -> List[Dependency]:
        deps = []
        try:
            tree = ET.parse(path)
            ns = {"m": "http://maven.apache.org/POM/4.0.0"}
            for dep in tree.iterfind(".//m:dependency", ns):
                group = dep.find("m:groupId", ns)
                artifact = dep.find("m:artifactId", ns)
                version = dep.find("m:version", ns)
                scope = dep.find("m:scope", ns)
                if group is not None and artifact is not None:
                    is_dev = scope is not None and scope.text in ("test", "provided")
                    deps.append(Dependency(
                        name=f"{group.text}:{artifact.text}",
                        version=(version.text if version is not None else "?"),
                        ecosystem=JavaParser.ECOSYSTEM,
                        source_file=str(path),
                        is_dev=is_dev,
                        declared_range=(version.text if version is not None else "?"),
                    ))
        except Exception:
            pass
        return deps

    @staticmethod
    def _parse_gradle(path: Path) -> List[Dependency]:
        deps = []
        text = path.read_text(encoding="utf-8")
        pattern = re.compile(r"(?:implementation|api|compileOnly|testImplementation|runtimeOnly)\s*[('\"]([^'\"')]+)[\'\")]")
        for match in pattern.finditer(text):
            coord = match.group(1)
            parts = coord.split(":")
            if len(parts) >= 2:
                name = ":".join(parts[:2])
                version = parts[2] if len(parts) >= 3 else "?"
                is_dev = "test" in match.group(0).lower()
                deps.append(Dependency(
                    name=name,
                    version=version,
                    ecosystem="Gradle" if path.name.endswith(".kts") else JavaParser.ECOSYSTEM,
                    source_file=str(path),
                    is_dev=is_dev,
                    declared_range=version,
                ))
        return deps

# ──────────────────────────────────────────────────────────────────────────────
# Vulnerability scanning (OSV integration)
# ──────────────────────────────────────────────────────────────────────────────

OSV_API_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_SEVERITY_ORDER = {"low": 1, "moderate": 2, "high": 3, "critical": 4}


def _osv_ecosystem(dep_ecosystem: str) -> str:
    mapping = {
        "npm": "npm",
        "PyPI": "PyPI",
        "crates.io": "crates.io",
        "Go": "Go",
        "RubyGems": "RubyGems",
        "Packagist": "Packagist",
        "Maven": "Maven",
        "Gradle": "Maven",
    }
    return mapping.get(dep_ecosystem, dep_ecosystem)


def query_osv(deps: List[Dependency]) -> List[Vulnerability]:
    if not deps:
        return []
    queries = []
    for dep in deps:
        if dep.version == "?" or not dep.version:
            continue
        queries.append({
            "package": {"name": dep.name, "ecosystem": _osv_ecosystem(dep.ecosystem)},
            "version": dep.version,
        })
    if not queries:
        return []

    vulnerabilities: List[Vulnerability] = []
    batch_size = 1000
    for i in range(0, len(queries), batch_size):
        batch = queries[i:i + batch_size]
        payload = json.dumps({"queries": batch}).encode("utf-8")
        req = Request(OSV_API_BATCH_URL, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            print(f"[warn] OSV batch query failed: {e.code} {e.reason}", file=sys.stderr)
            continue
        except Exception as e:
            print(f"[warn] OSV query error: {e}", file=sys.stderr)
            continue

        for j, result in enumerate(data.get("results", [])):
            dep = deps[i + j]
            for vuln in result.get("vulns", []):
                severity = _extract_osv_severity(vuln)
                fixed = None
                for aff in vuln.get("affected", []):
                    for r in aff.get("ranges", []):
                        for ev in r.get("events", []):
                            if "fixed" in ev:
                                fixed = ev["fixed"]
                                break
                vuln_obj = Vulnerability(
                    id=vuln.get("id", "UNKNOWN"),
                    dependency=dep.name,
                    ecosystem=dep.ecosystem,
                    severity=severity,
                    score=_extract_cvss_score(vuln),
                    fixed_version=fixed,
                    description=vuln.get("summary") or vuln.get("details", "")[:200],
                    references=[ref.get("url", "") for ref in vuln.get("references", [])[:3]],
                    aliases=[a.get("value", "") for a in vuln.get("aliases", [])],
                )
                vulnerabilities.append(vuln_obj)
    return vulnerabilities


def _extract_osv_severity(vuln: Dict[str, Any]) -> str:
    for sev in vuln.get("severity", []):
        if sev.get("type") == "CVSS_V3":
            score = float(sev.get("score", 0))
            if score >= 9.0:
                return "critical"
            if score >= 7.0:
                return "high"
            if score >= 4.0:
                return "moderate"
            return "low"
    db_sev = vuln.get("database_specific", {}).get("severity", "moderate").lower()
    if db_sev in OSV_SEVERITY_ORDER:
        return db_sev
    return "moderate"


def _extract_cvss_score(vuln: Dict[str, Any]) -> Optional[float]:
    for sev in vuln.get("severity", []):
        if sev.get("type") == "CVSS_V3":
            try:
                return float(sev.get("score", 0))
            except Exception:
                pass
    return None

# ──────────────────────────────────────────────────────────────────────────────
# Update recommendations
# ──────────────────────────────────────────────────────────────────────────────

def build_recommendations(deps: List[Dependency], vulns: List[Vulnerability]) -> List[UpdateRecommendation]:
    recs: List[UpdateRecommendation] = []
    vuln_map: Dict[str, List[Vulnerability]] = {}
    for v in vulns:
        vuln_map.setdefault(v.dependency, []).append(v)

    for dep in deps:
        if dep.version == "?" or not dep.version:
            continue
        current = _normalize_version(dep.version)
        dep_vulns = vuln_map.get(dep.name, [])
        target = None
        for v in dep_vulns:
            if v.fixed_version and _version_greater(_normalize_version(v.fixed_version), current):
                if target is None or _version_greater(_normalize_version(v.fixed_version), target):
                    target = _normalize_version(v.fixed_version)
        if target:
            recs.append(UpdateRecommendation(
                dependency=dep.name,
                ecosystem=dep.ecosystem,
                current=dep.version,
                target=target,
                type=_semver_bump_type(current, target),
                breaking_risk="low" if _semver_bump_type(current, target) == "patch" else "medium",
                reason=f"Fixes {len(dep_vulns)} known vulnerability(s)",
            ))
    return recs


def _normalize_version(v: str) -> str:
    v = v.lstrip("vV")
    v = v.split("+")[0]
    return v


def _version_greater(a: str, b: str) -> bool:
    def _parts(v: str):
        parts = re.split(r"[.-]", v)
        out = []
        for p in parts:
            if p.isdigit():
                out.append((0, int(p)))
            elif p in ("alpha", "a"):
                out.append((1, 0))
            elif p in ("beta", "b"):
                out.append((2, 0))
            elif p in ("rc", "preview"):
                out.append((3, 0))
            else:
                out.append((4, p))
        return out
    pa, pb = _parts(a), _parts(b)
    for x, y in zip(pa, pb):
        if x < y:
            return False
        if x > y:
            return True
    return len(pa) > len(pb)


def _semver_bump_type(current: str, target: str) -> str:
    c = current.split(".")
    t = target.split(".")
    if len(c) >= 1 and len(t) >= 1 and c[0] != t[0]:
        return "major"
    if len(c) >= 2 and len(t) >= 2 and c[1] != t[1]:
        return "minor"
    return "patch"


# ──────────────────────────────────────────────────────────────────────────────
# License audit helpers
# ──────────────────────────────────────────────────────────────────────────────

INCOMPATIBLE_LICENSES = {
    "gpl-2.0", "gpl-3.0", "agpl-3.0", "lgpl-2.1", "lgpl-3.0",
    "gpl2", "gpl3", "agpl3", "copyleft",
}
WARN_LICENSES = {"mpl-2.0", "epl-2.0", "cddl-1.0"}


def detect_license_conflicts(deps: List[Dependency]) -> List[Dict[str, Any]]:
    conflicts = []
    return conflicts


# ──────────────────────────────────────────────────────────────────────────────
# Bloat detection helpers
# ──────────────────────────────────────────────────────────────────────────────

def detect_bloat(deps: List[Dependency], root: Path) -> List[Dict[str, Any]]:
    flags = []
    names: Dict[str, List[str]] = {}
    for dep in deps:
        names.setdefault(dep.name, []).append(dep.version)
    for name, versions in names.items():
        if len(versions) > 1:
            flags.append({
                "type": "duplicate_versions",
                "dependency": name,
                "versions": versions,
                "severity": "info",
            })
    for lock_file in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock", "poetry.lock", "uv.lock", "Gemfile.lock", "composer.lock"):
        p = root / lock_file
        if p.exists() and p.stat().st_size > 2 * 1024 * 1024:
            flags.append({
                "type": "oversized_lock_file",
                "file": lock_file,
                "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                "severity": "warning",
            })
    return flags


# ──────────────────────────────────────────────────────────────────────────────
# Lock file consistency checks
# ──────────────────────────────────────────────────────────────────────────────

def check_lock_consistency(deps: List[Dependency], root: Path) -> List[str]:
    issues = []
    lock = root / "package-lock.json"
    if lock.exists():
        try:
            data = json.loads(lock.read_text(encoding="utf-8"))
            v = data.get("lockfileVersion", 1)
            if v < 2:
                issues.append("package-lock.json uses legacy lockfileVersion. Recommend npm 9+ (v3).")
        except Exception:
            pass
    if (root / "pyproject.toml").exists() and not any((root / f).exists() for f in ("poetry.lock", "uv.lock", "Pipfile.lock")):
        if not list(root.glob("requirements*.txt")):
            issues.append("pyproject.toml found but no lock file (poetry.lock/uv.lock/Pipfile.lock). Builds may be non-reproducible.")
    cargo_toml = root / "Cargo.toml"
    if cargo_toml.exists():
        text = cargo_toml.read_text(encoding="utf-8")
        if "[lib]" not in text and not (root / "Cargo.lock").exists():
            issues.append("Cargo.toml appears to be a binary crate but Cargo.lock is missing. Commit Cargo.lock for reproducible builds.")
    return issues

# ──────────────────────────────────────────────────────────────────────────────
# Report generators
# ──────────────────────────────────────────────────────────────────────────────

def generate_json_report(report: Report) -> str:
    def serialize(obj):
        if isinstance(obj, (Dependency, Vulnerability, UpdateRecommendation, Report)):
            return {k: serialize(v) for k, v in asdict(obj).items()}
        if isinstance(obj, list):
            return [serialize(i) for i in obj]
        if isinstance(obj, dict):
            return {k: serialize(v) for k, v in obj.items()}
        return obj
    return json.dumps(serialize(report), indent=2)


def generate_markdown_report(report: Report, min_severity: str = "low") -> str:
    min_level = OSV_SEVERITY_ORDER.get(min_severity, 1)
    lines = [
        "# Dependency Analysis Report",
        "",
        f"- **Project root**: `{report.project_root}`",
        f"- **Scan time**: {report.scan_time}",
        f"- **Ecosystems detected**: {', '.join(report.ecosystems) if report.ecosystems else 'None'}",
        "",
        "## Summary",
        "",
    ]
    summary = report.summary
    lines.append(f"- **Total dependencies**: {summary.get('total_dependencies', 0)}")
    lines.append(f"- **Direct dependencies**: {summary.get('direct_dependencies', 0)}")
    lines.append(f"- **Dev dependencies**: {summary.get('dev_dependencies', 0)}")
    lines.append(f"- **Vulnerabilities**: {summary.get('total_vulnerabilities', 0)} ({summary.get('critical', 0)} critical, {summary.get('high', 0)} high, {summary.get('moderate', 0)} moderate, {summary.get('low', 0)} low)")
    lines.append(f"- **Update recommendations**: {len(report.recommendations)}")
    lines.append(f"- **Bloat flags**: {len(report.bloat_flags)}")
    lines.append(f"- **Lock file issues**: {len(report.lock_file_issues)}")
    lines.append("")

    if report.vulnerabilities:
        lines.append("## Vulnerabilities")
        lines.append("")
        lines.append("| ID | Package | Severity | Fixed in | Description |")
        lines.append("|---|---|---|---|---|")
        for v in report.vulnerabilities:
            if OSV_SEVERITY_ORDER.get(v.severity, 1) < min_level:
                continue
            desc = (v.description or "").replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {v.id} | {v.dependency} | {v.severity} | {v.fixed_version or 'N/A'} | {desc} |")
        lines.append("")

    if report.recommendations:
        lines.append("## Update Recommendations")
        lines.append("")
        lines.append("| Package | Current | Target | Type | Risk | Reason |")
        lines.append("|---|---|---|---|---|---|")
        for r in report.recommendations:
            lines.append(f"| {r.dependency} | {r.current} | {r.target} | {r.type} | {r.breaking_risk} | {r.reason} |")
        lines.append("")

    if report.bloat_flags:
        lines.append("## Bloat & Quality Flags")
        lines.append("")
        for flag in report.bloat_flags:
            lines.append(f"- **{flag['type']}**: `{flag.get('dependency') or flag.get('file')}` -- severity: {flag['severity']}")
            if "versions" in flag:
                lines.append(f"  - versions: {', '.join(flag['versions'])}")
            if "size_mb" in flag:
                lines.append(f"  - size: {flag['size_mb']} MB")
        lines.append("")

    if report.lock_file_issues:
        lines.append("## Lock File & Reproducibility Issues")
        lines.append("")
        for issue in report.lock_file_issues:
            lines.append(f"- {issue}")
        lines.append("")

    lines.append("---")
    lines.append("*Generated by dev-dependency-manager analyze_dependencies.py*")
    return "\n".join(lines)


def generate_sarif_report(report: Report) -> str:
    results = []
    for v in report.vulnerabilities:
        results.append({
            "ruleId": v.id,
            "level": "error" if v.severity in ("critical", "high") else "warning",
            "message": {"text": f"[{v.severity}] {v.description} (Fixed in: {v.fixed_version or 'unknown'})"},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": report.project_root},
                }
            }],
            "properties": {
                "ecosystem": v.ecosystem,
                "dependency": v.dependency,
                "severity": v.severity,
                "cvssScore": v.score,
                "fixedVersion": v.fixed_version,
                "aliases": v.aliases,
            }
        })
    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "dev-dependency-manager",
                    "informationUri": "https://github.com/kimi-cli/skills",
                    "version": "1.0.0",
                }
            },
            "results": results,
        }]
    }
    return json.dumps(sarif, indent=2)

# ──────────────────────────────────────────────────────────────────────────────
# Main orchestration
# ──────────────────────────────────────────────────────────────────────────────

def scan_project(root: Path, check_vulns: bool = True, check_bloat: bool = True) -> Report:
    all_deps: List[Dependency] = []
    ecosystems: set = set()

    parsers = [
        NodeParser(),
        PythonParser(),
        RustParser(),
        GoParser(),
        RubyParser(),
        PHPParser(),
        JavaParser(),
    ]
    for parser in parsers:
        deps = parser.parse(root)
        if deps:
            ecosystems.add(parser.ECOSYSTEM)
            all_deps.extend(deps)

    report = Report(
        project_root=str(root.resolve()),
        scan_time=datetime.now(timezone.utc).isoformat(),
        ecosystems=sorted(ecosystems),
        dependencies=all_deps,
    )

    if check_vulns:
        report.vulnerabilities = query_osv(all_deps)
    report.recommendations = build_recommendations(all_deps, report.vulnerabilities)
    report.license_conflicts = detect_license_conflicts(all_deps)
    if check_bloat:
        report.bloat_flags = detect_bloat(all_deps, root)
    report.lock_file_issues = check_lock_consistency(all_deps, root)

    direct = sum(1 for d in all_deps if d.is_direct)
    dev = sum(1 for d in all_deps if d.is_dev)
    sev_counts = {"critical": 0, "high": 0, "moderate": 0, "low": 0}
    for v in report.vulnerabilities:
        sev_counts[v.severity] = sev_counts.get(v.severity, 0) + 1

    report.summary = {
        "total_dependencies": len(all_deps),
        "direct_dependencies": direct,
        "dev_dependencies": dev,
        "total_vulnerabilities": len(report.vulnerabilities),
        **sev_counts,
    }
    return report


def main():
    parser = argparse.ArgumentParser(description="Analyze project dependencies for updates and vulnerabilities")
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument("--format", choices=["json", "markdown", "sarif"], default="markdown", help="Output format")
    parser.add_argument("--severity", choices=["low", "moderate", "high", "critical"], default="low", help="Minimum vulnerability severity to include")
    parser.add_argument("--check-vulns", action="store_true", default=True, help="Query OSV for vulnerabilities")
    parser.add_argument("--no-check-vulns", dest="check_vulns", action="store_false", help="Skip vulnerability check")
    parser.add_argument("--check-outdated", action="store_true", default=True, help="Generate update recommendations")
    parser.add_argument("--check-bloat", action="store_true", default=True, help="Detect bloat and duplicates")
    parser.add_argument("--output", help="Write report to file instead of stdout")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"Error: {root} is not a directory", file=sys.stderr)
        sys.exit(1)

    report = scan_project(root, check_vulns=args.check_vulns, check_bloat=args.check_bloat)

    if args.format == "json":
        output = generate_json_report(report)
    elif args.format == "sarif":
        output = generate_sarif_report(report)
    else:
        output = generate_markdown_report(report, min_severity=args.severity)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
