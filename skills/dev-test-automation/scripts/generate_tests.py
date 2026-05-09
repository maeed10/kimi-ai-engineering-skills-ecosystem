#!/usr/bin/env python3
"""
generate_tests.py — Analyze source code and generate test scaffolds.

Supports Python, JavaScript, TypeScript, and Go.
Uses static analysis to extract functions/classes, signatures, raised exceptions,
and branch points, then emits a test file with Arrange-Act-Assert structure.

Usage:
    python generate_tests.py --source src/billing/calc.py --framework pytest --output tests/unit/test_calc.py
    python generate_tests.py --source src/utils/parser.ts --framework vitest --output src/utils/__tests__/parser.test.ts
    python generate_tests.py --source pkg/orders/service.go --framework go_test --output pkg/orders/service_test.go
"""

import argparse
import ast
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Parameter:
    name: str
    type_hint: str = ""
    default: str = ""


@dataclass
class FunctionInfo:
    name: str
    parameters: List[Parameter]
    return_type: str = ""
    is_async: bool = False
    is_method: bool = False
    raises: List[str] = field(default_factory=list)
    has_branching: bool = False
    docstring: str = ""
    decorators: List[str] = field(default_factory=list)


@dataclass
class ClassInfo:
    name: str
    methods: List[FunctionInfo]
    docstring: str = ""


@dataclass
class ModuleInfo:
    functions: List[FunctionInfo]
    classes: List[ClassInfo]
    imports: List[str] = field(default_factory=list)
    language: str = ""
    module_name: str = ""


# ---------------------------------------------------------------------------
# Python parser
# ---------------------------------------------------------------------------

class PythonAnalyzer(ast.NodeVisitor):
    def __init__(self, source: str):
        self.source = source
        self.functions: List[FunctionInfo] = []
        self.classes: List[ClassInfo] = []
        self.imports: List[str] = []
        self._current_class: Optional[ClassInfo] = None

    def analyze(self) -> ModuleInfo:
        tree = ast.parse(self.source)
        self.visit(tree)
        return ModuleInfo(
            functions=self.functions,
            classes=self.classes,
            imports=self.imports,
            language="python",
            module_name="",
        )

    def visit_Import(self, node: ast.Import):  # type: ignore[override]
        for alias in node.names:
            self.imports.append(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom):  # type: ignore[override]
        module = node.module or ""
        for alias in node.names:
            self.imports.append(f"{module}.{alias.name}")

    def visit_ClassDef(self, node: ast.ClassDef):  # type: ignore[override]
        cls = ClassInfo(name=node.name, methods=[], docstring=ast.get_docstring(node) or "")
        self.classes.append(cls)
        prev = self._current_class
        self._current_class = cls
        self.generic_visit(node)
        self._current_class = prev

    def visit_FunctionDef(self, node):  # type: ignore[override]
        self._process_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node):  # type: ignore[override]
        self._process_function(node, is_async=True)

    def _process_function(self, node, is_async: bool):
        params: List[Parameter] = []
        for arg in node.args.args:
            params.append(Parameter(name=arg.arg, type_hint=self._annotation(arg.annotation)))
        for arg in node.args.kwonlyargs:
            params.append(Parameter(name=arg.arg, type_hint=self._annotation(arg.annotation)))
        if node.args.vararg:
            params.append(Parameter(name=f"*{node.args.vararg.arg}"))
        if node.args.kwarg:
            params.append(Parameter(name=f"**{node.args.kwarg.arg}"))

        return_type = self._annotation(node.returns)
        decorators = [self._annotation(d) for d in node.decorator_list]

        raises = []
        has_branching = False
        for child in ast.walk(node):
            if isinstance(child, ast.Raise):
                exc_name = "Exception"
                if isinstance(child.exc, ast.Call) and isinstance(child.exc.func, ast.Name):
                    exc_name = child.exc.func.id
                elif isinstance(child.exc, ast.Name):
                    exc_name = child.exc.id
                raises.append(exc_name)
            if isinstance(child, (ast.If, ast.Try, ast.For, ast.While, ast.With)):
                has_branching = True

        info = FunctionInfo(
            name=node.name,
            parameters=params,
            return_type=return_type,
            is_async=is_async,
            is_method=self._current_class is not None,
            raises=list(set(raises)),
            has_branching=has_branching,
            docstring=ast.get_docstring(node) or "",
            decorators=decorators,
        )

        if self._current_class:
            self._current_class.methods.append(info)
        else:
            self.functions.append(info)

    def _annotation(self, node) -> str:
        if node is None:
            return ""
        try:
            return ast.unparse(node)
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# JavaScript / TypeScript parser (regex + lightweight)
# ---------------------------------------------------------------------------

JS_TS_FUNCTION_RE = re.compile(
    r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\((.*?)\)(?:\s*:\s*([^{;]+))?",
    re.DOTALL,
)
JS_TS_ARROW_RE = re.compile(
    r"(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\((.*?)\)|(\w+))\s*=>",
    re.DOTALL,
)
JS_TS_METHOD_RE = re.compile(
    r"(?:async\s+)?(\w+)\s*\((.*?)\)(?:\s*:\s*([^{;]+))?\s*\{",
    re.DOTALL,
)
JS_TS_CLASS_RE = re.compile(r"(?:export\s+)?class\s+(\w+)")
JS_TS_IMPORT_RE = re.compile(r"import\s+.*?\s+from\s+['\"](.+?)['\"];?")
JS_TS_REQUIRE_RE = re.compile(r"(?:const|let|var)\s+.*?=\s+require\(['\"](.+?)['\"]\);?")
JS_TS_THROW_RE = re.compile(r"\bthrow\s+(?:new\s+)?(\w+)")


def _js_ts_param_list(raw: str) -> List[Parameter]:
    params: List[Parameter] = []
    if not raw.strip():
        return params
    # Simple split — good enough for scaffolding
    depth = 0
    current = ""
    for ch in raw:
        if ch in "([{":
            depth += 1
        elif ch in ")]}" and depth > 0:
            depth -= 1
        if ch == "," and depth == 0:
            params.append(_parse_single_param(current.strip()))
            current = ""
        else:
            current += ch
    if current.strip():
        params.append(_parse_single_param(current.strip()))
    return params


def _parse_single_param(raw: str) -> Parameter:
    raw = raw.strip()
    if "=" in raw:
        name_part, default = raw.split("=", 1)
        name_part = name_part.strip()
        default = default.strip()
    else:
        name_part = raw
        default = ""
    if ":" in name_part:
        name, type_hint = name_part.split(":", 1)
        return Parameter(name=name.strip(), type_hint=type_hint.strip(), default=default)
    return Parameter(name=name_part, default=default)


class JsTsAnalyzer:
    def __init__(self, source: str):
        self.source = source

    def analyze(self) -> ModuleInfo:
        functions: List[FunctionInfo] = []
        classes: List[ClassInfo] = []
        imports: List[str] = []

        for m in JS_TS_IMPORT_RE.finditer(self.source):
            imports.append(m.group(1))
        for m in JS_TS_REQUIRE_RE.finditer(self.source):
            imports.append(m.group(1))

        # Top-level functions
        for m in JS_TS_FUNCTION_RE.finditer(self.source):
            name, params_raw, ret = m.groups()
            functions.append(self._build_func(name, params_raw, ret))
        for m in JS_TS_ARROW_RE.finditer(self.source):
            name, params_paren, param_single = m.groups()
            params_raw = params_paren if params_paren else param_single
            functions.append(self._build_func(name, params_raw, ""))

        # Classes and methods
        for cm in JS_TS_CLASS_RE.finditer(self.source):
            cls_name = cm.group(1)
            cls = ClassInfo(name=cls_name, methods=[])
            # Extract class body roughly
            start = cm.end()
            brace_match = re.search(r"\{", self.source[start:])
            if brace_match:
                body_start = start + brace_match.start()
                body = self._extract_braced(body_start)
                for m in JS_TS_METHOD_RE.finditer(body):
                    mname, params_raw, ret = m.groups()
                    cls.methods.append(self._build_func(mname, params_raw, ret, is_method=True))
            classes.append(cls)

        return ModuleInfo(
            functions=functions,
            classes=classes,
            imports=imports,
            language="javascript",
            module_name="",
        )

    def _build_func(self, name, params_raw, ret, is_method=False) -> FunctionInfo:
        body_start = self.source.find("{", self.source.find(name))
        body = self._extract_braced(body_start) if body_start != -1 else ""
        raises = list(set(JS_TS_THROW_RE.findall(body)))
        has_branching = any(k in body for k in ("if ", "switch", "try", "catch", "for ", "while "))
        is_async = "async " in self.source[max(0, body_start - 20):body_start]
        return FunctionInfo(
            name=name,
            parameters=_js_ts_param_list(params_raw or ""),
            return_type=(ret or "").strip(),
            is_async=is_async,
            is_method=is_method,
            raises=raises,
            has_branching=has_branching,
        )

    def _extract_braced(self, open_idx: int) -> str:
        depth = 0
        for i, ch in enumerate(self.source[open_idx:], start=open_idx):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return self.source[open_idx : i + 1]
        return self.source[open_idx:]


# ---------------------------------------------------------------------------
# Go parser (regex + lightweight)
# ---------------------------------------------------------------------------

GO_FUNC_RE = re.compile(
    r"(?:\/\/.*?\n)*^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\((.*?)\)\s*(?:\((.*?)\)\s*|(\S+)\s*)?\{",
    re.MULTILINE | re.DOTALL,
)
GO_IMPORT_RE = re.compile(r'"([^"]+)"')
GO_THROW_RE = re.compile(r"\breturn\s+(?:fmt\.Errorf|errors\.New)")


def _go_param_list(raw: str) -> List[Parameter]:
    params: List[Parameter] = []
    if not raw.strip():
        return params
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    # Go groups by type: "a, b int, c string"
    i = len(parts) - 1
    current_type = ""
    while i >= 0:
        p = parts[i]
        if " " in p:
            name, typ = p.rsplit(" ", 1)
            params.insert(0, Parameter(name=name.strip(), type_hint=typ.strip()))
            current_type = typ.strip()
        else:
            params.insert(0, Parameter(name=p, type_hint=current_type))
        i -= 1
    return params


class GoAnalyzer:
    def __init__(self, source: str):
        self.source = source

    def analyze(self) -> ModuleInfo:
        functions: List[FunctionInfo] = []
        imports: List[str] = []

        # Extract imports block roughly
        import_match = re.search(r"import\s*\((.*?)\)", self.source, re.DOTALL)
        if import_match:
            imports = GO_IMPORT_RE.findall(import_match.group(1))
        else:
            single_import = re.search(r'import\s+"([^"]+)"', self.source)
            if single_import:
                imports = [single_import.group(1)]

        for m in GO_FUNC_RE.finditer(self.source):
            # Skip methods with receivers (e.g., "func (s *Service) ProcessOrder")
            matched_text = m.group(0)
            func_name = m.group(1)
            # Detect receiver: text between "func " and function name contains "("
            prefix = matched_text[:matched_text.index(func_name)]
            if "(" in prefix.replace("func ", "", 1):
                continue  # skip receiver methods

            name, params_raw, multi_ret, single_ret = m.groups()
            ret = (multi_ret or single_ret or "").strip()
            body_start = m.end() - 1
            body = self._extract_braced(body_start)
            has_branching = any(k in body for k in ("if ", "switch", "for ", "range ", "select "))
            raises = []
            if "error" in ret.lower():
                raises.append("error")
            functions.append(
                FunctionInfo(
                    name=name,
                    parameters=_go_param_list(params_raw or ""),
                    return_type=ret,
                    is_async=False,
                    is_method=bool(m.group(0).startswith("func (")),
                    raises=raises,
                    has_branching=has_branching,
                )
            )

        return ModuleInfo(
            functions=functions,
            classes=[],
            imports=imports,
            language="go",
            module_name="",
        )

    def _extract_braced(self, open_idx: int) -> str:
        depth = 0
        for i, ch in enumerate(self.source[open_idx:], start=open_idx):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return self.source[open_idx : i + 1]
        return self.source[open_idx:]


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

EDGE_CASE_MAP = {
    "int": ["0", "-1", "1", "999999"],
    "float": ["0.0", "-1.0", "1.0", "1e9"],
    "str": ['""', '"hello"', '"a" * 10000'],
    "string": ['""', '"hello"'],
    "[]": ["[]", "[1]", "[1, 2, 3]"],
    "map": ["{}", '{"a": 1}'],
    "dict": ["{}", '{"a": 1}'],
    "list": ["[]", "[1]", "[1, 2, 3]"],
    "bool": ["True", "False"],
    "boolean": ["true", "false"],
}


def _guess_edge(param: Parameter, lang: str) -> List[str]:
    type_lower = param.type_hint.lower()
    for key, cases in EDGE_CASE_MAP.items():
        if key in type_lower:
            return cases
    if param.default:
        if lang in ("python", "javascript"):
            return [param.default, "None" if lang == "python" else "null"]
    return ['"example"']


def _is_mockable_import(imp: str) -> bool:
    mockable = ["requests", "httpx", "axios", "fetch", "fs", "os", "pathlib", "db", "sqlalchemy", "mongodb"]
    return any(m in imp.lower() for m in mockable)


def _mock_suggestions(imports: List[str]) -> List[str]:
    return [imp for imp in imports if _is_mockable_import(imp)]


class PytestGenerator:
    def generate(self, module: ModuleInfo, module_path: str) -> str:
        lines: List[str] = []
        module_name = Path(module_path).stem
        rel_import = _python_relative_import(module_path)

        lines.append("import pytest")
        lines.append("from unittest.mock import Mock, patch")
        if rel_import:
            lines.append(f"from {rel_import} import {module_name}")
        lines.append("")

        mocks = _mock_suggestions(module.imports)
        if mocks:
            lines.append(f"# Mock suggestions: {', '.join(mocks)}")
            lines.append("")

        for func in module.functions:
            lines.extend(self._generate_function(func, module_name))
        for cls in module.classes:
            lines.extend(self._generate_class(cls, module_name))

        return "\n".join(lines)

    def _generate_function(self, func: FunctionInfo, mod_name: str) -> List[str]:
        out: List[str] = []
        out.append(f"class Test{func.name.title()}:")
        out.append("")

        # Happy path
        out.append(f"    def test_{func.name}_success(self):")
        out.append("        # Arrange")
        for p in func.parameters:
            if p.name in ("self", "cls"):
                continue
            val = _guess_edge(p, "python")[0]
            out.append(f"        {p.name} = {val}")
        out.append("")
        out.append("        # Act")
        args = ", ".join(p.name for p in func.parameters if p.name not in ("self", "cls"))
        out.append(f"        result = {func.name}({args})")
        out.append("")
        out.append("        # Assert")
        out.append("        assert result is not None")
        if func.return_type and func.return_type != "None":
            out.append(f"        # TODO: assert isinstance(result, {func.return_type})")
        out.append("")

        # Error paths
        for exc in func.raises:
            out.append(f"    def test_{func.name}_raises_{exc.lower()}(self):")
            out.append("        # Arrange")
            for p in func.parameters:
                if p.name in ("self", "cls"):
                    continue
                val = _guess_edge(p, "python")[-1]
                out.append(f"        {p.name} = {val}")
            out.append("")
            out.append("        # Act / Assert")
            args = ", ".join(p.name for p in func.parameters if p.name not in ("self", "cls"))
            out.append(f"        with pytest.raises({exc}):")
            out.append(f"            {func.name}({args})")
            out.append("")

        # Edge cases if branching detected
        if func.has_branching:
            out.append(f"    def test_{func.name}_edge_cases(self):")
            out.append("        # TODO: add boundary value tests for each branch")
            out.append("        pass")
            out.append("")

        return out

    def _generate_class(self, cls: ClassInfo, mod_name: str) -> List[str]:
        out: List[str] = []
        out.append(f"class Test{cls.name}:")
        out.append("")

        # Extract __init__ params for instantiation
        init_params: List[Parameter] = []
        for m in cls.methods:
            if m.name == "__init__":
                init_params = [p for p in m.parameters if p.name != "self"]
                break

        for method in cls.methods:
            if method.name.startswith("_"):
                continue  # skip dunder and private methods

            out.append(f"    def test_{method.name}_success(self):")
            out.append(f"        # Arrange")

            # Instantiate with __init__ params if available
            init_args = ", ".join(p.name for p in init_params)
            for p in init_params:
                if p.name not in [mp.name for mp in method.parameters]:
                    out.append(f"        {p.name} = {_guess_edge(p, 'python')[0]}")
            out.append(f"        instance = {cls.name}({init_args})")

            for p in method.parameters:
                if p.name == "self":
                    continue
                val = _guess_edge(p, "python")[0]
                out.append(f"        {p.name} = {val}")
            out.append("")
            out.append("        # Act")
            args = ", ".join(p.name for p in method.parameters if p.name != "self")
            call = f"instance.{method.name}({args})" if args else f"instance.{method.name}()"
            out.append(f"        result = {call}")
            out.append("")
            out.append("        # Assert")
            out.append("        assert result is not None")
            out.append("")
        return out


class JestVitestGenerator:
    def __init__(self, framework: str):
        self.framework = framework  # "jest" or "vitest"

    def generate(self, module: ModuleInfo, module_path: str) -> str:
        lines: List[str] = []
        mod_name = Path(module_path).stem
        import_path = _js_relative_import(module_path)
        mock_fn = "vi.mock" if self.framework == "vitest" else "jest.mock"

        lines.append(f"import {{ {mod_name} }} from '{import_path}';")
        lines.append("")

        mocks = _mock_suggestions(module.imports)
        if mocks:
            lines.append(f"// Mock suggestions: {', '.join(mocks)}")
            for m in mocks:
                lines.append(f"{mock_fn}('{m}');")
            lines.append("")

        for func in module.functions:
            lines.extend(self._generate_function(func, mod_name))
        for cls in module.classes:
            lines.extend(self._generate_class(cls, mod_name))

        return "\n".join(lines)

    def _generate_function(self, func: FunctionInfo, mod_name: str) -> List[str]:
        out: List[str] = []
        out.append(f"describe('{func.name}', () => {{")
        out.append("")

        out.append(f"  it('returns expected result on valid input', () => {{")
        out.append("    // Arrange")
        for p in func.parameters:
            val = _guess_edge(p, "javascript")[0]
            out.append(f"    const {p.name} = {val};")
        out.append("")
        out.append("    // Act")
        args = ", ".join(p.name for p in func.parameters)
        out.append(f"    const result = {func.name}({args});")
        out.append("")
        out.append("    // Assert")
        out.append("    expect(result).toBeDefined();")
        out.append("    // TODO: add precise assertion")
        out.append("  });")
        out.append("")

        for exc in func.raises:
            out.append(f"  it('throws on invalid input', () => {{")
            out.append("    // Arrange")
            for p in func.parameters:
                val = _guess_edge(p, "javascript")[-1]
                out.append(f"    const {p.name} = {val};")
            out.append("")
            out.append("    // Act / Assert")
            args = ", ".join(p.name for p in func.parameters)
            out.append(f"    expect(() => {func.name}({args})).toThrow();")
            out.append("  });")
            out.append("")

        if func.has_branching:
            out.append("  it('handles edge cases', () => {")
            out.append("    // TODO: add boundary value tests for each branch")
            out.append("  });")
            out.append("")

        out.append("});")
        out.append("")
        return out

    def _generate_class(self, cls: ClassInfo, mod_name: str) -> List[str]:
        out: List[str] = []
        out.append(f"describe('{cls.name}', () => {{")
        out.append("")

        # Extract constructor params for instantiation
        ctor_params: List[Parameter] = []
        for m in cls.methods:
            if m.name == "constructor":
                ctor_params = [p for p in m.parameters if p.name != "self"]
                break

        for method in cls.methods:
            if method.name.startswith("_") or method.name == "constructor":
                continue
            out.append(f"  describe('{method.name}', () => {{")
            out.append(f"    it('returns expected result on valid input', () => {{")

            ctor_args = ", ".join(p.name for p in ctor_params)
            for p in ctor_params:
                if p.name not in [mp.name for mp in method.parameters]:
                    out.append(f"      const {p.name} = {_guess_edge(p, 'javascript')[0]};")
            out.append(f"      const instance = new {cls.name}({ctor_args});")

            for p in method.parameters:
                if p.name == "self":
                    continue
                val = _guess_edge(p, "javascript")[0]
                out.append(f"      const {p.name} = {val};")
            out.append("")
            args = ", ".join(p.name for p in method.parameters if p.name != "self")
            call = f"instance.{method.name}({args})" if args else f"instance.{method.name}()"
            out.append(f"      const result = {call};")
            out.append("      expect(result).toBeDefined();")
            out.append("    });")
            out.append("  });")
            out.append("")
        out.append("});")
        out.append("")
        return out


def _go_zero_value(typ: str) -> str:
    t = typ.strip()
    if t.startswith("*") or t.startswith("[]") or t.startswith("map[") or t == "error" or t.startswith("func"):
        return "nil"
    if t in ("int", "int8", "int16", "int32", "int64", "uint", "uint8", "uint16", "uint32", "uint64"):
        return "0"
    if t in ("float32", "float64"):
        return "0.0"
    if t == "string":
        return '""'
    if t == "bool":
        return "false"
    if t.startswith("chan "):
        return "nil"
    return f"{t}{{}}"  # struct zero value


class GoTestGenerator:
    def generate(self, module: ModuleInfo, module_path: str) -> str:
        lines: List[str] = []
        pkg_name = _go_package_name(module_path, module.imports)

        lines.append(f"package {pkg_name}")
        lines.append("")
        lines.append('import "testing"')
        if any(f.has_branching for f in module.functions):
            lines.append('import "reflect"')
        lines.append("")

        for func in module.functions:
            lines.extend(self._generate_function(func))

        return "\n".join(lines)

    def _generate_function(self, func: FunctionInfo) -> List[str]:
        out: List[str] = []
        out.append(f"func Test{func.name.title()}(t *testing.T) {{")
        out.append("    tests := []struct {")
        out.append("        name     string")
        for p in func.parameters:
            go_type = p.type_hint or "string"
            out.append(f"        {p.name}     {go_type}")
        if func.return_type:
            for i, r in enumerate(func.return_type.split(",")):
                out.append(f"        expected{i} {r.strip()}")
        else:
            out.append("        expected string")
        out.append("    }{")
        # Generate a few cases
        vals = []
        for p in func.parameters:
            edge = _guess_edge(p, "go")
            vals.append(edge[0])
        expected_vals = []
        if func.return_type:
            for r in func.return_type.split(","):
                expected_vals.append(_go_zero_value(r))
        expected_part = ", ".join(expected_vals) if expected_vals else '""'
        out.append(f'        {{"happy path", {", ".join(vals)}, {expected_part}}},')
        if func.raises:
            bad_vals = []
            for p in func.parameters:
                edge = _guess_edge(p, "go")
                bad_vals.append(edge[-1])
            out.append(f'        {{"error path", {", ".join(bad_vals)}, {expected_part}}},')
        out.append("    }")
        out.append("")
        out.append("    for _, tt := range tests {")
        out.append("        t.Run(tt.name, func(t *testing.T) {")
        out.append(f"            got := {func.name}({', '.join('tt.' + p.name for p in func.parameters)})")
        if func.return_type:
            if "error" in func.return_type.lower():
                out.append("            if tt.name == \"error path\" {")
                out.append("                if got == nil {")
                out.append('                    t.Errorf("expected error, got nil")')
                out.append("                }")
                out.append("                return")
                out.append("            }")
            else:
                out.append("            // TODO: assert got == tt.expected")
                out.append("            _ = got")
        out.append("        })")
        out.append("    }")
        out.append("}")
        out.append("")
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _python_relative_import(source_path: str) -> str:
    """Guess a Python import path from a filesystem path."""
    parts = Path(source_path).parts
    # Find likely package root (src/, lib/, or first folder)
    for i, part in enumerate(parts):
        if part in ("src", "lib", "app", "package"):
            return ".".join(parts[i + 1 : -1])
    # Fallback: use parent directories up to 2 levels
    path = Path(source_path)
    return ".".join(path.parent.parts[-2:]) if len(path.parent.parts) >= 2 else path.parent.name


def _js_relative_import(source_path: str) -> str:
    """Guess a JS/TS import path from filesystem path."""
    path = Path(source_path)
    stem = path.stem
    # Relative import
    return f"./{stem}"


def _go_package_name(source_path: str, imports: List[str]) -> str:
    """Guess a Go package name from the directory name."""
    path = Path(source_path)
    return path.parent.name or "main"


def _detect_language(source_path: str) -> str:
    ext = Path(source_path).suffix.lower()
    if ext in (".py",):
        return "python"
    if ext in (".js", ".jsx", ".ts", ".tsx", ".mjs"):
        return "javascript"
    if ext in (".go",):
        return "go"
    return ""


def _select_generator(framework: str, language: str):
    if language == "python" or framework in ("pytest", "unittest"):
        return PytestGenerator()
    if language in ("javascript", "typescript") or framework in ("jest", "vitest", "mocha"):
        return JestVitestGenerator(framework)
    if language == "go" or framework in ("go_test", "gotest"):
        return GoTestGenerator()
    # Default fallback
    return PytestGenerator()


def _select_framework(language: str) -> str:
    return {"python": "pytest", "javascript": "jest", "typescript": "vitest", "go": "go_test"}.get(
        language, "pytest"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyze source code and generate test scaffolds."
    )
    parser.add_argument("--source", required=True, help="Path to source file")
    parser.add_argument("--framework", default="", help="Test framework (pytest, jest, vitest, go_test)")
    parser.add_argument("--output", required=True, help="Path for generated test file")
    parser.add_argument("--dry-run", action="store_true", help="Print to stdout instead of writing")
    parser.add_argument("--json", action="store_true", help="Emit analysis as JSON instead of test code")
    args = parser.parse_args()

    source_path = Path(args.source)
    if not source_path.exists():
        print(f"Error: source file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    source = source_path.read_text(encoding="utf-8")
    language = _detect_language(str(source_path))
    if not language:
        print(f"Error: unsupported file extension: {source_path.suffix}", file=sys.stderr)
        sys.exit(1)

    framework = args.framework or _select_framework(language)

    # Analyze
    if language == "python":
        module = PythonAnalyzer(source).analyze()
    elif language in ("javascript", "typescript"):
        module = JsTsAnalyzer(source).analyze()
    elif language == "go":
        module = GoAnalyzer(source).analyze()
    else:
        module = ModuleInfo(functions=[], classes=[], imports=[], language=language)

    module.module_name = source_path.stem

    if args.json:
        # Dump analysis as JSON
        data = {
            "module_name": module.module_name,
            "language": module.language,
            "imports": module.imports,
            "functions": [
                {
                    "name": f.name,
                    "parameters": [{"name": p.name, "type": p.type_hint, "default": p.default} for p in f.parameters],
                    "return_type": f.return_type,
                    "is_async": f.is_async,
                    "is_method": f.is_method,
                    "raises": f.raises,
                    "has_branching": f.has_branching,
                    "docstring": f.docstring,
                }
                for f in module.functions
            ],
            "classes": [
                {
                    "name": c.name,
                    "methods": [
                        {
                            "name": f.name,
                            "parameters": [{"name": p.name, "type": p.type_hint} for p in f.parameters],
                            "return_type": f.return_type,
                            "raises": f.raises,
                            "has_branching": f.has_branching,
                        }
                        for f in c.methods
                    ],
                }
                for c in module.classes
            ],
        }
        output = json.dumps(data, indent=2)
    else:
        generator = _select_generator(framework, language)
        output = generator.generate(module, str(source_path))

    if args.dry_run:
        print(output)
    else:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"Generated: {out_path}")


if __name__ == "__main__":
    main()
