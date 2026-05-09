#!/usr/bin/env python3
"""
run-review.py — Heuristic + deterministic code review runner for the self-reviewer skill v4.0.

This script combines:
  1. Deterministic AST structural analysis via ast-analyzer.py (design, complexity,
     coupling, duplication, SOLID)
  2. Regex-based security smell detection (secrets, injection, weak crypto, etc.)
  3. Pattern consistency checks (naming, print, commented-out code)

Usage:
    python run-review.py --files src/users/service.py src/auth/handler.py
    python run-review.py --diff changes.patch
    python run-review.py --repo . --since HEAD~1

Outputs:
    - Markdown report to stdout (default)
    - JSON report to --output-json path
    - Markdown report to --output-md path

Exit codes:
    0  — review passed (no critical findings)
    1  — critical findings detected (delivery blocked)
    2  — runtime / argument error
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional


# ─────────────────────────── Configuration ───────────────────────────

COMPLEXITY_THRESHOLD = 10
FUNCTION_LENGTH_THRESHOLD = 50
NESTING_DEPTH_THRESHOLD = 4

SECURITY_PATTERNS = {
    "hardcoded_secret": re.compile(
        r"(?i)(api[_-]?key|password|secret|token|private[_-]?key)\s*[:=]\s*['\"][^'\"]{8,}['\"]"
    ),
    "sql_injection": re.compile(
        r"(?i)(execute|query|raw)\s*\(.*%s|\.format\s*\(.*|f['\"].*SELECT|f['\"].*INSERT|f['\"].*UPDATE|f['\"].*DELETE"
    ),
    "command_injection": re.compile(
        r"(?i)(os\.system|subprocess\.call|subprocess\.run|eval\s*\(|exec\s*\().*\+.*|\$\{.*\}|%.*%"
    ),
    "unsafe_deserialization": re.compile(
        r"(?i)(pickle\.loads?|yaml\.load\s*\(|eval\s*\()"
    ),
    "weak_crypto": re.compile(
        r"(?i)(md5|sha1|des|rsa[_-]?1024|random\.random\s*\()"
    ),
    "sensitive_logging": re.compile(
        r"(?i)(log(?:ger)?\.(?:debug|info|warning|error|critical).*(?:password|secret|token|ssn|credit[_-]?card))"
    ),
    "timing_attack_risk": re.compile(
        r"(?i)(==\s*['\"].*secret|==\s*.*token|==\s*.*password)"
    ),
}


# ─────────────────────────── Data model ───────────────────────────

@dataclass
class Finding:
    id: str
    severity: str  # critical, medium, low
    uncertainty: str  # low, medium, high
    category: str  # security, design, pattern, solid, complexity, coupling, duplication
    file: str
    line: int
    function: Optional[str]
    message: str
    rationale: str
    fix_suggestion: str
    # v4.0 deterministic fields
    metric: Optional[str] = None
    metric_value: Optional[float] = None
    threshold: Optional[float] = None
    ast_node_type: Optional[str] = None


@dataclass
class ReviewReport:
    summary: dict = field(default_factory=lambda: {"critical": 0, "medium": 0, "low": 0, "total": 0})
    blocked: bool = False
    findings: List[Finding] = field(default_factory=list)


# ─────────────────────────── AST helpers (legacy light AST) ───────────────────────────

class FunctionAnalyzer(ast.NodeVisitor):
    """Collect per-function metrics from an AST (used for security input-validation check)."""

    def __init__(self):
        self.functions: List[dict] = []
        self._current_function: Optional[str] = None
        self._function_lines: int = 0
        self._function_start: int = 0
        self._complexity: int = 0
        self._nesting: int = 0
        self._max_nesting: int = 0

    def visit_FunctionDef(self, node: ast.FunctionDef):
        outer = self._current_function
        outer_lines = self._function_lines
        outer_start = self._function_start
        outer_complexity = self._complexity
        outer_max_nesting = self._max_nesting
        outer_nesting = self._nesting

        self._current_function = node.name
        self._function_start = node.lineno
        self._function_lines = (node.end_lineno or node.lineno) - node.lineno
        self._complexity = 1  # baseline
        self._nesting = 1
        self._max_nesting = 1

        for child in ast.iter_child_nodes(node):
            self.visit(child)

        self.functions.append({
            "name": self._current_function,
            "start": self._function_start,
            "end": node.end_lineno or node.lineno,
            "lines": self._function_lines,
            "complexity": self._complexity,
            "max_nesting": self._max_nesting,
            "args": [arg.arg for arg in node.args.args],
        })

        self._current_function = outer
        self._function_lines = outer_lines
        self._function_start = outer_start
        self._complexity = outer_complexity
        self._max_nesting = outer_max_nesting
        self._nesting = outer_nesting

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_If(self, node: ast.If):
        self._complexity += 1
        self._nesting += 1
        self._max_nesting = max(self._max_nesting, self._nesting)
        self.generic_visit(node)
        self._nesting -= 1

    def visit_For(self, node: ast.For):
        self._complexity += 1
        self._nesting += 1
        self._max_nesting = max(self._max_nesting, self._nesting)
        self.generic_visit(node)
        self._nesting -= 1

    def visit_While(self, node: ast.While):
        self._complexity += 1
        self._nesting += 1
        self._max_nesting = max(self._max_nesting, self._nesting)
        self.generic_visit(node)
        self._nesting -= 1

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        self._complexity += 1
        self.generic_visit(node)

    def visit_With(self, node: ast.With):
        self._nesting += 1
        self._max_nesting = max(self._max_nesting, self._nesting)
        self.generic_visit(node)
        self._nesting -= 1

    def visit_Try(self, node: ast.Try):
        self._nesting += 1
        self._max_nesting = max(self._max_nesting, self._nesting)
        self.generic_visit(node)
        self._nesting -= 1


def has_input_validation(node: ast.FunctionDef) -> bool:
    """Heuristic: does the function body start with guard clauses?"""
    if not node.body:
        return False
    for stmt in node.body[:5]:
        if isinstance(stmt, ast.If):
            if isinstance(stmt.body[0], ast.Raise) if stmt.body else False:
                return True
            test = stmt.test
            if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                if any(isinstance(s, ast.Raise) for s in stmt.body):
                    return True
        if isinstance(stmt, ast.Assert):
            return True
    return False


# ─────────────────────────── Deterministic structural analysis (ast-analyzer) ───────────────────────────

def run_ast_analyzer(files: List[Path]) -> List[Finding]:
    """Invoke ast-analyzer.py as the deterministic structural engine and convert its output to Findings."""
    analyzer_path = Path(__file__).with_name("ast-analyzer.py")
    if not analyzer_path.exists():
        print(f"[WARN] ast-analyzer.py not found at {analyzer_path}; skipping deterministic structural analysis.", file=sys.stderr)
        return []

    cmd = [sys.executable, str(analyzer_path), "--output-json", "-"]
    if files:
        cmd += ["--files"] + [str(f) for f in files]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as e:
        print(f"[WARN] ast-analyzer.py failed: {e}", file=sys.stderr)
        return []

    if result.returncode not in (0, 1):
        print(f"[WARN] ast-analyzer.py exited {result.returncode}: {result.stderr}", file=sys.stderr)
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"[WARN] Could not parse ast-analyzer.py output: {e}", file=sys.stderr)
        return []

    findings: List[Finding] = []
    for item in data.get("findings", []):
        loc = item.get("location", {})
        findings.append(Finding(
            id=item.get("id", ""),
            severity=item.get("severity", "medium"),
            uncertainty="low",  # AST-derived findings are objective
            category=item.get("category", "design"),
            file=loc.get("file", ""),
            line=loc.get("line", 0),
            function=loc.get("function"),
            message=item.get("message", ""),
            rationale=item.get("rationale", ""),
            fix_suggestion=item.get("fix_suggestion", ""),
            metric=item.get("metric"),
            metric_value=item.get("value"),
            threshold=item.get("threshold"),
            ast_node_type=item.get("ast_node_type"),
        ))
    return findings


# ─────────────────────────── Review engines (security + pattern) ───────────────────────────

def review_security(filepath: str, source: str, tree: ast.AST) -> Iterator[Finding]:
    """Yield security-smell findings for a single file."""
    lines = source.splitlines()

    for line_no, line in enumerate(lines, start=1):
        for smell_name, pattern in SECURITY_PATTERNS.items():
            if pattern.search(line):
                if smell_name == "hardcoded_secret":
                    yield Finding(
                        id="", severity="critical", uncertainty="low", category="security",
                        file=filepath, line=line_no, function=None,
                        message="Potential hardcoded secret detected",
                        rationale="Hardcoded credentials are a critical security risk; they leak in version control and logs.",
                        fix_suggestion="Load secrets from environment variables (e.g., os.environ) or a secrets manager. Never commit credentials.",
                    )
                elif smell_name == "sql_injection":
                    yield Finding(
                        id="", severity="critical", uncertainty="medium", category="security",
                        file=filepath, line=line_no, function=None,
                        message="Potential SQL injection vector",
                        rationale="Dynamic SQL built with string formatting is vulnerable to injection attacks.",
                        fix_suggestion="Use parameterized queries or an ORM. Never concatenate user input into SQL.",
                    )
                elif smell_name == "command_injection":
                    yield Finding(
                        id="", severity="critical", uncertainty="medium", category="security",
                        file=filepath, line=line_no, function=None,
                        message="Potential command injection vector",
                        rationale="Passing user input to shell commands allows arbitrary code execution.",
                        fix_suggestion="Use subprocess with argument lists instead of shell strings. Validate and sanitize all inputs.",
                    )
                elif smell_name == "unsafe_deserialization":
                    yield Finding(
                        id="", severity="critical", uncertainty="low", category="security",
                        file=filepath, line=line_no, function=None,
                        message="Unsafe deserialization detected",
                        rationale="Deserializing untrusted data can lead to remote code execution.",
                        fix_suggestion="Use json.loads for safe deserialization, or restrict pickle to trusted sources with signing.",
                    )
                elif smell_name == "weak_crypto":
                    yield Finding(
                        id="", severity="medium", uncertainty="low", category="security",
                        file=filepath, line=line_no, function=None,
                        message="Weak cryptographic primitive detected",
                        rationale="MD5, SHA1, and small RSA are cryptographically broken.",
                        fix_suggestion="Use SHA-256+ for hashing, bcrypt/argon2 for passwords, RSA-2048+ for asymmetric crypto.",
                    )
                elif smell_name == "sensitive_logging":
                    yield Finding(
                        id="", severity="critical", uncertainty="low", category="security",
                        file=filepath, line=line_no, function=None,
                        message="Sensitive data may be logged",
                        rationale="Logging secrets or PII exposes them to log aggregators and breaches.",
                        fix_suggestion="Redact sensitive fields before logging. Use structured logging with allow-lists.",
                    )
                elif smell_name == "timing_attack_risk":
                    yield Finding(
                        id="", severity="medium", uncertainty="medium", category="security",
                        file=filepath, line=line_no, function=None,
                        message="Timing attack risk in secret comparison",
                        rationale="`==` comparison short-circuits, leaking timing information.",
                        fix_suggestion="Use hmac.compare_digest() or secrets.compare_digest() for constant-time comparison.",
                    )

    # AST-based: missing input validation on public functions
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_") and not has_input_validation(node):
                yield Finding(
                    id="", severity="critical", uncertainty="high", category="security",
                    file=filepath, line=node.lineno, function=node.name,
                    message=f"Public function '{node.name}' may lack input validation",
                    rationale="Public functions without guard clauses are susceptible to invalid inputs causing crashes or security issues.",
                    fix_suggestion="Add guard clauses at the top of the function: check for None, empty values, and type/range constraints.",
                )


def review_patterns(filepath: str, source: str, tree: ast.AST) -> Iterator[Finding]:
    """Yield pattern-consistency findings for a single file."""
    lines = source.splitlines()
    for line_no, line in enumerate(lines, start=1):
        if "print(" in line:
            yield Finding(
                id="", severity="low", uncertainty="medium", category="pattern",
                file=filepath, line=line_no, function=None,
                message="Use of print() detected",
                rationale="Repository norm uses structured logging, not print statements.",
                fix_suggestion="Replace print() with logger.debug/info/warning from the project's logging module.",
            )

    # Check for commented-out code blocks
    comment_block: List[int] = []
    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#") and len(stripped) > 2:
            comment_block.append(line_no)
        else:
            if len(comment_block) > 5:
                yield Finding(
                    id="", severity="low", uncertainty="medium", category="pattern",
                    file=filepath, line=comment_block[0], function=None,
                    message="Large commented-out code block detected",
                    rationale="Commented-out code rots and confuses readers. Version control preserves history.",
                    fix_suggestion="Delete the commented block. If needed, retrieve it from git history.",
                )
            comment_block = []

    # Check naming conventions heuristically
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if not re.match(r"^[a-z_][a-z0-9_]*$", node.name):
                yield Finding(
                    id="", severity="low", uncertainty="low", category="pattern",
                    file=filepath, line=node.lineno, function=node.name,
                    message=f"Function '{node.name}' does not follow snake_case convention",
                    rationale="Consistent naming reduces cognitive load and matches repository Style Enforcer rules.",
                    fix_suggestion="Rename to snake_case (e.g., do_something). Update all call sites.",
                )
        if isinstance(node, ast.ClassDef):
            if not re.match(r"^[A-Z][a-zA-Z0-9]*$", node.name):
                yield Finding(
                    id="", severity="low", uncertainty="low", category="pattern",
                    file=filepath, line=node.lineno, function=node.name,
                    message=f"Class '{node.name}' does not follow PascalCase convention",
                    rationale="Consistent naming matches repository Style Enforcer rules.",
                    fix_suggestion="Rename to PascalCase (e.g., MyClass). Update all references.",
                )


# ─────────────────────────── File loading ───────────────────────────

def load_files_from_args(args) -> List[Path]:
    files: List[Path] = []
    if args.files:
        files.extend(Path(f) for f in args.files)
    if args.diff:
        diff_text = Path(args.diff).read_text()
        for match in re.finditer(r"^\+\+\+ b?/(.*)$", diff_text, re.MULTILINE):
            p = Path(match.group(1))
            if p.exists() and p.suffix == ".py":
                files.append(p)
    if args.repo:
        repo = Path(args.repo)
        for py_file in repo.rglob("*.py"):
            if ".venv" not in str(py_file) and "__pycache__" not in str(py_file):
                files.append(py_file)
    if args.since:
        result = subprocess.run(
            ["git", "diff", "--name-only", args.since],
            capture_output=True, text=True, cwd=args.repo or ".",
        )
        for line in result.stdout.strip().splitlines():
            p = Path(line)
            if p.exists() and p.suffix == ".py":
                files.append(p)
    return files


# ─────────────────────────── Report generation ───────────────────────────

def generate_markdown(report: ReviewReport) -> str:
    lines: List[str] = []
    lines.append("## Self-Review Report (v4.0)\n")
    s = report.summary
    lines.append(f"### Summary\n- **Critical**: {s['critical']} | **Medium**: {s['medium']} | **Low**: {s['low']} | **Total**: {s['total']}\n")

    def section(title: str, sev: str):
        findings = [f for f in report.findings if f.severity == sev]
        if not findings:
            return
        lines.append(f"### {title} Findings\n")
        for f in findings:
            lines.append(f"#### {f.id} — {f.message}")
            lines.append(f"- **File**: `{f.file}:{f.line}`")
            if f.function:
                lines.append(f"- **Function**: `{f.function}`")
            if f.metric is not None:
                lines.append(f"- **Metric**: `{f.metric} = {f.metric_value}` (threshold = {f.threshold})")
                if f.ast_node_type:
                    lines.append(f"- **AST node**: {f.ast_node_type}")
            lines.append(f"- **Severity**: {f.severity.upper()}")
            lines.append(f"- **Category**: {f.category}")
            if f.uncertainty != "low" or f.category == "security":
                lines.append(f"- **Uncertainty**: {f.uncertainty}")
            lines.append(f"- **Rationale**: {f.rationale}")
            lines.append(f"- **Fix suggestion**: {f.fix_suggestion}")
            lines.append("")

    section("Critical (Delivery Blocked)", "critical")
    section("Medium", "medium")
    section("Low", "low")
    return "\n".join(lines)


def generate_json(report: ReviewReport) -> str:
    return json.dumps(asdict(report), indent=2)


# ─────────────────────────── Main ───────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Heuristic + deterministic code review runner")
    parser.add_argument("--files", nargs="+", help="Python files to review")
    parser.add_argument("--diff", help="Unified diff file to parse")
    parser.add_argument("--repo", help="Repository root to scan")
    parser.add_argument("--since", help="Git commit range (e.g., HEAD~1)")
    parser.add_argument("--output-json", help="Path to write JSON report")
    parser.add_argument("--output-md", help="Path to write Markdown report")
    parser.add_argument("--no-ast-analyzer", action="store_true", help="Skip deterministic structural analysis")
    args = parser.parse_args()

    if not any([args.files, args.diff, args.repo]):
        parser.print_help()
        return 2

    files = load_files_from_args(args)
    if not files:
        print("No Python files found to review.", file=sys.stderr)
        return 2

    report = ReviewReport()

    # Phase 1: deterministic structural analysis via ast-analyzer.py
    if not args.no_ast_analyzer:
        ast_findings = run_ast_analyzer(files)
        report.findings.extend(ast_findings)

    # Phase 2: security + pattern heuristics per file
    for filepath in files:
        try:
            source = filepath.read_text()
            tree = ast.parse(source)
        except SyntaxError as e:
            print(f"[WARN] Syntax error in {filepath}: {e}", file=sys.stderr)
            continue
        except Exception as e:
            print(f"[WARN] Could not read {filepath}: {e}", file=sys.stderr)
            continue

        for finding in review_security(str(filepath), source, tree):
            report.findings.append(finding)
        for finding in review_patterns(str(filepath), source, tree):
            report.findings.append(finding)

    # Deduplicate by (file, line, message)
    seen = set()
    deduped: List[Finding] = []
    for f in report.findings:
        key = (f.file, f.line, f.message)
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    report.findings = deduped

    # Summarize
    report.summary = {"critical": 0, "medium": 0, "low": 0, "total": 0}
    for f in report.findings:
        report.summary["total"] += 1
        report.summary[f.severity] += 1
    report.blocked = report.summary["critical"] > 0

    # Renumber IDs
    for idx, f in enumerate(report.findings, start=1):
        f.id = f"F{idx:03d}"

    md_output = generate_markdown(report)
    json_output = generate_json(report)

    if args.output_md:
        Path(args.output_md).write_text(md_output)
        print(f"Markdown report written to {args.output_md}")
    else:
        print(md_output)

    if args.output_json:
        Path(args.output_json).write_text(json_output)
        print(f"JSON report written to {args.output_json}")

    return 1 if report.blocked else 0


if __name__ == "__main__":
    sys.exit(main())
