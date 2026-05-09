#!/usr/bin/env python3
"""
generate_docs.py

Scans a project codebase, extracts documentation from source comments,
generates or updates READMEs, changelogs, and API reference docs,
and detects code-to-documentation drift.

Usage:
    python generate_docs.py --help
    python generate_docs.py api --src src/ --out docs/API.md --lang ts
    python generate_docs.py readme --out README.md
    python generate_docs.py changelog --out CHANGELOG.md --since v1.0.0
    python generate_docs.py sync --docs docs/
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class DocParam:
    name: str
    type_hint: str = ""
    description: str = ""
    default: str = ""


@dataclass
class DocFunction:
    name: str
    signature: str = ""
    description: str = ""
    params: List[DocParam] = field(default_factory=list)
    returns: str = ""
    returns_description: str = ""
    throws: List[Tuple[str, str]] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    deprecated: str = ""
    since: str = ""
    is_async: bool = False
    is_exported: bool = True


@dataclass
class DocClass:
    name: str
    description: str = ""
    methods: List[DocFunction] = field(default_factory=list)
    properties: List[DocParam] = field(default_factory=list)
    extends: str = ""
    deprecated: str = ""


@dataclass
class DocModule:
    name: str
    description: str = ""
    functions: List[DocFunction] = field(default_factory=list)
    classes: List[DocClass] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Language parsers
# ---------------------------------------------------------------------------

class BaseParser:
    BLOCK_START: str = ""
    BLOCK_END: str = ""
    BLOCK_LINE: str = ""
    TAG_PATTERN: re.Pattern = re.compile(r"^\s*@(\w+)")

    def __init__(self, source: str):
        self.source = source
        self.lines = source.splitlines()
        self.index = 0

    def parse(self) -> List[DocModule]:
        raise NotImplementedError

    def _extract_blocks(self) -> List[Tuple[int, int, List[str]]]:
        """Return list of (start_line, end_line, comment_lines) for doc blocks."""
        blocks = []
        i = 0
        while i < len(self.lines):
            block = self._try_block(i)
            if block:
                start, end, lines = block
                blocks.append((start, end, lines))
                i = end + 1
            else:
                i += 1
        return blocks

    def _try_block(self, i: int) -> Optional[Tuple[int, int, List[str]]]:
        return None

    def _next_definition(self, after: int) -> Optional[str]:
        for i in range(after, min(after + 10, len(self.lines))):
            line = self.lines[i].strip()
            if line and not line.startswith("#") and not line.startswith("//"):
                return line
        return None


class JSDocParser(BaseParser):
    """Parse JSDoc / TSDoc blocks."""

    BLOCK_START = "/**"
    BLOCK_END = "*/"
    TAG_PATTERN = re.compile(r"^\s*@(\w+)\s*(.*)")

    def _try_block(self, i: int) -> Optional[Tuple[int, int, List[str]]]:
        if not self.lines[i].strip().startswith("/**"):
            return None
        lines = []
        j = i
        while j < len(self.lines):
            raw = self.lines[j]
            stripped = raw.strip()
            if stripped.startswith("/**"):
                lines.append(raw)
            elif stripped.endswith("*/"):
                lines.append(raw)
                break
            else:
                lines.append(raw)
            j += 1
        return (i, j, lines)

    def parse(self) -> List[DocModule]:
        blocks = self._extract_blocks()
        functions: List[DocFunction] = []
        classes: List[DocClass] = []
        for start, end, lines in blocks:
            tags, description = self._parse_block(lines)
            definition = self._next_definition(end + 1)
            if not definition:
                continue
            if definition.startswith("class ") or definition.startswith("export class "):
                classes.append(self._build_class(tags, description, definition))
            elif "function" in definition or "=>" in definition or "async" in definition:
                functions.append(self._build_function(tags, description, definition))
            elif definition.startswith("export ") and ("const" in definition or "let" in definition or "var" in definition):
                # arrow function assigned to exported const
                if "=>" in definition:
                    functions.append(self._build_function(tags, description, definition))
        return [DocModule(name="API", functions=functions, classes=classes)]

    def _parse_block(self, lines: List[str]) -> Tuple[Dict[str, List[str]], str]:
        tags: Dict[str, List[str]] = {}
        description_lines = []
        current_tag = None
        for line in lines:
            line = line.strip()
            line = line.lstrip("/").lstrip("*").strip()
            if not line:
                continue
            m = self.TAG_PATTERN.match(line)
            if m:
                current_tag = m.group(1)
                rest = m.group(2)
                tags.setdefault(current_tag, []).append(rest)
            elif current_tag:
                tags[current_tag][-1] += " " + line
            else:
                description_lines.append(line)
        description = " ".join(description_lines).strip()
        return tags, description

    def _build_function(self, tags: Dict[str, List[str]], description: str, definition: str) -> DocFunction:
        name = self._extract_name(definition)
        sig = self._extract_signature(definition)
        params = []
        for p in tags.get("param", []):
            param = self._parse_param(p)
            params.append(param)
        returns = ""
        returns_desc = ""
        for r in tags.get("returns", []):
            returns, returns_desc = self._parse_returns(r)
        throws = []
        for t in tags.get("throws", []):
            throws.append(self._parse_throws(t))
        deprecated = " ".join(tags.get("deprecated", []))
        since = " ".join(tags.get("since", []))
        examples = tags.get("example", [])
        return DocFunction(
            name=name,
            signature=sig,
            description=description,
            params=params,
            returns=returns,
            returns_description=returns_desc,
            throws=throws,
            examples=examples,
            deprecated=deprecated,
            since=since,
            is_async="async" in definition,
        )

    def _build_class(self, tags: Dict[str, List[str]], description: str, definition: str) -> DocClass:
        name = self._extract_name(definition)
        extends = ""
        if "extends" in definition:
            parts = definition.split("extends")
            extends = parts[1].strip().split(" ")[0].rstrip("{").rstrip(" ")
        deprecated = " ".join(tags.get("deprecated", []))
        return DocClass(name=name, description=description, extends=extends, deprecated=deprecated)

    def _extract_name(self, definition: str) -> str:
        definition = definition.replace("export ", "").replace("async ", "").replace("function ", "").replace("class ", "")
        definition = definition.split("(")[0].split("=")[0].strip()
        return definition

    def _extract_signature(self, definition: str) -> str:
        if "{" in definition:
            definition = definition.split("{")[0].strip()
        if "=>" in definition:
            definition = definition.split("=>")[0].strip()
        return definition

    def _parse_param(self, text: str) -> DocParam:
        parts = text.split(" ", 2)
        if parts[0].startswith("{"):
            type_hint = parts[0].strip("{}")
            name = parts[1] if len(parts) > 1 else ""
            desc = parts[2] if len(parts) > 2 else ""
        else:
            name = parts[0]
            type_hint = ""
            desc = " ".join(parts[1:])
        default = ""
        if " - " in desc:
            desc, default = desc.rsplit(" - ", 1)
        return DocParam(name=name, type_hint=type_hint, description=desc, default=default)

    def _parse_returns(self, text: str) -> Tuple[str, str]:
        parts = text.split(" ", 1)
        if parts[0].startswith("{"):
            return parts[0].strip("{}"), parts[1] if len(parts) > 1 else ""
        return "", text

    def _parse_throws(self, text: str) -> Tuple[str, str]:
        parts = text.split(" ", 1)
        return parts[0], parts[1] if len(parts) > 1 else ""


class PythonDocParser(BaseParser):
    """Parse Python docstrings."""

    def _try_block(self, i: int) -> Optional[Tuple[int, int, List[str]]]:
        stripped = self.lines[i].strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote = stripped[:3]
            lines = [stripped]
            j = i
            if not stripped[3:].endswith(quote):
                j = i + 1
                while j < len(self.lines):
                    raw = self.lines[j]
                    lines.append(raw)
                    if quote in raw:
                        break
                    j += 1
            return (i, j, lines)
        return None

    def parse(self) -> List[DocModule]:
        blocks = self._extract_blocks()
        functions: List[DocFunction] = []
        classes: List[DocClass] = []
        for start, end, lines in blocks:
            description, params, returns, raises = self._parse_docstring(lines)
            definition = self._next_definition(end + 1)
            if not definition:
                continue
            if definition.startswith("class ") or definition.startswith("async class"):
                classes.append(DocClass(name=self._extract_name(definition), description=description))
            elif definition.startswith("def ") or definition.startswith("async def "):
                functions.append(
                    DocFunction(
                        name=self._extract_name(definition),
                        signature=self._extract_signature(definition),
                        description=description,
                        params=params,
                        returns=returns[0] if returns else "",
                        returns_description=returns[1] if returns else "",
                        throws=raises,
                        is_async="async def" in definition,
                    )
                )
        return [DocModule(name="API", functions=functions, classes=classes)]

    def _parse_docstring(self, lines: List[str]) -> Tuple[str, List[DocParam], List[Tuple[str, str]], List[Tuple[str, str]]]:
        text = "\n".join(lines)
        for q in ('"""', "'''"):
            text = text.replace(q, "")
        text = text.strip()
        # Sections
        sections = re.split(r"\n(?=:param|:return|:raises|:type|:rtype|:example)", text)
        description = sections[0].strip() if sections else ""
        params = []
        returns: List[Tuple[str, str]] = []
        raises = []
        for sec in sections[1:]:
            sec = sec.strip()
            if sec.startswith(":param"):
                m = re.match(r":param\s+(\w+):\s*(.*)", sec, re.DOTALL)
                if m:
                    params.append(DocParam(name=m.group(1), description=m.group(2).strip()))
            elif sec.startswith(":return"):
                m = re.match(r":returns?:\s*(.*)", sec, re.DOTALL)
                if m:
                    returns.append(("", m.group(1).strip()))
            elif sec.startswith(":raise"):
                m = re.match(r":raises?\s+(\w+):\s*(.*)", sec, re.DOTALL)
                if m:
                    raises.append((m.group(1), m.group(2).strip()))
        return description, params, returns, raises

    def _extract_name(self, definition: str) -> str:
        definition = definition.replace("async def ", "def ").replace("def ", "").split("(")[0].split(":")[0].strip()
        return definition

    def _extract_signature(self, definition: str) -> str:
        return definition.rstrip(":").strip()


class GoDocParser(BaseParser):
    """Parse Go doc comments (no block syntax; preceding // lines)."""

    def _try_block(self, i: int) -> Optional[Tuple[int, int, List[str]]]:
        if not self.lines[i].strip().startswith("// "):
            return None
        lines = []
        j = i
        while j >= 0 and self.lines[j].strip().startswith("//"):
            j -= 1
        j += 1
        start = j
        while j < len(self.lines) and self.lines[j].strip().startswith("//"):
            lines.append(self.lines[j])
            j += 1
        return (start, j - 1, lines)

    def parse(self) -> List[DocModule]:
        blocks = self._extract_blocks()
        functions: List[DocFunction] = []
        for start, end, lines in blocks:
            description = "\n".join([line.strip().lstrip("/").strip() for line in lines]).strip()
            definition = self._next_definition(end + 1)
            if not definition:
                continue
            if definition.startswith("func "):
                functions.append(
                    DocFunction(
                        name=self._extract_name(definition),
                        signature=self._extract_signature(definition),
                        description=description,
                    )
                )
        return [DocModule(name="API", functions=functions)]

    def _extract_name(self, definition: str) -> str:
        definition = definition.replace("func ", "").split("(")[0].strip()
        if " " in definition:
            definition = definition.split(" ")[1]
        return definition

    def _extract_signature(self, definition: str) -> str:
        return definition.strip()


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

class MarkdownAPIGenerator:
    def generate(self, modules: List[DocModule]) -> str:
        lines: List[str] = [
            "# API Reference",
            "",
            f"Generated on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.",
            "",
        ]
        for mod in modules:
            if mod.description:
                lines.append(mod.description)
                lines.append("")
            for cls in mod.classes:
                lines.extend(self._render_class(cls))
            for fn in mod.functions:
                lines.extend(self._render_function(fn))
        return "\n".join(lines)

    def _render_function(self, fn: DocFunction) -> List[str]:
        lines: List[str] = []
        sig = f"`{fn.signature}`" if fn.signature else f"`{fn.name}()`"
        anchor = fn.name.lower().replace(" ", "-")
        lines.append(f"### {fn.name}")
        lines.append("")
        if fn.deprecated:
            lines.append(f"> **Deprecated.** {fn.deprecated}")
            lines.append("")
        lines.append(sig)
        lines.append("")
        if fn.description:
            lines.append(fn.description)
            lines.append("")
        if fn.params:
            lines.append("**Parameters**")
            lines.append("")
            lines.append("| Name | Type | Description |")
            lines.append("|------|------|-------------|")
            for p in fn.params:
                type_col = f"`{p.type_hint}`" if p.type_hint else ""
                lines.append(f"| `{p.name}` | {type_col} | {p.description} |")
            lines.append("")
        if fn.returns or fn.returns_description:
            lines.append("**Returns**")
            lines.append("")
            ret_type = f"`{fn.returns}`" if fn.returns else ""
            lines.append(f"| Type | Description |")
            lines.append(f"|------|-------------|")
            lines.append(f"| {ret_type} | {fn.returns_description} |")
            lines.append("")
        if fn.throws:
            lines.append("**Throws**")
            lines.append("")
            lines.append("| Error | Condition |")
            lines.append("|-------|-----------|")
            for err, cond in fn.throws:
                lines.append(f"| `{err}` | {cond} |")
            lines.append("")
        if fn.examples:
            lines.append("**Example**")
            lines.append("")
            for ex in fn.examples:
                lines.append("```")
                lines.append(ex)
                lines.append("```")
                lines.append("")
        if fn.since:
            lines.append(f"*Since: {fn.since}*")
            lines.append("")
        lines.append("---")
        lines.append("")
        return lines

    def _render_class(self, cls: DocClass) -> List[str]:
        lines: List[str] = []
        lines.append(f"## Class `{cls.name}`")
        lines.append("")
        if cls.deprecated:
            lines.append(f"> **Deprecated.** {cls.deprecated}")
            lines.append("")
        if cls.description:
            lines.append(cls.description)
            lines.append("")
        if cls.extends:
            lines.append(f"**Extends:** `{cls.extends}`")
            lines.append("")
        if cls.properties:
            lines.append("**Properties**")
            lines.append("")
            lines.append("| Property | Type | Description |")
            lines.append("|----------|------|-------------|")
            for p in cls.properties:
                type_col = f"`{p.type_hint}`" if p.type_hint else ""
                lines.append(f"| `{p.name}` | {type_col} | {p.description} |")
            lines.append("")
        if cls.methods:
            lines.append("**Methods**")
            lines.append("")
            for m in cls.methods:
                lines.extend(self._render_function(m))
        lines.append("---")
        lines.append("")
        return lines


# ---------------------------------------------------------------------------
# README generator
# ---------------------------------------------------------------------------

def detect_project_metadata(root: Path) -> Dict[str, str]:
    meta: Dict[str, str] = {
        "name": root.name,
        "description": "",
        "license": "",
        "version": "",
    }
    # package.json
    pkg = root / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            meta["name"] = data.get("name", meta["name"])
            meta["description"] = data.get("description", "")
            meta["license"] = data.get("license", "")
            meta["version"] = data.get("version", "")
        except Exception:
            pass
    # pyproject.toml
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8")
        m = re.search(r'name\s*=\s*"([^"]+)"', text)
        if m:
            meta["name"] = m.group(1)
        m = re.search(r'description\s*=\s*"([^"]+)"', text)
        if m:
            meta["description"] = m.group(1)
        m = re.search(r'version\s*=\s*"([^"]+)"', text)
        if m:
            meta["version"] = m.group(1)
    # Cargo.toml
    cargo = root / "Cargo.toml"
    if cargo.exists():
        text = cargo.read_text(encoding="utf-8")
        m = re.search(r'^name\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if m:
            meta["name"] = m.group(1)
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if m:
            meta["version"] = m.group(1)
        m = re.search(r'^description\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if m:
            meta["description"] = m.group(1)
    # go.mod
    gomod = root / "go.mod"
    if gomod.exists():
        text = gomod.read_text(encoding="utf-8")
        m = re.search(r'module\s+(\S+)', text)
        if m:
            meta["name"] = m.group(1).split("/")[-1]
    # LICENSE
    for lic in (root / "LICENSE", root / "LICENSE.txt", root / "LICENSE.md"):
        if lic.exists():
            meta["license"] = lic.stem
            break
    return meta


def generate_readme(root: Path, meta: Dict[str, str]) -> str:
    name = meta.get("name", root.name)
    desc = meta.get("description", "")
    version = meta.get("version", "")
    license_str = meta.get("license", "")
    lines = [
        f"# {name}",
        "",
        f"{desc}",
        "",
    ]
    if version:
        lines.append(f"[![Version](https://img.shields.io/badge/version-{version}-blue)]()")
    if license_str:
        lines.append(f"[![License](https://img.shields.io/badge/license-{license_str}-green)]()")
    if version or license_str:
        lines.append("")
    lines.extend([
        "## Overview",
        "",
        f"{desc}",
        "",
        "## Installation",
        "",
        "```bash",
        "# TODO: add install command",
        "```",
        "",
        "## Quick Start",
        "",
        "```",
        "# TODO: add quick start example",
        "```",
        "",
        "## Project Structure",
        "",
        "```",
    ])
    # Light tree
    for item in sorted(root.iterdir()):
        if item.name.startswith(".") and item.name not in {".github", ".ci"}:
            continue
        if item.is_dir():
            lines.append(f"{item.name}/")
        else:
            lines.append(f"{item.name}")
    lines.extend([
        "```",
        "",
        "## Contributing",
        "",
        "Please read [CONTRIBUTING.md](CONTRIBUTING.md).",
        "",
        "## License",
        "",
        f"See [LICENSE](LICENSE).",
        "",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Changelog generator
# ---------------------------------------------------------------------------

def generate_changelog(since_tag: Optional[str] = None) -> str:
    cmd = ["git", "log", "--pretty=format:%s|%H|%ad", "--date=short"]
    if since_tag:
        cmd.append(f"{since_tag}..HEAD")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to run git log: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("git not found in PATH.", file=sys.stderr)
        sys.exit(1)

    categories: Dict[str, List[str]] = {
        "Added": [],
        "Changed": [],
        "Deprecated": [],
        "Removed": [],
        "Fixed": [],
        "Security": [],
    }
    for line in result.stdout.splitlines():
        if "|" not in line:
            continue
        msg, sha, date = line.split("|", 2)
        msg = msg.strip()
        if msg.startswith("feat"):
            categories["Added"].append(f"- {msg} ({sha[:7]})")
        elif msg.startswith("fix"):
            categories["Fixed"].append(f"- {msg} ({sha[:7]})")
        elif msg.startswith("docs"):
            categories["Changed"].append(f"- {msg} ({sha[:7]})")
        elif msg.startswith("refactor") or msg.startswith("perf"):
            categories["Changed"].append(f"- {msg} ({sha[:7]})")
        elif msg.startswith("chore") or msg.startswith("test"):
            categories["Changed"].append(f"- {msg} ({sha[:7]})")
        elif msg.startswith("security") or msg.startswith("sec"):
            categories["Security"].append(f"- {msg} ({sha[:7]})")
        elif msg.startswith("BREAKING CHANGE"):
            categories["Changed"].append(f"- **BREAKING** {msg} ({sha[:7]})")
        else:
            categories["Changed"].append(f"- {msg} ({sha[:7]})")

    lines = [
        "# Changelog",
        "",
        "All notable changes to this project will be documented in this file.",
        "",
        "## [Unreleased]",
        "",
    ]
    for cat in ["Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"]:
        entries = categories.get(cat, [])
        if entries:
            lines.append(f"### {cat}")
            lines.extend(entries)
            lines.append("")
    if all(not v for v in categories.values()):
        lines.append("_No changes yet._")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sync checker
# ---------------------------------------------------------------------------

def check_sync(root: Path, docs_dir: Path) -> List[str]:
    issues: List[str] = []
    # Collect public API symbols from source
    public_symbols = set()
    for ext, parser_cls in {
        ".js": JSDocParser,
        ".ts": JSDocParser,
        ".tsx": JSDocParser,
        ".py": PythonDocParser,
        ".go": GoDocParser,
    }.items():
        for src in root.rglob(f"*{ext}"):
            if "node_modules" in str(src) or ".git" in str(src) or "vendor" in str(src):
                continue
            try:
                parser = parser_cls(src.read_text(encoding="utf-8"))
                modules = parser.parse()
                for mod in modules:
                    for fn in mod.functions:
                        public_symbols.add(fn.name)
                    for cls in mod.classes:
                        public_symbols.add(cls.name)
            except Exception:
                pass

    # Scan docs for references to those symbols
    if docs_dir.exists():
        for doc in docs_dir.rglob("*.md"):
            text = doc.read_text(encoding="utf-8")
            for sym in public_symbols:
                # crude: symbol present in doc but not as a heading could mean reference
                pass
        # More practical: check README for stale install / run commands
        readme = root / "README.md"
        if readme.exists():
            text = readme.read_text(encoding="utf-8")
            # Check for common stale patterns
            if "npm install" in text and not (root / "package.json").exists():
                issues.append("README references npm install but no package.json found")
            if "pip install" in text and not (root / "pyproject.toml").exists() and not (root / "setup.py").exists():
                issues.append("README references pip install but no Python packaging files found")
            if "cargo build" in text and not (root / "Cargo.toml").exists():
                issues.append("README references cargo but no Cargo.toml found")
            if "go build" in text and not (root / "go.mod").exists():
                issues.append("README references go build but no go.mod found")

    # Check for undocumented public symbols
    for sym in public_symbols:
        found = False
        if docs_dir.exists():
            for doc in docs_dir.rglob("*.md"):
                if sym in doc.read_text(encoding="utf-8"):
                    found = True
                    break
        if not found:
            issues.append(f"Public symbol '{sym}' not found in documentation")

    return issues


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate and maintain developer documentation from code."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # api
    api_parser = subparsers.add_parser("api", help="Generate API reference Markdown")
    api_parser.add_argument("--src", required=True, help="Source directory to scan")
    api_parser.add_argument("--out", required=True, help="Output Markdown file")
    api_parser.add_argument("--lang", choices=["ts", "js", "py", "go", "auto"], default="auto",
                            help="Source language (default: auto-detect)")

    # readme
    readme_parser = subparsers.add_parser("readme", help="Generate README from project metadata")
    readme_parser.add_argument("--root", default=".", help="Project root directory")
    readme_parser.add_argument("--out", default="README.md", help="Output file")

    # changelog
    changelog_parser = subparsers.add_parser("changelog", help="Generate changelog from conventional commits")
    changelog_parser.add_argument("--since", help="Git tag to generate changelog since")
    changelog_parser.add_argument("--out", help="Output file (default: print to stdout)")

    # sync
    sync_parser = subparsers.add_parser("sync", help="Check code-to-doc synchronization issues")
    sync_parser.add_argument("--root", default=".", help="Project root directory")
    sync_parser.add_argument("--docs", default="docs", help="Documentation directory")

    args = parser.parse_args()

    if args.command == "api":
        src_dir = Path(args.src)
        lang = args.lang
        all_modules: List[DocModule] = []
        parser_map = {
            ".js": JSDocParser,
            ".ts": JSDocParser,
            ".tsx": JSDocParser,
            ".py": PythonDocParser,
            ".go": GoDocParser,
        }
        if lang == "auto":
            # infer from first matching file
            for ext in parser_map:
                found = list(src_dir.rglob(f"*{ext}"))
                if found:
                    lang = ext.lstrip(".")
                    if lang in ("js", "ts", "tsx"):
                        lang = "ts"
                    break
        ext_map = {"ts": [".ts", ".tsx", ".js"], "js": [".js", ".ts", ".tsx"],
                    "py": [".py"], "go": [".go"]}
        extensions = ext_map.get(lang, [".ts", ".js"])
        for ext in extensions:
            for f in src_dir.rglob(f"*{ext}"):
                if "node_modules" in str(f) or ".git" in str(f) or "vendor" in str(f):
                    continue
                try:
                    cls = parser_map.get(ext, JSDocParser)
                    p = cls(f.read_text(encoding="utf-8"))
                    mods = p.parse()
                    for m in mods:
                        m.name = str(f.relative_to(src_dir))
                    all_modules.extend(mods)
                except Exception as e:
                    print(f"Warning: failed to parse {f}: {e}", file=sys.stderr)
        gen = MarkdownAPIGenerator()
        md = gen.generate(all_modules)
        out_path = Path(args.out)
        out_path.write_text(md, encoding="utf-8")
        print(f"Generated API docs: {out_path}")

    elif args.command == "readme":
        root = Path(args.root).resolve()
        meta = detect_project_metadata(root)
        readme = generate_readme(root, meta)
        out_path = Path(args.out)
        out_path.write_text(readme, encoding="utf-8")
        print(f"Generated README: {out_path}")

    elif args.command == "changelog":
        changelog = generate_changelog(since_tag=args.since)
        if args.out:
            out_path = Path(args.out)
            out_path.write_text(changelog, encoding="utf-8")
            print(f"Generated changelog: {out_path}")
        else:
            print(changelog)

    elif args.command == "sync":
        root = Path(args.root).resolve()
        docs_dir = Path(args.docs).resolve()
        issues = check_sync(root, docs_dir)
        if issues:
            print("Sync issues found:")
            for issue in issues:
                print(f"  - {issue}")
            return 1
        else:
            print("No sync issues detected.")
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
