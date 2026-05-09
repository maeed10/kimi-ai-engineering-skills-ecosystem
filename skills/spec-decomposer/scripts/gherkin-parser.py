#!/usr/bin/env python3
"""
gherkin-parser.py

Standalone Gherkin / BDD acceptance-criteria parser for spec-decomposer.

Capabilities:
- Parse native `.feature` files (Cucumber/Gherkin syntax).
- Parse Gherkin blocks embedded in markdown specs (code-fenced or inline).
- Extract structured Scenario / Scenario Outline / Background nodes with
  Given / When / Then / And / But steps.
- Emit AcceptanceCriterion dataclass instances with trace IDs and Gherkin text.
- Flag specs that contain ZERO acceptance criteria as ambiguous.
- Validate that every Scenario has at least one Given, one When, and one Then.

Usage:
    python gherkin-parser.py <path-to-spec-or-feature> [--output json|markdown]
    python gherkin-parser.py --embedded <path-to-spec.md>

Exit codes:
    0 — At least one valid acceptance criterion found.
    1 — File not found or unreadable.
    2 — No acceptance criteria found (ambiguous spec).
    3 — Invalid Gherkin syntax detected (e.g., Scenario missing Then).
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class GherkinStep:
    keyword: str  # "Given", "When", "Then", "And", "But"
    text: str
    line_number: int = 0

    def to_line(self) -> str:
        return f"{self.keyword} {self.text}"


@dataclass
class GherkinScenario:
    id: str
    name: str
    tags: List[str] = field(default_factory=list)
    steps: List[GherkinStep] = field(default_factory=list)
    examples: List[dict] = field(default_factory=list)  # For Scenario Outline
    line_number: int = 0
    background: bool = False
    outline: bool = False

    @property
    def has_given(self) -> bool:
        return any(s.keyword in ("Given", "And", "But") for s in self.steps)

    @property
    def has_when(self) -> bool:
        return any(s.keyword == "When" for s in self.steps)

    @property
    def has_then(self) -> bool:
        return any(s.keyword in ("Then", "And", "But") for s in self.steps)

    @property
    def is_valid(self) -> bool:
        # Background only needs Given steps; normal scenarios need Given+When+Then
        if self.background:
            return self.has_given
        return self.has_given and self.has_when and self.has_then

    @property
    def gherkin_text(self) -> str:
        lines = []
        if self.tags:
            lines.append(" ".join(f"@{t}" for t in self.tags))
        keyword = "Scenario Outline" if self.outline else ("Background" if self.background else "Scenario")
        lines.append(f"{keyword}: {self.name}")
        for step in self.steps:
            lines.append(f"  {step.to_line()}")
        if self.examples:
            lines.append("  Examples:")
            for ex in self.examples:
                lines.append(f"    | {ex} |")
        return "\n".join(lines)


@dataclass
class AcceptanceCriterion:
    id: str
    text: str
    testable: bool = True
    gherkin: str = ""
    source_line: int = 0
    tags: List[str] = field(default_factory=list)
    validation_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "testable": self.testable,
            "gherkin": self.gherkin,
            "source_line": self.source_line,
            "tags": self.tags,
            "validation_errors": self.validation_errors,
        }


@dataclass
class GherkinParseResult:
    source_path: str
    scenarios: List[GherkinScenario] = field(default_factory=list)
    criteria: List[AcceptanceCriterion] = field(default_factory=list)
    ambiguities: List[str] = field(default_factory=list)
    syntax_errors: List[str] = field(default_factory=list)
    background_steps: List[GherkinStep] = field(default_factory=list)

    @property
    def has_acceptance_criteria(self) -> bool:
        return len(self.criteria) > 0 and any(c.testable for c in self.criteria)


# ---------------------------------------------------------------------------
# Parsing internals
# ---------------------------------------------------------------------------

# Keywords that start a new top-level block
BLOCK_KEYWORDS = re.compile(
    r"^\s*(Feature|Scenario|Scenario Outline|Background|Examples|@\w+)\b",
    re.IGNORECASE,
)

# Step keywords
STEP_RE = re.compile(
    r"^\s*(Given|When|Then|And|But)\s+(.+)$",
    re.IGNORECASE,
)

# Tags
TAG_RE = re.compile(r"@(\w+)")


def _tokenize_lines(text: str) -> List[Tuple[int, str]]:
    """Return list of (line_number, stripped_line) preserving order."""
    return [(i + 1, line.rstrip()) for i, line in enumerate(text.splitlines())]


def _extract_gherkin_blocks_from_markdown(text: str) -> str:
    """Pull Gherkin out of markdown ```gherkin ... ``` fences and plain text."""
    blocks = []
    # Code-fenced Gherkin
    fence_re = re.compile(r"```(?:gherkin|feature|cucumber)?\s*\n(.*?)\n```", re.DOTALL)
    for m in fence_re.finditer(text):
        blocks.append(m.group(1))
    # Also treat any line starting with "Scenario:" or "Feature:" as start of inline Gherkin
    # We return the full text; the line parser will pick up keywords anywhere.
    # But to reduce noise, if we found fenced blocks, prefer those.
    if blocks:
        return "\n".join(blocks)
    return text


def parse_gherkin_text(text: str, source_path: str = "", ac_id_prefix: str = "AC") -> GherkinParseResult:
    """Parse raw Gherkin text into structured scenarios and acceptance criteria."""
    result = GherkinParseResult(source_path=source_path)
    lines = _tokenize_lines(text)

    current_scenario: Optional[GherkinScenario] = None
    current_tags: List[str] = []
    in_examples = False
    example_headers: List[str] = []
    scenario_counter = 0
    buffer_steps: List[GherkinStep] = []

    def flush_scenario():
        nonlocal current_scenario, buffer_steps
        if current_scenario is None:
            return
        # Merge background steps into normal scenarios implicitly
        if current_scenario.background:
            result.background_steps.extend(current_scenario.steps)
        else:
            # Prepend background steps to each normal scenario for completeness
            merged = list(result.background_steps) + current_scenario.steps
            current_scenario.steps = merged
            result.scenarios.append(current_scenario)
        current_scenario = None
        buffer_steps = []

    i = 0
    while i < len(lines):
        line_no, line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # Tags
        if stripped.startswith("@"):
            current_tags.extend(TAG_RE.findall(stripped))
            i += 1
            continue

        # Feature (ignored as container)
        if re.match(r"^Feature:\s*(.+)$", stripped, re.IGNORECASE):
            # Just consume; we don't model Feature as a node
            i += 1
            continue

        # Background
        bg_match = re.match(r"^Background:\s*(.*)$", stripped, re.IGNORECASE)
        if bg_match:
            flush_scenario()
            current_scenario = GherkinScenario(
                id=f"{ac_id_prefix}-BG",
                name=bg_match.group(1).strip() or "Background",
                tags=list(current_tags),
                line_number=line_no,
                background=True,
            )
            current_tags = []
            i += 1
            continue

        # Scenario Outline
        so_match = re.match(r"^Scenario Outline:\s*(.+)$", stripped, re.IGNORECASE)
        if so_match:
            flush_scenario()
            scenario_counter += 1
            current_scenario = GherkinScenario(
                id=f"{ac_id_prefix}-{scenario_counter:02d}",
                name=so_match.group(1).strip(),
                tags=list(current_tags),
                line_number=line_no,
                outline=True,
            )
            current_tags = []
            i += 1
            continue

        # Scenario
        sc_match = re.match(r"^Scenario:\s*(.+)$", stripped, re.IGNORECASE)
        if sc_match:
            flush_scenario()
            scenario_counter += 1
            current_scenario = GherkinScenario(
                id=f"{ac_id_prefix}-{scenario_counter:02d}",
                name=sc_match.group(1).strip(),
                tags=list(current_tags),
                line_number=line_no,
            )
            current_tags = []
            i += 1
            continue

        # Examples table (simplified — read until blank line or new block)
        if re.match(r"^Examples:\s*", stripped, re.IGNORECASE):
            in_examples = True
            example_headers = []
            i += 1
            continue

        if in_examples:
            if not stripped or stripped.startswith("|") is False:
                in_examples = False
                if current_scenario:
                    current_scenario.examples = []  # We could parse table rows here
                i += 1
                continue
            # Very simple table parse
            cells = [c.strip() for c in stripped.split("|") if c.strip()]
            if cells:
                if not example_headers:
                    example_headers = cells
                else:
                    row = dict(zip(example_headers, cells))
                    if current_scenario:
                        current_scenario.examples.append(row)
            i += 1
            continue

        # Steps
        step_match = STEP_RE.match(stripped)
        if step_match and current_scenario is not None:
            keyword = step_match.group(1).capitalize()
            step_text = step_match.group(2).strip()
            # Resolve "And"/"But" to previous keyword for readability
            if keyword in ("And", "But") and current_scenario.steps:
                # Inherit from most recent non-And/But step for display, keep original keyword
                pass
            current_scenario.steps.append(
                GherkinStep(keyword=keyword, text=step_text, line_number=line_no)
            )
            i += 1
            continue

        i += 1

    flush_scenario()

    # Convert valid scenarios to AcceptanceCriterion objects
    for sc in result.scenarios:
        errors = []
        if not sc.has_given:
            errors.append(f"Scenario '{sc.name}' missing Given step")
        if not sc.has_when:
            errors.append(f"Scenario '{sc.name}' missing When step")
        if not sc.has_then:
            errors.append(f"Scenario '{sc.name}' missing Then step")
        if errors:
            result.syntax_errors.extend(errors)
            # Still emit as ambiguous / non-testable criterion so it's not silently dropped
            ac = AcceptanceCriterion(
                id=sc.id,
                text=sc.name,
                testable=False,
                gherkin=sc.gherkin_text,
                source_line=sc.line_number,
                tags=sc.tags,
                validation_errors=errors,
            )
            result.criteria.append(ac)
            result.ambiguities.append(f"{sc.id}: {', '.join(errors)}")
        else:
            ac = AcceptanceCriterion(
                id=sc.id,
                text=sc.name,
                testable=True,
                gherkin=sc.gherkin_text,
                source_line=sc.line_number,
                tags=sc.tags,
            )
            result.criteria.append(ac)

    # Final ambiguity check: zero criteria at all
    if not result.criteria:
        result.ambiguities.append(
            "AMBIGUOUS: No acceptance criteria (Given/When/Then) found in spec — requires clarification"
        )

    return result


def parse_feature_file(path: str) -> GherkinParseResult:
    """Parse a native .feature file."""
    text = Path(path).read_text(encoding="utf-8")
    return parse_gherkin_text(text, source_path=path, ac_id_prefix="AC")


def parse_markdown_for_gherkin(path: str) -> GherkinParseResult:
    """Extract and parse Gherkin blocks from a markdown spec."""
    text = Path(path).read_text(encoding="utf-8")
    gherkin_text = _extract_gherkin_blocks_from_markdown(text)
    result = parse_gherkin_text(gherkin_text, source_path=path, ac_id_prefix="AC")
    # If no fenced blocks were found, try to find inline Scenario lines in the raw text
    if not result.criteria:
        result = parse_gherkin_text(text, source_path=path, ac_id_prefix="AC")
    return result


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _fmt_markdown(result: GherkinParseResult) -> str:
    lines = [f"# Gherkin Parse Result: {Path(result.source_path).name}\n"]
    lines.append(f"## Acceptance Criteria ({len(result.criteria)})\n")
    for ac in result.criteria:
        status = "✅" if ac.testable else "⚠️"
        lines.append(f"### {status} {ac.id}\n")
        lines.append(f"- **Text**: {ac.text}\n")
        lines.append(f"- **Line**: {ac.source_line}\n")
        lines.append(f"- **Tags**: {', '.join(ac.tags) or 'none'}\n")
        if ac.validation_errors:
            lines.append(f"- **Errors**: {', '.join(ac.validation_errors)}\n")
        lines.append(f"```gherkin\n{ac.gherkin}\n```\n")
    if result.ambiguities:
        lines.append(f"\n## Ambiguities\n")
        for a in result.ambiguities:
            lines.append(f"- ⚠️ {a}\n")
    if result.syntax_errors:
        lines.append(f"\n## Syntax Errors\n")
        for e in result.syntax_errors:
            lines.append(f"- ❌ {e}\n")
    return "".join(lines)


def _fmt_json(result: GherkinParseResult) -> str:
    return json.dumps(
        {
            "source": result.source_path,
            "criteria": [c.to_dict() for c in result.criteria],
            "ambiguities": result.ambiguities,
            "syntax_errors": result.syntax_errors,
            "has_acceptance_criteria": result.has_acceptance_criteria,
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Gherkin / BDD acceptance criteria from specs.")
    parser.add_argument("input", nargs="?", help="Path to .feature or .md spec file")
    parser.add_argument("--embedded", dest="embedded_md", help="Explicitly parse a markdown spec for embedded Gherkin")
    parser.add_argument("--output", choices=["json", "markdown"], default="markdown", help="Output format")
    parser.add_argument("--prefix", default="AC", help="ID prefix for acceptance criteria (default: AC)")
    parser.add_argument("--strict", action="store_true", help="Exit with error if any ambiguity or syntax error found")
    args = parser.parse_args()

    target = args.embedded_md or args.input
    if not target:
        parser.print_help()
        return 1

    if not Path(target).exists():
        print(f"[ERROR] File not found: {target}")
        return 1

    is_feature = target.endswith(".feature")
    if is_feature:
        result = parse_feature_file(target)
    else:
        result = parse_markdown_for_gherkin(target)
        # Also merge with any adjacent .feature files in same directory
        feature_dir = Path(target).parent
        for feature_file in sorted(feature_dir.glob("*.feature")):
            if feature_file.name != Path(target).name:
                extra = parse_feature_file(str(feature_file))
                # Re-id to avoid collisions
                for ac in extra.criteria:
                    ac.id = f"{ac.id}-{feature_file.stem}"
                result.criteria.extend(extra.criteria)
                result.ambiguities.extend(extra.ambiguities)
                result.syntax_errors.extend(extra.syntax_errors)

    if args.output == "json":
        print(_fmt_json(result))
    else:
        print(_fmt_markdown(result))

    if not result.has_acceptance_criteria:
        print("\n[EXIT] No acceptance criteria found — spec is ambiguous.", file=sys.stderr)
        return 2

    if args.strict and (result.ambiguities or result.syntax_errors):
        print("\n[EXIT] Strict mode: ambiguities or syntax errors detected.", file=sys.stderr)
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
