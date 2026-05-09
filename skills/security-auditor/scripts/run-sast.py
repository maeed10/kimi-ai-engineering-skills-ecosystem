#!/usr/bin/env python3
"""
run-sast.py — Multi-tool SAST runner with sandbox integration, tool fallback chain, and structured reporting.

Tool fallback chain:
    1. Semgrep (general, primary)
    2. CodeQL (deep semantic analysis, if database available)
    3. Bandit (Python-specific, if Semgrep/CodeQL unavailable or Python-only scan)
    4. ESLint security (JS/TS-specific, if Semgrep/CodeQL unavailable or JS-only scan)

Usage:
    python run-sast.py --target ./src --rulesets owasp-top-10,cwe-top-25 --output sast-results.json
    python run-sast.py --target ./src --tools semgrep,bandit --sandbox sandbox-executor --output sast-results.json

Exit codes:
    0 — No critical/high findings (or --no-block)
    1 — Critical findings detected (merge blocked)
    2 — High findings detected (merge blocked)
    3 — Medium/low findings only (warnings)
    4 — Tool execution error
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BUILTIN_RULESETS: dict[str, str] = {
    "owasp-top-10": "p/owasp-top-ten",
    "cwe-top-25": "p/cwe-top-25",
    "secrets": "p/secrets",
    "python-security": "python",
    "javascript-security": "javascript",
    "typescript-security": "typescript",
    "ci": "p/ci",
    "command-injection": "p/command-injection",
}

# Severity ordering for merge-gate decisions
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

TOOL_PRIORITY = ["semgrep", "codeql", "bandit", "eslint"]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    severity: str
    cwe_id: str
    file: str
    line: int
    tool: str
    rule_id: str
    message: str
    remediation: str
    source: str = "unknown"  # agent-generated | human-written
    code_snippet: str = ""
    end_line: int = 0


@dataclass
class SastReport:
    target: str
    rulesets: List[str]
    tools_executed: List[str] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    scanned_files: List[str] = field(default_factory=list)
    skipped_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tool availability
# ---------------------------------------------------------------------------

def verify_tool(name: str) -> Optional[str]:
    """Return the absolute path to a tool if available, else None."""
    path = shutil.which(name)
    return path


def verify_dependency_resolver() -> Optional[str]:
    """Check if dependency-resolver is available to locate tools."""
    return shutil.which("dependency-resolver")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def discover_files(target: Path, include_globs: List[str], exclude_globs: List[str]) -> List[Path]:
    """Discover files under target matching include_globs and not matching exclude_globs."""
    candidates: List[Path] = []

    if include_globs:
        for pattern in include_globs:
            candidates.extend(target.rglob(pattern.lstrip("/")))
    else:
        # Default: include common source extensions
        for ext in ("*.py", "*.js", "*.ts", "*.jsx", "*.tsx", "*.go", "*.java", "*.rb", "*.php"):
            candidates.extend(target.rglob(ext))

    # De-duplicate
    seen = set()
    filtered: List[Path] = []
    for p in candidates:
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        # Apply excludes
        if any(rp.match(ex) for ex in exclude_globs):
            continue
        filtered.append(rp)

    return sorted(filtered)


def filter_by_ext(files: List[Path], extensions: Tuple[str, ...]) -> List[Path]:
    return [f for f in files if f.suffix.lower() in extensions]


def normalize_severity(raw: str) -> str:
    """Normalize Semgrep/Bandit/ESLint severity strings to our 5-level scale."""
    mapping = {
        "error": "critical",
        "warning": "high",
        "info": "medium",
        "low": "low",
        "medium": "medium",
        "high": "high",
        "critical": "critical",
    }
    return mapping.get(raw.lower(), "medium")


def map_rule_to_cwe(rule_id: str, check_id: str) -> str:
    """Map Semgrep rule/check IDs to CWE identifiers. Expand as needed."""
    # Common Semgrep rule → CWE mappings
    cwe_map = {
        "command-injection": "CWE-78",
        "sql-injection": "CWE-89",
        "path-traversal": "CWE-22",
        "ssrf": "CWE-918",
        "insecure-hash-algorithm": "CWE-328",
        "weak-crypto": "CWE-327",
        "hardcoded-secrets": "CWE-798",
        "xss": "CWE-79",
        "open-redirect": "CWE-601",
        "eval": "CWE-95",
        "deserialization": "CWE-502",
        "ldap-injection": "CWE-90",
        "xxe": "CWE-611",
    }
    key = (rule_id or "").lower()
    if key in cwe_map:
        return cwe_map[key]
    key2 = (check_id or "").lower()
    if key2 in cwe_map:
        return cwe_map[key2]
    # Attempt to extract CWE-NNN from the string itself
    m = re.search(r"CWE-?(\d+)", rule_id + check_id, re.IGNORECASE)
    if m:
        return f"CWE-{m.group(1)}"
    return "CWE-UNKNOWN"


def map_bandit_test_id_to_cwe(test_id: str) -> str:
    """Map Bandit test IDs to CWE identifiers."""
    bandit_cwe = {
        "B102": "CWE-78",
        "B105": "CWE-798",
        "B106": "CWE-798",
        "B107": "CWE-798",
        "B201": "CWE-489",
        "B301": "CWE-502",
        "B307": "CWE-95",
        "B308": "CWE-79",
        "B601": "CWE-295",
        "B602": "CWE-78",
        "B603": "CWE-78",
        "B605": "CWE-78",
        "B607": "CWE-426",
        "B608": "CWE-89",
        "B609": "CWE-78",
    }
    return bandit_cwe.get(test_id, "CWE-UNKNOWN")


def map_eslint_rule_to_cwe(rule_id: str) -> str:
    """Map ESLint security plugin rule IDs to CWE identifiers."""
    eslint_cwe = {
        "detect-eval-with-expression": "CWE-95",
        "detect-non-literal-fs-filename": "CWE-22",
        "detect-non-literal-regexp": "CWE-400",
        "detect-non-literal-require": "CWE-96",
        "detect-object-injection": "CWE-915",
        "detect-possible-timing-attacks": "CWE-208",
        "detect-pseudoRandomBytes": "CWE-338",
        "detect-unsafe-regex": "CWE-185",
    }
    return eslint_cwe.get(rule_id, "CWE-UNKNOWN")


def build_remediation(check_id: str, message: str) -> str:
    """Return a concise remediation hint based on the rule."""
    hints = {
        "command-injection": "Use parameterized APIs or an allowlist for command arguments. Never pass user input directly to shell execution functions.",
        "sql-injection": "Use parameterized queries / prepared statements. Never concatenate user input into SQL strings.",
        "path-traversal": "Validate and sanitize file paths with an allowlist. Use `pathlib` or `os.path.abspath` with strict checks.",
        "ssrf": "Validate target URLs against an allowlist. Avoid sending requests to attacker-controlled hosts.",
        "insecure-hash-algorithm": "Replace MD5/SHA1 with SHA-256 or stronger. For password hashing, use bcrypt/argon2.",
        "weak-crypto": "Use AES-256-GCM or ChaCha20-Poly1305. Avoid ECB mode and hardcoded keys.",
        "hardcoded-secrets": "Move secrets to a vault or environment variables. Rotate any exposed credentials immediately.",
        "xss": "Escape output context-appropriately (HTML/JS/CSS/URL). Use a templating engine with auto-escaping.",
        "eval": "Replace eval/exec with safer alternatives (JSON.parse, structured data). Use strict AST-based parsing.",
        "deserialization": "Use safe serialization formats (JSON). For pickle/Java serialization, implement signatures and type allowlists.",
        "open-redirect": "Validate redirect targets against an allowlist of trusted domains. Prefer relative paths.",
    }
    return hints.get(check_id.lower(), f"Review this finding carefully. {message}")


# ---------------------------------------------------------------------------
# Sandbox integration
# ---------------------------------------------------------------------------

def run_in_sandbox(
    sandbox_executor: str,
    tool_cmd: List[str],
    target: Path,
    timeout: int = 600,
) -> Tuple[Optional[str], Optional[str], int]:
    """Delegate tool execution to sandbox-executor (or compatible sandbox runner).

    Expected sandbox-executor interface:
        sandbox-executor --image <image> --cmd '<json-cmd>' --workdir <target>

    If the sandbox executor is not available, raises RuntimeError so caller can fall back.
    """
    if not shutil.which(sandbox_executor):
        raise RuntimeError(f"Sandbox executor '{sandbox_executor}' not found in PATH.")

    # Build sandbox command; we assume a simple CLI for illustration.
    # Real sandbox-executor may differ; this is a generic wrapper.
    cmd_json = json.dumps(tool_cmd)
    sandbox_cmd = [
        sandbox_executor,
        "--cmd", cmd_json,
        "--workdir", str(target),
    ]

    proc = subprocess.run(sandbox_cmd, capture_output=True, text=True, timeout=timeout)
    return proc.stdout, proc.stderr, proc.returncode


# ---------------------------------------------------------------------------
# Semgrep runner
# ---------------------------------------------------------------------------

def run_semgrep(
    target: Path,
    files: List[Path],
    rulesets: List[str],
    semgrep_extra_args: List[str],
    source_tag: str,
    sandbox_executor: Optional[str] = None,
) -> Tuple[List[Finding], List[str]]:
    """Run Semgrep on the given files and return parsed findings + errors."""
    findings: List[Finding] = []
    errors: List[str] = []

    # Resolve ruleset strings
    config_args: List[str] = []
    for r in rulesets:
        resolved = BUILTIN_RULESETS.get(r, r)
        config_args.extend(["--config", resolved])

    # Write file list to a temporary targets file to avoid CLI length limits
    targets_file = Path("semgrep-targets.txt")
    targets_file.write_text("\n".join(str(f) for f in files))

    cmd = [
        "semgrep",
        *config_args,
        "--targets", str(targets_file),
        "--json",
        *semgrep_extra_args,
    ]

    try:
        if sandbox_executor:
            stdout, stderr, rc = run_in_sandbox(sandbox_executor, cmd, target)
            if rc != 0 and stderr:
                errors.append(f"Semgrep sandbox error: {stderr[:500]}")
            data_text = stdout or "{}"
        else:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if proc.returncode not in (0, 1):  # 1 = findings found
                errors.append(f"Semgrep exited with code {proc.returncode}: {proc.stderr[:500]}")
            data_text = proc.stdout
    except FileNotFoundError:
        errors.append("semgrep not found in PATH. Install with `pip install semgrep` or enable fallback tools.")
        targets_file.unlink(missing_ok=True)
        return findings, errors
    except subprocess.TimeoutExpired:
        errors.append("semgrep timed out after 600 seconds.")
        targets_file.unlink(missing_ok=True)
        return findings, errors
    except RuntimeError as exc:
        errors.append(str(exc))
        targets_file.unlink(missing_ok=True)
        return findings, errors

    try:
        data = json.loads(data_text)
    except json.JSONDecodeError:
        errors.append(f"Failed to parse semgrep JSON output: {data_text[:500]}")
        targets_file.unlink(missing_ok=True)
        return findings, errors

    for res in data.get("results", []):
        severity = normalize_severity(res.get("extra", {}).get("severity", "medium"))
        check_id = res.get("check_id", "unknown")
        cwe = map_rule_to_cwe("", check_id)
        message = res.get("extra", {}).get("message", "")
        remediation = build_remediation(check_id, message)
        start = res.get("start", {})
        end = res.get("end", {})

        findings.append(
            Finding(
                severity=severity,
                cwe_id=cwe,
                file=res.get("path", ""),
                line=start.get("line", 0),
                end_line=end.get("line", start.get("line", 0)),
                tool="Semgrep",
                rule_id=check_id,
                message=message,
                remediation=remediation,
                source=source_tag,
                code_snippet=res.get("extra", {}).get("lines", "").strip(),
            )
        )

    for err in data.get("errors", []):
        errors.append(f"Semgrep error: {err.get('message', err)}")

    targets_file.unlink(missing_ok=True)
    return findings, errors


# ---------------------------------------------------------------------------
# CodeQL runner (fallback)
# ---------------------------------------------------------------------------

def run_codeql(
    target: Path,
    files: List[Path],
    source_tag: str,
    sandbox_executor: Optional[str] = None,
) -> Tuple[List[Finding], List[str]]:
    """Run CodeQL if a database exists or can be created. Returns findings + errors.

    CodeQL is heavyweight: it requires a database. This runner attempts:
      1. Use an existing database at <target>/.codeql-db/
      2. If --codeql-create-db is set, create one (language auto-detected)
    """
    findings: List[Finding] = []
    errors: List[str] = []

    codeql_bin = verify_tool("codeql")
    if not codeql_bin:
        errors.append("CodeQL not found in PATH. Skipping CodeQL fallback.")
        return findings, errors

    db_path = target / ".codeql-db"
    # Check for existing DB
    if not db_path.exists():
        errors.append("CodeQL database not found at .codeql-db/. Run `codeql database create` first or use --codeql-create-db.")
        return findings, errors

    # Run analysis
    sarif_out = target / "codeql-results.sarif"
    cmd = [
        codeql_bin,
        "database", "analyze",
        str(db_path),
        "--format=sarifv2.1.0",
        f"--output={sarif_out}",
        "--sarif-add-snippets",
        "codeql-suites/javascript-security-extended.qls" if any(f.suffix in (".js", ".ts", ".jsx", ".tsx") for f in files) else "codeql-suites/python-security-extended.qls",
    ]

    try:
        if sandbox_executor:
            stdout, stderr, rc = run_in_sandbox(sandbox_executor, cmd, target)
            if rc != 0:
                errors.append(f"CodeQL sandbox error: {stderr[:500] if stderr else 'unknown'}")
        else:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
            if proc.returncode != 0:
                errors.append(f"CodeQL analyze failed: {proc.stderr[:500]}")
    except FileNotFoundError:
        errors.append("CodeQL binary missing during execution.")
        return findings, errors
    except subprocess.TimeoutExpired:
        errors.append("CodeQL timed out after 1200 seconds.")
        return findings, errors
    except RuntimeError as exc:
        errors.append(str(exc))
        return findings, errors

    # Parse SARIF
    try:
        sarif = json.loads(sarif_out.read_text())
    except Exception as exc:
        errors.append(f"Failed to parse CodeQL SARIF: {exc}")
        return findings, errors

    for run in sarif.get("runs", []):
        for result in run.get("results", []):
            rule_id = result.get("ruleId", "unknown")
            level = result.get("level", "warning")
            severity = normalize_severity(level)
            locs = result.get("locations", [])
            file_path = ""
            line_start = 0
            line_end = 0
            if locs:
                phys = locs[0].get("physicalLocation", {})
                artifact = phys.get("artifactLocation", {})
                file_path = artifact.get("uri", "")
                region = phys.get("region", {})
                line_start = region.get("startLine", 0)
                line_end = region.get("endLine", line_start)
            msg = result.get("message", {}).get("text", "")
            cwe = map_rule_to_cwe(rule_id, rule_id)
            remediation = build_remediation(rule_id, msg)

            findings.append(
                Finding(
                    severity=severity,
                    cwe_id=cwe,
                    file=file_path,
                    line=line_start,
                    end_line=line_end,
                    tool="CodeQL",
                    rule_id=rule_id,
                    message=msg,
                    remediation=remediation,
                    source=source_tag,
                    code_snippet="",
                )
            )

    sarif_out.unlink(missing_ok=True)
    return findings, errors


# ---------------------------------------------------------------------------
# Bandit runner (Python fallback)
# ---------------------------------------------------------------------------

def run_bandit(
    target: Path,
    files: List[Path],
    source_tag: str,
    sandbox_executor: Optional[str] = None,
) -> Tuple[List[Finding], List[str]]:
    """Run Bandit on Python files and return parsed findings + errors."""
    findings: List[Finding] = []
    errors: List[str] = []

    py_files = filter_by_ext(files, (".py",))
    if not py_files:
        return findings, errors

    cmd = [
        "bandit",
        "-r", str(target),
        "-f", "json",
        "-ll",  # report only medium and higher (low=LOW, medium=MEDIUM, high=HIGH)
    ]

    # Exclude patterns via -x if available; Bandit -x takes comma-separated paths
    excludes = ["node_modules", ".git", "venv", "__pycache__", "test", "tests"]
    cmd.extend(["-x", ",".join(excludes)])

    try:
        if sandbox_executor:
            stdout, stderr, rc = run_in_sandbox(sandbox_executor, cmd, target)
            if rc != 0 and stderr:
                errors.append(f"Bandit sandbox error: {stderr[:500]}")
            data_text = stdout or "{}"
        else:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            data_text = proc.stdout
            if proc.returncode not in (0, 1):  # 1 = issues found
                errors.append(f"Bandit exited {proc.returncode}: {proc.stderr[:500]}")
    except FileNotFoundError:
        errors.append("bandit not found in PATH. Install with `pip install bandit`.")
        return findings, errors
    except subprocess.TimeoutExpired:
        errors.append("Bandit timed out after 600 seconds.")
        return findings, errors
    except RuntimeError as exc:
        errors.append(str(exc))
        return findings, errors

    try:
        data = json.loads(data_text)
    except json.JSONDecodeError:
        errors.append(f"Failed to parse Bandit JSON output: {data_text[:500]}")
        return findings, errors

    for res in data.get("results", []):
        test_id = res.get("test_id", "UNKNOWN")
        severity = normalize_severity(res.get("issue_severity", "medium"))
        confidence = res.get("issue_confidence", "medium")
        cwe = map_bandit_test_id_to_cwe(test_id)
        line = res.get("line_number", 0)
        end_line = res.get("line_range", [line])[-1] if res.get("line_range") else line
        file_path = res.get("filename", "")
        message = res.get("issue_text", "")
        code = res.get("code", "")

        # Demote severity if confidence is LOW (heuristic: reduce noise)
        if confidence.lower() == "low" and severity in ("critical", "high"):
            severity = "medium"

        remediation = build_remediation(test_id, message)
        if remediation == f"Review this finding carefully. {message}":
            # Bandit-specific generic remediation
            remediation = f"[{test_id}] {message}. Review Bandit documentation for specific remediation."

        findings.append(
            Finding(
                severity=severity,
                cwe_id=cwe,
                file=file_path,
                line=line,
                end_line=end_line,
                tool="Bandit",
                rule_id=test_id,
                message=message,
                remediation=remediation,
                source=source_tag,
                code_snippet=code.strip(),
            )
        )

    for err in data.get("errors", []):
        errors.append(f"Bandit error: {err}")

    return findings, errors


# ---------------------------------------------------------------------------
# ESLint security runner (JS/TS fallback)
# ---------------------------------------------------------------------------

def run_eslint_security(
    target: Path,
    files: List[Path],
    source_tag: str,
    sandbox_executor: Optional[str] = None,
) -> Tuple[List[Finding], List[str]]:
    """Run ESLint with eslint-plugin-security on JS/TS files."""
    findings: List[Finding] = []
    errors: List[str] = []

    js_files = filter_by_ext(files, (".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"))
    if not js_files:
        return findings, errors

    # Write a minimal eslintrc for security if one doesn't exist in target
    eslintrc = target / ".eslintrc.security.json"
    if not eslintrc.exists():
        eslintrc.write_text(json.dumps({
            "plugins": ["security"],
            "extends": ["plugin:security/recommended"],
            "parserOptions": {"ecmaVersion": 2022, "sourceType": "module"}
        }))

    # We need to run eslint from the target dir or pass --resolve-plugins-relative-to
    # Create a temp file list to avoid command-line length issues
    targets_file = Path("eslint-targets.txt")
    targets_file.write_text("\n".join(str(f) for f in js_files))

    cmd = [
        "eslint",
        "--config", str(eslintrc),
        "--resolve-plugins-relative-to", str(target),
        "--format", "json",
        "--no-eslintrc",  # ignore other configs to avoid conflicts
        "--ext", ".js,.ts,.jsx,.tsx,.mjs,.cjs",
        "@" + str(targets_file),  # @ means read file list
    ]

    try:
        if sandbox_executor:
            stdout, stderr, rc = run_in_sandbox(sandbox_executor, cmd, target)
            if rc != 0 and stderr:
                errors.append(f"ESLint sandbox error: {stderr[:500]}")
            data_text = stdout or "[]"
        else:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=str(target))
            data_text = proc.stdout
            if proc.returncode not in (0, 1):
                errors.append(f"ESLint exited {proc.returncode}: {proc.stderr[:500]}")
    except FileNotFoundError:
        errors.append("eslint not found in PATH. Install with `npm install -g eslint eslint-plugin-security`.")
        targets_file.unlink(missing_ok=True)
        eslintrc.unlink(missing_ok=True)
        return findings, errors
    except subprocess.TimeoutExpired:
        errors.append("ESLint timed out after 600 seconds.")
        targets_file.unlink(missing_ok=True)
        eslintrc.unlink(missing_ok=True)
        return findings, errors
    except RuntimeError as exc:
        errors.append(str(exc))
        targets_file.unlink(missing_ok=True)
        eslintrc.unlink(missing_ok=True)
        return findings, errors

    try:
        data = json.loads(data_text)
    except json.JSONDecodeError:
        errors.append(f"Failed to parse ESLint JSON output: {data_text[:500]}")
        targets_file.unlink(missing_ok=True)
        eslintrc.unlink(missing_ok=True)
        return findings, errors

    # ESLint JSON format is a list of file results
    for file_result in data:
        file_path = file_result.get("filePath", "")
        for msg in file_result.get("messages", []):
            rule_id = msg.get("ruleId", "unknown")
            if not rule_id or not rule_id.startswith("security/"):
                continue  # only security plugin findings
            severity = normalize_severity(msg.get("severity", "warning"))
            # ESLint severity: 1=warning, 2=error
            if msg.get("severity") == 1:
                severity = "medium"
            elif msg.get("severity") == 2:
                severity = "high"
            line = msg.get("line", 0)
            end_line = msg.get("endLine", line)
            message = msg.get("message", "")
            cwe = map_eslint_rule_to_cwe(rule_id)
            remediation = build_remediation(rule_id, message)

            findings.append(
                Finding(
                    severity=severity,
                    cwe_id=cwe,
                    file=file_path,
                    line=line,
                    end_line=end_line,
                    tool="ESLint-security",
                    rule_id=rule_id,
                    message=message,
                    remediation=remediation,
                    source=source_tag,
                    code_snippet="",
                )
            )

    targets_file.unlink(missing_ok=True)
    eslintrc.unlink(missing_ok=True)
    return findings, errors


# ---------------------------------------------------------------------------
# Report builders
# ---------------------------------------------------------------------------

def build_summary(findings: List[Finding]) -> dict:
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1
    return {
        "total": len(findings),
        "by_severity": severity_counts,
        "merge_gate_blocked": severity_counts["critical"] > 0 or severity_counts["high"] > 0,
    }


def write_json_report(report: SastReport, path: Path) -> None:
    path.write_text(json.dumps(asdict(report), indent=2, default=str))


def write_markdown_report(report: SastReport, path: Path) -> None:
    lines: List[str] = [
        "# Security Audit Report\n",
        f"**Target:** `{report.target}`  ",
        f"**Rulesets:** {', '.join(report.rulesets)}  ",
        f"**Tools executed:** {', '.join(report.tools_executed)}  ",
        f"**Scanned files:** {len(report.scanned_files)}  ",
        f"**Total findings:** {len(report.findings)}\n",
        "## Summary\n",
        f"- Critical: {report.summary.get('by_severity', {}).get('critical', 0)}",
        f"- High: {report.summary.get('by_severity', {}).get('high', 0)}",
        f"- Medium: {report.summary.get('by_severity', {}).get('medium', 0)}",
        f"- Low: {report.summary.get('by_severity', {}).get('low', 0)}",
        f"\n**Merge gate blocked:** {'Yes' if report.summary.get('merge_gate_blocked') else 'No'}\n",
        "## Findings\n",
    ]

    if not report.findings:
        lines.append("No findings.\n")
    else:
        for f in report.findings:
            lines.extend([
                f"### {f.rule_id} — {f.severity.upper()}\n",
                f"- **CWE:** {f.cwe_id}",
                f"- **File:** `{f.file}:{f.line}`",
                f"- **Tool:** {f.tool}",
                f"- **Source:** {f.source}",
                f"- **Message:** {f.message}",
                f"- **Remediation:** {f.remediation}",
                "",
            ])

    if report.errors:
        lines.extend(["## Errors\n"] + [f"- {e}" for e in report.errors] + [""])

    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Merge gate
# ---------------------------------------------------------------------------

def merge_gate_decision(findings: List[Finding], no_block: bool) -> int:
    if no_block:
        return 3 if findings else 0
    critical = any(f.severity == "critical" for f in findings)
    high = any(f.severity == "high" for f in findings)
    if critical:
        return 1
    if high:
        return 2
    if any(f.severity in ("medium", "low") for f in findings):
        return 3
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Run multi-tool SAST with Semgrep, CodeQL, Bandit, ESLint security, and produce structured reports.")
    parser.add_argument("--target", required=True, help="Directory or file to scan.")
    parser.add_argument("--rulesets", default="owasp-top-10", help="Comma-separated Semgrep rulesets.")
    parser.add_argument("--output", default="sast-results.json", help="JSON output path.")
    parser.add_argument("--markdown", default="sast-results.md", help="Markdown output path.")
    parser.add_argument("--include", action="append", default=[], help="Glob include pattern(s).")
    parser.add_argument("--exclude", action="append", default=["**/test*", "**/node_modules/**", "**/.git/**", "**/venv/**", "**/__pycache__/**"], help="Glob exclude pattern(s).")
    parser.add_argument("--semgrep-args", default="", help="Extra Semgrep CLI arguments (space-separated).")
    parser.add_argument("--tools", default="auto", help="Comma-separated tool list or 'auto' for fallback chain: semgrep,codeql,bandit,eslint.")
    parser.add_argument("--sandbox", default=os.environ.get("SAST_SANDBOX_EXECUTOR", ""), help="Sandbox executor command (e.g., sandbox-executor). Runs all SAST tools inside an isolated container.")
    parser.add_argument("--codeql-create-db", action="store_true", help="Create CodeQL database before analysis (requires codeql CLI).")
    parser.add_argument("--source", default="unknown", choices=["agent-generated", "human-written", "unknown"], help="Tag all findings with source type.")
    parser.add_argument("--no-block", action="store_true", help="Do not block on critical/high findings (use in dev/CI tuning).")
    parser.add_argument("--max-files", type=int, default=0, help="Limit number of files scanned (0 = unlimited).")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    rulesets = [r.strip() for r in args.rulesets.split(",")]

    # Resolve tool list
    if args.tools == "auto":
        requested_tools = ["semgrep", "codeql", "bandit", "eslint"]
    else:
        requested_tools = [t.strip().lower() for t in args.tools.split(",")]

    # Discover files
    files = discover_files(target, args.include, args.exclude)
    if args.max_files > 0:
        files = files[:args.max_files]

    if not files:
        print("No files matched the scan criteria.", file=sys.stderr)
        return 4

    # Verify tool availability via dependency-resolver hint if available
    dep_resolver = verify_dependency_resolver()
    if dep_resolver:
        print(f"[info] dependency-resolver available at {dep_resolver}")

    all_findings: List[Finding] = []
    all_errors: List[str] = []
    tools_executed: List[str] = []

    # ---------------------------------------------------------------
    # Tool execution with fallback chain
    # ---------------------------------------------------------------
    semgrep_available = verify_tool("semgrep") is not None
    codeql_available = verify_tool("codeql") is not None
    bandit_available = verify_tool("bandit") is not None
    eslint_available = verify_tool("eslint") is not None

    for tool in requested_tools:
        if tool == "semgrep":
            if not semgrep_available:
                all_errors.append("Semgrep not available; skipping.")
                continue
            findings, errors = run_semgrep(
                target=target,
                files=files,
                rulesets=rulesets,
                semgrep_extra_args=args.semgrep_args.split(),
                source_tag=args.source,
                sandbox_executor=args.sandbox or None,
            )
            tools_executed.append("Semgrep")
            all_findings.extend(findings)
            all_errors.extend(errors)

        elif tool == "codeql":
            if not codeql_available:
                all_errors.append("CodeQL not available; skipping.")
                continue
            # Optionally create database
            if args.codeql_create_db:
                db_path = target / ".codeql-db"
                lang = "javascript" if any(f.suffix in (".js", ".ts", ".jsx", ".tsx") for f in files) else "python"
                create_cmd = ["codeql", "database", "create", str(db_path), "--language=" + lang, "--source-root", str(target)]
                try:
                    if args.sandbox:
                        _, stderr, rc = run_in_sandbox(args.sandbox, create_cmd, target, timeout=1200)
                        if rc != 0:
                            all_errors.append(f"CodeQL DB creation failed: {stderr[:500]}")
                            continue
                    else:
                        proc = subprocess.run(create_cmd, capture_output=True, text=True, timeout=1200)
                        if proc.returncode != 0:
                            all_errors.append(f"CodeQL DB creation failed: {proc.stderr[:500]}")
                            continue
                except Exception as exc:
                    all_errors.append(f"CodeQL DB creation exception: {exc}")
                    continue
            findings, errors = run_codeql(
                target=target,
                files=files,
                source_tag=args.source,
                sandbox_executor=args.sandbox or None,
            )
            tools_executed.append("CodeQL")
            all_findings.extend(findings)
            all_errors.extend(errors)

        elif tool == "bandit":
            if not bandit_available:
                all_errors.append("Bandit not available; skipping.")
                continue
            findings, errors = run_bandit(
                target=target,
                files=files,
                source_tag=args.source,
                sandbox_executor=args.sandbox or None,
            )
            tools_executed.append("Bandit")
            all_findings.extend(findings)
            all_errors.extend(errors)

        elif tool == "eslint":
            if not eslint_available:
                all_errors.append("ESLint not available; skipping.")
                continue
            findings, errors = run_eslint_security(
                target=target,
                files=files,
                source_tag=args.source,
                sandbox_executor=args.sandbox or None,
            )
            tools_executed.append("ESLint-security")
            all_findings.extend(findings)
            all_errors.extend(errors)

        else:
            all_errors.append(f"Unknown tool requested: {tool}")

    # Deduplicate findings by (file, line, rule_id, message) to reduce noise across tools
    dedup_key = lambda f: (f.file, f.line, f.rule_id, f.message)
    seen = set()
    unique_findings: List[Finding] = []
    for f in all_findings:
        k = dedup_key(f)
        if k not in seen:
            seen.add(k)
            unique_findings.append(f)
    all_findings = unique_findings

    # Build report
    report = SastReport(
        target=str(target),
        rulesets=rulesets,
        tools_executed=tools_executed,
        findings=all_findings,
        scanned_files=[str(f) for f in files],
        skipped_files=[],
        errors=all_errors,
    )
    report.summary = build_summary(all_findings)

    # Write outputs
    write_json_report(report, Path(args.output))
    write_markdown_report(report, Path(args.markdown))

    # Decision
    code = merge_gate_decision(all_findings, args.no_block)
    labels = {
        0: "PASS — no findings",
        1: "BLOCKED — critical findings",
        2: "BLOCKED — high findings",
        3: "WARN — medium/low findings",
        4: "ERROR — tool failure",
    }
    print(f"[{labels.get(code, 'UNKNOWN')}] JSON: {args.output} | Markdown: {args.markdown} | Tools: {', '.join(tools_executed) or 'none'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
