#!/usr/bin/env python3
"""
run_security_scan.py — Multi-tool security scan orchestrator with unified reporting.

Auto-discovers project type, runs appropriate security scanners, normalizes and
deduplicates findings, harmonizes severity, and outputs SARIF, JSON, HTML, or Markdown.

Usage:
    python run_security_scan.py --all --output-format sarif --output-file results.sarif
    python run_security_scan.py --sast --secrets --fail-on critical,high
    python run_security_scan.py --dependencies --containers --output-format html
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ───────────────────────────────
# Unified Data Model
# ───────────────────────────────

@dataclass
class FindingLocation:
    uri: str
    start_line: int = 1
    start_column: int = 1
    end_line: Optional[int] = None
    end_column: Optional[int] = None
    snippet: Optional[str] = None


@dataclass
class Finding:
    rule_id: str
    tool: str
    category: str  # sast | secrets | dependencies | containers | infrastructure
    severity: str  # critical | high | medium | low | info
    confidence: str = "medium"  # high | medium | low
    message: str = ""
    locations: List[FindingLocation] = field(default_factory=list)
    cwe_id: Optional[str] = None
    cve_id: Optional[str] = None
    cvss_score: Optional[float] = None
    fix_available: bool = False
    fix_version: Optional[str] = None
    dependency_name: Optional[str] = None
    dependency_version: Optional[str] = None
    transitive: bool = False
    properties: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def dedup_key(self) -> str:
        """Stable key for deduplication."""
        loc = self.locations[0] if self.locations else FindingLocation(uri="", start_line=0)
        text = f"{self.rule_id}:{loc.uri}:{loc.start_line}:{loc.start_column}:{self.message[:120]}"
        return hashlib.sha256(text.encode()).hexdigest()


# ───────────────────────────────
# Severity Harmonization
# ───────────────────────────────

SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


def normalize_severity(raw_severity: str, tool: str) -> str:
    """Map tool-specific severity strings to unified scale."""
    raw = raw_severity.lower().strip()

    # Direct mappings
    if raw in {"critical", "crITICAL"}:
        return "critical"
    if raw in {"high", "error", "severe"}:
        return "high"
    if raw in {"medium", "moderate", "warning"}:
        return "medium"
    if raw in {"low", "minor", "note"}:
        return "low"
    if raw in {"info", "informational", "none", "unknown"}:
        return "info"

    # Tool-specific overrides
    if tool == "npm_audit":
        mapping = {"critical": "critical", "high": "high", "moderate": "medium", "low": "low"}
        return mapping.get(raw, "info")
    if tool == "trivy":
        mapping = {"critical": "critical", "high": "high", "medium": "medium", "low": "low", "unknown": "info"}
        return mapping.get(raw, "info")
    if tool in {"checkov", "tfsec"}:
        mapping = {"critical": "critical", "high": "high", "medium": "medium", "low": "low", "info": "info"}
        return mapping.get(raw, "info")

    return "info"


def severity_rank(sev: str) -> int:
    return SEVERITY_ORDER.get(sev.lower(), 0)


# ───────────────────────────────
# Tool Detection & Project Discovery
# ───────────────────────────────

class ProjectDiscovery:
    MARKERS = {
        "python": {"files": ["requirements.txt", "Pipfile", "pyproject.toml", "setup.py"], "lockfiles": ["Pipfile.lock"]},
        "javascript": {"files": ["package.json"], "lockfiles": ["package-lock.json", "yarn.lock", "pnpm-lock.yaml"]},
        "typescript": {"files": ["package.json", "tsconfig.json"], "lockfiles": ["package-lock.json", "yarn.lock"]},
        "go": {"files": ["go.mod"], "lockfiles": ["go.sum"]},
        "rust": {"files": ["Cargo.toml"], "lockfiles": ["Cargo.lock"]},
        "java": {"files": ["pom.xml", "build.gradle", "build.gradle.kts"]},
        "docker": {"files": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"]},
        "terraform": {"files": [".tf"]},
        "cloudformation": {"files": [".yaml", ".yml", ".json"], "contents": ["AWSTemplateFormatVersion", "Resources:"]},
        "kubernetes": {"files": [".yaml", ".yml"], "contents": ["apiVersion:", "kind:"]},
    }

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.detected: Dict[str, bool] = {}
        self._scan()

    def _scan(self) -> None:
        for lang, meta in self.MARKERS.items():
            found = False
            for pattern in meta.get("files", []):
                if pattern.startswith("."):
                    # Extension search
                    found = any(f.suffix == pattern for f in self.root.rglob(f"*{pattern}"))
                else:
                    found = (self.root / pattern).exists() or any(
                        (self.root / d / pattern).exists() for d in ["."] + [str(p) for p in self.root.iterdir() if p.is_dir()]
                    )
                if found:
                    break
            if not found and "contents" in meta:
                for f in self.root.rglob("*"):
                    if f.is_file() and f.suffix in (".yaml", ".yml", ".json"):
                        try:
                            text = f.read_text(encoding="utf-8", errors="ignore")
                            if any(marker in text for marker in meta["contents"]):
                                found = True
                                break
                        except Exception:
                            continue
            self.detected[lang] = found

    def languages(self) -> List[str]:
        return [k for k, v in self.detected.items() if v and k not in {"docker", "terraform", "cloudformation", "kubernetes"}]

    def has_infrastructure(self) -> bool:
        return any(self.detected.get(k) for k in ("terraform", "cloudformation", "kubernetes"))

    def has_containers(self) -> bool:
        return self.detected.get("docker", False)


# ───────────────────────────────
# Tool Runners
# ───────────────────────────────

class ToolRunner:
    def __init__(self, root: Path, discovery: ProjectDiscovery):
        self.root = root
        self.discovery = discovery
        self._check_cache: Dict[str, bool] = {}

    def _has_tool(self, name: str) -> bool:
        if name not in self._check_cache:
            self._check_cache[name] = subprocess.run(
                ["which", name], capture_output=True
            ).returncode == 0
        return self._check_cache[name]

    def run_command(self, cmd: List[str], timeout: int = 300) -> Tuple[int, str, str]:
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return proc.returncode, proc.stdout, proc.stderr
        except FileNotFoundError:
            return 127, "", f"Command not found: {cmd[0]}"
        except subprocess.TimeoutExpired:
            return -1, "", "Command timed out"

    # ── SAST ──────────────────────

    def run_semgrep(self) -> List[Finding]:
        if not self._has_tool("semgrep"):
            return []
        rc, out, err = self.run_command([
            "semgrep", "--config=p/security-audit", "--config=p/owasp-top-ten",
            "--config=p/cwe-top-25", "--json", "--quiet", "."
        ])
        if rc not in (0, 1):
            print(f"[warn] semgrep failed (rc={rc}): {err[:200]}", file=sys.stderr)
            return []
        return self._parse_semgrep_json(out)

    def _parse_semgrep_json(self, text: str) -> List[Finding]:
        findings: List[Finding] = []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return findings
        for r in data.get("results", []):
            start = r.get("start", {})
            end = r.get("end", {})
            loc = FindingLocation(
                uri=r.get("path", ""),
                start_line=start.get("line", 1),
                start_column=start.get("col", 1),
                end_line=end.get("line"),
                end_column=end.get("col"),
                snippet=r.get("extra", {}).get("lines"),
            )
            extra = r.get("extra", {})
            sev = normalize_severity(extra.get("metadata", {}).get("severity", extra.get("severity", "warning")), "semgrep")
            cwe = None
            if "cwe" in extra.get("metadata", {}):
                cwes = extra["metadata"]["cwe"]
                if isinstance(cwes, list) and cwes:
                    cwe = cwes[0]
                elif isinstance(cwes, str):
                    cwe = cwes
            findings.append(Finding(
                rule_id=r.get("check_id", "semgrep.unknown"),
                tool="semgrep",
                category="sast",
                severity=sev,
                confidence="high" if sev in ("critical", "high") else "medium",
                message=extra.get("message", ""),
                locations=[loc],
                cwe_id=cwe,
                properties={"metavars": extra.get("metavars", {})},
                raw=r,
            ))
        return findings

    def run_bandit(self) -> List[Finding]:
        if not self._has_tool("bandit"):
            return []
        rc, out, err = self.run_command([
            "bandit", "-r", ".", "-f", "json", "-x", "./tests,./venv,./.venv,./node_modules"
        ])
        if rc not in (0, 1):
            return []
        return self._parse_bandit_json(out)

    def _parse_bandit_json(self, text: str) -> List[Finding]:
        findings: List[Finding] = []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return findings
        for r in data.get("results", []):
            loc = FindingLocation(
                uri=r.get("filename", ""),
                start_line=r.get("line_number", 1),
                start_column=1,
                snippet=r.get("code"),
            )
            findings.append(Finding(
                rule_id=r.get("test_id", "B???"),
                tool="bandit",
                category="sast",
                severity=normalize_severity(r.get("issue_severity", "medium"), "bandit"),
                confidence=r.get("issue_confidence", "medium").lower(),
                message=f"[{r.get('test_name', '')}] {r.get('issue_text', '')}",
                locations=[loc],
                properties={"more_info": r.get("more_info")},
                raw=r,
            ))
        return findings

    def run_gosec(self) -> List[Finding]:
        if not self._has_tool("gosec"):
            return []
        rc, out, err = self.run_command([
            "gosec", "-fmt", "json", "-exclude-generated", "./..."
        ])
        if rc not in (0, 1):
            return []
        return self._parse_gosec_json(out)

    def _parse_gosec_json(self, text: str) -> List[Finding]:
        findings: List[Finding] = []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return findings
        for r in data.get("Issues", []):
            loc = FindingLocation(
                uri=r.get("file", ""),
                start_line=r.get("line", 1),
                start_column=r.get("column", 1),
                snippet=r.get("code"),
            )
            findings.append(Finding(
                rule_id=r.get("rule_id", ""),
                tool="gosec",
                category="sast",
                severity=normalize_severity(r.get("severity", "medium"), "gosec"),
                confidence="high",
                message=r.get("details", ""),
                locations=[loc],
                cwe_id=r.get("cwe", {}).get("id"),
                raw=r,
            ))
        return findings

    def run_eslint_security(self) -> List[Finding]:
        if not self._has_tool("eslint"):
            return []
        rc, out, err = self.run_command([
            "eslint", ".", "--ext", ".js,.jsx,.ts,.tsx",
            "--format", "json", "--plugin", "security",
            "--rule", "security/detect-object-injection:error",
        ])
        if rc not in (0, 1):
            return []
        return self._parse_eslint_json(out)

    def _parse_eslint_json(self, text: str) -> List[Finding]:
        findings: List[Finding] = []
        try:
            files = json.loads(text)
        except json.JSONDecodeError:
            return findings
        for f in files:
            for m in f.get("messages", []):
                if not m.get("ruleId", "").startswith("security/"):
                    continue
                loc = FindingLocation(
                    uri=f.get("filePath", ""),
                    start_line=m.get("line", 1),
                    start_column=m.get("column", 1),
                    end_line=m.get("endLine"),
                    end_column=m.get("endColumn"),
                )
                sev = "high" if m.get("severity") == 2 else "medium"
                findings.append(Finding(
                    rule_id=m.get("ruleId", ""),
                    tool="eslint-security",
                    category="sast",
                    severity=sev,
                    confidence="medium",
                    message=m.get("message", ""),
                    locations=[loc],
                    raw=m,
                ))
        return findings

    # ── Secret Scanning ───────────

    def run_gitleaks(self) -> List[Finding]:
        if not self._has_tool("gitleaks"):
            return []
        rc, out, err = self.run_command([
            "gitleaks", "detect", "--source", ".", "--verbose", "--redact",
            "--report-format", "json", "--report-path", "/tmp/gitleaks.json"
        ])
        if rc not in (0, 1):
            return []
        try:
            text = Path("/tmp/gitleaks.json").read_text()
            data = json.loads(text)
        except Exception:
            return []
        return self._parse_gitleaks_json(data)

    def _parse_gitleaks_json(self, data: Any) -> List[Finding]:
        findings: List[Finding] = []
        items = data if isinstance(data, list) else data.get("findings", [])
        for r in items:
            loc = FindingLocation(
                uri=r.get("File", ""),
                start_line=r.get("StartLine", 1),
                start_column=r.get("StartColumn", 1),
                end_line=r.get("EndLine"),
                end_column=r.get("EndColumn"),
                snippet=r.get("Match"),
            )
            findings.append(Finding(
                rule_id=r.get("RuleID", "secret.unknown"),
                tool="gitleaks",
                category="secrets",
                severity="high",
                confidence="high",
                message=f"Possible secret: {r.get('Description', '')}",
                locations=[loc],
                raw=r,
            ))
        return findings

    def run_trufflehog(self) -> List[Finding]:
        if not self._has_tool("trufflehog"):
            return []
        rc, out, err = self.run_command([
            "trufflehog", "filesystem", ".", "--json", "--only-verified"
        ])
        if rc not in (0, 1):
            return []
        return self._parse_trufflehog_json(out)

    def _parse_trufflehog_json(self, text: str) -> List[Finding]:
        findings: List[Finding] = []
        for line in text.strip().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            meta = r.get("SourceMetadata", {}).get("Data", {})
            fs = meta.get("Filesystem", {})
            loc = FindingLocation(
                uri=fs.get("file", ""),
                start_line=fs.get("line", 1),
                snippet=r.get("RawV2") or r.get("Raw"),
            )
            verified = r.get("Verified", False)
            sev = "critical" if verified else "high"
            findings.append(Finding(
                rule_id=r.get("DetectorName", "secret.unknown"),
                tool="trufflehog",
                category="secrets",
                severity=sev,
                confidence="high" if verified else "medium",
                message=f"{'Verified' if verified else 'Possible'} secret: {r.get('DetectorName', '')}",
                locations=[loc],
                raw=r,
            ))
        return findings

    # ── Dependency Scanning ───────

    def run_npm_audit(self) -> List[Finding]:
        if not (self.root / "package.json").exists():
            return []
        if not self._has_tool("npm"):
            return []
        rc, out, err = self.run_command(["npm", "audit", "--json"])
        if rc not in (0, 1):
            return []
        return self._parse_npm_audit_json(out)

    def _parse_npm_audit_json(self, text: str) -> List[Finding]:
        findings: List[Finding] = []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return findings
        for adv_id, adv in data.get("advisories", {}).items():
            sev = normalize_severity(adv.get("severity", "moderate"), "npm_audit")
            for finding_data in adv.get("findings", []):
                for path in finding_data.get("paths", []):
                    findings.append(Finding(
                        rule_id=adv.get("cves", [adv_id])[0] if adv.get("cves") else adv_id,
                        tool="npm_audit",
                        category="dependencies",
                        severity=sev,
                        confidence="high",
                        message=adv.get("overview", adv.get("title", "")),
                        locations=[FindingLocation(uri="package.json", start_line=1)],
                        cve_id=adv.get("cves", [None])[0],
                        cvss_score=adv.get("cvss", {}).get("score"),
                        fix_available=bool(adv.get("patched_versions")),
                        fix_version=adv.get("patched_versions"),
                        dependency_name=adv.get("module_name"),
                        dependency_version=finding_data.get("version"),
                        transitive=">" in path,
                        properties={"vulnerable_versions": adv.get("vulnerable_versions")},
                        raw=adv,
                    ))
        return findings

    def run_pip_audit(self) -> List[Finding]:
        if not self._has_tool("pip-audit"):
            return []
        rc, out, err = self.run_command(["pip-audit", "--desc", "--format=json", "-r", "requirements.txt"])
        if rc not in (0, 1):
            return []
        return self._parse_pip_audit_json(out)

    def _parse_pip_audit_json(self, text: str) -> List[Finding]:
        findings: List[Finding] = []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return findings
        for dep in data.get("dependencies", []):
            for vuln in dep.get("vulns", []):
                findings.append(Finding(
                    rule_id=vuln.get("id", "CVE-???"),
                    tool="pip-audit",
                    category="dependencies",
                    severity="high",
                    confidence="high",
                    message=vuln.get("description", f"Vulnerability in {dep.get('name', '')}"),
                    locations=[FindingLocation(uri="requirements.txt", start_line=1)],
                    dependency_name=dep.get("name"),
                    dependency_version=dep.get("version"),
                    fix_available=bool(vuln.get("fix_versions")),
                    fix_version=vuln.get("fix_versions", [None])[0] if vuln.get("fix_versions") else None,
                    properties={"aliases": vuln.get("aliases", [])},
                    raw=vuln,
                ))
        return findings

    def run_cargo_audit(self) -> List[Finding]:
        if not (self.root / "Cargo.lock").exists():
            return []
        if not self._has_tool("cargo-audit"):
            return []
        rc, out, err = self.run_command(["cargo", "audit", "--json"])
        if rc not in (0, 1):
            return []
        return self._parse_cargo_audit_json(out)

    def _parse_cargo_audit_json(self, text: str) -> List[Finding]:
        findings: List[Finding] = []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return findings
        for vuln in data.get("vulnerabilities", {}).get("list", []):
            adv = vuln.get("advisory", {})
            pkg = vuln.get("package", {})
            findings.append(Finding(
                rule_id=adv.get("id", "RUSTSEC-???"),
                tool="cargo-audit",
                category="dependencies",
                severity=normalize_severity(adv.get("cvss", {}).get("severity", "medium"), "cargo_audit") if adv.get("cvss") else "high",
                confidence="high",
                message=adv.get("title", ""),
                locations=[FindingLocation(uri="Cargo.toml", start_line=1)],
                dependency_name=pkg.get("name"),
                dependency_version=pkg.get("version"),
                properties={"categories": adv.get("categories", [])},
                raw=vuln,
            ))
        return findings

    # ── Container Scanning ────────

    def run_trivy_config(self) -> List[Finding]:
        if not self._has_tool("trivy"):
            return []
        rc, out, err = self.run_command([
            "trivy", "config", "--format", "json", "--output", "/tmp/trivy_config.json", "."
        ])
        if rc not in (0, 1):
            return []
        try:
            text = Path("/tmp/trivy_config.json").read_text()
            data = json.loads(text)
        except Exception:
            return []
        return self._parse_trivy_json(data, "trivy-config")

    def run_trivy_image(self, image: Optional[str] = None) -> List[Finding]:
        if not self._has_tool("trivy"):
            return []
        target = image or self._infer_docker_image()
        if not target:
            return []
        rc, out, err = self.run_command([
            "trivy", "image", "--format", "json", "--output", "/tmp/trivy_image.json",
            "--severity", "HIGH,CRITICAL,MEDIUM,LOW", target
        ])
        if rc not in (0, 1):
            return []
        try:
            text = Path("/tmp/trivy_image.json").read_text()
            data = json.loads(text)
        except Exception:
            return []
        return self._parse_trivy_json(data, "trivy-image")

    def _infer_docker_image(self) -> Optional[str]:
        # Attempt to read image name from CI env or fall back
        return os.environ.get("SCAN_IMAGE") or None

    def _parse_trivy_json(self, data: Dict, tool_name: str) -> List[Finding]:
        findings: List[Finding] = []
        for result in data.get("Results", []):
            for vuln in result.get("Misconfigurations", result.get("Vulnerabilities", [])):
                is_misconfig = "Misconfigurations" in result
                loc = FindingLocation(
                    uri=result.get("Target", "Dockerfile"),
                    start_line=vuln.get("CauseMetadata", {}).get("StartLine", 1) if is_misconfig else 1,
                )
                sev = normalize_severity(vuln.get("Severity", "unknown"), "trivy")
                findings.append(Finding(
                    rule_id=vuln.get("ID", vuln.get("CheckID", "TRIVY-???")),
                    tool=tool_name,
                    category="containers" if not is_misconfig else "infrastructure",
                    severity=sev,
                    confidence="high",
                    message=vuln.get("Title", vuln.get("Description", "")),
                    locations=[loc],
                    cve_id=vuln.get("VulnerabilityID") if not is_misconfig else None,
                    cvss_score=vuln.get("CVSS", {}).get("nvd", {}).get("V3Score") if not is_misconfig else None,
                    fix_available=bool(vuln.get("FixedVersion")),
                    fix_version=vuln.get("FixedVersion"),
                    dependency_name=vuln.get("PkgName"),
                    dependency_version=vuln.get("InstalledVersion"),
                    raw=vuln,
                ))
        return findings

    # ── Infrastructure Scanning ───

    def run_checkov(self) -> List[Finding]:
        if not self._has_tool("checkov"):
            return []
        rc, out, err = self.run_command([
            "checkov", "-d", ".", "--output", "json", "--soft-fail"
        ])
        if rc not in (0, 1):
            return []
        return self._parse_checkov_json(out)

    def _parse_checkov_json(self, text: str) -> List[Finding]:
        findings: List[Finding] = []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return findings
        for check_type, files in data.items():
            if not isinstance(files, dict):
                continue
            for fpath, file_results in files.items():
                for r in file_results.get("failed_checks", []):
                    loc = FindingLocation(
                        uri=fpath,
                        start_line=r.get("file_line_range", [1, 1])[0],
                        end_line=r.get("file_line_range", [1, 1])[1],
                    )
                    findings.append(Finding(
                        rule_id=r.get("check_id", "CKV-???"),
                        tool="checkov",
                        category="infrastructure",
                        severity=normalize_severity(r.get("severity", "medium"), "checkov"),
                        confidence="medium",
                        message=r.get("check_name", ""),
                        locations=[loc],
                        raw=r,
                    ))
        return findings

    def run_tfsec(self) -> List[Finding]:
        if not self._has_tool("tfsec"):
            return []
        rc, out, err = self.run_command([
            "tfsec", "--format", "json", "--out", "/tmp/tfsec.json", "."
        ])
        if rc not in (0, 1):
            return []
        try:
            text = Path("/tmp/tfsec.json").read_text()
            data = json.loads(text)
        except Exception:
            return []
        return self._parse_tfsec_json(data)

    def _parse_tfsec_json(self, data: Dict) -> List[Finding]:
        findings: List[Finding] = []
        for r in data.get("results", []):
            loc = FindingLocation(
                uri=r.get("location", {}).get("filename", ""),
                start_line=r.get("location", {}).get("start_line", 1),
                end_line=r.get("location", {}).get("end_line"),
            )
            findings.append(Finding(
                rule_id=r.get("rule_id", ""),
                tool="tfsec",
                category="infrastructure",
                severity=normalize_severity(r.get("severity", "medium"), "tfsec"),
                confidence="high",
                message=r.get("description", ""),
                locations=[loc],
                raw=r,
            ))
        return findings


# ───────────────────────────────
# Orchestrator
# ───────────────────────────────

class SecurityOrchestrator:
    def __init__(self, root: Path, args: argparse.Namespace):
        self.root = root
        self.args = args
        self.discovery = ProjectDiscovery(root)
        self.runner = ToolRunner(root, self.discovery)

    def collect_findings(self) -> List[Finding]:
        findings: List[Finding] = []
        cats = self._selected_categories()

        print(f"[info] Detected project types: {', '.join(k for k,v in self.discovery.detected.items() if v)}")
        print(f"[info] Running categories: {', '.join(cats)}")

        if "sast" in cats:
            print("[scan] Running SAST scanners...")
            findings.extend(self.runner.run_semgrep())
            if self.discovery.detected.get("python"):
                findings.extend(self.runner.run_bandit())
            if self.discovery.detected.get("go"):
                findings.extend(self.runner.run_gosec())
            if self.discovery.detected.get("javascript") or self.discovery.detected.get("typescript"):
                findings.extend(self.runner.run_eslint_security())

        if "secrets" in cats:
            print("[scan] Running secret scanners...")
            findings.extend(self.runner.run_gitleaks())
            findings.extend(self.runner.run_trufflehog())

        if "dependencies" in cats:
            print("[scan] Running dependency scanners...")
            if self.discovery.detected.get("javascript") or self.discovery.detected.get("typescript"):
                findings.extend(self.runner.run_npm_audit())
            if self.discovery.detected.get("python"):
                findings.extend(self.runner.run_pip_audit())
            if self.discovery.detected.get("rust"):
                findings.extend(self.runner.run_cargo_audit())

        if "containers" in cats and self.discovery.has_containers():
            print("[scan] Running container scanners...")
            findings.extend(self.runner.run_trivy_config())
            if self.args.image:
                findings.extend(self.runner.run_trivy_image(self.args.image))

        if "infrastructure" in cats and self.discovery.has_infrastructure():
            print("[scan] Running infrastructure scanners...")
            findings.extend(self.runner.run_checkov())
            if self.discovery.detected.get("terraform"):
                findings.extend(self.runner.run_tfsec())

        return findings

    def _selected_categories(self) -> List[str]:
        if self.args.all:
            return ["sast", "secrets", "dependencies", "containers", "infrastructure"]
        cats = []
        if self.args.sast:
            cats.append("sast")
        if self.args.secrets:
            cats.append("secrets")
        if self.args.dependencies:
            cats.append("dependencies")
        if self.args.containers:
            cats.append("containers")
        if self.args.infrastructure:
            cats.append("infrastructure")
        if not cats:
            # Default to SAST + secrets if nothing specified
            cats = ["sast", "secrets"]
        return cats

    def deduplicate(self, findings: List[Finding]) -> List[Finding]:
        dedup: Dict[str, Finding] = {}
        for f in findings:
            key = f.dedup_key()
            existing = dedup.get(key)
            if existing is None:
                dedup[key] = f
            else:
                # Keep the one with higher severity or higher confidence
                if severity_rank(f.severity) > severity_rank(existing.severity):
                    dedup[key] = f
                elif severity_rank(f.severity) == severity_rank(existing.severity):
                    if f.confidence == "high" and existing.confidence != "high":
                        dedup[key] = f
                    elif f.fix_available and not existing.fix_available:
                        dedup[key] = f
        return list(dedup.values())

    def apply_fail_gate(self, findings: List[Finding]) -> bool:
        if not self.args.fail_on:
            return True
        fail_levels = [s.strip().lower() for s in self.args.fail_on.split(",")]
        worst = 0
        for f in findings:
            rank = severity_rank(f.severity)
            if f.severity.lower() in fail_levels:
                worst = max(worst, rank)
        if worst > 0:
            print(f"[fail] Found findings at or above fail-on threshold: {self.args.fail_on}")
            return False
        return True


# ───────────────────────────────
# Exporters
# ───────────────────────────────

class SarifExporter:
    SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"

    @classmethod
    def export(cls, findings: List[Finding], root: Path) -> Dict[str, Any]:
        runs: List[Dict[str, Any]] = []
        tools = {}
        for f in findings:
            tools.setdefault(f.tool, []).append(f)

        for tool_name, tool_findings in tools.items():
            rules: List[Dict[str, Any]] = []
            rule_indices: Dict[str, int] = {}
            results: List[Dict[str, Any]] = []

            for f in tool_findings:
                if f.rule_id not in rule_indices:
                    rule_indices[f.rule_id] = len(rules)
                    rules.append({
                        "id": f.rule_id,
                        "name": f.rule_id,
                        "shortDescription": {"text": f.message[:120]},
                        "fullDescription": {"text": f.message},
                        "properties": {
                            "tags": [f.category, f"external/cwe/{f.cwe_id}"] if f.cwe_id else [f.category],
                            "security-severity": str(f.cvss_score or (8.0 if f.severity == "high" else 5.0)),
                            "precision": f.confidence,
                        }
                    })

                sarif_level = {"critical": "error", "high": "error", "medium": "warning", "low": "warning", "info": "note"}.get(f.severity, "warning")
                location = {}
                if f.locations:
                    loc = f.locations[0]
                    location = {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": loc.uri,
                                "uriBaseId": "%SRCROOT%"
                            },
                            "region": {
                                "startLine": loc.start_line,
                                "startColumn": loc.start_column,
                                "endLine": loc.end_line,
                                "endColumn": loc.end_column,
                            }
                        }
                    }
                    if loc.snippet:
                        location["physicalLocation"]["region"]["snippet"] = {"text": loc.snippet}

                result = {
                    "ruleId": f.rule_id,
                    "ruleIndex": rule_indices[f.rule_id],
                    "level": sarif_level,
                    "message": {"text": f.message},
                    "locations": [location] if location else [],
                    "properties": {
                        "unifiedSeverity": f.severity,
                        "toolName": f.tool,
                        "category": f.category,
                        "cvssScore": f.cvss_score,
                        "cweId": f.cwe_id,
                        "cveId": f.cve_id,
                        "fixAvailable": f.fix_available,
                        "fixVersion": f.fix_version,
                        "dependencyName": f.dependency_name,
                        "dependencyVersion": f.dependency_version,
                        "transitive": f.transitive,
                        "confidence": f.confidence,
                    }
                }
                results.append(result)

            runs.append({
                "tool": {
                    "driver": {
                        "name": tool_name,
                        "version": "1.0.0",
                        "informationUri": "https://github.com/org/security-scanner"
                    }
                },
                "results": results,
                "taxonomies": [{
                    "name": "CWE",
                    "version": "4.13",
                    "taxa": [{"id": r["id"], "name": r["id"]} for r in rules]
                }] if any(f.cwe_id for f in tool_findings) else []
            })

        return {
            "$schema": cls.SCHEMA,
            "version": "2.1.0",
            "runs": runs
        }


class JsonExporter:
    @classmethod
    def export(cls, findings: List[Finding], root: Path) -> Dict[str, Any]:
        return {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "projectRoot": str(root),
            "summary": {
                "total": len(findings),
                "bySeverity": cls._count_by(findings, "severity"),
                "byCategory": cls._count_by(findings, "category"),
                "byTool": cls._count_by(findings, "tool"),
            },
            "findings": [asdict(f) for f in findings],
        }

    @staticmethod
    def _count_by(findings: List[Finding], attr: str) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for f in findings:
            val = getattr(f, attr)
            counts[val] = counts.get(val, 0) + 1
        return counts


class MarkdownExporter:
    @classmethod
    def export(cls, findings: List[Finding], root: Path) -> str:
        lines = [
            "# Security Scan Report",
            "",
            f"- **Project**: `{root}`",
            f"- **Generated**: {datetime.now(timezone.utc).isoformat()}",
            f"- **Total Findings**: {len(findings)}",
            "",
            "## Summary",
            "",
            "| Severity | Count |",
            "|----------|-------|",
        ]
        sev_counts = JsonExporter._count_by(findings, "severity")
        for sev in ("critical", "high", "medium", "low", "info"):
            if sev in sev_counts:
                lines.append(f"| {sev.capitalize()} | {sev_counts[sev]} |")
        lines.append("")
        lines.append("## Findings")
        lines.append("")

        for f in sorted(findings, key=lambda x: (-severity_rank(x.severity), x.tool, x.rule_id)):
            lines.append(f"### {f.rule_id} ({f.severity.upper()})")
            lines.append(f"- **Tool**: {f.tool}")
            lines.append(f"- **Category**: {f.category}")
            lines.append(f"- **Message**: {f.message}")
            if f.locations:
                loc = f.locations[0]
                lines.append(f"- **Location**: `{loc.uri}:{loc.start_line}`")
            if f.cve_id:
                lines.append(f"- **CVE**: {f.cve_id}")
            if f.cwe_id:
                lines.append(f"- **CWE**: {f.cwe_id}")
            if f.fix_available:
                lines.append(f"- **Fix**: Upgrade to {f.fix_version or 'patched version'}")
            lines.append("")

        return "\n".join(lines)


class HtmlExporter:
    @classmethod
    def export(cls, findings: List[Finding], root: Path) -> str:
        sev_counts = JsonExporter._count_by(findings, "severity")
        rows = []
        for f in sorted(findings, key=lambda x: (-severity_rank(x.severity), x.tool, x.rule_id)):
            loc = f.locations[0] if f.locations else FindingLocation(uri="", start_line=0)
            rows.append(
                f"<tr class='{f.severity}'>"
                f"<td>{f.severity.upper()}</td>"
                f"<td>{f.tool}</td>"
                f"<td>{f.category}</td>"
                f"<td><code>{f.rule_id}</code></td>"
                f"<td>{cls._escape(f.message)}</td>"
                f"<td><code>{cls._escape(loc.uri)}:{loc.start_line}</code></td>"
                f"<td>{f.cve_id or '-'}</td>"
                f"<td>{'Yes' if f.fix_available else 'No'}</td>"
                f"</tr>"
            )

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Security Scan Report</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
  h1 {{ font-size: 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
  th, td {{ border: 1px solid #ccc; padding: 0.5rem; text-align: left; font-size: 0.9rem; }}
  th {{ background: #f4f4f4; }}
  .critical {{ background: #ffe6e6; }}
  .high {{ background: #fff0e6; }}
  .medium {{ background: #ffffe6; }}
  .low {{ background: #f0f8ff; }}
  .info {{ background: #f4f4f4; }}
  .summary {{ display: flex; gap: 1rem; margin-bottom: 1rem; }}
  .badge {{ padding: 0.4rem 0.8rem; border-radius: 0.4rem; font-weight: 600; }}
</style>
</head>
<body>
<h1>Security Scan Report</h1>
<p><strong>Project:</strong> <code>{root}</code></p>
<p><strong>Generated:</strong> {datetime.now(timezone.utc).isoformat()}</p>
<div class="summary">
  <span class="badge critical">Critical: {sev_counts.get('critical', 0)}</span>
  <span class="badge high">High: {sev_counts.get('high', 0)}</span>
  <span class="badge medium">Medium: {sev_counts.get('medium', 0)}</span>
  <span class="badge low">Low: {sev_counts.get('low', 0)}</span>
  <span class="badge info">Info: {sev_counts.get('info', 0)}</span>
</div>
<table>
<thead>
  <tr><th>Severity</th><th>Tool</th><th>Category</th><th>Rule</th><th>Message</th><th>Location</th><th>CVE</th><th>Fix</th></tr>
</thead>
<tbody>
  {'\n'.join(rows)}
</tbody>
</table>
</body>
</html>"""

    @staticmethod
    def _escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ───────────────────────────────
# CLI
# ───────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Orchestrate multi-tool security scans with unified reporting."
    )
    p.add_argument("--root", default=".", help="Project root directory to scan")
    p.add_argument("--all", action="store_true", help="Run all scan categories")
    p.add_argument("--sast", action="store_true", help="Run SAST scanners")
    p.add_argument("--secrets", action="store_true", help="Run secret scanners")
    p.add_argument("--dependencies", action="store_true", help="Run dependency scanners")
    p.add_argument("--containers", action="store_true", help="Run container scanners")
    p.add_argument("--infrastructure", action="store_true", help="Run infrastructure scanners")
    p.add_argument("--image", help="Container image tag to scan (for --containers)")
    p.add_argument("--output-format", choices=["sarif", "json", "html", "markdown"], default="json",
                   help="Output format")
    p.add_argument("--output-file", help="Write output to file instead of stdout")
    p.add_argument("--fail-on", help="Comma-separated severities to fail on (e.g., critical,high)")
    p.add_argument("--no-dedup", action="store_true", help="Disable deduplication")
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = Path(args.root).resolve()

    if not root.exists():
        print(f"[error] Root path does not exist: {root}", file=sys.stderr)
        return 2

    orchestrator = SecurityOrchestrator(root, args)
    findings = orchestrator.collect_findings()

    if not args.no_dedup:
        before = len(findings)
        findings = orchestrator.deduplicate(findings)
        after = len(findings)
        if before != after:
            print(f"[info] Deduplicated {before - after} redundant findings")

    # Severity summary
    counts = JsonExporter._count_by(findings, "severity")
    print(f"[summary] Total findings: {len(findings)}")
    for sev in ("critical", "high", "medium", "low", "info"):
        if sev in counts:
            print(f"[summary]   {sev.capitalize()}: {counts[sev]}")

    # Export
    if args.output_format == "sarif":
        output = json.dumps(SarifExporter.export(findings, root), indent=2)
    elif args.output_format == "json":
        output = json.dumps(JsonExporter.export(findings, root), indent=2)
    elif args.output_format == "html":
        output = HtmlExporter.export(findings, root)
    else:
        output = MarkdownExporter.export(findings, root)

    if args.output_file:
        Path(args.output_file).write_text(output, encoding="utf-8")
        print(f"[info] Wrote {args.output_format} report to {args.output_file}")
    else:
        print(output)

    # Fail gate
    if not orchestrator.apply_fail_gate(findings):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
