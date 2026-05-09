#!/usr/bin/env python3
"""API Contract Tester — validate OpenAPI specs and generate contract tests."""

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
        description="Validate OpenAPI specs and generate basic contract tests."
    )
    parser.add_argument("--spec", required=True, help="Path to OpenAPI JSON or YAML spec")
    parser.add_argument("--output", default=".", help="Output directory for reports and tests")
    parser.add_argument(
        "--generate-tests", action="store_true", help="Generate pytest contract tests"
    )
    parser.add_argument("--format", choices=["json", "yaml"], help="Spec format (auto-detected if omitted)")
    return parser.parse_args()


def load_spec(spec_path: str, fmt: str | None) -> dict[str, Any]:
    """Load and parse an OpenAPI spec file."""
    path = Path(spec_path)
    if not path.exists():
        raise FileNotFoundError(f"Spec file not found: {spec_path}")

    raw = path.read_text(encoding="utf-8")

    detected = fmt
    if detected is None:
        if path.suffix in (".yaml", ".yml"):
            detected = "yaml"
        elif path.suffix == ".json":
            detected = "json"
        elif raw.strip().startswith("{"):
            detected = "json"
        else:
            detected = "yaml"

    if detected == "json":
        return json.loads(raw)

    try:
        import yaml
        return yaml.safe_load(raw)
    except ImportError as exc:
        raise RuntimeError("PyYAML is required for YAML specs. Install: pip install pyyaml") from exc


def validate_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate basic OpenAPI structure and return a list of violations."""
    violations = []

    if not isinstance(spec, dict):
        violations.append({"severity": "CRITICAL", "message": "Spec root must be an object"})
        return violations

    openapi_version = spec.get("openapi") or spec.get("swagger")
    if not openapi_version:
        violations.append({"severity": "CRITICAL", "message": "Missing 'openapi' or 'swagger' version field"})

    info = spec.get("info")
    if not isinstance(info, dict):
        violations.append({"severity": "HIGH", "message": "Missing 'info' object"})
    else:
        if not info.get("title"):
            violations.append({"severity": "MEDIUM", "message": "info.title is missing"})
        if not info.get("version"):
            violations.append({"severity": "MEDIUM", "message": "info.version is missing"})

    paths = spec.get("paths")
    if not isinstance(paths, dict) or not paths:
        violations.append({"severity": "HIGH", "message": "No paths defined"})

    components = spec.get("components", {})
    schemas = components.get("schemas") if isinstance(components, dict) else None
    if not schemas:
        violations.append({"severity": "LOW", "message": "No components.schemas defined"})

    # Validate path items
    if isinstance(paths, dict):
        valid_methods = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
        for path_url, path_item in paths.items():
            if not isinstance(path_item, dict):
                violations.append({"severity": "HIGH", "message": f"Path '{path_url}' must be an object"})
                continue
            for method, operation in path_item.items():
                if method.startswith("x-"):
                    continue
                if method not in valid_methods:
                    violations.append({"severity": "MEDIUM", "message": f"Invalid method '{method}' in '{path_url}'"})
                    continue
                if not isinstance(operation, dict):
                    continue
                if not operation.get("operationId"):
                    violations.append({"severity": "LOW", "message": f"Missing operationId for {method.upper()} {path_url}"})
                if "responses" not in operation:
                    violations.append({"severity": "HIGH", "message": f"Missing responses for {method.upper()} {path_url}"})

    return violations


def generate_contract_tests(spec: dict[str, Any], output_dir: Path) -> Path:
    """Generate pytest contract tests from an OpenAPI spec."""
    paths = spec.get("paths", {})
    servers = spec.get("servers", [{"url": "http://localhost"}])
    base_url = servers[0].get("url", "http://localhost") if servers else "http://localhost"

    lines = [
        "# Auto-generated API contract tests",
        "import pytest",
        "import requests",
        "",
        f"BASE_URL = {base_url!r}",
        "",
    ]

    test_count = 0
    for path_url, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method in ("parameters",) or method.startswith("x-"):
                continue
            if method not in {"get", "put", "post", "delete", "patch"}:
                continue
            if not isinstance(operation, dict):
                continue
            op_id = operation.get("operationId") or f"{method}_{path_url.strip('/').replace('/', '_')}"
            op_id = re.sub(r"[^a-zA-Z0-9_]", "_", op_id)
            responses = operation.get("responses", {})
            expected_codes = list(responses.keys()) or ["200"]
            expected_code = expected_codes[0]
            # Prefer 2xx if available
            for code in expected_codes:
                if code.startswith("2"):
                    expected_code = code
                    break

            lines.append(f"def test_{op_id}():")
            lines.append(f'    """Contract test for {method.upper()} {path_url}"""')
            lines.append(f"    url = BASE_URL + {path_url!r}")
            lines.append(f"    response = requests.{method}(url)")
            lines.append(f"    assert response.status_code == {expected_code}")
            lines.append("    # TODO: validate response schema")
            lines.append("")
            test_count += 1

    test_file = output_dir / "contract_tests.py"
    test_file.write_text("\n".join(lines), encoding="utf-8")
    return test_file


def build_report(spec: dict[str, Any], violations: list[dict[str, Any]], test_file: Path | None) -> dict[str, Any]:
    """Build a structured JSON report."""
    paths = spec.get("paths", {})
    endpoint_count = 0
    for p in paths.values():
        if isinstance(p, dict):
            endpoint_count += sum(1 for k in p if k not in ("parameters",) and not k.startswith("x-"))

    severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for v in violations:
        severity_counts[v.get("severity", "LOW")] = severity_counts.get(v.get("severity", "LOW"), 0) + 1

    can_deploy = severity_counts["CRITICAL"] == 0 and severity_counts["HIGH"] == 0

    return {
        "openapi_version": spec.get("openapi") or spec.get("swagger"),
        "title": spec.get("info", {}).get("title", "Unknown"),
        "version": spec.get("info", {}).get("version", "Unknown"),
        "endpoint_count": endpoint_count,
        "violations": violations,
        "severity_counts": severity_counts,
        "can_i_deploy": can_deploy,
        "generated_test_file": str(test_file) if test_file else None,
    }


def main() -> int:
    """Main entry point."""
    args = parse_args()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        spec = load_spec(args.spec, args.format)
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}), file=sys.stderr)
        return 1

    violations = validate_spec(spec)

    test_file = None
    if args.generate_tests:
        try:
            test_file = generate_contract_tests(spec, output_dir)
        except Exception as exc:
            violations.append({"severity": "MEDIUM", "message": f"Test generation failed: {exc}"})

    report = build_report(spec, violations, test_file)
    report["success"] = True

    report_path = output_dir / "contract_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
