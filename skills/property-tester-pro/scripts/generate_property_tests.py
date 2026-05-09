#!/usr/bin/env python3
"""generate_property_tests.py — Property-based test generation.

Given a Python function signature, generates Hypothesis-style property tests.
"""

import argparse
import ast
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Property Tester Pro")
    parser.add_argument("--file", required=True, help="Python file to analyze")
    parser.add_argument("--function", required=True, help="Function name")
    parser.add_argument("--output", default="test_properties.py")
    args = parser.parse_args()

    source = Path(args.file).read_text(encoding="utf-8")
    tree = ast.parse(source)

    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == args.function:
            func = node
            break

    if not func:
        print(f"ERROR: Function {args.function} not found in {args.file}", file=sys.stderr)
        return 1

    tests = _generate_properties(func)
    Path(args.output).write_text(tests, encoding="utf-8")
    print(f"Property tests written to {args.output}")
    return 0


def _generate_properties(func):
    name = func.name
    args = [arg.arg for arg in func.args.args]

    lines = [
        f"# Auto-generated property tests for {name}",
        "import pytest",
        "from hypothesis import given, strategies as st",
        f"from {func.name}_module import {name}",
        "",
        f"@given({', '.join(f'{a}=st.integers()' for a in args)})",
        f"def test_{name}_never_raises({', '.join(args)}):",
        f"    # Invariant: {name} should not raise on valid inputs",
        f"    {name}({', '.join(args)})",
        "",
        f"@given({', '.join(f'{a}=st.integers(min_value=0, max_value=100)' for a in args)})",
        f"def test_{name}_idempotent_double_call({', '.join(args)}):",
        f"    # Invariant: calling {name} twice with same args gives same result",
        f"    r1 = {name}({', '.join(args)})",
        f"    r2 = {name}({', '.join(args)})",
        f"    assert r1 == r2",
        "",
    ]

    # Add output-type-specific invariants
    lines.extend([
        f"@given({', '.join(f'{a}=st.integers()' for a in args)})",
        f"def test_{name}_output_type_consistent({', '.join(args)}):",
        f"    result = {name}({', '.join(args)})",
        f"    if result is not None:",
        f"        assert type(result) in (int, float, str, bool, list, dict)",
        "",
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
