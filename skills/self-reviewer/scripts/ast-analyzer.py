#!/usr/bin/env python3
"""
ast-analyzer.py — Deterministic AST-based code analyzer for SOLID, complexity,
coupling, and duplication. Part of the self-reviewer skill v4.0.

Design principle: ALL findings are derived from AST metrics. Same code always
produces the same findings. The LLM interprets results; it does NOT generate them.

Usage:
    python ast-analyzer.py --files src/users/service.py src/auth/handler.py
    python ast-analyzer.py --repo . --output-json findings.json

Outputs:
    - JSON/Markdown report with every finding containing:
        * metric: the AST-derived measurement (e.g., cyclomatic_complexity = 15)
        * threshold: the configured limit (e.g., 10)
        * location: file, line, function/class
"""

import argparse
import ast
import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple


# ─────────────────────────── Configuration / Thresholds ───────────────────────────

THRESHOLDS = {
    "cyclomatic_complexity": 10,
    "function_length": 50,
    "class_length": 500,
    "class_methods": 10,
    "interface_methods": 5,
    "nesting_depth": 4,
    "imports_per_file": 20,
    "duplication_min_lines": 5,
    "dip_instantiations_per_file": 3,
}

# High-level module path indicators used for DIP heuristics.
HIGH_LEVEL_INDICATORS = ("domain", "service", "usecase", "application", "core", "business")
# Low-level module path indicators.
LOW_LEVEL_INDICATORS = ("infrastructure", "db", "database", "http", "api", "storage", "file", "cache", "smtp")


# ─────────────────────────── Data model ───────────────────────────

@dataclass(frozen=True)
class Location:
    file: str
    line: int
    function: Optional[str] = None
    class_name: Optional[str] = None

    def as_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class MetricFinding:
    id: str
    severity: str  # critical, medium, low
    category: str  # solid, complexity, coupling, duplication, security
    metric: str  # e.g., "cyclomatic_complexity"
    value: float  # measured value
    threshold: float  # configured limit
    location: Location
    message: str
    rationale: str
    fix_suggestion: str
    ast_node_type: Optional[str] = None  # AST node type for traceability

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "severity": self.severity,
            "category": self.category,
            "metric": self.metric,
            "value": self.value,
            "threshold": self.threshold,
            "location": self.location.as_dict(),
            "message": self.message,
            "rationale": self.rationale,
            "fix_suggestion": self.fix_suggestion,
            "ast_node_type": self.ast_node_type,
        }


@dataclass
class AnalysisReport:
    summary: dict = field(default_factory=lambda: {
        "critical": 0, "medium": 0, "low": 0, "total": 0,
        "metrics_collected": 0,
    })
    findings: List[MetricFinding] = field(default_factory=list)
    blocked: bool = False


# ─────────────────────────── AST Helpers ───────────────────────────

class _MetricExtractor(ast.NodeVisitor):
    """Collects per-function and per-class raw metrics from an AST."""

    def __init__(self, source: str, filepath: str):
        self.source = source
        self.filepath = filepath
        self.functions: List[dict] = []
        self.classes: List[dict] = []
        self.imports: List[dict] = []
        self.instantiations: List[dict] = []
        self.switch_type_nodes: List[dict] = []
        self._func_stack: List[ast.FunctionDef] = []
        self._class_stack: List[ast.ClassDef] = []

    # ── Functions ──
    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._func_stack.append(node)
        self.generic_visit(node)
        self._func_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    # ── Classes ──
    def visit_ClassDef(self, node: ast.ClassDef):
        methods = [
            n for n in node.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        start = node.lineno
        end = node.end_lineno or start
        self.classes.append({
            "name": node.name,
            "start": start,
            "end": end,
            "lines": end - start,
            "methods": methods,
            "method_count": len(methods),
            "bases": [self._name(b) for b in node.bases],
            "node": node,
        })
        self._class_stack.append(node)
        self.generic_visit(node)
        self._class_stack.pop()

    # ── Imports ──
    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append({
                "line": node.lineno,
                "module": alias.name,
                "name": alias.asname or alias.name,
                "level": 0,
            })

    def visit_ImportFrom(self, node: ast.ImportFrom):
        mod = node.module or ""
        for alias in node.names:
            self.imports.append({
                "line": node.lineno,
                "module": f"{mod}.{alias.name}" if mod else alias.name,
                "name": alias.asname or alias.name,
                "level": node.level,
            })

    # ── Instantiations (DIP detection) ──
    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            self.instantiations.append({
                "line": node.lineno,
                "class_name": node.func.id,
                "node": node,
            })
        self.generic_visit(node)

    # ── Switch-on-type (OCP detection) ──
    def visit_If(self, node: ast.If):
        if self._is_type_switch(node.test):
            self.switch_type_nodes.append({
                "line": node.lineno,
                "node": node,
                "test": ast.dump(node.test),
            })
        self.generic_visit(node)

    # ── Helpers ──
    def _name(self, node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._name(node.value)}.{node.attr}"
        return ""

    @staticmethod
    def _is_type_switch(test: ast.expr) -> bool:
        """Detect isinstance(...) or type(...) == ... patterns."""
        # isinstance(x, SomeType)
        if isinstance(test, ast.Call):
            if isinstance(test.func, ast.Name) and test.func.id == "isinstance":
                return True
        # type(x) == SomeType or type(x) is SomeType
        if isinstance(test, (ast.Compare, ast.Is)):
            left = test.left if isinstance(test, ast.Compare) else test.left
            if isinstance(left, ast.Call) and isinstance(left.func, ast.Name) and left.func.id == "type":
                return True
        return False


def compute_cyclomatic_complexity(node: ast.AST) -> int:
    """Deterministic cyclomatic complexity from AST branching nodes."""
    complexity = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += len(child.values) - 1
        elif isinstance(child, ast.comprehension):
            complexity += 1
            if child.ifs:
                complexity += len(child.ifs)
        elif isinstance(child, ast.Try):
            complexity += len(child.handlers)
    return complexity


def compute_nesting_depth(node: ast.AST) -> int:
    """Maximum nesting depth of control-flow constructs inside a node."""
    max_depth = 0

    def _walk(n: ast.AST, depth: int):
        nonlocal max_depth
        if isinstance(n, (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.comprehension)):
            depth += 1
            max_depth = max(max_depth, depth)
        for child in ast.iter_child_nodes(n):
            _walk(child, depth)

    _walk(node, 0)
    return max_depth


def extract_function_metrics(extractor: _MetricExtractor) -> List[dict]:
    """Build deterministic per-function metrics from extracted raw data."""
    func_metrics: List[dict] = []
    for cls in extractor.classes:
        for method in cls["methods"]:
            func_metrics.append(_build_func_metric(extractor, method, class_name=cls["name"]))
    # Module-level functions not inside a class
    module_funcs = [
        n for n in ast.walk(ast.parse(extractor.source))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not getattr(n, "_parent_class", None)
    ]
    # We need module-level ones not already captured
    seen = {id(m) for cls in extractor.classes for m in cls["methods"]}
    for func in module_funcs:
        if id(func) not in seen:
            func_metrics.append(_build_func_metric(extractor, func, class_name=None))
    return func_metrics


def _build_func_metric(extractor: _MetricExtractor, node: ast.FunctionDef, class_name: Optional[str]) -> dict:
    start = node.lineno
    end = node.end_lineno or start
    body = node.body
    # Exclude docstring from line count
    docstring = ast.get_docstring(node)
    doc_lines = docstring.count("\n") + 1 if docstring else 0
    lines = end - start - doc_lines
    complexity = compute_cyclomatic_complexity(node)
    nesting = compute_nesting_depth(node)
    return {
        "name": node.name,
        "class_name": class_name,
        "start": start,
        "end": end,
        "lines": max(lines, 1),
        "complexity": complexity,
        "nesting": nesting,
        "args": [a.arg for a in node.args.args],
        "node": node,
    }


# ─────────────────────────── Normalized AST Hash (Duplication) ───────────────────────────

class _ASTHasher(ast.NodeVisitor):
    """Compute a structural hash of an AST subtree, ignoring variable names and literals."""

    def __init__(self):
        self._parts: List[str] = []

    def hash_node(self, node: ast.AST) -> str:
        self._parts = []
        self.visit(node)
        raw = "|".join(self._parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def generic_visit(self, node: ast.AST):
        self._parts.append(type(node).__name__)
        for field_name, field_value in ast.iter_fields(node):
            if isinstance(field_value, list):
                for item in field_value:
                    if isinstance(item, ast.AST):
                        self.visit(item)
                    elif isinstance(item, (str, int, float)):
                        self._parts.append(f"[{field_name}:LIT]")
            elif isinstance(field_value, ast.AST):
                self.visit(field_value)
            elif isinstance(field_value, (str, int, float)):
                self._parts.append(f"[{field_name}:LIT]")
            elif field_value is not None:
                self._parts.append(f"[{field_name}:{type(field_value).__name__}]")


def ast_subtree_hash(node: ast.AST) -> str:
    return _ASTHasher().hash_node(node)


def find_duplicates(trees: Dict[str, ast.AST], min_lines: int = 5) -> Iterator[Tuple[str, int, str, int, int]]:
    """
    Detect structurally similar code blocks across files.
    Yields: (file_a, line_a, file_b, line_b, shared_lines)
    """
    # Flatten all statement-level subtrees that are at least min_lines long
    hashes: Dict[str, List[Tuple[str, int, int, ast.AST]]] = {}
    for filepath, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.For, ast.While, ast.If, ast.With, ast.Try)):
                start = node.lineno
                end = node.end_lineno or start
                lines = end - start
                if lines >= min_lines:
                    h = ast_subtree_hash(node)
                    hashes.setdefault(h, []).append((filepath, start, lines, node))

    seen_pairs: Set[Tuple[str, int, str, int]] = set()
    for h, occurrences in hashes.items():
        if len(occurrences) < 2:
            continue
        # Report each pair once
        for i in range(len(occurrences)):
            for j in range(i + 1, len(occurrences)):
                fa, la, lines_a, _ = occurrences[i]
                fb, lb, lines_b, _ = occurrences[j]
                pair = tuple(sorted([(fa, la), (fb, lb)]))  # type: ignore[assignment]
                if pair not in seen_pairs:
                    seen_pairs.add(pair)  # type: ignore[arg-type]
                    yield (fa, la, fb, lb, min(lines_a, lines_b))


# ─────────────────────────── SOLID Check Engines ───────────────────────────

def check_srp(extractor: _MetricExtractor) -> Iterator[MetricFinding]:
    """Single Responsibility: flag classes with > THRESHOLD methods or lines."""
    for cls in extractor.classes:
        if cls["method_count"] > THRESHOLDS["class_methods"]:
            yield MetricFinding(
                id="",
                severity="medium",
                category="solid",
                metric="class_method_count",
                value=cls["method_count"],
                threshold=THRESHOLDS["class_methods"],
                location=Location(
                    file=extractor.filepath,
                    line=cls["start"],
                    class_name=cls["name"],
                ),
                message=(
                    f"Class '{cls['name']}' has {cls['method_count']} methods "
                    f"(threshold = {THRESHOLDS['class_methods']})"
                ),
                rationale="Large classes often violate Single Responsibility Principle, becoming hard to maintain.",
                fix_suggestion="Split into focused classes by responsibility (e.g., separate persistence from domain logic).",
                ast_node_type="ClassDef",
            )
        if cls["lines"] > THRESHOLDS["class_length"]:
            yield MetricFinding(
                id="",
                severity="medium",
                category="solid",
                metric="class_length_lines",
                value=cls["lines"],
                threshold=THRESHOLDS["class_length"],
                location=Location(
                    file=extractor.filepath,
                    line=cls["start"],
                    class_name=cls["name"],
                ),
                message=(
                    f"Class '{cls['name']}' spans {cls['lines']} lines "
                    f"(threshold = {THRESHOLDS['class_length']})"
                ),
                rationale="Excessive class length indicates accumulated responsibilities and change hotspots.",
                fix_suggestion="Extract cohesive behavior clusters into separate classes or module-level functions.",
                ast_node_type="ClassDef",
            )


def check_ocp(extractor: _MetricExtractor) -> Iterator[MetricFinding]:
    """Open/Closed: detect if/elif chains that switch on type (isinstance / type checks)."""
    # Count contiguous if/elif blocks with type switches
    tree = ast.parse(extractor.source)
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            chain = _collect_if_elif_chain(node)
            type_switch_count = sum(1 for n in chain if _MetricExtractor._is_type_switch(n.test))
            if type_switch_count >= 2:
                yield MetricFinding(
                    id="",
                    severity="medium",
                    category="solid",
                    metric="type_switch_chain_length",
                    value=type_switch_count,
                    threshold=2,
                    location=Location(
                        file=extractor.filepath,
                        line=node.lineno,
                    ),
                    message=(
                        f"Detected {type_switch_count}-branch type-switch chain "
                        f"(isinstance/type checks) starting at line {node.lineno}"
                    ),
                    rationale="Switching on type violates Open/Closed Principle: adding a variant requires modifying existing code.",
                    fix_suggestion="Replace conditionals with polymorphism (Strategy pattern) or introduce an abstraction/protocol for the variation point.",
                    ast_node_type="If",
                )


def _collect_if_elif_chain(node: ast.If) -> List[ast.If]:
    """Return the if + all directly chained elif nodes."""
    chain = [node]
    current = node
    while (
        len(current.orelse) == 1
        and isinstance(current.orelse[0], ast.If)
    ):
        current = current.orelse[0]
        chain.append(current)
    return chain


def check_lsp(extractor: _MetricExtractor) -> Iterator[MetricFinding]:
    """
    Liskov Substitution: flag method overrides that change parameter types
    (covariance/contravariance issues) compared to base method.
    """
    # Build inheritance map per file (naive: only bases declared in same file)
    class_methods: Dict[str, Dict[str, ast.FunctionDef]] = {}
    for cls in extractor.classes:
        methods = {m.name: m for m in cls["methods"]}
        class_methods[cls["name"]] = methods

    for cls in extractor.classes:
        for base_name in cls["bases"]:
            base_methods = class_methods.get(base_name)
            if not base_methods:
                continue
            for method_name, method in class_methods[cls["name"]].items():
                base_method = base_methods.get(method_name)
                if not base_method:
                    continue
                # Compare arg counts
                sub_args = _arg_sig(method)
                base_args = _arg_sig(base_method)
                if sub_args != base_args:
                    yield MetricFinding(
                        id="",
                        severity="critical",
                        category="solid",
                        metric="override_signature_change",
                        value=len(sub_args),
                        threshold=len(base_args),
                        location=Location(
                            file=extractor.filepath,
                            line=method.lineno,
                            function=method.name,
                            class_name=cls["name"],
                        ),
                        message=(
                            f"Method '{method.name}' in '{cls['name']}' overrides base "
                            f"'{base_name}' but changes parameter signature "
                            f"({sub_args} vs base {base_args})"
                        ),
                        rationale="LSP requires substitutability: subclass methods must accept the same arguments as the base.",
                        fix_suggestion="Redesign hierarchy to preserve base method contract, or use composition instead of inheritance.",
                        ast_node_type="FunctionDef",
                    )


def _arg_sig(node: ast.FunctionDef) -> Tuple[int, int, bool]:
    """Return (positional_count, kwonly_count, has_varargs, has_kwargs) flattened for comparison."""
    args = node.args
    pos = len(args.args) + len(args.posonlyargs)
    kw = len(args.kwonlyargs)
    var = args.vararg is not None
    kwarg = args.kwarg is not None
    return (pos, kw, var, kwarg)


def check_isp(extractor: _MetricExtractor) -> Iterator[MetricFinding]:
    """
    Interface Segregation: flag interfaces / protocols / ABCs with > threshold methods
    or mixed concerns (method names from disjoint semantic domains).
    """
    for cls in extractor.classes:
        # Identify interface-ish classes: no non-trivial method bodies, or ABC base
        is_abc = any(
            b in ("ABC", "abc.ABC") or "ABC" in b
            for b in cls["bases"]
        )
        is_protocol = any("Protocol" in b for b in cls["bases"])
        is_interface = is_abc or is_protocol or cls["name"].endswith("Interface")
        # Also treat classes where all methods are pass/raise NotImplementedError
        all_trivial = all(
            _is_trivial_method_body(m)
            for m in cls["methods"]
        )
        if not (is_interface or all_trivial):
            continue

        method_names = [m.name for m in cls["methods"]]
        if len(method_names) > THRESHOLDS["interface_methods"]:
            yield MetricFinding(
                id="",
                severity="low",
                category="solid",
                metric="interface_method_count",
                value=len(method_names),
                threshold=THRESHOLDS["interface_methods"],
                location=Location(
                    file=extractor.filepath,
                    line=cls["start"],
                    class_name=cls["name"],
                ),
                message=(
                    f"Interface/ABC '{cls['name']}' defines {len(method_names)} methods "
                    f"(threshold = {THRESHOLDS['interface_methods']})"
                ),
                rationale="Fat interfaces force clients to depend on methods they do not use, violating Interface Segregation.",
                fix_suggestion="Split into role-specific smaller protocols or ABCs; compose roles instead of single large inheritance.",
                ast_node_type="ClassDef",
            )

        # Mixed-concerns heuristic: method names span > 2 semantic prefixes
        prefixes = {name.split("_")[0] for name in method_names if "_" in name}
        if len(prefixes) > 2:
            yield MetricFinding(
                id="",
                severity="low",
                category="solid",
                metric="interface_mixed_concerns",
                value=len(prefixes),
                threshold=2,
                location=Location(
                    file=extractor.filepath,
                    line=cls["start"],
                    class_name=cls["name"],
                ),
                message=(
                    f"Interface '{cls['name']}' mixes {len(prefixes)} semantic concerns "
                    f"(prefixes: {sorted(prefixes)})"
                ),
                rationale="Mixed naming prefixes suggest unrelated responsibilities grouped in one interface.",
                fix_suggestion="Group methods by semantic role and extract separate interfaces for each role.",
                ast_node_type="ClassDef",
            )


def _is_trivial_method_body(node: ast.FunctionDef) -> bool:
    """True if body is only docstring + pass / ... / raise NotImplementedError."""
    body = node.body
    # Strip docstring
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, (ast.Constant, ast.Str)):
        body = body[1:]
    if not body:
        return True
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is ...:
            continue
        if isinstance(stmt, ast.Raise):
            # allow raise NotImplementedError
            continue
        return False
    return True


BUILTIN_NON_DI_CLASSES = frozenset({
    "True", "False", "None", "NotImplemented", "Ellipsis",
    "ValueError", "TypeError", "KeyError", "IndexError", "AttributeError",
    "RuntimeError", "AssertionError", "StopIteration", "OverflowError",
    "ZeroDivisionError", "NameError", "ImportError", "ModuleNotFoundError",
    "FileNotFoundError", "IOError", "OSError", "PermissionError",
    "MemoryError", "RecursionError", "SystemError", "SyntaxError",
    "ReferenceError", "BufferError", "LookupError", "ArithmeticError",
    "FloatingPointError", "EOFError", "GeneratorExit", "SystemExit",
    "KeyboardInterrupt", "Exception", "BaseException", "Warning",
    "UserWarning", "DeprecationWarning", "PendingDeprecationWarning",
    "RuntimeWarning", "FutureWarning", "ImportWarning", "UnicodeWarning",
    "BytesWarning", "ResourceWarning",
    "int", "float", "str", "list", "dict", "set", "tuple", "bool",
    "object", "type", "bytes", "bytearray", "memoryview", "frozenset",
    "complex", "range", "slice", "property", "classmethod", "staticmethod",
    "super", "vars", "locals", "globals", "repr", "ascii", "chr", "ord",
    "hex", "oct", "bin", "format", "filter", "map", "zip", "enumerate",
    "reversed", "sorted", "sum", "min", "max", "any", "all", "len",
    "abs", "round", "divmod", "pow", "callable", "hasattr", "getattr",
    "setattr", "delattr", "issubclass", "isinstance", "hasattr",
})


def check_dip(extractor: _MetricExtractor) -> Iterator[MetricFinding]:
    """
    Dependency Inversion: detect direct `ConcreteClass()` instantiations.
    Escalate severity if file path suggests high-level module.
    """
    filepath_lower = extractor.filepath.lower()
    is_high_level = any(ind in filepath_lower for ind in HIGH_LEVEL_INDICATORS)
    is_low_level = any(ind in filepath_lower for ind in LOW_LEVEL_INDICATORS)

    for inst in extractor.instantiations:
        class_name = inst["class_name"]
        # Heuristic: concrete if starts with uppercase and is not a builtin
        if not class_name or not class_name[0].isupper():
            continue
        if class_name in BUILTIN_NON_DI_CLASSES:
            continue
        severity = "medium" if is_high_level else "low"
        # If high-level module instantiates a low-level sounding class, escalate
        if is_high_level and any(ind in class_name.lower() for ind in LOW_LEVEL_INDICATORS):
            severity = "critical"

        yield MetricFinding(
            id="",
            severity=severity,
            category="solid",
            metric="direct_concrete_instantiation",
            value=1,
            threshold=0,
            location=Location(
                file=extractor.filepath,
                line=inst["line"],
            ),
            message=(
                f"Direct instantiation of concrete class '{class_name}' "
                f"in {'high-level' if is_high_level else 'module'} file"
            ),
            rationale="High-level modules should depend on abstractions, not concrete implementations.",
            fix_suggestion="Introduce a protocol/interface and inject the dependency, or use a factory at the composition root.",
            ast_node_type="Call",
        )

    # Batch threshold: too many direct instantiations in one file
    concrete_count = sum(
        1 for i in extractor.instantiations
        if i["class_name"] and i["class_name"][0].isupper()
    )
    if concrete_count > THRESHOLDS["dip_instantiations_per_file"]:
        yield MetricFinding(
            id="",
            severity="medium",
            category="solid",
            metric="direct_concrete_instantiation_count",
            value=concrete_count,
            threshold=THRESHOLDS["dip_instantiations_per_file"],
            location=Location(file=extractor.filepath, line=1),
            message=(
                f"File contains {concrete_count} direct concrete instantiations "
                f"(threshold = {THRESHOLDS['dip_instantiations_per_file']})"
            ),
            rationale="Files with many direct instantiations are tightly coupled to concrete implementations.",
            fix_suggestion="Refactor to dependency injection or a factory pattern to reduce coupling.",
            ast_node_type="Module",
        )


# ─────────────────────────── Complexity Checks ───────────────────────────

def check_complexity(extractor: _MetricExtractor) -> Iterator[MetricFinding]:
    """Cyclomatic complexity, function length, nesting depth from AST."""
    funcs = extract_function_metrics(extractor)
    for func in funcs:
        if func["complexity"] > THRESHOLDS["cyclomatic_complexity"]:
            yield MetricFinding(
                id="",
                severity="medium",
                category="complexity",
                metric="cyclomatic_complexity",
                value=func["complexity"],
                threshold=THRESHOLDS["cyclomatic_complexity"],
                location=Location(
                    file=extractor.filepath,
                    line=func["start"],
                    function=func["name"],
                    class_name=func["class_name"],
                ),
                message=(
                    f"Function '{func['name']}' cyclomatic complexity = {func['complexity']} "
                    f"(threshold = {THRESHOLDS['cyclomatic_complexity']})"
                ),
                rationale="High complexity increases bug density and reduces testability.",
                fix_suggestion="Extract helper functions for branches, replace nested conditionals with lookup tables or polymorphism.",
                ast_node_type="FunctionDef",
            )
        if func["lines"] > THRESHOLDS["function_length"]:
            yield MetricFinding(
                id="",
                severity="low",
                category="complexity",
                metric="function_length_lines",
                value=func["lines"],
                threshold=THRESHOLDS["function_length"],
                location=Location(
                    file=extractor.filepath,
                    line=func["start"],
                    function=func["name"],
                    class_name=func["class_name"],
                ),
                message=(
                    f"Function '{func['name']}' length = {func['lines']} lines "
                    f"(threshold = {THRESHOLDS['function_length']})"
                ),
                rationale="Long functions are harder to read, test, and reuse.",
                fix_suggestion="Extract cohesive blocks into private helpers. Target < 50 lines per function.",
                ast_node_type="FunctionDef",
            )
        if func["nesting"] > THRESHOLDS["nesting_depth"]:
            yield MetricFinding(
                id="",
                severity="medium",
                category="complexity",
                metric="nesting_depth",
                value=func["nesting"],
                threshold=THRESHOLDS["nesting_depth"],
                location=Location(
                    file=extractor.filepath,
                    line=func["start"],
                    function=func["name"],
                    class_name=func["class_name"],
                ),
                message=(
                    f"Function '{func['name']}' max nesting depth = {func['nesting']} "
                    f"(threshold = {THRESHOLDS['nesting_depth']})"
                ),
                rationale="Deep nesting harms readability and suggests missing abstractions.",
                fix_suggestion="Use guard clauses to flatten early exits, or extract nested logic into named helpers.",
                ast_node_type="FunctionDef",
            )


# ─────────────────────────── Coupling Checks ───────────────────────────

def check_coupling(extractor: _MetricExtractor, all_extractors: List[_MetricExtractor]) -> Iterator[MetricFinding]:
    """Tight coupling via import graph analysis and cross-domain imports."""
    imports = extractor.imports
    if len(imports) > THRESHOLDS["imports_per_file"]:
        yield MetricFinding(
            id="",
            severity="medium",
            category="coupling",
            metric="imports_per_file",
            value=len(imports),
            threshold=THRESHOLDS["imports_per_file"],
            location=Location(file=extractor.filepath, line=1),
            message=(
                f"File has {len(imports)} imports "
                f"(threshold = {THRESHOLDS['imports_per_file']})"
            ),
            rationale="Excessive imports indicate the module may be assuming too many responsibilities or lacking cohesion.",
            fix_suggestion="Refactor into smaller modules, each with a focused set of dependencies.",
            ast_node_type="Module",
        )

    # Cross-domain: high-level module importing low-level module
    filepath_lower = extractor.filepath.lower()
    is_high_level = any(ind in filepath_lower for ind in HIGH_LEVEL_INDICATORS)
    for imp in imports:
        module_lower = imp["module"].lower()
        if is_high_level and any(ind in module_lower for ind in LOW_LEVEL_INDICATORS):
            yield MetricFinding(
                id="",
                severity="critical",
                category="coupling",
                metric="cross_domain_import",
                value=1,
                threshold=0,
                location=Location(
                    file=extractor.filepath,
                    line=imp["line"],
                ),
                message=(
                    f"High-level module imports low-level module '{imp['module']}' "
                    f"(crosses domain boundary)"
                ),
                rationale="Domain-layer modules should not depend on infrastructure-layer modules per Dependency Inversion.",
                fix_suggestion="Introduce a port/interface in the domain layer and implement an adapter in the infrastructure layer.",
                ast_node_type="ImportFrom",
            )

    # Circular import detection (within analyzed set)
    file_mod = _module_from_path(extractor.filepath)
    for other in all_extractors:
        if other is extractor:
            continue
        other_mod = _module_from_path(other.filepath)
        # Does extractor import other?
        imports_other = any(
            imp["module"].startswith(other_mod) or imp["module"] == other_mod
            for imp in imports
        )
        # Does other import extractor?
        other_imports_this = any(
            imp["module"].startswith(file_mod) or imp["module"] == file_mod
            for imp in other.imports
        )
        if imports_other and other_imports_this:
            yield MetricFinding(
                id="",
                severity="critical",
                category="coupling",
                metric="circular_import",
                value=1,
                threshold=0,
                location=Location(file=extractor.filepath, line=1),
                message=(
                    f"Circular import detected between '{extractor.filepath}' "
                    f"and '{other.filepath}'"
                ),
                rationale="Circular dependencies create tight coupling, make testing harder, and complicate deployment.",
                fix_suggestion="Extract shared types into a neutral common/types package, or apply dependency inversion to break the cycle.",
                ast_node_type="Module",
            )
            # Yield only once per pair; break after first discovery for this pair
            break


def _module_from_path(filepath: str) -> str:
    """Naive conversion of filepath to dotted module name for cross-import checks."""
    p = Path(filepath)
    parts = p.with_suffix("").parts
    # Strip leading /mnt/... or src/ etc.
    if parts and parts[0] in ("/", "\\"):
        parts = parts[1:]
    if parts and parts[0] in ("mnt", "agents", "output", "src", "lib", "app"):
        parts = parts[1:]
    return ".".join(parts)


# ─────────────────────────── Duplication Checks ───────────────────────────

def check_duplication(trees: Dict[str, ast.AST]) -> Iterator[MetricFinding]:
    """Code duplication via normalized AST hash comparison."""
    for fa, la, fb, lb, shared_lines in find_duplicates(trees, THRESHOLDS["duplication_min_lines"]):
        yield MetricFinding(
            id="",
            severity="medium",
            category="duplication",
            metric="duplicate_ast_subtree_lines",
            value=shared_lines,
            threshold=THRESHOLDS["duplication_min_lines"],
            location=Location(file=fa, line=la),
            message=(
                f"AST-duplicate block of ~{shared_lines} lines found in '{fa}:{la}' "
                f"and '{fb}:{lb}'"
            ),
            rationale="Duplicated code increases maintenance burden and risk of inconsistent fixes.",
            fix_suggestion="Extract the common block into a shared function, class, or utility.",
            ast_node_type="Module",
        )


# ─────────────────────────── Orchestration ───────────────────────────

def analyze_file(filepath: Path) -> Optional[_MetricExtractor]:
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"[WARN] Syntax error in {filepath}: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[WARN] Could not read {filepath}: {e}", file=sys.stderr)
        return None

    extractor = _MetricExtractor(source, str(filepath))
    extractor.visit(tree)
    return extractor


def run_analysis(files: List[Path]) -> AnalysisReport:
    report = AnalysisReport()
    extractors: List[_MetricExtractor] = []
    trees: Dict[str, ast.AST] = {}

    # Phase 1: parse all files deterministically
    for filepath in files:
        ex = analyze_file(filepath)
        if ex:
            extractors.append(ex)
            trees[str(filepath)] = ast.parse(ex.source)
            report.summary["metrics_collected"] += 1

    # Phase 2: per-file checks
    for ex in extractors:
        for finding in check_srp(ex):
            report.findings.append(finding)
        for finding in check_ocp(ex):
            report.findings.append(finding)
        for finding in check_lsp(ex):
            report.findings.append(finding)
        for finding in check_isp(ex):
            report.findings.append(finding)
        for finding in check_dip(ex):
            report.findings.append(finding)
        for finding in check_complexity(ex):
            report.findings.append(finding)
        for finding in check_coupling(ex, extractors):
            report.findings.append(finding)

    # Phase 3: cross-file checks
    for finding in check_duplication(trees):
        report.findings.append(finding)

    # Deduplicate by (file, line, metric)
    seen: Set[Tuple[str, int, str]] = set()
    deduped: List[MetricFinding] = []
    for f in report.findings:
        key = (f.location.file, f.location.line, f.metric)
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    report.findings = deduped

    # Renumber IDs
    for idx, f in enumerate(report.findings, start=1):
        f.id = f"A{idx:03d}"

    # Summary
    for f in report.findings:
        report.summary["total"] += 1
        report.summary[f.severity] += 1
    report.blocked = report.summary["critical"] > 0

    return report


def generate_markdown(report: AnalysisReport) -> str:
    lines: List[str] = []
    lines.append("## AST Analysis Report (Deterministic)\n")
    s = report.summary
    lines.append(
        f"### Summary\n"
        f"- **Critical**: {s['critical']} | **Medium**: {s['medium']} | **Low**: {s['low']} | **Total**: {s['total']}\n"
        f"- **Metrics collected**: {s['metrics_collected']}\n"
    )

    def section(title: str, sev: str):
        findings = [f for f in report.findings if f.severity == sev]
        if not findings:
            return
        lines.append(f"### {title} Findings\n")
        for f in findings:
            lines.append(f"#### {f.id} — {f.message}")
            loc = f.location
            lines.append(f"- **File**: `{loc.file}:{loc.line}`")
            if loc.function:
                lines.append(f"- **Function**: `{loc.function}`")
            if loc.class_name:
                lines.append(f"- **Class**: `{loc.class_name}`")
            lines.append(f"- **Metric**: `{f.metric} = {f.value}` (threshold = {f.threshold})")
            lines.append(f"- **Severity**: {f.severity.upper()}")
            lines.append(f"- **Category**: {f.category}")
            lines.append(f"- **AST node**: {f.ast_node_type or 'N/A'}")
            lines.append(f"- **Rationale**: {f.rationale}")
            lines.append(f"- **Fix suggestion**: {f.fix_suggestion}")
            lines.append("")

    section("Critical (Delivery Blocked)", "critical")
    section("Medium", "medium")
    section("Low", "low")
    return "\n".join(lines)


def generate_json(report: AnalysisReport) -> str:
    return json.dumps({
        "summary": report.summary,
        "blocked": report.blocked,
        "findings": [f.to_dict() for f in report.findings],
    }, indent=2)


# ─────────────────────────── CLI ───────────────────────────

def load_files_from_args(args) -> List[Path]:
    files: List[Path] = []
    if args.files:
        files.extend(Path(f) for f in args.files)
    if args.repo:
        repo = Path(args.repo)
        for py_file in repo.rglob("*.py"):
            if ".venv" not in str(py_file) and "__pycache__" not in str(py_file):
                files.append(py_file)
    if args.since:
        import subprocess
        result = subprocess.run(
            ["git", "diff", "--name-only", args.since],
            capture_output=True,
            text=True,
            cwd=args.repo or ".",
        )
        for line in result.stdout.strip().splitlines():
            p = Path(line)
            if p.exists() and p.suffix == ".py":
                files.append(p)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic AST-based code analyzer")
    parser.add_argument("--files", nargs="+", help="Python files to analyze")
    parser.add_argument("--repo", help="Repository root to scan")
    parser.add_argument("--since", help="Git commit range (e.g., HEAD~1)")
    parser.add_argument("--output-json", help="Path to write JSON report")
    parser.add_argument("--output-md", help="Path to write Markdown report")
    args = parser.parse_args()

    if not any([args.files, args.repo]):
        parser.print_help()
        return 2

    files = load_files_from_args(args)
    if not files:
        print("No Python files found to analyze.", file=sys.stderr)
        return 2

    report = run_analysis(files)
    md_output = generate_markdown(report)
    json_output = generate_json(report)

    # If JSON to stdout requested, emit JSON and skip default Markdown
    if args.output_json == "-":
        print(json_output)
    else:
        if args.output_md:
            Path(args.output_md).write_text(md_output, encoding="utf-8")
            print(f"Markdown report written to {args.output_md}")
        else:
            print(md_output)

    if args.output_json and args.output_json != "-":
        Path(args.output_json).write_text(json_output, encoding="utf-8")
        print(f"JSON report written to {args.output_json}")

    return 1 if report.blocked else 0


if __name__ == "__main__":
    sys.exit(main())
