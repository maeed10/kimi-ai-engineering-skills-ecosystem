#!/usr/bin/env python3
"""
evaluate_fitness.py — Architectural fitness function evaluator.

Measures codebase compliance against constraint definitions and produces
a JSON fitness result suitable for rendering into FITNESS_REPORT.md.

Usage:
    python evaluate_fitness.py --constraints .fitness/constraints.yaml --src src/
    python evaluate_fitness.py --baseline --src src/
    python evaluate_fitness.py --constraints .fitness/constraints.yaml --src src/ --output fitness_result.json

Exit codes:
    0 — evaluation completed (check gate field in output)
    1 — configuration error
    2 — source path not found
"""

from __future__ import annotations

import argparse
import ast
import glob
import json
import os
import re
import sys
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Optional YAML support with graceful fallback
try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Violation:
    file: str
    line: int
    message: str
    severity: str  # critical | warning
    constraint: str


@dataclass
class ConstraintResult:
    name: str
    score: float  # 0.0 - 1.0
    status: str  # PASS | WARNING | CRITICAL
    violations: list[Violation] = field(default_factory=list)


@dataclass
class CategoryResult:
    name: str
    weight: float
    score: float
    status: str
    delta: float = 0.0
    constraints: list[ConstraintResult] = field(default_factory=list)


@dataclass
class FitnessResult:
    run_id: str
    timestamp: str
    project: str
    trigger: str
    overall_score: float = 0.0
    gate: str = "PROCEED"  # PROCEED | WARN | HALT
    categories: list[CategoryResult] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    trend: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Source code parsing utilities
# ---------------------------------------------------------------------------


class ImportVisitor(ast.NodeVisitor):
    """Collect all import statements from a Python file."""

    def __init__(self, file_path: str, src_root: str) -> None:
        self.file_path = file_path
        self.src_root = src_root
        self.imports: list[dict] = []
        self.module_name = self._module_name(file_path, src_root)

    def _module_name(self, file_path: str, src_root: str) -> str:
        rel = os.path.relpath(file_path, src_root)
        mod = rel.replace(os.sep, ".").replace(".py", "")
        if mod.endswith(".__init__"):
            mod = mod[:-9]
        return mod

    def _add(self, node: ast.AST, module: str, names: list[str] | None = None) -> None:
        self.imports.append({
            "module": self.module_name,
            "imports_from": module,
            "names": names or [],
            "file": self.file_path,
            "line": getattr(node, "lineno", 0),
        })

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self._add(node, alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        mod = node.module or ""
        names = [a.name for a in node.names]
        level = node.level or 0
        if level > 0:
            parts = self.module_name.split(".")
            if level <= len(parts):
                mod = ".".join(parts[:-level] + ([mod] if mod else []))
            else:
                mod = ""
        self._add(node, mod, names)
        self.generic_visit(node)


def parse_file_imports(file_path: str, src_root: str) -> list[dict]:
    """Parse imports from a single Python file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=file_path)
    except (SyntaxError, UnicodeDecodeError):
        return []
    visitor = ImportVisitor(file_path, src_root)
    visitor.visit(tree)
    return visitor.imports


def collect_imports(src_root: str, include: list[str], exclude: list[str]) -> list[dict]:
    """Collect imports across all matched Python files."""
    all_imports: list[dict] = []
    matched_files: set[str] = set()
    for pattern in include:
        matched_files.update(glob.glob(os.path.join(src_root, pattern), recursive=True))
    for pattern in exclude:
        matched_files -= set(glob.glob(os.path.join(src_root, pattern), recursive=True))
    for fp in sorted(matched_files):
        if fp.endswith(".py") and os.path.isfile(fp):
            all_imports.extend(parse_file_imports(fp, src_root))
    return all_imports


def build_module_graph(imports: list[dict]) -> dict[str, set[str]]:
    """Build a module -> {imported_modules} adjacency graph."""
    graph: dict[str, set[str]] = defaultdict(set)
    for imp in imports:
        src = imp["module"]
        dst = imp["imports_from"]
        if dst and src != dst:
            graph[src].add(dst)
    return dict(graph)


def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Find all simple cycles in the module dependency graph via DFS."""
    cycles: list[list[str]] = []
    visited: set[str] = set()
    rec_stack: list[str] = []
    rec_set: set[str] = set()

    def dfs(node: str) -> None:
        visited.add(node)
        rec_stack.append(node)
        rec_set.add(node)
        for neighbor in graph.get(node, set()):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in rec_set:
                idx = rec_stack.index(neighbor)
                cycle = rec_stack[idx:] + [neighbor]
                if len(cycle) >= 3:
                    cycles.append(cycle)
        rec_stack.pop()
        rec_set.remove(node)

    for node in list(graph.keys()):
        if node not in visited:
            dfs(node)
    # Deduplicate cycles by their sorted tuple representation
    seen: set[tuple] = set()
    unique: list[list[str]] = []
    for c in cycles:
        key = tuple(sorted(c))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def compute_coupling(imports: list[dict]) -> dict[str, dict[str, int]]:
    """Compute Ca (afferent) and Ce (efferent) coupling per module."""
    ce: dict[str, set[str]] = defaultdict(set)  # outgoing
    ca: dict[str, set[str]] = defaultdict(set)  # incoming
    for imp in imports:
        src = imp["module"]
        dst = imp["imports_from"]
        if dst:
            ce[src].add(dst)
            ca[dst].add(src)
    all_modules = set(ce.keys()) | set(ca.keys())
    result: dict[str, dict[str, int]] = {}
    for mod in all_modules:
        ca_count = len(ca.get(mod, set()))
        ce_count = len(ce.get(mod, set()))
        total = ca_count + ce_count
        instability = ce_count / total if total > 0 else 0.0
        result[mod] = {"ca": ca_count, "ce": ce_count, "instability": round(instability, 2)}
    return result


def compute_complexity(file_path: str) -> list[dict]:
    """Compute per-function complexity metrics for a Python file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=file_path)
    except (SyntaxError, UnicodeDecodeError):
        return []

    functions: list[dict] = []

    class ComplexityVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.current_function: str | None = None
            self.cyclomatic = 1
            self.cognitive = 0
            self.nesting = 0

        def _inc_cyclomatic(self) -> None:
            self.cyclomatic += 1

        def _inc_cognitive(self, weight: int = 1) -> None:
            self.cognitive += weight * (1 + self.nesting)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            outer = self.current_function
            outer_cyc = self.cyclomatic
            outer_cog = self.cognitive
            outer_nest = self.nesting
            self.current_function = node.name
            self.cyclomatic = 1
            self.cognitive = 0
            self.nesting = 0
            self.generic_visit(node)
            func_loc = node.end_lineno - node.lineno if node.end_lineno else 0
            functions.append({
                "name": node.name,
                "file": file_path,
                "line": node.lineno,
                "cyclomatic": self.cyclomatic,
                "cognitive": self.cognitive,
                "loc": func_loc,
            })
            self.current_function = outer
            self.cyclomatic = outer_cyc
            self.cognitive = outer_cog
            self.nesting = outer_nest

        visit_AsyncFunctionDef = visit_FunctionDef  # noqa: N815

        def visit_If(self, node: ast.If) -> None:  # noqa: N802
            self._inc_cyclomatic()
            self._inc_cognitive()
            self.nesting += 1
            self.generic_visit(node)
            self.nesting -= 1

        def visit_For(self, node: ast.For) -> None:  # noqa: N802
            self._inc_cyclomatic()
            self._inc_cognitive()
            self.nesting += 1
            self.generic_visit(node)
            self.nesting -= 1

        def visit_While(self, node: ast.While) -> None:  # noqa: N802
            self._inc_cyclomatic()
            self._inc_cognitive()
            self.nesting += 1
            self.generic_visit(node)
            self.nesting -= 1

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:  # noqa: N802
            self._inc_cyclomatic()
            self._inc_cognitive()
            self.generic_visit(node)

        def visit_With(self, node: ast.With) -> None:  # noqa: N802
            self._inc_cognitive(weight=0)
            self.generic_visit(node)

        def visit_Try(self, node: ast.Try) -> None:  # noqa: N802
            self._inc_cognitive()
            self.nesting += 1
            self.generic_visit(node)
            self.nesting -= 1

        def visit_BoolOp(self, node: ast.BoolOp) -> None:  # noqa: N802
            self._inc_cyclomatic()
            self._inc_cognitive()
            self.generic_visit(node)

    ComplexityVisitor().visit(tree)
    return functions


def collect_api_surface(src_root: str, include: list[str], exclude: list[str]) -> list[dict]:
    """Collect public API surface information from Python modules."""
    issues: list[dict] = []
    matched_files: set[str] = set()
    for pattern in include:
        matched_files.update(glob.glob(os.path.join(src_root, pattern), recursive=True))
    for pattern in exclude:
        matched_files -= set(glob.glob(os.path.join(src_root, pattern), recursive=True))

    for fp in sorted(matched_files):
        if not fp.endswith(".py") or not os.path.isfile(fp):
            continue
        try:
            with open(fp, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source, filename=fp)
        except (SyntaxError, UnicodeDecodeError):
            continue

        # Check for __all__ definition
        has_all = False
        all_defined: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        has_all = True
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            all_defined = [
                                e.s for e in node.value.elts
                                if isinstance(e, ast.Constant) and isinstance(e.s, str)
                            ]

        # Check for internal imports in what appears to be public API files
        rel_path = os.path.relpath(fp, src_root)
        is_public = "public" in rel_path or "api" in rel_path
        is_internal = "internal" in rel_path or "/_" in rel_path

        if is_public and not has_all:
            issues.append({
                "file": fp,
                "line": 1,
                "type": "missing_all",
                "message": f"Public module {rel_path} missing __all__ definition",
            })

        # Check for internal path leaks in public files
        if is_public:
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if "internal" in mod or "._" in mod:
                        issues.append({
                            "file": fp,
                            "line": getattr(node, "lineno", 0),
                            "type": "internal_leak",
                            "message": f"Public module imports internal path: {mod}",
                        })

        # Check for @stable decorator changes (heuristic: presence check)
        source_lines = source.splitlines()
        for i, line in enumerate(source_lines, 1):
            if "@stable" in line and ("def " in source_lines[min(i, len(source_lines) - 1)] or "class " in source_lines[min(i, len(source_lines) - 1)]):
                # Just flag for manual review — we don't have a historical baseline
                issues.append({
                    "file": fp,
                    "line": i,
                    "type": "stable_marker",
                    "message": f"Symbol marked @stable at {fp}:{i} — verify signature stability",
                })

    return issues


# ---------------------------------------------------------------------------
# Constraint evaluators
# ---------------------------------------------------------------------------


def evaluate_layer_rule(rule: dict, imports: list[dict]) -> ConstraintResult:
    """Evaluate a layer_rule constraint against collected imports."""
    name = rule["name"]
    layers = {l["name"]: l["paths"] for l in rule.get("layers", [])}
    rules_spec = rule.get("rules", [])
    scoring_mode = rule.get("scoring", {}).get("mode", "ratio")
    severity = rule.get("severity", "warning")

    def _module_to_layer(mod: str) -> str | None:
        for layer_name, paths in layers.items():
            for p in paths:
                pattern = p.replace("**", ".*").replace("*", "[^/]*").rstrip("/")
                if re.search(pattern, mod):
                    return layer_name
        return None

    violations: list[Violation] = []
    total_checked = 0

    for imp in imports:
        src_layer = _module_to_layer(imp["module"])
        dst_layer = _module_to_layer(imp["imports_from"])
        if src_layer and dst_layer:
            total_checked += 1
            for r in rules_spec:
                if src_layer == r.get("from"):
                    forbidden = r.get("forbidden_to", [])
                    if dst_layer in forbidden:
                        violations.append(Violation(
                            file=imp["file"],
                            line=imp["line"],
                            message=f"Layer violation: {src_layer} -> {dst_layer} "
                                    f"(import {imp['imports_from']})",
                            severity=severity,
                            constraint=name,
                        ))

    if scoring_mode == "binary":
        score = 1.0 if not violations else 0.0
    else:
        score = 1.0 - (len(violations) / max(total_checked, 1))
        score = max(0.0, score)

    status = "PASS" if score >= 0.8 else ("CRITICAL" if score < 0.6 or severity == "critical" and violations else "WARNING")
    if scoring_mode == "binary" and violations and severity == "critical":
        status = "CRITICAL"

    return ConstraintResult(name=name, score=round(score, 2), status=status, violations=violations)


def evaluate_cycle_rule(rule: dict, imports: list[dict]) -> ConstraintResult:
    """Evaluate a cycle_rule constraint."""
    name = rule["name"]
    severity = rule.get("severity", "critical")
    graph = build_module_graph(imports)
    cycles = find_cycles(graph)

    violations: list[Violation] = []
    for cycle in cycles:
        cycle_str = " -> ".join(cycle)
        violations.append(Violation(
            file=cycle[0].replace(".", "/") + ".py",
            line=0,
            message=f"Cyclic dependency detected: {cycle_str}",
            severity=severity,
            constraint=name,
        ))

    score = 1.0 if not cycles else 0.0
    status = "PASS" if not cycles else ("CRITICAL" if severity == "critical" else "WARNING")
    return ConstraintResult(name=name, score=score, status=status, violations=violations)


def evaluate_coupling_rule(rule: dict, imports: list[dict]) -> ConstraintResult:
    """Evaluate a coupling_rule constraint."""
    name = rule["name"]
    thresholds = rule.get("thresholds", {})
    ce_max = thresholds.get("ce_max", 20)
    ca_max = thresholds.get("ca_max", 30)
    instability_min, instability_max = thresholds.get("instability_range", [0.0, 1.0])
    scoring_mode = rule.get("scoring", {}).get("mode", "ratio")
    penalty = rule.get("scoring", {}).get("penalty_per_excess", 0.05)
    severity = rule.get("severity", "warning")

    coupling = compute_coupling(imports)
    violations: list[Violation] = []
    total_penalty = 0.0

    for mod, metrics in coupling.items():
        excess_ce = max(0, metrics["ce"] - ce_max)
        excess_ca = max(0, metrics["ca"] - ca_max)
        i = metrics["instability"]
        i_breach = (i < instability_min) or (i > instability_max)

        if excess_ce > 0 or excess_ca > 0 or i_breach:
            msg = f"{mod}: Ce={metrics['ce']} Ca={metrics['ca']} I={i}"
            violations.append(Violation(
                file=mod.replace(".", "/") + ".py",
                line=0,
                message=msg,
                severity=severity,
                constraint=name,
            ))
            total_penalty += (excess_ce + excess_ca) * penalty
            if i_breach:
                total_penalty += penalty

    if scoring_mode == "binary":
        score = 1.0 if not violations else 0.0
    else:
        score = max(0.0, 1.0 - total_penalty)

    status = "PASS" if score >= 0.8 else ("CRITICAL" if score < 0.6 else "WARNING")
    return ConstraintResult(name=name, score=round(score, 2), status=status, violations=violations)


def evaluate_complexity_rule(rule: dict, src_root: str, include: list[str], exclude: list[str]) -> ConstraintResult:
    """Evaluate a complexity_rule constraint."""
    name = rule["name"]
    metrics_spec = rule.get("metrics", [])
    limits: dict[str, int] = {m["metric"]: m["max"] for m in metrics_spec}
    scoring_mode = rule.get("scoring", {}).get("mode", "ratio")
    budget_scope = rule.get("scoring", {}).get("budget_scope", "per_function")
    severity = rule.get("severity", "warning")

    matched_files: set[str] = set()
    for pattern in include:
        matched_files.update(glob.glob(os.path.join(src_root, pattern), recursive=True))
    for pattern in exclude:
        matched_files -= set(glob.glob(os.path.join(src_root, pattern), recursive=True))

    violations: list[Violation] = []
    total_functions = 0
    over_budget = 0
    total_excess = 0

    for fp in sorted(matched_files):
        if not fp.endswith(".py") or not os.path.isfile(fp):
            continue
        funcs = compute_complexity(fp)
        for f in funcs:
            total_functions += 1
            exceeded = False
            for metric, limit in limits.items():
                actual = f.get(metric, 0)
                if actual > limit:
                    exceeded = True
                    violations.append(Violation(
                        file=f["file"],
                        line=f["line"],
                        message=f"{f['name']}: {metric}={actual} (max {limit})",
                        severity=severity,
                        constraint=name,
                    ))
                    total_excess += (actual - limit)
            if exceeded:
                over_budget += 1

    if total_functions == 0:
        score = 1.0
    elif scoring_mode == "ratio":
        if budget_scope == "per_function":
            score = 1.0 - (over_budget / total_functions)
        else:
            score = max(0.0, 1.0 - (total_excess / max(total_functions, 1) * 0.05))
    else:
        score = 1.0 if over_budget == 0 else 0.0

    score = max(0.0, min(1.0, score))
    status = "PASS" if score >= 0.8 else ("CRITICAL" if score < 0.6 else "WARNING")
    return ConstraintResult(name=name, score=round(score, 2), status=status, violations=violations)


def evaluate_api_surface_rule(rule: dict, src_root: str, include: list[str], exclude: list[str]) -> ConstraintResult:
    """Evaluate an api_surface_rule constraint."""
    name = rule["name"]
    severity = rule.get("severity", "warning")
    scoring_mode = rule.get("scoring", {}).get("mode", "ratio")

    issues = collect_api_surface(src_root, include, exclude)
    violations: list[Violation] = []

    for issue in issues:
        sev = severity
        if issue["type"] in ("internal_leak",):
            sev = "critical"
        violations.append(Violation(
            file=issue["file"],
            line=issue["line"],
            message=issue["message"],
            severity=sev,
            constraint=name,
        ))

    if scoring_mode == "binary":
        score = 1.0 if not violations else 0.0
    else:
        # Penalize more heavily for internal leaks
        penalty = 0
        for v in violations:
            if "internal" in v.message.lower():
                penalty += 2
            else:
                penalty += 1
        score = max(0.0, 1.0 - (penalty * 0.05))

    status = "PASS" if score >= 0.8 else ("CRITICAL" if score < 0.6 else "WARNING")
    return ConstraintResult(name=name, score=round(score, 2), status=status, violations=violations)


# ---------------------------------------------------------------------------
# Baseline auto-generation
# ---------------------------------------------------------------------------


def generate_baseline_constraints(src_root: str) -> dict:
    """Generate a baseline constraint set from codebase structure."""
    # Heuristic layer detection from directory structure
    layers = []
    layer_candidates = {
        "domain": ["domain", "model", "entity", "core"],
        "application": ["app", "service", "usecase", "application"],
        "presentation": ["api", "ui", "view", "controller", "route", "handler"],
        "infrastructure": ["infra", "db", "cache", "repository", "adapter", "client"],
    }

    src_path = Path(src_root)
    detected: dict[str, list[str]] = {}
    if src_path.exists():
        for d in src_path.iterdir():
            if d.is_dir():
                dname = d.name.lower()
                for layer_name, keywords in layer_candidates.items():
                    if any(k in dname for k in keywords):
                        detected.setdefault(layer_name, []).append(str(d) + "/")

    if detected:
        layers = [{"name": k, "paths": v} for k, v in detected.items()]

    constraints = {
        "version": "1.0",
        "project": src_path.name or "project",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "evaluate_fitness.py --baseline",
        "categories": [
            {
                "name": "layering",
                "weight": 0.25,
                "constraints": [
                    {
                        "name": "auto_layer_rule",
                        "type": "layer_rule",
                        "description": "Auto-generated layer constraint from directory structure",
                        "severity": "warning",
                        "enabled": bool(layers),
                        "scope": {"type": "file", "include": ["**/*.py"], "exclude": []},
                        "layers": layers,
                        "rules": [],
                        "scoring": {"mode": "ratio"},
                    }
                ],
            },
            {
                "name": "cycles",
                "weight": 0.25,
                "constraints": [
                    {
                        "name": "auto_no_cycles",
                        "type": "cycle_rule",
                        "description": "No cyclic dependencies between modules",
                        "severity": "critical",
                        "enabled": True,
                        "scope": {"type": "module", "include": ["**/*.py"], "exclude": []},
                        "graph_source": "imports",
                        "granularity": "module",
                        "allow_self_cycles": False,
                        "scoring": {"mode": "binary"},
                    }
                ],
            },
            {
                "name": "coupling",
                "weight": 0.20,
                "constraints": [
                    {
                        "name": "auto_coupling_budget",
                        "type": "coupling_rule",
                        "description": "Keep per-module coupling within budget",
                        "severity": "warning",
                        "enabled": True,
                        "scope": {"type": "module", "include": ["**/*.py"], "exclude": []},
                        "thresholds": {"ce_max": 20, "ca_max": 30, "instability_range": [0.2, 0.8]},
                        "scoring": {"mode": "ratio", "penalty_per_excess": 0.05},
                    }
                ],
            },
            {
                "name": "complexity",
                "weight": 0.15,
                "constraints": [
                    {
                        "name": "auto_complexity_budget",
                        "type": "complexity_rule",
                        "description": "Functions must stay within complexity budget",
                        "severity": "warning",
                        "enabled": True,
                        "scope": {"type": "file", "include": ["**/*.py"], "exclude": ["**/*_test.py"]},
                        "metrics": [
                            {"metric": "cyclomatic", "max": 10},
                            {"metric": "cognitive", "max": 15},
                            {"metric": "lines_of_code", "max": 50},
                        ],
                        "scoring": {"mode": "ratio", "budget_scope": "per_function"},
                    }
                ],
            },
            {
                "name": "api_surface",
                "weight": 0.15,
                "constraints": [
                    {
                        "name": "auto_api_surface",
                        "type": "api_surface_rule",
                        "description": "Public API must not leak internal implementation details",
                        "severity": "warning",
                        "enabled": True,
                        "scope": {"type": "module", "include": ["**/*.py"], "exclude": []},
                        "rules": [
                            {"pattern": "public_from_internal", "description": "Detect internal path leaks"},
                            {"pattern": "export_consistency", "description": "Ensure __all__ is defined"},
                        ],
                        "scoring": {"mode": "ratio"},
                    }
                ],
            },
        ],
    }
    return constraints


# ---------------------------------------------------------------------------
# Main evaluation orchestrator
# ---------------------------------------------------------------------------


def load_constraints(path: str | None, src_root: str) -> dict:
    """Load constraints from file or generate baseline."""
    if path and os.path.isfile(path):
        if not HAS_YAML:
            print("ERROR: PyYAML required for constraint files. Install: pip install pyyaml", file=sys.stderr)
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    # Try auto-generated constraints
    auto_path = os.path.join(src_root, ".fitness", "auto_gen.yaml")
    if os.path.isfile(auto_path):
        if not HAS_YAML:
            print("ERROR: PyYAML required for constraint files. Install: pip install pyyaml", file=sys.stderr)
            sys.exit(1)
        with open(auto_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    # Fallback: baseline
    print("No constraint file found. Generating baseline constraints from codebase structure.", file=sys.stderr)
    return generate_baseline_constraints(src_root)


def evaluate_category(cat: dict, src_root: str) -> CategoryResult:
    """Evaluate all constraints in a category."""
    name = cat["name"]
    weight = cat.get("weight", 0.2)
    constraints = cat.get("constraints", [])
    results: list[ConstraintResult] = []

    # Collect imports once per category scope
    imports: list[dict] = []
    scope_include: list[str] = ["**/*.py"]
    scope_exclude: list[str] = []

    for c in constraints:
        scope = c.get("scope", {})
        scope_include = scope.get("include", scope_include)
        scope_exclude = scope.get("exclude", scope_exclude)
        break  # use first constraint's scope for import collection

    imports = collect_imports(src_root, scope_include, scope_exclude)

    for c in constraints:
        if not c.get("enabled", True):
            continue
        ctype = c.get("type")
        if ctype == "layer_rule":
            results.append(evaluate_layer_rule(c, imports))
        elif ctype == "cycle_rule":
            results.append(evaluate_cycle_rule(c, imports))
        elif ctype == "coupling_rule":
            results.append(evaluate_coupling_rule(c, imports))
        elif ctype == "complexity_rule":
            results.append(evaluate_complexity_rule(c, src_root, scope_include, scope_exclude))
        elif ctype == "api_surface_rule":
            results.append(evaluate_api_surface_rule(c, src_root, scope_include, scope_exclude))
        else:
            # Unknown type — skip with warning
            print(f"WARNING: Unknown constraint type '{ctype}' in {c.get('name', '?')}", file=sys.stderr)

    if not results:
        return CategoryResult(name=name, weight=weight, score=1.0, status="PASS")

    # Weighted average within category (constraints have equal weight unless specified)
    total_score = sum(r.score for r in results) / len(results)
    status = "PASS" if total_score >= 0.8 else ("CRITICAL" if total_score < 0.6 else "WARNING")

    return CategoryResult(
        name=name,
        weight=weight,
        score=round(total_score, 2),
        status=status,
        constraints=results,
    )


def compute_overall(categories: list[CategoryResult]) -> tuple[float, str]:
    """Compute overall score and gate decision."""
    total_weight = sum(c.weight for c in categories)
    if total_weight == 0:
        return 1.0, "PROCEED"
    overall = sum(c.score * c.weight for c in categories) / total_weight
    overall = round(max(0.0, min(1.0, overall)), 2)

    if overall >= 0.8:
        gate = "PROCEED"
    elif overall >= 0.6:
        gate = "WARN"
    else:
        gate = "HALT"

    return overall, gate


def serialize_result(result: FitnessResult) -> dict:
    """Convert result to JSON-serializable dict."""
    def _v(v: Violation) -> dict:
        return {"file": v.file, "line": v.line, "message": v.message,
                "severity": v.severity, "constraint": v.constraint}

    def _cr(cr: ConstraintResult) -> dict:
        return {"name": cr.name, "score": cr.score, "status": cr.status,
                "violations": [_v(v) for v in cr.violations]}

    def _cat(c: CategoryResult) -> dict:
        return {"name": c.name, "weight": c.weight, "score": c.score,
                "status": c.status, "delta": c.delta,
                "constraints": [_cr(cr) for cr in c.constraints]}

    return {
        "run_id": result.run_id,
        "timestamp": result.timestamp,
        "project": result.project,
        "trigger": result.trigger,
        "overall_score": result.overall_score,
        "gate": result.gate,
        "categories": [_cat(c) for c in result.categories],
        "violations": [_v(v) for v in result.violations],
        "trend": result.trend,
    }


def load_previous_result(src_root: str) -> dict | None:
    """Load the previous fitness result for delta calculation."""
    audit_path = os.path.join(src_root, ".fitness", "audit.log")
    if os.path.isfile(audit_path):
        try:
            with open(audit_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if lines:
                return json.loads(lines[-1].strip())
        except (json.JSONDecodeError, OSError):
            pass
    return None


def append_audit(result: FitnessResult, src_root: str) -> None:
    """Append evaluation record to audit log."""
    fitness_dir = os.path.join(src_root, ".fitness")
    os.makedirs(fitness_dir, exist_ok=True)
    audit_path = os.path.join(fitness_dir, "audit.log")

    record = {
        "timestamp": result.timestamp,
        "run_id": result.run_id,
        "overall_score": result.overall_score,
        "categories": {c.name: c.score for c in result.categories},
        "gate": result.gate,
        "trigger": result.trigger,
        "violations_count": len(result.violations),
    }

    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate architectural fitness functions")
    parser.add_argument("--constraints", "-c", default=None, help="Path to constraints YAML file")
    parser.add_argument("--src", "-s", default=".", help="Source root directory")
    parser.add_argument("--output", "-o", default=None, help="Output JSON file path")
    parser.add_argument("--baseline", action="store_true", help="Generate baseline constraints only")
    parser.add_argument("--trigger", default="manual", choices=["post-execute", "evolution", "manual"])
    args = parser.parse_args()

    src_root = os.path.abspath(args.src)
    if not os.path.isdir(src_root):
        print(f"ERROR: Source path not found: {src_root}", file=sys.stderr)
        sys.exit(2)

    # Ensure .fitness directory exists
    os.makedirs(os.path.join(src_root, ".fitness"), exist_ok=True)

    if args.baseline:
        baseline = generate_baseline_constraints(src_root)
        out_path = os.path.join(src_root, ".fitness", "auto_gen.yaml")
        if HAS_YAML:
            with open(out_path, "w", encoding="utf-8") as f:
                yaml.dump(baseline, f, default_flow_style=False, sort_keys=False)
        else:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(baseline, f, indent=2)
        print(f"Baseline constraints written to {out_path}")
        sys.exit(0)

    # Load and evaluate
    constraints = load_constraints(args.constraints, src_root)
    project = constraints.get("project", os.path.basename(src_root))
    categories_spec = constraints.get("categories", [])

    prev = load_previous_result(src_root)
    prev_scores: dict[str, float] = prev.get("categories", {}) if prev else {}

    cat_results: list[CategoryResult] = []
    all_violations: list[Violation] = []

    for cat_spec in categories_spec:
        cat_result = evaluate_category(cat_spec, src_root)
        prev_score = prev_scores.get(cat_result.name, cat_result.score)
        cat_result.delta = round(cat_result.score - prev_score, 2)
        cat_results.append(cat_result)
        for cr in cat_result.constraints:
            all_violations.extend(cr.violations)

    overall, gate = compute_overall(cat_results)

    result = FitnessResult(
        run_id=str(uuid.uuid4())[:8],
        timestamp=datetime.now(timezone.utc).isoformat(),
        project=project,
        trigger=args.trigger,
        overall_score=overall,
        gate=gate,
        categories=cat_results,
        violations=sorted(all_violations, key=lambda v: (0 if v.severity == "critical" else 1, v.file))[:50],
    )

    # Append to audit log
    append_audit(result, src_root)

    # Output
    serialized = serialize_result(result)
    output_json = json.dumps(serialized, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"Fitness result written to {args.output}")
    else:
        print(output_json)

    # Exit with non-zero on HALT so CI can catch it
    sys.exit(0 if gate != "HALT" else 3)


if __name__ == "__main__":
    main()
