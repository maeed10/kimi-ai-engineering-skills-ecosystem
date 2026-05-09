#!/usr/bin/env python3
"""
validate_adr.py — Validate MADR-JSON documents and extract architectural constraints.

Usage:
    python validate_adr.py --adr path/to/decision.json
    python validate_adr.py --adr path/to/decision.json --strict
    python validate_adr.py --adr path/to/decision.json --extract-constraints --output constraints.json
    python validate_adr.py --dir decisions/ --strict
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Embedded MADR-JSON Schema (Draft-07 compatible subset)
# ---------------------------------------------------------------------------

MADR_SCHEMA = {
    "type": "object",
    "required": ["meta", "context", "decision"],
    "properties": {
        "meta": {
            "type": "object",
            "required": ["id", "date", "status"],
            "properties": {
                "id": {"type": "string", "pattern": r"^[A-Z]{2,4}-[0-9]{4,}$"},
                "date": {"type": "string"},
                "status": {"type": "string", "enum": ["proposed", "accepted", "deprecated", "superseded", "rejected"]},
                "authors": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "version": {"type": "string", "pattern": r"^[0-9]+\.[0-9]+\.[0-9]+$"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "status_history": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["from", "to", "date", "actor"],
                        "properties": {
                            "from": {"type": "string", "enum": ["proposed", "accepted", "deprecated", "superseded", "rejected"]},
                            "to": {"type": "string", "enum": ["proposed", "accepted", "deprecated", "superseded", "rejected"]},
                            "date": {"type": "string"},
                            "actor": {"type": "string"},
                            "reason": {"type": "string"}
                        }
                    }
                }
            }
        },
        "context": {
            "type": "object",
            "required": ["problem"],
            "properties": {
                "problem": {"type": "string"},
                "background": {"type": "string"},
                "forces": {"type": "array", "items": {"type": "string"}},
                "constraints": {"type": "array", "items": {"type": "string"}},
                "assumptions": {"type": "array", "items": {"type": "string"}},
                "scope": {
                    "type": "object",
                    "properties": {
                        "system": {"type": "string"},
                        "subsystem": {"type": "string"},
                        "bounded_context": {"type": "string"},
                        " Applies_to": {"type": "array", "items": {"type": "string"}},
                        "exclusions": {"type": "array", "items": {"type": "string"}}
                    }
                }
            }
        },
        "decision": {
            "type": "object",
            "required": ["statement"],
            "properties": {
                "statement": {"type": "string"},
                "rationale": {"type": "string"},
                "option_details": {"type": "object"}
            }
        },
        "consequences": {
            "type": "object",
            "properties": {
                "positive": {"type": "array", "items": {"type": "string"}},
                "negative": {"type": "array", "items": {"type": "string"}},
                "neutral": {"type": "array", "items": {"type": "string"}}
            }
        },
        "alternatives": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["option", "rationale_rejected"],
                "properties": {
                    "option": {"type": "string"},
                    "rationale_rejected": {"type": "string"},
                    "consequences_if_chosen": {
                        "type": "object",
                        "properties": {
                            "positive": {"type": "array", "items": {"type": "string"}},
                            "negative": {"type": "array", "items": {"type": "string"}}
                        }
                    }
                }
            }
        },
        "linked": {
            "type": "object",
            "properties": {
                "requirements": {"type": "array", "items": {"type": "string"}},
                "supersedes": {"type": ["string", "null"]},
                "superseded_by": {"type": ["string", "null"]},
                "related_adrs": {"type": "array", "items": {"type": "string", "pattern": r"^[A-Z]{2,4}-[0-9]{4,}$"}},
                "code_paths": {"type": "array", "items": {"type": "string"}},
                "stakeholders": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "role": {"type": "string"},
                            "concern": {"type": "string"}
                        }
                    }
                }
            }
        },
        "derived_constraints": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "source_adr", "predicate", "severity"],
                "properties": {
                    "id": {"type": "string", "pattern": r"^CON-[0-9]+$"},
                    "source_adr": {"type": "string", "pattern": r"^[A-Z]{2,4}-[0-9]{4,}$"},
                    "predicate": {"type": "string"},
                    "target": {"type": "string"},
                    "severity": {"type": "string", "enum": ["must", "should", "may"]},
                    "automation_hint": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string"},
                            "config_ref": {"type": "string"}
                        }
                    }
                }
            }
        }
    }
}

# ---------------------------------------------------------------------------
# Validation engine
# ---------------------------------------------------------------------------

class ValidationError:
    def __init__(self, path: str, message: str, severity: str = "error"):
        self.path = path
        self.message = message
        self.severity = severity

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.path}: {self.message}"


class Validator:
    def __init__(self, strict: bool = False):
        self.strict = strict
        self.errors: List[ValidationError] = []

    def _add(self, path: str, message: str, severity: str = "error") -> None:
        self.errors.append(ValidationError(path, message, severity))

    def _check_type(self, value: Any, expected: str, path: str) -> bool:
        if expected == "string" and not isinstance(value, str):
            self._add(path, f"expected string, got {type(value).__name__}")
            return False
        if expected == "array" and not isinstance(value, list):
            self._add(path, f"expected array, got {type(value).__name__}")
            return False
        if expected == "object" and not isinstance(value, dict):
            self._add(path, f"expected object, got {type(value).__name__}")
            return False
        return True

    def _check_pattern(self, value: str, pattern: str, path: str) -> None:
        if not re.match(pattern, value):
            self._add(path, f"value '{value}' does not match pattern {pattern}")

    def _validate_node(self, data: Any, schema: Dict[str, Any], path: str) -> None:
        if schema.get("type") == "object":
            if not self._check_type(data, "object", path):
                return
            required = schema.get("required", [])
            for key in required:
                if key not in data:
                    self._add(f"{path}.{key}", f"required field missing")
            for key, subschema in schema.get("properties", {}).items():
                if key in data:
                    self._validate_node(data[key], subschema, f"{path}.{key}")
        elif schema.get("type") == "array":
            if not self._check_type(data, "array", path):
                return
            items_schema = schema.get("items", {})
            for i, item in enumerate(data):
                self._validate_node(item, items_schema, f"{path}[{i}]")
        elif schema.get("type") == "string":
            if not self._check_type(data, "string", path):
                return
            if "pattern" in schema:
                self._check_pattern(data, schema["pattern"], path)
            if "enum" in schema and data not in schema["enum"]:
                self._add(path, f"value '{data}' not in enum {schema['enum']}")
        elif schema.get("type") == "number":
            if not isinstance(data, (int, float)):
                self._add(path, f"expected number, got {type(data).__name__}")
        elif "anyOf" in schema:
            matched = False
            for alt in schema["anyOf"]:
                alt_errors_before = len(self.errors)
                self._validate_node(data, alt, path)
                if len(self.errors) == alt_errors_before:
                    matched = True
                    break
            if not matched:
                pass  # errors already recorded
        elif "type" not in schema:
            return  # unconstrained

    def _validate_consistency(self, data: Dict[str, Any]) -> None:
        meta = data.get("meta", {})
        status = meta.get("status")
        linked = data.get("linked", {})

        # Superseded consistency
        if status == "superseded":
            if not linked.get("superseded_by"):
                self._add("linked.superseded_by", "status is 'superseded' but superseded_by is not set")
        if linked.get("superseded_by") and status != "superseded":
            self._add("meta.status", f"linked.superseded_by is set but status is '{status}', expected 'superseded'")

        # Deprecated should not have superseded_by
        if status == "deprecated" and linked.get("superseded_by"):
            self._add("linked.superseded_by", "deprecated ADRs should not have superseded_by; use superseded instead")

        # Status history consistency
        history = meta.get("status_history", [])
        if history:
            current_from_history = history[-1].get("to") if history else None
            if current_from_history and current_from_history != status:
                self._add("meta.status", f"status '{status}' does not match last history entry 'to' value '{current_from_history}'")

    def _validate_strict(self, data: Dict[str, Any]) -> None:
        meta = data.get("meta", {})
        if "authors" not in meta:
            self._add("meta.authors", "required in strict mode", "warning")
        if "tags" not in meta:
            self._add("meta.tags", "required in strict mode", "warning")

        context = data.get("context", {})
        if "forces" not in context:
            self._add("context.forces", "required in strict mode", "warning")
        if "constraints" not in context:
            self._add("context.constraints", "required in strict mode", "warning")
        if "scope" not in context:
            self._add("context.scope", "required in strict mode", "warning")

        if "consequences" not in data:
            self._add("consequences", "required in strict mode", "warning")
        if "alternatives" not in data:
            self._add("alternatives", "required in strict mode", "warning")

        linked = data.get("linked", {})
        if "requirements" not in linked:
            self._add("linked.requirements", "required in strict mode", "warning")
        if "code_paths" not in linked:
            self._add("linked.code_paths", "required in strict mode", "warning")

    def validate(self, data: Dict[str, Any]) -> List[ValidationError]:
        self.errors = []
        self._validate_node(data, MADR_SCHEMA, "$")
        self._validate_consistency(data)
        if self.strict:
            self._validate_strict(data)
        return self.errors


# ---------------------------------------------------------------------------
# Constraint extraction engine
# ---------------------------------------------------------------------------

CONSTRAINT_PATTERNS: List[Tuple[str, str, str, Optional[str]]] = [
    # (regex_pattern, severity, human_template, automation_hint_tool)
    (
        r"(?i)(append-only|immutable|cannot\s+(?:delete|update|modify)|no\s+(?:delete|update|modify)|reject\s+(?:update|delete))",
        "must",
        "{subject} must enforce immutability: no UPDATE/DELETE operations permitted",
        "postgresql-integration-test"
    ),
    (
        r"(?i)(must\s+(?:use|run\s+on|integrate\s+with|support))",
        "must",
        "Hard constraint detected: {match}",
        None
    ),
    (
        r"(?i)(?:under|less\s+than|below)\s+(\d+(?:\.\d+)?)\s*(ms|milliseconds?)",
        "should",
        "Latency target: must remain under {value}ms",
        "k6-load-test"
    ),
    (
        r"(?i)(p99|p95|percentile\s*99)\s*(?:under|less\s+than|below|:)?\s*(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|seconds?)",
        "should",
        "{percentile} latency must remain under {value}{unit}",
        "k6-load-test"
    ),
    (
        r"(?i)(\d+(?:,?\d*)*)\s*(?:concurrent\s+users?|requests?\s+per\s+second|rps|tps|throughput)",
        "should",
        "Throughput target: must support {match}",
        "k6-load-test"
    ),
    (
        r"(?i)(encrypt(?:ed|ion)?|cryptographic|ciphertext|tls|ssl|https)",
        "must",
        "Security constraint: cryptographic protection required for {subject}",
        "security-scan"
    ),
    (
        r"(?i)(authentication|authorization|auth[nz]|oauth|oidc|sso|mfa|2fa)",
        "must",
        "Security constraint: identity and access control required for {subject}",
        "security-scan"
    ),
    (
        r"(?i)(bounded\s+context|service\s+boundar|domain\s+boundar|context\s+map)",
        "must",
        "Architecture boundary constraint: {subject} must respect defined bounded contexts",
        "archunit"
    ),
    (
        r"(?i)(must\s+not|mustn't|forbidden|prohibited)\s+(.*)",
        "must",
        "Prohibition constraint: must not {match}",
        None
    ),
]


def extract_constraints(adr: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Heuristic constraint extraction from ADR text."""
    constraints: List[Dict[str, Any]] = []
    adr_id = adr.get("meta", {}).get("id", "UNKNOWN")
    counter = 1

    # Gather all text sources for analysis
    text_sources: List[Tuple[str, str]] = []
    context = adr.get("context", {})
    decision = adr.get("decision", {})
    consequences = adr.get("consequences", {})

    text_sources.append(("context.problem", context.get("problem", "")))
    text_sources.append(("context.background", context.get("background", "")))
    text_sources.append(("decision.statement", decision.get("statement", "")))
    text_sources.append(("decision.rationale", decision.get("rationale", "")))
    for i, f in enumerate(context.get("forces", [])):
        text_sources.append((f"context.forces[{i}]", f))
    for i, c in enumerate(context.get("constraints", [])):
        text_sources.append((f"context.constraints[{i}]", c))
    for cat in ["positive", "negative", "neutral"]:
        for i, item in enumerate(consequences.get(cat, [])):
            text_sources.append((f"consequences.{cat}[{i}]", item))

    seen = set()
    for source_path, text in text_sources:
        if not text:
            continue
        for pattern, severity, template, tool in CONSTRAINT_PATTERNS:
            for match in re.finditer(pattern, text):
                key = (adr_id, match.group(0).lower(), severity, template)
                if key in seen:
                    continue
                seen.add(key)

                human = template
                if "{match}" in human:
                    human = human.replace("{match}", match.group(0))
                if "{subject}" in human:
                    human = human.replace("{subject}", source_path.split(".")[0])
                if "{value}" in human and match.groups():
                    human = human.replace("{value}", match.group(1))
                if "{percentile}" in human and match.groups():
                    human = human.replace("{percentile}", match.group(1).upper())
                if "{unit}" in human and len(match.groups()) > 1:
                    human = human.replace("{unit}", match.group(2))

                constraint: Dict[str, Any] = {
                    "id": f"CON-{counter}",
                    "source_adr": adr_id,
                    "predicate": human,
                    "severity": severity,
                    "extraction_source": source_path,
                    "matched_text": match.group(0),
                }
                if tool:
                    constraint["automation_hint"] = {"tool": tool, "config_ref": f"auto-derived/{source_path}"}
                if decision.get("statement"):
                    constraint["target"] = "architecture-fitness-function"

                constraints.append(constraint)
                counter += 1

    # Merge with author-provided derived_constraints if present
    author_constraints = adr.get("derived_constraints", [])
    for ac in author_constraints:
        # Validate author constraints reference correct ADR
        if ac.get("source_adr") != adr_id:
            ac["source_adr"] = adr_id
        constraints.append(ac)

    return constraints


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_adr(path: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    errors: List[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        errors.append(f"File not found: {path}")
        return None, errors
    except json.JSONDecodeError as e:
        errors.append(f"Invalid JSON in {path}: {e}")
        return None, errors
    if not isinstance(data, dict):
        errors.append(f"Root element must be an object in {path}")
        return None, errors
    return data, errors


def validate_file(path: str, strict: bool = False) -> Tuple[bool, List[ValidationError]]:
    data, load_errors = load_adr(path)
    if data is None:
        errs = [ValidationError("$", msg) for msg in load_errors]
        return False, errs

    validator = Validator(strict=strict)
    errors = validator.validate(data)
    return all(e.severity != "error" for e in errors), errors


def validate_dir(dir_path: str, strict: bool = False) -> Dict[str, Tuple[bool, List[ValidationError]]]:
    results: Dict[str, Tuple[bool, List[ValidationError]]] = {}
    root = Path(dir_path)
    if not root.exists():
        results[str(root)] = (False, [ValidationError("$", f"Directory not found: {dir_path}")])
        return results

    for path in root.rglob("*.json"):
        ok, errors = validate_file(str(path), strict=strict)
        results[str(path)] = (ok, errors)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate MADR-JSON documents")
    parser.add_argument("--adr", help="Path to a single MADR-JSON file")
    parser.add_argument("--dir", help="Path to directory of MADR-JSON files (recursively scanned)")
    parser.add_argument("--strict", action="store_true", help="Enable strict mode (requires recommended fields)")
    parser.add_argument("--extract-constraints", action="store_true", help="Extract architectural constraints")
    parser.add_argument("--output", help="Output file for extracted constraints (JSON)")
    args = parser.parse_args()

    if not args.adr and not args.dir:
        parser.error("One of --adr or --dir is required")

    exit_code = 0
    all_constraints: List[Dict[str, Any]] = []

    if args.adr:
        ok, errors = validate_file(args.adr, strict=args.strict)
        for e in errors:
            print(str(e))
            if e.severity == "error":
                exit_code = 1

        if ok and args.extract_constraints:
            data, _ = load_adr(args.adr)
            if data:
                constraints = extract_constraints(data)
                all_constraints.extend(constraints)
                print(f"\nExtracted {len(constraints)} constraint(s):")
                for c in constraints:
                    print(f"  {c['id']} [{c['severity']}] {c['predicate']}")

    if args.dir:
        results = validate_dir(args.dir, strict=args.strict)
        for path, (ok, errors) in results.items():
            if not ok:
                exit_code = 1
            severity = "OK" if ok else "FAIL"
            print(f"[{severity}] {path}")
            for e in errors:
                print(f"  {e}")

            if ok and args.extract_constraints:
                data, _ = load_adr(path)
                if data:
                    constraints = extract_constraints(data)
                    all_constraints.extend(constraints)

    if args.output and all_constraints:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(all_constraints, f, indent=2)
        print(f"\nWrote {len(all_constraints)} constraint(s) to {args.output}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
