#!/usr/bin/env python3
"""
run-tests.py - Standardized test execution runner for multiple frameworks.

Usage:
    python run-tests.py [project_path] [options]

Options:
    --framework FRAMEWORK   Force test framework (pytest, jest, unittest, go, cargo)
    --coverage              Run tests with coverage reporting
    --output FILE           Write structured JSON report to FILE
    --timeout SECONDS       Maximum test execution time (default: 120)
    --verbose               Show detailed test output
    --sandbox               Run inside an isolated Docker sandbox
    --help                  Show this help message and exit

Auto-detection order:
    1. pytest      (pytest.ini, conftest.py, or test_*.py files)
    2. jest        (jest.config.*, or package.json with jest)
    3. unittest    (test_*.py or *_test.py with unittest imports)
    4. go test     (*.go files with _test.go suffix)
    5. cargo test  (Cargo.toml with [dependencies])

Safety: Tests run in isolated subprocesses. The working directory is never
modified. Coverage files and temp outputs are written to .codetester/ subdir.

Exit Codes:
    Exit code matches the test framework's exit code (0 = all passed)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# Sandbox integration
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR.parent.parent / "sandbox-executor" / "scripts"))
try:
    from sandboxed_runner import SandboxRunner
    _SANDBOX_AVAILABLE = True
except Exception:
    _SANDBOX_AVAILABLE = False
    SandboxRunner = None  # type: ignore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_DIR = ".codetester"
DEFAULT_TIMEOUT = 120


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class TestStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class TestCase:
    name: str
    status: str
    duration: float = 0.0
    file: str = ""
    line: int = 0
    error_message: str = ""
    error_type: str = ""


@dataclass
class TestReport:
    framework: str = ""
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration: float = 0.0
    coverage_percent: Optional[float] = None
    test_cases: list[TestCase] = field(default_factory=list)
    summary: str = ""
    output_dir: str = ""


# ---------------------------------------------------------------------------
# Framework detection
# ---------------------------------------------------------------------------

def detect_framework(project_path: Path) -> Optional[str]:
    """Auto-detect the test framework used in the project."""
    files = list(project_path.rglob("*"))
    file_names = [f.name for f in files]
    file_paths = [str(f) for f in files]

    # pytest
    pytest_markers = ["pytest.ini", "pyproject.toml", "setup.cfg", "conftest.py", "setup.py"]
    if any(m in file_names for m in pytest_markers):
        return "pytest"
    if any(re.search(r"test_.*\.py$", p) for p in file_paths):
        return "pytest"

    # jest
    if any(re.search(r"jest\.config\.", p) for p in file_paths):
        return "jest"
    package_json = project_path / "package.json"
    if package_json.exists():
        try:
            with open(package_json, "r", encoding="utf-8") as f:
                pkg = json.load(f)
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            scripts = pkg.get("scripts", {})
            if "jest" in deps or any("jest" in v for v in scripts.values()):
                return "jest"
            # Check for vitest too (use jest runner as fallback)
            if "vitest" in deps or any("vitest" in v for v in scripts.values()):
                return "jest"
        except (json.JSONDecodeError, OSError):
            pass

    # unittest
    if any(re.search(r"_test\.py$", p) for p in file_paths):
        return "unittest"

    # go test
    if any(f.name.endswith("_test.go") for f in files):
        return "go"

    # cargo test
    if any(f.name == "Cargo.toml" for f in files):
        return "cargo"

    # Default fallback: if we see any Python test files
    if any(f.suffix == ".py" and "test" in f.name.lower() for f in files):
        return "pytest"

    return None


# ---------------------------------------------------------------------------
# Test runners
# ---------------------------------------------------------------------------

def run_pytest(project_path: Path, coverage: bool, timeout: int, verbose: bool) -> tuple[int, TestReport]:
    """Run pytest and parse results."""
    report = TestReport(framework="pytest")
    output_dir = project_path / OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)
    report.output_dir = str(output_dir)

    # Install pytest-json-report if not present
    json_file = output_dir / "pytest-results.json"
    cov_file = output_dir / "coverage.json"

    cmd = [sys.executable, "-m", "pytest", "-v" if verbose else "-q", "--tb=short"]

    if coverage:
        cmd.extend(["--cov=.", f"--cov-report=json:{cov_file}"])

    # Try JSON report
    try:
        subprocess.run(
            [sys.executable, "-m", "pytest", "--version"],
            capture_output=True, timeout=10
        )
        # Try installing json report plugin
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pytest-json-report", "-q"],
            capture_output=True, timeout=30
        )
        cmd.append(f"--json-report --json-report-file={json_file}")
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        report.duration = time.time() - start

        # Try JSON report parsing
        if json_file.exists():
            _parse_pytest_json(json_file, report)
        else:
            _parse_pytest_text(result.stdout, result.stderr, report)

        # Parse coverage
        if coverage and cov_file.exists():
            _parse_coverage_json(cov_file, report)

        return result.returncode, report

    except subprocess.TimeoutExpired:
        report.duration = timeout
        report.summary = f"Timed out after {timeout}s"
        return 1, report
    except FileNotFoundError:
        report.summary = "pytest not found"
        return 1, report


def _parse_pytest_json(json_file: Path, report: TestReport) -> None:
    """Parse pytest JSON report."""
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        report.total = data.get("summary", {}).get("total", 0)
        report.passed = data.get("summary", {}).get("passed", 0)
        report.failed = data.get("summary", {}).get("failed", 0)
        report.skipped = data.get("summary", {}).get("skipped", 0)
        report.errors = data.get("summary", {}).get("error", 0)

        for test in data.get("tests", []):
            tc = TestCase(
                name=test.get("nodeid", ""),
                status=test.get("outcome", "unknown"),
                duration=test.get("call", {}).get("duration", 0.0) if test.get("call") else 0.0,
                file=test.get("nodeid", "").split("::")[0] if "::" in test.get("nodeid", "") else "",
            )
            if tc.status == "passed":
                report.passed += 1
            elif tc.status == "failed":
                report.failed += 1
                setup = test.get("setup")
                call = test.get("call")
                teardown = test.get("teardown")
                for phase in [setup, call, teardown]:
                    if phase and phase.get("outcome") == "failed":
                        tc.error_message = phase.get("longrepr", "")
                        break
            elif tc.status in ("skipped", "xfail"):
                tc.status = "skipped"
                report.skipped += 1
            report.test_cases.append(tc)

        report.summary = f"{report.passed} passed, {report.failed} failed, {report.skipped} skipped"
    except (json.JSONDecodeError, OSError) as exc:
        report.summary = f"Could not parse JSON report: {exc}"


def _parse_pytest_text(stdout: str, stderr: str, report: TestReport) -> None:
    """Fallback: parse pytest text output."""
    combined = stdout + "\n" + stderr

    passed = len(re.findall(r"\bPASSED\b", combined))
    failed = len(re.findall(r"\bFAILED\b", combined))
    skipped = len(re.findall(r"\bSKIPPED\b", combined))
    errors = len(re.findall(r"\bERROR\b", combined))

    summary_match = re.search(
        r"(\d+) passed.*?(\d+ failed)?.*?(\d+ skipped)?.*?(\d+ error)?.*?in ([\d.]+)s",
        combined, re.IGNORECASE
    )
    if summary_match:
        report.passed = int(summary_match.group(1) or 0)
        report.failed = int(summary_match.group(2) or 0) if summary_match.group(2) else failed
        report.skipped = int(summary_match.group(3) or 0) if summary_match.group(3) else skipped
        report.errors = int(summary_match.group(4) or 0) if summary_match.group(4) else errors
        report.duration = float(summary_match.group(5))
    else:
        report.passed = passed
        report.failed = failed
        report.skipped = skipped
        report.errors = errors

    report.total = report.passed + report.failed + report.skipped + report.errors
    report.summary = f"{report.passed} passed, {report.failed} failed, {report.skipped} skipped"

    for line in combined.splitlines():
        fail_match = re.search(r"(FAILED|ERROR)\s+([\w/._:]+)", line)
        if fail_match:
            tc = TestCase(
                name=fail_match.group(2),
                status="failed",
            )
            report.test_cases.append(tc)


def run_jest(project_path: Path, coverage: bool, timeout: int, verbose: bool) -> tuple[int, TestReport]:
    """Run jest/vitest and parse results."""
    report = TestReport(framework="jest")
    output_dir = project_path / OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)
    report.output_dir = str(output_dir)

    result_file = output_dir / "jest-results.json"
    cov_dir = output_dir / "coverage"

    runner = "npx"
    pkg_json = project_path / "package.json"
    test_cmd = "jest"
    if pkg_json.exists():
        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                pkg = json.load(f)
            scripts = pkg.get("scripts", {})
            test_script = scripts.get("test", "")
            if "vitest" in test_script:
                test_cmd = "vitest"
            elif "jest" in test_script:
                test_cmd = "jest"
        except (json.JSONDecodeError, OSError):
            pass

    cmd = [runner, test_cmd, "--json", f"--outputFile={result_file}", "--passWithNoTests"]
    if coverage:
        cmd.append("--coverage")
    if not verbose:
        cmd.append("--silent")

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        report.duration = time.time() - start

        if result_file.exists():
            _parse_jest_json(result_file, report)
        else:
            _parse_jest_text(result.stdout, result.stderr, report)

        if coverage:
            cov_summary = project_path / "coverage" / "coverage-summary.json"
            if cov_summary.exists():
                try:
                    with open(cov_summary, "r", encoding="utf-8") as f:
                        cov = json.load(f)
                    total = cov.get("total", {})
                    lines = total.get("lines", {})
                    report.coverage_percent = lines.get("pct")
                except (json.JSONDecodeError, OSError):
                    pass

        return result.returncode, report

    except subprocess.TimeoutExpired:
        report.duration = timeout
        report.summary = f"Timed out after {timeout}s"
        return 1, report
    except FileNotFoundError:
        report.summary = "npx not found (Node.js required)"
        return 1, report


def _parse_jest_json(result_file: Path, report: TestReport) -> None:
    """Parse jest JSON results."""
    try:
        with open(result_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        results = data if isinstance(data, dict) else {}
        success = results.get("success", False)
        test_results = results.get("testResults", [])

        for tr in test_results:
            for tc in tr.get("assertionResults", []):
                status = tc.get("status", "unknown")
                test_case = TestCase(
                    name=tc.get("title", ""),
                    status=status,
                    duration=tc.get("duration", 0) / 1000.0,
                    file=tr.get("name", ""),
                )
                if status == "failed":
                    test_case.error_message = tc.get("failureMessages", [""])[0] if tc.get("failureMessages") else ""
                report.test_cases.append(test_case)

        report.passed = sum(1 for t in report.test_cases if t.status == "passed")
        report.failed = sum(1 for t in report.test_cases if t.status == "failed")
        report.skipped = sum(1 for t in report.test_cases if t.status == "pending" or t.status == "skipped")
        report.total = len(report.test_cases)
        report.summary = f"{report.passed} passed, {report.failed} failed, {report.skipped} skipped"

    except (json.JSONDecodeError, OSError) as exc:
        report.summary = f"Could not parse jest JSON: {exc}"


def _parse_jest_text(stdout: str, stderr: str, report: TestReport) -> None:
    """Parse jest text output."""
    combined = stdout + "\n" + stderr
    passed = len(re.findall(r"\u2713|\u2714|PASS", combined))
    failed = len(re.findall(r"\u2715|\u2716|FAIL", combined))
    skipped = len(re.findall(r"skipped|pending", combined, re.IGNORECASE))

    m = re.search(r"Tests:\s*(\d+)\s*passed,?\s*(\d+)?\s*failed?" 
                  r",?\s*(\d+)?\s*(?:skipped|pending)?", combined, re.IGNORECASE)
    if m:
        report.passed = int(m.group(1) or 0)
        report.failed = int(m.group(2) or 0) if m.group(2) else failed
        report.skipped = int(m.group(3) or 0) if m.group(3) else skipped
    else:
        report.passed = passed
        report.failed = failed
        report.skipped = skipped

    report.total = report.passed + report.failed + report.skipped
    report.summary = f"{report.passed} passed, {report.failed} failed, {report.skipped} skipped"


def run_unittest(project_path: Path, coverage: bool, timeout: int, verbose: bool) -> tuple[int, TestReport]:
    """Run unittest discovery and parse results."""
    report = TestReport(framework="unittest")
    output_dir = project_path / OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)
    report.output_dir = str(output_dir)

    result_file = output_dir / "unittest-results.xml"

    cmd = [sys.executable, "-m", "unittest", "discover", "-v" if verbose else "-v"]
    if coverage:
        cmd = [sys.executable, "-m", "coverage", "run", "--source=.", "-m", "unittest", "discover"]

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        report.duration = time.time() - start

        _parse_unittest_text(result.stdout, result.stderr, report)

        if coverage:
            cov_result = subprocess.run(
                [sys.executable, "-m", "coverage", "json", "-o", str(output_dir / "coverage.json")],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            cov_file = output_dir / "coverage.json"
            if cov_file.exists():
                try:
                    with open(cov_file, "r", encoding="utf-8") as f:
                        cov_data = json.load(f)
                    totals = cov_data.get("totals", {})
                    if totals:
                        covered = totals.get("covered_lines", 0)
                        total_lines = totals.get("num_statements", 1)
                        report.coverage_percent = round((covered / total_lines) * 100, 1) if total_lines else 0
                except (json.JSONDecodeError, OSError):
                    pass

        return result.returncode, report

    except subprocess.TimeoutExpired:
        report.duration = timeout
        report.summary = f"Timed out after {timeout}s"
        return 1, report


def _parse_unittest_text(stdout: str, stderr: str, report: TestReport) -> None:
    """Parse unittest text output."""
    combined = stdout + "\n" + stderr

    ran_match = re.search(r"Ran\s+(\d+)\s+tests?\s+in\s+([\d.]+)s", combined)
    if ran_match:
        report.total = int(ran_match.group(1))
        report.duration = float(ran_match.group(2))

    if "OK" in combined:
        report.passed = report.total
    elif "FAIL" in combined:
        failures = re.findall(r"FAIL:\s+([\w.]+)", combined)
        errors = re.findall(r"ERROR:\s+([\w.]+)", combined)
        report.failed = len(failures)
        report.errors = len(errors)
        report.passed = report.total - report.failed - report.errors

    skipped_match = re.findall(r"skipped\s+'([^']+)'", combined)
    report.skipped = len(skipped_match)
    report.passed -= report.skipped

    report.summary = f"{report.passed} passed, {report.failed} failed, {report.skipped} skipped"

    for line in combined.splitlines():
        fail_match = re.search(r"(FAIL|ERROR):\s+([\w.]+)", line)
        if fail_match:
            report.test_cases.append(TestCase(
                name=fail_match.group(2),
                status="failed",
            ))


def run_go_test(project_path: Path, coverage: bool, timeout: int, verbose: bool) -> tuple[int, TestReport]:
    """Run go test and parse results."""
    report = TestReport(framework="go")
    output_dir = project_path / OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)
    report.output_dir = str(output_dir)

    cmd = ["go", "test", "./...", "-json"]
    if coverage:
        cmd.append("-cover")
    if verbose:
        cmd.append("-v")

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        report.duration = time.time() - start

        for line in (result.stdout + result.stderr).splitlines():
            try:
                event = json.loads(line)
                action = event.get("Action", "")
                test_name = event.get("Test", "")
                pkg = event.get("Package", "")
                elapsed = event.get("Elapsed", 0.0)
                output = event.get("Output", "")

                if action == "pass" and test_name:
                    report.passed += 1
                    report.test_cases.append(TestCase(
                        name=f"{pkg}/{test_name}",
                        status="passed",
                        duration=elapsed,
                    ))
                elif action == "fail" and test_name:
                    report.failed += 1
                    report.test_cases.append(TestCase(
                        name=f"{pkg}/{test_name}",
                        status="failed",
                        error_message=output.strip(),
                    ))
                elif action == "skip" and test_name:
                    report.skipped += 1

                cov_match = re.search(r"coverage:\s+([\d.]+)%", output)
                if cov_match:
                    report.coverage_percent = float(cov_match.group(1))

            except json.JSONDecodeError:
                continue

        report.total = report.passed + report.failed + report.skipped
        report.summary = f"{report.passed} passed, {report.failed} failed, {report.skipped} skipped"
        return result.returncode, report

    except subprocess.TimeoutExpired:
        report.duration = timeout
        report.summary = f"Timed out after {timeout}s"
        return 1, report
    except FileNotFoundError:
        report.summary = "go command not found"
        return 1, report


def run_cargo_test(project_path: Path, coverage: bool, timeout: int, verbose: bool) -> tuple[int, TestReport]:
    """Run cargo test and parse results."""
    report = TestReport(framework="cargo")
    output_dir = project_path / OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)
    report.output_dir = str(output_dir)

    cmd = ["cargo", "test"]
    if not verbose:
        cmd.append("--quiet")

    env = os.environ.copy()
    if coverage:
        env["CARGO_INCREMENTAL"] = "0"
        env["RUSTFLAGS"] = "-Cinstrument=coverage"
        env["LLVM_PROFILE_FILE"] = str(output_dir / "cargo-%p-%m.profraw")

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        report.duration = time.time() - start

        stdout = result.stdout
        stderr = result.stderr
        combined = stdout + "\n" + stderr

        result_match = re.search(
            r"test result:\s+(ok|FAILED)\.\s*(\d+)\s+passed;\s*(\d+)\s+failed;\s*(\d+)\s+(?:ignored|skipped)",
            combined
        )
        if result_match:
            status = result_match.group(1)
            report.passed = int(result_match.group(2))
            report.failed = int(result_match.group(3))
            report.skipped = int(result_match.group(4))
            report.total = report.passed + report.failed + report.skipped

            for line in combined.splitlines():
                test_match = re.search(r"test\s+(\S+)\s+\.\.\.\s+(ok|FAILED|ignored|FAILED)", line)
                if test_match:
                    tc = TestCase(
                        name=test_match.group(1),
                        status="passed" if test_match.group(2) == "ok" else "failed" if test_match.group(2) == "FAILED" else "skipped",
                    )
                    report.test_cases.append(tc)
        else:
            report.passed = len(re.findall(r"\.\.\.\s+ok$", combined, re.MULTILINE))
            report.failed = len(re.findall(r"\.\.\.\s+FAILED$", combined, re.MULTILINE))
            report.total = report.passed + report.failed

        report.summary = f"{report.passed} passed, {report.failed} failed, {report.skipped} skipped"
        return result.returncode, report

    except subprocess.TimeoutExpired:
        report.duration = timeout
        report.summary = f"Timed out after {timeout}s"
        return 1, report
    except FileNotFoundError:
        report.summary = "cargo command not found (Rust toolchain required)"
        return 1, report


# ---------------------------------------------------------------------------
# Sandbox wrapper
# ---------------------------------------------------------------------------

def _runner_sandboxed(framework: str, project_path: Path, coverage: bool, timeout: int, verbose: bool) -> tuple[int, TestReport]:
    """Run tests inside a sandbox container."""
    runner = SandboxRunner("code-tester")

    if framework == "pytest":
        cmd = ["python", "-m", "pytest", "-v" if verbose else "-q", "--tb=short"]
        if coverage:
            cmd.extend(["--cov=.", "--cov-report=json"])
        cmd.append("/workspace")
    elif framework == "jest":
        cmd = ["npx", "jest", "--passWithNoTests"]
        if not verbose:
            cmd.append("--silent")
        if coverage:
            cmd.append("--coverage")
        cmd.append("/workspace")
    elif framework == "unittest":
        cmd = ["python", "-m", "unittest", "discover", "-v" if verbose else "-v", "/workspace"]
    elif framework == "go":
        cmd = ["go", "test", "./...", "-v" if verbose else ""]
        if coverage:
            cmd.append("-cover")
        cmd = [c for c in cmd if c]
    elif framework == "cargo":
        cmd = ["cargo", "test"]
        if not verbose:
            cmd.append("--quiet")
    else:
        return 1, TestReport(framework=framework, summary=f"Unknown framework: {framework}")

    env = {"CI": "true"}
    if framework == "cargo" and coverage:
        env["CARGO_INCREMENTAL"] = "0"
        env["RUSTFLAGS"] = "-Cinstrument=coverage"

    result = runner.run(
        command=cmd,
        cwd="/workspace",
        env=env,
        timeout=timeout,
        network=True,
        source_mounts=[{"host": str(project_path), "container": "/workspace", "read_only": False}],
    )

    report = TestReport(framework=framework)
    report.summary = f"Sandbox exit {result.exit_code}"
    if result.stdout:
        report.summary += f" | stdout: {result.stdout[:200]}"
    return result.exit_code, report


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def print_report(report: TestReport) -> None:
    """Print a human-readable test report."""
    print("\n" + "=" * 60)
    print(f"Test Execution Report - {report.framework}")
    print("=" * 60)
    print(f"  Total:    {report.total}")
    print(f"  Passed:   {report.passed}")
    print(f"  Failed:   {report.failed}")
    print(f"  Skipped:  {report.skipped}")
    print(f"  Errors:   {report.errors}")
    print(f"  Duration: {report.duration:.2f}s")
    if report.coverage_percent is not None:
        print(f"  Coverage: {report.coverage_percent:.1f}%")
    print(f"  Summary:  {report.summary}")

    failed_tests = [t for t in report.test_cases if t.status == "failed"]
    if failed_tests:
        print(f"\n  --- Failed Tests ({len(failed_tests)}) ---")
        for tc in failed_tests[:20]:
            print(f"    [FAIL] {tc.name}")
            if tc.error_message:
                msg = tc.error_message[:200].replace("\n", " ")
                print(f"      {msg}")
        if len(failed_tests) > 20:
            print(f"    ... and {len(failed_tests) - 20} more")

    print("=" * 60)


def write_json_report(report: TestReport, output_file: str) -> None:
    """Write structured JSON report."""
    data = {
        "framework": report.framework,
        "summary": {
            "total": report.total,
            "passed": report.passed,
            "failed": report.failed,
            "skipped": report.skipped,
            "errors": report.errors,
            "duration_seconds": round(report.duration, 2),
            "coverage_percent": report.coverage_percent,
        },
        "test_cases": [
            {
                "name": tc.name,
                "status": tc.status,
                "duration": round(tc.duration, 3),
                "file": tc.file,
                "error_message": tc.error_message[:500] if tc.error_message else "",
            }
            for tc in report.test_cases
        ],
    }
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\nJSON report written to {output_file}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run tests with standardized output parsing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Safety: Tests run in isolated subprocesses. "
            "No source files are modified. Output goes to .codetester/ subdirectory."
        ),
    )
    parser.add_argument("project_path", nargs="?", default=".",
                        help="Path to the project (default: current directory)")
    parser.add_argument("--framework", choices=["pytest", "jest", "unittest", "go", "cargo"],
                        help="Force a specific test framework")
    parser.add_argument("--coverage", action="store_true",
                        help="Run with coverage reporting")
    parser.add_argument("--output", metavar="FILE",
                        help="Write JSON report to FILE")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"Maximum test execution time in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed test output")
    parser.add_argument("--sandbox", action="store_true",
                        help="Run tests inside an isolated Docker sandbox (mandatory for Phase 4)")
    parser.add_argument("--version", action="version", version="%(prog)s 1.0")

    args = parser.parse_args()

    if args.sandbox and not _SANDBOX_AVAILABLE:
        print("Error: --sandbox requested but sandbox-executor is not available.", file=sys.stderr)
        sys.exit(1)

    project_path = Path(args.project_path).resolve()
    if not project_path.is_dir():
        print(f"Error: Not a directory: {project_path}", file=sys.stderr)
        return 1

    # Detect or use forced framework
    framework = args.framework or detect_framework(project_path)
    if framework is None:
        print(
            "Error: Could not auto-detect test framework. "
            "Use --framework to specify one of: pytest, jest, unittest, go, cargo",
            file=sys.stderr,
        )
        return 1

    print(f"Detected framework: {framework}")
    print(f"Project: {project_path}")
    if args.coverage:
        print("Coverage: enabled")

    # Dispatch to runner
    runners = {
        "pytest": run_pytest,
        "jest": run_jest,
        "unittest": run_unittest,
        "go": run_go_test,
        "cargo": run_cargo_test,
    }

    if args.sandbox:
        exit_code, report = _runner_sandboxed(framework, project_path, args.coverage, args.timeout, args.verbose)
    else:
        runner = runners[framework]
        exit_code, report = runner(project_path, args.coverage, args.timeout, args.verbose)

    # Print and save report
    print_report(report)

    if args.output:
        write_json_report(report, args.output)

    # Also save to default location
    output_dir = project_path / OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)
    write_json_report(report, str(output_dir / "test-report.json"))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
