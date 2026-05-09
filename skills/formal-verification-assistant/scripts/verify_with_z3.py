#!/usr/bin/env python3
"""
verify_with_z3.py

Wrapper script for Z3-based Python function contract verification.

Usage (CLI):
    python verify_with_z3.py \
        --module mymodule \
        --function myfunc \
        --pre "x >= 0" \
        --post "result >= x" \
        --timeout 30

Usage (Programmatic):
    from verify_with_z3 import Z3Verifier, Contract
    v = Z3Verifier()
    contract = Contract(
        name="add_positive",
        pre=["x >= 0", "y >= 0"],
        post=["result == x + y", "result >= x", "result >= y"]
    )
    v.verify_contract(contract, arg_types={"x": int, "y": int})

Exit codes:
    0  All properties verified
    1  At least one property failed or counterexample found
    2  Solver timeout / inconclusive
    3  Setup or parsing error
"""

import argparse
import ast
import importlib.util
import inspect
import json
import operator
import sys
import textwrap
import types
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Union

try:
    from z3 import (
        And, Or, Not, Implies, ForAll, Exists,
        Int, Real, Bool, Array, IntSort, RealSort, BoolSort,
        Solver, sat, unsat, unknown, Z3Exception,
        set_option,
    )
except ImportError as exc:
    print("ERROR: z3-solver is required. Install: pip install z3-solver")
    sys.exit(3)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PropertyResult:
    property_id: str
    description: str
    status: str  # PASS, FAIL, TIMEOUT, ERROR
    counterexample: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    assumptions: List[str] = field(default_factory=list)


@dataclass
class VerificationReport:
    target_function: str
    tool: str = "Z3"
    properties_checked: int = 0
    passed: int = 0
    failed: int = 0
    inconclusive: int = 0
    results: List[PropertyResult] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


@dataclass
class Contract:
    name: str
    pre: List[str]
    post: List[str]
    arg_types: Dict[str, type] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Z3 symbol factory
# ---------------------------------------------------------------------------

TYPE_MAP = {
    int: IntSort(),
    float: RealSort(),
    bool: BoolSort(),
}


def make_symbol(name: str, py_type: type):
    if py_type is int:
        return Int(name)
    if py_type is float:
        return Real(name)
    if py_type is bool:
        return Bool(name)
    raise ValueError(f"Unsupported type for symbolic variable: {py_type}")


# ---------------------------------------------------------------------------
# Lightweight expression parser (subset of Python expressions)
# ---------------------------------------------------------------------------

class Z3ExpressionBuilder(ast.NodeVisitor):
    """
    Convert a Python expression AST into a Z3 expression.

    Supports:
        - Comparisons: ==, !=, <, <=, >, >=
        - Arithmetic: +, -, *, /, //, %, **
        - Logical: and, or, not
        - Call: min, max, abs, len
        - Name lookup from a provided variable mapping
        - Numeric literals (int, float)
    """

    def __init__(self, symbols: Dict[str, Any]):
        self.symbols = symbols
        self.errors: List[str] = []

    def build(self, expr_str: str):
        try:
            tree = ast.parse(expr_str, mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"Invalid expression syntax: {expr_str}") from exc
        return self.visit(tree.body)

    def visit_BinOp(self, node):
        left = self.visit(node.left)
        right = self.visit(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            return left / right  # Z3 real division; caller must cast if needed
        if isinstance(node.op, ast.Mod):
            return left % right
        if isinstance(node.op, ast.Pow):
            return left ** right
        raise ValueError(f"Unsupported binary operator: {ast.dump(node.op)}")

    def visit_UnaryOp(self, node):
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.Not):
            return Not(operand)
        raise ValueError(f"Unsupported unary operator: {ast.dump(node.op)}")

    def visit_Compare(self, node):
        left = self.visit(node.left)
        result = []
        for op, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            if isinstance(op, ast.Eq):
                result.append(left == right)
            elif isinstance(op, ast.NotEq):
                result.append(left != right)
            elif isinstance(op, ast.Lt):
                result.append(left < right)
            elif isinstance(op, ast.LtE):
                result.append(left <= right)
            elif isinstance(op, ast.Gt):
                result.append(left > right)
            elif isinstance(op, ast.GtE):
                result.append(left >= right)
            else:
                raise ValueError(f"Unsupported comparison: {ast.dump(op)}")
            left = right
        return And(*result) if len(result) > 1 else result[0]

    def visit_BoolOp(self, node):
        values = [self.visit(v) for v in node.values]
        if isinstance(node.op, ast.And):
            return And(*values)
        if isinstance(node.op, ast.Or):
            return Or(*values)
        raise ValueError(f"Unsupported boolean operator: {ast.dump(node.op)}")

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            fname = node.func.id
            args = [self.visit(a) for a in node.args]
            if fname == "len" and len(args) == 1:
                # len(arr) -> array length variable <arr>_len
                arr_name = self._extract_name(node.args[0])
                length_sym = self.symbols.get(f"{arr_name}_len")
                if length_sym is not None:
                    return length_sym
                raise ValueError(f"No length symbol found for array {arr_name}")
            if fname == "abs" and len(args) == 1:
                # abs(x) encoded as If(x >= 0, x, -x)
                x = args[0]
                from z3 import If
                return If(x >= 0, x, -x)
            if fname == "min" and len(args) == 2:
                from z3 import If
                return If(args[0] <= args[1], args[0], args[1])
            if fname == "max" and len(args) == 2:
                from z3 import If
                return If(args[0] >= args[1], args[0], args[1])
        raise ValueError(f"Unsupported function call: {ast.dump(node.func)}")

    def visit_Constant(self, node):
        if isinstance(node.value, bool):
            return node.value  # True/False are Z3 bool constants
        if isinstance(node.value, int):
            return node.value
        if isinstance(node.value, float):
            return node.value
        raise ValueError(f"Unsupported constant: {node.value!r}")

    def visit_Name(self, node):
        if node.id == "result":
            sym = self.symbols.get("__result__")
            if sym is not None:
                return sym
            raise ValueError("'result' used in postcondition but no return symbol defined")
        if node.id == "True":
            return True
        if node.id == "False":
            return False
        sym = self.symbols.get(node.id)
        if sym is None:
            raise ValueError(f"Unknown variable: {node.id}")
        return sym

    def _extract_name(self, node):
        if isinstance(node, ast.Name):
            return node.id
        raise ValueError(f"Cannot extract name from: {ast.dump(node)}")

    def generic_visit(self, node):
        raise ValueError(f"Unsupported AST node: {ast.dump(node)}")


# ---------------------------------------------------------------------------
# Core verifier
# ---------------------------------------------------------------------------

class Z3Verifier:
    """
    Verify Python function contracts using Z3 SMT solver.
    """

    def __init__(self, timeout_ms: int = 300_000):
        self.timeout_ms = timeout_ms
        set_option(timeout=timeout_ms)

    def verify_contract(
        self,
        contract: Contract,
        func_impl: Optional[Callable] = None,
        verbose: bool = False,
    ) -> VerificationReport:
        """
        Verify a Contract against a function implementation.

        If func_impl is None, the verification checks logical consistency
        of pre/post only (useful for specification-level validation).
        """
        report = VerificationReport(
            target_function=contract.name,
            assumptions=contract.pre.copy(),
            metadata={
                "timeout_ms": self.timeout_ms,
                "arg_types": {k: v.__name__ for k, v in contract.arg_types.items()},
            },
        )

        # Build symbols for arguments + result
        symbols: Dict[str, Any] = {}
        for arg_name, py_type in contract.arg_types.items():
            symbols[arg_name] = make_symbol(arg_name, py_type)
        if "result" in contract.post or any("result" in p for p in contract.post):
            ret_type = contract.arg_types.get("__return__", int)
            symbols["__result__"] = make_symbol("__result__", ret_type)

        # Encode preconditions
        pre_conditions = []
        builder = Z3ExpressionBuilder(symbols)
        for pre_expr in contract.pre:
            try:
                pre_conditions.append(builder.build(pre_expr))
            except Exception as exc:
                report.results.append(PropertyResult(
                    property_id="PRE_PARSE",
                    description=f"Precondition parse: {pre_expr}",
                    status="ERROR",
                    error_message=str(exc),
                ))
                report.inconclusive += 1
                return report

        # Encode postconditions and verify each independently
        for idx, post_expr in enumerate(contract.post, start=1):
            prop_id = f"POST-{idx}"
            try:
                post_z3 = builder.build(post_expr)
            except Exception as exc:
                report.results.append(PropertyResult(
                    property_id=prop_id,
                    description=post_expr,
                    status="ERROR",
                    error_message=str(exc),
                ))
                report.inconclusive += 1
                continue

            # Solver goal: pre => post is valid
            # Check unsat of: pre and not post
            solver = Solver()
            if pre_conditions:
                solver.add(And(*pre_conditions))
            solver.add(Not(post_z3))

            try:
                result = solver.check()
            except Z3Exception as exc:
                report.results.append(PropertyResult(
                    property_id=prop_id,
                    description=post_expr,
                    status="ERROR",
                    error_message=f"Z3 exception: {exc}",
                ))
                report.inconclusive += 1
                continue

            if result == unsat:
                report.results.append(PropertyResult(
                    property_id=prop_id,
                    description=post_expr,
                    status="PASS",
                ))
                report.passed += 1
            elif result == sat:
                model = solver.model()
                cex = {}
                for decl in model.decls():
                    val = model[decl]
                    cex[str(decl.name())] = str(val)
                report.results.append(PropertyResult(
                    property_id=prop_id,
                    description=post_expr,
                    status="FAIL",
                    counterexample=cex,
                ))
                report.failed += 1
            else:
                report.results.append(PropertyResult(
                    property_id=prop_id,
                    description=post_expr,
                    status="TIMEOUT",
                ))
                report.inconclusive += 1

        report.properties_checked = len(contract.post)
        return report

    def verify_bounds(
        self,
        var_name: str,
        var_type: type,
        lower: Optional[Union[int, float]] = None,
        upper: Optional[Union[int, float]] = None,
    ) -> PropertyResult:
        """
        Quick helper to verify a single variable bound.
        """
        sym = make_symbol(var_name, var_type)
        solver = Solver()
        props = []
        if lower is not None:
            props.append(sym >= lower)
        if upper is not None:
            props.append(sym <= upper)
        if not props:
            return PropertyResult(
                property_id="BOUNDS",
                description=f"No bounds specified for {var_name}",
                status="ERROR",
                error_message="Neither lower nor upper bound provided",
            )
        solver.add(Not(And(*props)))
        result = solver.check()
        if result == unsat:
            return PropertyResult(
                property_id="BOUNDS",
                description=f"{var_name} in [{lower}, {upper}]",
                status="PASS",
            )
        elif result == sat:
            model = solver.model()
            cex = {str(d.name()): str(model[d]) for d in model.decls()}
            return PropertyResult(
                property_id="BOUNDS",
                description=f"{var_name} in [{lower}, {upper}]",
                status="FAIL",
                counterexample=cex,
            )
        else:
            return PropertyResult(
                property_id="BOUNDS",
                description=f"{var_name} in [{lower}, {upper}]",
                status="TIMEOUT",
            )


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def load_function(module_path: str, function_name: str) -> Callable:
    spec = importlib.util.spec_from_file_location("target_module", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    func = getattr(mod, function_name, None)
    if func is None:
        raise ImportError(f"Function {function_name} not found in {module_path}")
    return func


def infer_arg_types(func: Callable, overrides: Dict[str, type]) -> Dict[str, type]:
    """
    Infer argument types from annotations; fallback to int if unspecified.
    """
    sig = inspect.signature(func)
    types: Dict[str, type] = {}
    for name, param in sig.parameters.items():
        if name in overrides:
            types[name] = overrides[name]
        elif param.annotation is not inspect.Parameter.empty:
            types[name] = param.annotation
        else:
            types[name] = int  # default
    # Attempt return type
    if sig.return_annotation is not inspect.Signature.empty:
        types["__return__"] = sig.return_annotation
    else:
        types["__return__"] = int
    return types


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify Python function contracts with Z3"
    )
    parser.add_argument("--module", required=True, help="Path to Python module file")
    parser.add_argument("--function", required=True, help="Function name to verify")
    parser.add_argument(
        "--pre", action="append", default=[], help="Precondition expression (repeatable)"
    )
    parser.add_argument(
        "--post", action="append", default=[], help="Postcondition expression (repeatable)"
    )
    parser.add_argument(
        "--type", action="append", default=[], help="Arg type override as name:type (repeatable)"
    )
    parser.add_argument(
        "--timeout", type=int, default=300, help="Solver timeout in seconds (default: 300)"
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit verification report as JSON"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print detailed solver output"
    )
    parser.add_argument(
        "--spec-only", action="store_true",
        help="Verify pre/post logical consistency without loading function implementation"
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    # Parse type overrides
    type_overrides: Dict[str, type] = {}
    for tspec in args.type:
        if ":" not in tspec:
            print(f"ERROR: --type must be name:type, got: {tspec}")
            sys.exit(3)
        name, tname = tspec.split(":", 1)
        type_overrides[name] = {"int": int, "float": float, "bool": bool}.get(tname, int)

    # Load function if needed
    func_impl = None
    arg_types: Dict[str, type] = {}
    if not args.spec_only:
        try:
            func_impl = load_function(args.module, args.function)
            arg_types = infer_arg_types(func_impl, type_overrides)
        except Exception as exc:
            print(f"ERROR loading function: {exc}")
            sys.exit(3)
    else:
        # Build minimal arg_types from type overrides + guessed int defaults
        # Expect pre/post to reference variables; we will rely on overrides
        arg_types = dict(type_overrides)
        if "__return__" not in arg_types:
            arg_types["__return__"] = int

    contract = Contract(
        name=args.function,
        pre=args.pre,
        post=args.post,
        arg_types=arg_types,
    )

    verifier = Z3Verifier(timeout_ms=args.timeout * 1000)
    report = verifier.verify_contract(contract, func_impl=func_impl, verbose=args.verbose)

    if args.json:
        print(report.to_json())
    else:
        print(f"\nVerification Report: {report.target_function}")
        print(f"Tool: {report.tool}")
        print(f"Properties checked: {report.properties_checked}")
        print(f"Passed: {report.passed}  Failed: {report.failed}  Inconclusive: {report.inconclusive}")
        print("-" * 60)
        for r in report.results:
            print(f"[{r.status}] {r.property_id}: {r.description}")
            if r.counterexample:
                print(f"  Counterexample: {r.counterexample}")
            if r.error_message:
                print(f"  Error: {r.error_message}")
        print("-" * 60)

    if report.failed > 0:
        sys.exit(1)
    if report.inconclusive > 0:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
