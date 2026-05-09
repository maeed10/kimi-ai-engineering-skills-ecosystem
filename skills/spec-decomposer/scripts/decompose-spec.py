#!/usr/bin/env python3
"""
decompose-spec.py  v4.0

Reads SPEC.md / PRD.md / REQUIREMENTS.md, validates requirements, infers non-functional
requirements, cross-references Architecture Design ADRs, decomposes into atomic task
nodes with dependencies, and writes Obsidian-ready markdown files.

v4.0 upgrades:
- Gherkin/BDD mode: parses Given/When/Then blocks via gherkin-parser.py
- NFR inference: auto-infers performance, security, scalability requirements from context
- ADR cross-reference: reads ADRs for constraints, flags violations, propagates NFRs
- Mandatory field validation: rejects decomposition if description, acceptance criteria,
  definition of done, or estimated effort are missing
- Safety rule enforcement: never silently drop non-functionals, never decompose without
  at least one acceptance criterion per task, always cross-reference ADRs

Usage:
    python decompose-spec.py <path-to-spec.md> [--output-dir ./vault/tasks] [--adr-dir ./adr]
"""

import argparse
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Tuple

# Dynamically load gherkin-parser.py (module names cannot contain hyphens)
_SCRIPT_DIR = Path(__file__).parent
_GHERKIN_PARSER_PATH = _SCRIPT_DIR / "gherkin-parser.py"
_spec = importlib.util.spec_from_file_location("gherkin_parser", _GHERKIN_PARSER_PATH)
_gherkin_module = importlib.util.module_from_spec(_spec)
sys.modules["gherkin_parser"] = _gherkin_module
_spec.loader.exec_module(_gherkin_module)

GherkinParseResult = _gherkin_module.GherkinParseResult
parse_markdown_for_gherkin = _gherkin_module.parse_markdown_for_gherkin


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class AcceptanceCriterion:
    id: str
    text: str
    testable: bool = True
    gherkin: str = ""
    inferred: bool = False  # True if this AC was inferred by NFR engine, not explicit in spec


@dataclass
class Requirement:
    id: str
    section: str
    text: str
    req_type: str  # "functional" | "non-functional" | "security" | "performance" | "story"
    acceptance_criteria: List[AcceptanceCriterion] = field(default_factory=list)
    definition_of_done: List[str] = field(default_factory=list)
    priority: str = "P2"
    ambiguous: bool = False
    ambiguity_reasons: List[str] = field(default_factory=list)
    inferred_nfrs: List[str] = field(default_factory=list)  # NFRs inferred from context


@dataclass
class ADRConstraint:
    id: str
    title: str
    decision: str
    constraints: List[str] = field(default_factory=list)
    consequences: List[str] = field(default_factory=list)
    nfrs: List[str] = field(default_factory=list)


@dataclass
class TaskNode:
    id: str
    node_type: str  # "epic" | "story" | "task" | "subtask"
    parent_id: str
    title: str
    source_spec: str
    source_section: str
    source_requirement: str
    status: str = "pending"
    priority: str = "P2"
    acceptance_criteria: List[str] = field(default_factory=list)
    definition_of_done: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    blocks: List[str] = field(default_factory=list)
    assignee: str = ""
    estimate: str = ""
    gherkin_scenario: str = ""
    body: str = ""
    adr_references: List[str] = field(default_factory=list)
    inferred_nfrs: List[str] = field(default_factory=list)
    security_tags: List[str] = field(default_factory=list)
    validation_errors: List[str] = field(default_factory=list)
    flagged: bool = False


@dataclass
class DecompositionResult:
    spec_path: str
    spec_title: str = ""
    requirements: List[Requirement] = field(default_factory=list)
    nodes: List[TaskNode] = field(default_factory=list)
    ambiguities: List[str] = field(default_factory=list)
    dependency_edges: List[tuple] = field(default_factory=list)
    adr_violations: List[str] = field(default_factory=list)
    inferred_nfr_log: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Spec parsing
# ---------------------------------------------------------------------------

REQUIREMENT_RE = re.compile(
    r"^(?:[-*]|\d+\.\s*)?(REQ|FR|NFR|SR|PERF|US)-(\d+)[\s:.:-]+(.+)$",
    re.IGNORECASE | re.MULTILINE,
)

STORY_RE = re.compile(
    r"^(?:[-*]|\d+\.\s*)?(?:As\s+a|As\s+an)\s+(.+)$",
    re.IGNORECASE | re.MULTILINE,
)

AC_RE = re.compile(
    r"^(?:[-*]|\d+\.\s*)?AC-?(\d+)?[\s:.:-]+(.+)$",
    re.IGNORECASE | re.MULTILINE,
)

DOD_RE = re.compile(
    r"^(?:[-*]|\d+\.\s*)?(?:Definition\s+of\s+Done|DoD)[\s:.:-]+(.+)$",
    re.IGNORECASE | re.MULTILINE,
)

PRIORITY_RE = re.compile(r"Priority\s*[:\-]\s*(P0|P1|P2|P3)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# NFR Inference Engine
# ---------------------------------------------------------------------------

NFR_CONTEXT_PATTERNS: List[Tuple[List[str], List[str], List[str], List[str]]] = [
    # (keywords, inferred_performance, inferred_security, inferred_scalability)
    (
        ["auth", "login", "token", "session", "password", "sso", "oauth", "jwt"],
        ["Latency < 100ms for auth endpoints at p99", "Token refresh < 50ms"],
        ["OWASP ASVS Level 2 compliance", "Secure token storage (httpOnly, SameSite)", "Rate limiting on login endpoints"],
        ["Support 10,000 concurrent sessions"],
    ),
    (
        ["payment", "checkout", "billing", "credit card", "card", "pci", "wallet", "transaction"],
        ["Payment flow completes < 3s end-to-end", "Webhook delivery < 5s"],
        ["PCI-DSS SAQ-A compliance", "End-to-end encryption for card data", "Audit log all payment events", "No card data in logs"],
        ["Handle 1,000 concurrent checkout sessions"],
    ),
    (
        ["upload", "file", "image", "video", "media", "attachment", "blob"],
        ["Upload processing < 5s per 10MB", "Thumbnail generation < 2s"],
        ["Virus / malware scan on upload", "Content-Type validation", "Sandbox file processing"],
        ["Storage scales to 10TB", "Support 500 concurrent uploads"],
    ),
    (
        ["search", "query", "filter", "autocomplete", "suggest", "index"],
        ["Search results < 200ms at p99", "Autocomplete < 100ms"],
        ["Input sanitization on query params", "Prevent SQL/NoSQL injection in search"],
        ["Index supports 1M documents", "Query throughput 5,000 QPS"],
    ),
    (
        ["user count", "concurrent", "dau", "mau", "million users", "daily active", "monthly active", "subscriber"],
        ["API p99 < 200ms under peak load", "Page load < 1s"],
        ["DDoS protection on public endpoints", "Bot detection"],
        ["Horizontal scaling to 1M DAU", "Database read replicas", "CDN for static assets", "Cache hit ratio > 80%"],
    ),
    (
        ["real-time", "websocket", "live", "stream", "chat", "notification", "push"],
        ["Message delivery < 100ms", "Heartbeat interval 30s"],
        ["Authenticate every WebSocket connection", "Rate-limit messages per user"],
        ["Support 100,000 concurrent connections", "Graceful degradation when > capacity"],
    ),
    (
        ["export", "report", "download", "csv", "pdf", "excel", "batch"],
        ["Export generation < 30s for 100k rows", "Progress reporting for long jobs"],
        ["RBAC on exported data", "Watermark sensitive reports", "Audit log downloads"],
        ["Async job queue for exports", "Memory-safe streaming (> 1GB files)"],
    ),
    (
        ["api", "endpoint", "rest", "graphql", "grpc"],
        ["Response p99 < 200ms", "Error rate < 0.1%"],
        ["OAuth2 / mTLS for service-to-service", "Input validation on all endpoints", "Rate limiting per client"],
        ["Auto-scaling based on request queue depth", "Circuit breaker on downstream calls"],
    ),
]


def infer_non_functional_requirements(text: str, section_heading: str) -> Tuple[List[str], List[str], List[str]]:
    """Infer performance, security, and scalability requirements from spec text.

    Returns:
        (performance_nfrs, security_nfrs, scalability_nfrs)
    """
    lowered = (text + " " + section_heading).lower()
    perf: List[str] = []
    sec: List[str] = []
    scale: List[str] = []

    for keywords, p, s, sc in NFR_CONTEXT_PATTERNS:
        if any(k in lowered for k in keywords):
            perf.extend(p)
            sec.extend(s)
            scale.extend(sc)

    # Deduplicate while preserving order
    def uniq(lst: List[str]) -> List[str]:
        seen = set()
        out = []
        for item in lst:
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out

    return uniq(perf), uniq(sec), uniq(scale)


# ---------------------------------------------------------------------------
# ADR Cross-Reference Engine
# ---------------------------------------------------------------------------

ADR_RE = re.compile(
    r"^(?:ADR|ADR-?)(\d+)[\s:.:-]+(.+)$",
    re.IGNORECASE | re.MULTILINE,
)


def load_adr_constraints(adr_dir: str) -> List[ADRConstraint]:
    """Read all ADR markdown files in a directory and extract constraints."""
    adrs: List[ADRConstraint] = []
    path = Path(adr_dir)
    if not path.exists() or not path.is_dir():
        return adrs

    for md_file in sorted(path.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        # Extract ADR ID from filename or frontmatter
        adr_id = md_file.stem
        title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else adr_id

        decision_match = re.search(
            r"(?:Decision|## Decision|### Decision)\s*\n+(.+?)(?=\n#{1,3}\s|\Z)",
            text, re.IGNORECASE | re.DOTALL,
        )
        decision = decision_match.group(1).strip() if decision_match else ""

        # Extract constraints / consequences
        constraints: List[str] = []
        consequences: List[str] = []
        nfrs: List[str] = []

        for heading, pattern in [
            ("constraints", r"(?:Constraints|## Constraints|### Constraints)\s*\n+(.+?)(?=\n#{1,3}\s|\Z)"),
            ("consequences", r"(?:Consequences|## Consequences|### Consequences)\s*\n+(.+?)(?=\n#{1,3}\s|\Z)"),
            ("non-functional", r"(?:Non-Functional|NFR|## Non-Functional|### Non-Functional)\s*\n+(.+?)(?=\n#{1,3}\s|\Z)"),
        ]:
            m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if m:
                block = m.group(1)
                items = [line.strip().lstrip("-* ") for line in block.splitlines() if line.strip().lstrip("-* ")]
                if heading == "constraints":
                    constraints.extend(items)
                elif heading == "consequences":
                    consequences.extend(items)
                else:
                    nfrs.extend(items)

        adrs.append(ADRConstraint(
            id=adr_id,
            title=title,
            decision=decision,
            constraints=constraints,
            consequences=consequences,
            nfrs=nfrs,
        ))

    return adrs


def validate_adr_compliance(nodes: List[TaskNode], adrs: List[ADRConstraint]) -> Tuple[List[str], List[TaskNode]]:
    """Flag tasks that violate ADR constraints and return updated nodes + violation list."""
    violations: List[str] = []
    if not adrs:
        return violations, nodes

    # Generic words that should NOT trigger violation matches
    GENERIC_WORDS = {
        "auth", "login", "token", "user", "data", "access", "endpoint", "api", "service",
        "client", "server", "request", "response", "database", "storage", "cache",
        "frontend", "backend", "mobile", "web", "app", "system", "application",
        "direct", "from", "with", "using", "must", "should", "will", "that", "this",
        "have", "been", "only", "all", "any", "use", "based", "for", "the", "and",
    }

    for node in nodes:
        node_text = (node.title + " " + node.body).lower()
        for adr in adrs:
            # Quick relevance filter: skip ADR if no keyword overlap with node
            adr_text = (adr.title + " " + " ".join(adr.constraints + adr.nfrs)).lower()
            adr_keywords = set(w for w in re.findall(r"[a-z]+", adr_text) if len(w) > 3 and w not in GENERIC_WORDS)
            node_keywords = set(w for w in re.findall(r"[a-z]+", node_text) if len(w) > 3)
            if not (adr_keywords & node_keywords):
                continue

            adr_matched = False
            for constraint in adr.constraints:
                constraint_lower = constraint.lower()
                # Detect forbidding constraints
                forbidden_prefixes = [
                    "no ", "must not ", "do not ", "forbidden ", "avoid ", "never ",
                    "prohibited ", "banned ", "disallowed ", "shall not ", "will not ",
                ]
                is_forbidding = any(
                    constraint_lower.startswith(fp) or (" " + fp) in constraint_lower
                    for fp in forbidden_prefixes
                )
                if is_forbidding:
                    # Extract technical terms: capitalized words, hyphenated words, quoted strings
                    tech_terms = re.findall(
                        r'"([^"]+)"|\b([A-Z][a-zA-Z0-9]*(?:-[a-zA-Z0-9]+)*)\b',
                        constraint,
                    )
                    candidates = []
                    for quoted, capitalized in tech_terms:
                        term = quoted or capitalized
                        if term and len(term) > 2:
                            candidates.append(term.lower())
                    # Also grab the first significant noun phrase after the forbidden prefix
                    for fp in forbidden_prefixes:
                        if constraint_lower.startswith(fp):
                            remainder = constraint_lower[len(fp):]
                            phrase = " ".join(remainder.split()[:3])
                            candidates.extend([w for w in phrase.split() if w not in GENERIC_WORDS])
                            break

                    candidates = list(dict.fromkeys([c for c in candidates if c not in GENERIC_WORDS]))
                    matched_terms = [c for c in candidates if c in node_text]
                    if matched_terms:
                        violation = (
                            f"{node.id} may violate {adr.id} ({adr.title}): "
                            f"constraint '{constraint}' — forbidden term(s) detected: {', '.join(matched_terms)}"
                        )
                        violations.append(violation)
                        node.validation_errors.append(violation)
                        adr_matched = True
                        node.flagged = True
                    else:
                        adr_matched = True
                else:
                    adr_matched = True
            if adr_matched and adr.id not in node.adr_references:
                node.adr_references.append(adr.id)

    return violations, nodes


def propagate_adr_nfrs_to_tasks(nodes: List[TaskNode], adrs: List[ADRConstraint]) -> List[TaskNode]:
    """Inject ADR-derived non-functional acceptance criteria into relevant task nodes."""
    for adr in adrs:
        adr_keywords = set(re.findall(r"[a-z]+", (adr.title + " " + " ".join(adr.nfrs)).lower()))
        for nfr in adr.nfrs:
            for node in nodes:
                if node.node_type in ("task", "subtask"):
                    node_text = (node.title + " " + node.body).lower()
                    node_keywords = set(re.findall(r"[a-z]+", node_text))
                    # Only inject if ADR and task share at least 2 significant keywords
                    # or if the NFR text itself contains keywords from the task
                    nfr_lower = nfr.lower()
                    nfr_keywords = set(re.findall(r"[a-z]+", nfr_lower))
                    shared_with_nfr = len(nfr_keywords & node_keywords)
                    shared_with_adr = len(adr_keywords & node_keywords)
                    if shared_with_nfr >= 1 or shared_with_adr >= 2:
                        ac_text = f"[{adr.id}] {nfr}"
                        if ac_text not in node.definition_of_done:
                            node.definition_of_done.append(ac_text)
                            node.inferred_nfrs.append(ac_text)
    return nodes


# ---------------------------------------------------------------------------
# Mandatory Field Validation
# ---------------------------------------------------------------------------

MANDATORY_FIELDS = ["description", "acceptance_criteria", "definition_of_done", "estimated_effort"]


def validate_mandatory_fields(nodes: List[TaskNode]) -> Tuple[List[str], List[TaskNode]]:
    """Ensure every task node at story level or below has all mandatory fields.

    Returns:
        (errors, updated_nodes) — errors list is empty if all valid.
    """
    errors: List[str] = []
    for node in nodes:
        if node.node_type in ("story", "task", "subtask"):
            missing: List[str] = []
            # description / body
            if not (node.body and node.body.strip()):
                missing.append("description")
            # acceptance criteria (only story and task; subtasks inherit from parent)
            if node.node_type in ("story", "task") and not node.acceptance_criteria:
                missing.append("acceptance_criteria")
            # definition of done
            if not node.definition_of_done:
                missing.append("definition_of_done")
            # estimated effort
            if not (node.estimate and node.estimate.strip()):
                missing.append("estimated_effort")

            if missing:
                err_msg = f"{node.id} ({node.node_type}) missing mandatory fields: {', '.join(missing)}"
                errors.append(err_msg)
                node.validation_errors.append(err_msg)
                node.status = "blocked"
                node.flagged = True
                if node.node_type == "story":
                    node.title = f"[FLAGGED] {node.title}" if not node.title.startswith("[FLAGGED]") else node.title
    return errors, nodes


# ---------------------------------------------------------------------------
# Spec parsing (with Gherkin integration)
# ---------------------------------------------------------------------------

def parse_markdown_spec(path: str, adr_dir: Optional[str] = None) -> DecompositionResult:
    """Parse a markdown spec into requirements and metadata."""
    text = Path(path).read_text(encoding="utf-8")
    result = DecompositionResult(spec_path=path)

    # Title from first H1
    title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    result.spec_title = title_match.group(1).strip() if title_match else Path(path).stem

    # --- Gherkin extraction FIRST ---
    gherkin_result = parse_markdown_for_gherkin(path)
    gherkin_criteria = {ac.id: ac for ac in gherkin_result.criteria}

    # If Gherkin found ambiguities at the global level, capture them
    for amb in gherkin_result.ambiguities:
        if amb not in result.ambiguities:
            result.ambiguities.append(amb)

    # Load ADRs if directory provided
    adrs: List[ADRConstraint] = []
    if adr_dir:
        adrs = load_adr_constraints(adr_dir)

    # Split into sections by H2
    sections = re.split(r"\n##\s+", text)
    if not sections:
        sections = [text]

    req_counter = 1
    for section_raw in sections:
        lines = section_raw.splitlines()
        section_heading = lines[0].strip() if lines else "Untitled"

        # Infer NFRs from section context
        section_perf, section_sec, section_scale = infer_non_functional_requirements(
            "\n".join(lines), section_heading
        )
        section_inferred = section_perf + section_sec + section_scale

        # Extract requirements per section
        assigned_gherkin_ids: set = set()
        for line in lines:
            req_match = REQUIREMENT_RE.match(line)
            story_match = STORY_RE.match(line)

            if req_match or story_match:
                req_id = f"REQ-{req_counter:03d}"
                req_counter += 1

                if req_match:
                    prefix, num, body = req_match.groups()
                    req_type = _map_prefix_to_type(prefix)
                    text_body = body.strip()
                else:
                    req_type = "story"
                    text_body = f"As a {story_match.group(1).strip()}"

                # Look ahead for AC and DoD in next 15 lines
                idx = lines.index(line)
                acs = _extract_acceptance_criteria(lines[idx: idx + 15], gherkin_criteria, assigned_gherkin_ids)
                dod = _extract_definition_of_done(lines[idx: idx + 15])
                prio = _extract_priority(lines[idx: idx + 10]) or "P2"

                # Merge inferred NFRs into DoD / AC if not already present
                if section_inferred:
                    for nfr in section_inferred:
                        if nfr not in dod:
                            dod.append(f"[INFERRED] {nfr}")

                ambiguous, reasons = _validate_requirement(text_body, acs, dod)

                req = Requirement(
                    id=req_id,
                    section=section_heading,
                    text=text_body,
                    req_type=req_type,
                    acceptance_criteria=acs,
                    definition_of_done=dod,
                    priority=prio,
                    ambiguous=ambiguous,
                    ambiguity_reasons=reasons,
                    inferred_nfrs=section_inferred,
                )
                result.requirements.append(req)
                if ambiguous:
                    result.ambiguities.append(f"{req_id}: {', '.join(reasons)}")
                if section_inferred:
                    result.inferred_nfr_log.append(
                        f"{req_id}: inferred {len(section_inferred)} NFR(s) from context"
                    )

    return result


def _map_prefix_to_type(prefix: str) -> str:
    prefix = prefix.upper()
    mapping = {
        "REQ": "functional",
        "FR": "functional",
        "NFR": "non-functional",
        "SR": "security",
        "PERF": "performance",
        "US": "story",
    }
    return mapping.get(prefix, "functional")


def _extract_acceptance_criteria(lines: List[str], gherkin_map: Optional[Dict] = None, assigned_gherkin_ids: Optional[set] = None) -> List[AcceptanceCriterion]:
    """Extract acceptance criteria from explicit AC lines and merge Gherkin scenarios."""
    acs = []
    matched = assigned_gherkin_ids if assigned_gherkin_ids is not None else set()

    # 1. Extract explicit AC lines from the spec text
    for line in lines:
        m = AC_RE.match(line.strip())
        if m:
            num, text = m.groups()
            ac_id = f"AC-{num}" if num else f"AC-{len(acs)+1}"
            gherkin_text = ""
            if gherkin_map and ac_id in gherkin_map:
                gherkin_text = gherkin_map[ac_id].gherkin
                matched.add(ac_id)
            acs.append(AcceptanceCriterion(id=ac_id, text=text.strip(), gherkin=gherkin_text))

    # 2. If no explicit ACs but Gherkin scenarios exist, create ACs from unmatched Gherkin
    if not acs and gherkin_map:
        for gid, gac in sorted(gherkin_map.items(), key=lambda x: x[1].source_line):
            if gid in matched:
                continue
            acs.append(AcceptanceCriterion(
                id=gac.id,
                text=gac.text,
                testable=gac.testable,
                gherkin=gac.gherkin,
            ))
            matched.add(gid)
        return acs

    # 3. Merge unmatched Gherkin scenarios by text similarity
    if gherkin_map:
        for gid, gac in gherkin_map.items():
            if gid in matched:
                continue
            g_text = (gac.text + " " + gac.gherkin).lower()
            g_words = set(re.findall(r"[a-z]+", g_text))
            best_match = None
            best_score = 0
            for ac in acs:
                ac_text = (ac.text + " " + ac.gherkin).lower()
                ac_words = set(re.findall(r"[a-z]+", ac_text))
                score = len(g_words & ac_words)
                if score > best_score:
                    best_score = score
                    best_match = ac
            if best_match and best_score >= 2:
                best_match.gherkin = gac.gherkin
                if not best_match.testable:
                    best_match.testable = gac.testable
                matched.add(gid)
            # Do NOT append as new AC here; if no good match, leave for other requirements

    return acs


def _extract_definition_of_done(lines: List[str]) -> List[str]:
    dod = []
    for line in lines:
        m = DOD_RE.match(line.strip())
        if m:
            dod.append(m.group(1).strip())
    return dod


def _extract_priority(lines: List[str]) -> Optional[str]:
    for line in lines:
        m = PRIORITY_RE.search(line)
        if m:
            return m.group(1).upper()
    return None


def _validate_requirement(text: str, acs: List[AcceptanceCriterion], dod: List[str]) -> tuple:
    """Return (ambiguous, [reasons])."""
    reasons = []
    if not acs:
        reasons.append("missing acceptance criteria")
    else:
        for ac in acs:
            if len(ac.text.split()) < 3:
                reasons.append(f"{ac.id} is too vague")
            if not ac.testable:
                reasons.append(f"{ac.id} is non-testable (Gherkin validation failed)")
    if not dod:
        reasons.append("missing definition of done")
    # Check for weasel words that make things untestable
    weasels = ["easy", "fast", "user-friendly", "seamless", "robust", "intuitive", "scalable", "efficient"]
    lowered = text.lower()
    for w in weasels:
        if w in lowered:
            reasons.append(f"contains untestable weasel word '{w}'")
    return (bool(reasons), reasons)


# ---------------------------------------------------------------------------
# Decomposition
# ---------------------------------------------------------------------------

STATUS_DEFAULT = "pending"


def decompose_requirements(result: DecompositionResult, adrs: Optional[List[ADRConstraint]] = None) -> DecompositionResult:
    """Turn requirements into a task tree with dependencies."""
    nodes: List[TaskNode] = []

    for req in result.requirements:
        if req.ambiguous:
            epic = TaskNode(
                id=f"{req.id}-EPIC",
                node_type="epic",
                parent_id="root",
                title=f"[FLAGGED] {req.text[:60]}",
                source_spec=Path(result.spec_path).name,
                source_section=req.section,
                source_requirement=req.id,
                status="blocked",
                priority=req.priority,
                acceptance_criteria=[ac.id for ac in req.acceptance_criteria],
                definition_of_done=req.definition_of_done,
                inferred_nfrs=req.inferred_nfrs,
                flagged=True,
                body=f"## Ambiguity\n- {'\n- '.join(req.ambiguity_reasons)}\n\n## Source\n{req.text}",
            )
            nodes.append(epic)
            continue

        # Epic
        epic_id = f"{req.id}-EPIC"
        epic = TaskNode(
            id=epic_id,
            node_type="epic",
            parent_id="root",
            title=req.text[:80],
            source_spec=Path(result.spec_path).name,
            source_section=req.section,
            source_requirement=req.id,
            status=STATUS_DEFAULT,
            priority=req.priority,
            acceptance_criteria=[ac.id for ac in req.acceptance_criteria],
            definition_of_done=req.definition_of_done,
            inferred_nfrs=req.inferred_nfrs,
            body=f"## Description\n{req.text}\n\n## Acceptance Criteria\n" + "\n".join(f"- {ac.id}: {ac.text}" for ac in req.acceptance_criteria),
        )
        nodes.append(epic)

        # Story
        story_id = f"{req.id}-STORY"
        story = TaskNode(
            id=story_id,
            node_type="story",
            parent_id=epic_id,
            title=req.text[:80],
            source_spec=Path(result.spec_path).name,
            source_section=req.section,
            source_requirement=req.id,
            status=STATUS_DEFAULT,
            priority=req.priority,
            acceptance_criteria=[ac.id for ac in req.acceptance_criteria],
            definition_of_done=req.definition_of_done,
            inferred_nfrs=req.inferred_nfrs,
            estimate="2d",
            body=f"## Story\n{req.text}\n\n## Acceptance Criteria\n" + "\n".join(f"- {ac.id}: {ac.text}" for ac in req.acceptance_criteria),
        )
        nodes.append(story)
        epic.blocks.append(story_id)

        # Tasks (one per acceptance criterion + one for DoD integration)
        task_ids = []
        for i, ac in enumerate(req.acceptance_criteria, 1):
            task_id = f"{req.id}-T{i:02d}"
            task = TaskNode(
                id=task_id,
                node_type="task",
                parent_id=story_id,
                title=ac.text[:80],
                source_spec=Path(result.spec_path).name,
                source_section=req.section,
                source_requirement=req.id,
                status=STATUS_DEFAULT,
                priority=req.priority,
                acceptance_criteria=[ac.id],
                definition_of_done=req.definition_of_done,
                gherkin_scenario=ac.gherkin,
                estimate="4h",
                inferred_nfrs=req.inferred_nfrs,
                body=f"## Acceptance Criterion\n{ac.text}\n\n## Definition of Done\n" + "\n".join(f"- {d}" for d in req.definition_of_done),
            )
            nodes.append(task)
            story.blocks.append(task_id)
            task_ids.append(task_id)

        # NFR / security / performance: add a dedicated task if none exist
        if req.req_type in ("non-functional", "security", "performance") and not task_ids:
            task_id = f"{req.id}-T01"
            task = TaskNode(
                id=task_id,
                node_type="task",
                parent_id=story_id,
                title=f"Implement / verify {req.req_type} requirement",
                source_spec=Path(result.spec_path).name,
                source_section=req.section,
                source_requirement=req.id,
                status=STATUS_DEFAULT,
                priority=req.priority,
                definition_of_done=req.definition_of_done,
                estimate="4h",
                inferred_nfrs=req.inferred_nfrs,
                body=f"## {req.req_type.upper()} Requirement\n{req.text}\n\n## Definition of Done\n" + "\n".join(f"- {d}" for d in req.definition_of_done),
            )
            nodes.append(task)
            story.blocks.append(task_id)
            task_ids.append(task_id)

        # Subtasks (engineering steps per task)
        for task_id in task_ids:
            subtasks = _auto_subtasks(task_id, req)
            for sub in subtasks:
                nodes.append(sub)
                parent = next(n for n in nodes if n.id == task_id)
                parent.blocks.append(sub.id)
                sub.dependencies.append(task_id)

        # Dependency inference across tasks within the same story
        for i in range(1, len(task_ids)):
            prev_task = next(n for n in nodes if n.id == task_ids[i - 1])
            curr_task = next(n for n in nodes if n.id == task_ids[i])
            curr_task.dependencies.append(prev_task.id)
            prev_task.blocks.append(curr_task.id)
            result.dependency_edges.append((prev_task.id, curr_task.id))

    # --- ADR Cross-Reference ---
    if adrs:
        violations, nodes = validate_adr_compliance(nodes, adrs)
        result.adr_violations.extend(violations)
        nodes = propagate_adr_nfrs_to_tasks(nodes, adrs)

    # --- Mandatory Field Validation ---
    mandatory_errors, nodes = validate_mandatory_fields(nodes)
    if mandatory_errors:
        result.ambiguities.extend(mandatory_errors)

    result.nodes = nodes
    return result


def _auto_subtasks(parent_task_id: str, req: Requirement) -> List[TaskNode]:
    """Generate sensible subtasks for a task based on type."""
    subs = []
    base = parent_task_id
    templates = {
        "functional": [
            ("design", "Design interface / contract"),
            ("impl", "Implement core logic"),
            ("test", "Write unit / integration tests"),
            ("doc", "Update documentation"),
        ],
        "story": [
            ("design", "Design UI / interaction"),
            ("impl", "Implement frontend / backend"),
            ("test", "Write E2E / acceptance test"),
            ("review", "Demo / review with stakeholder"),
        ],
        "non-functional": [
            ("bench", "Establish baseline measurement"),
            ("impl", "Apply optimization / configuration"),
            ("verify", "Verify target met"),
        ],
        "security": [
            ("threat", "Threat model review"),
            ("impl", "Implement control / fix"),
            ("scan", "Run security scan / audit"),
        ],
        "performance": [
            ("profile", "Profile current performance"),
            ("impl", "Optimize bottleneck"),
            ("verify", "Re-profile and confirm target"),
        ],
    }
    steps = templates.get(req.req_type, templates["functional"])
    for i, (suffix, title) in enumerate(steps, 1):
        sub_id = f"{base}-S{i:02d}"
        subs.append(
            TaskNode(
                id=sub_id,
                node_type="subtask",
                parent_id=parent_task_id,
                title=title,
                source_spec=req.section,
                source_section=req.section,
                source_requirement=req.id,
                status=STATUS_DEFAULT,
                priority=req.priority,
                estimate="1h",
                definition_of_done=[f"{title} completed and reviewed"],
                body=f"## Subtask: {title}\nPart of {parent_task_id} for {req.id}.",
            )
        )
    return subs


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

OBSIDIAN_TEMPLATE = """---
id: {id}
type: {node_type}
parent: {parent_id}
title: {title}
status: {status}
priority: {priority}
source_spec: {source_spec}
source_section: {source_section}
source_requirement: {source_requirement}
acceptance_criteria: {acs_json}
definition_of_done: {dod_json}
dependencies: {deps_json}
blocks: {blocks_json}
assignee: "{assignee}"
estimate: "{estimate}"
gherkin_scenario: "{gherkin}"
adr_references: {adr_json}
inferred_nfrs: {inferred_json}
security_tags: {sec_json}
flagged: {flagged}
---

# {title}

## Traceability
- **Spec**: `{source_spec}` → **Section**: `{source_section}` → **Requirement**: `{source_requirement}`

## Status
`{status}`

## Description
{body}

## Acceptance Criteria
{acs_bullets}

## Definition of Done
{dod_bullets}

## Dependencies
{deps_bullets}

## Blocks
{blocks_bullets}

## ADR Cross-References
{adr_bullets}

## Inferred Non-Functional Requirements
{inferred_bullets}

## Validation
{validation_bullets}

## History
- Created: auto-generated by spec-decomposer v4.0
"""


def write_obsidian_nodes(result: DecompositionResult, output_dir: str) -> None:
    """Write each node as an Obsidian markdown file."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    for node in result.nodes:
        filepath = out / f"{node.id}.md"
        content = OBSIDIAN_TEMPLATE.format(
            id=node.id,
            node_type=node.node_type,
            parent_id=node.parent_id,
            title=node.title,
            status=node.status,
            priority=node.priority,
            source_spec=node.source_spec,
            source_section=node.source_section,
            source_requirement=node.source_requirement,
            acs_json=json.dumps(node.acceptance_criteria),
            dod_json=json.dumps(node.definition_of_done),
            deps_json=json.dumps(node.dependencies),
            blocks_json=json.dumps(node.blocks),
            assignee=node.assignee,
            estimate=node.estimate,
            gherkin=node.gherkin_scenario.replace("\"", "\\\""),
            adr_json=json.dumps(node.adr_references),
            inferred_json=json.dumps(node.inferred_nfrs),
            sec_json=json.dumps(node.security_tags),
            flagged=str(node.flagged).lower(),
            body=node.body or node.title,
            acs_bullets="\n".join(f"- {ac}" for ac in node.acceptance_criteria) or "- None",
            dod_bullets="\n".join(f"- {d}" for d in node.definition_of_done) or "- None",
            deps_bullets="\n".join(f"- {d}" for d in node.dependencies) or "- None",
            blocks_bullets="\n".join(f"- {b}" for b in node.blocks) or "- None",
            adr_bullets="\n".join(f"- [[{adr}]]" for adr in node.adr_references) or "- None",
            inferred_bullets="\n".join(f"- {nfr}" for nfr in node.inferred_nfrs) or "- None",
            validation_bullets="\n".join(f"- ⚠️ {e}" for e in node.validation_errors) or "- Passed",
        )
        filepath.write_text(content, encoding="utf-8")

    # Write spec-index.md
    index_path = out / "spec-index.md"
    lines = [
        f"# Spec Index: {result.spec_title}\n",
        f"- **Source**: `{result.spec_path}`\n",
        f"- **Total Nodes**: {len(result.nodes)}\n",
        f"- **Ambiguities**: {len(result.ambiguities)}\n",
        "## Epics\n",
    ]
    for node in result.nodes:
        if node.node_type == "epic":
            lines.append(f"- [[{node.id}]] — {node.title} (`{node.status}`)\n")
    if result.ambiguities:
        lines.append("\n## Flagged Ambiguities\n")
        for amb in result.ambiguities:
            lines.append(f"- ⚠️ {amb}\n")
    if result.adr_violations:
        lines.append("\n## ADR Violations\n")
        for v in result.adr_violations:
            lines.append(f"- ❌ {v}\n")
    if result.inferred_nfr_log:
        lines.append("\n## Inferred NFRs\n")
        for nfr in result.inferred_nfr_log:
            lines.append(f"- ℹ️ {nfr}\n")
    index_path.write_text("".join(lines), encoding="utf-8")


def write_test_stubs(result: DecompositionResult, test_dir: str) -> None:
    """Write test stub markdown files per acceptance criterion."""
    out = Path(test_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = set()
    for node in result.nodes:
        for ac_id in node.acceptance_criteria:
            if not ac_id or ac_id in written:
                continue
            written.add(ac_id)
            text = ac_id
            gherkin_text = ""
            # Prefer the requirement matching the node's source_requirement
            target_req = None
            for req in result.requirements:
                if req.id == node.source_requirement:
                    target_req = req
                    break
            # Search target requirement first, then fall back to any requirement
            search_reqs = ([target_req] if target_req else []) + [r for r in result.requirements if r != target_req]
            for req in search_reqs:
                for ac in req.acceptance_criteria:
                    if ac.id == ac_id:
                        text = ac.text
                        gherkin_text = ac.gherkin
                        break
                if text != ac_id:
                    break
            stub = f"""---
type: test-stub
linked_task: {node.id}
acceptance_criterion: {ac_id}
---

# Test Stub: {ac_id}

## Criterion
{text}

## Gherkin Scenario
```gherkin
{gherkin_text or "# No Gherkin provided — write imperative test or request clarification"}
```

## Suggested Test Type
- [ ] Unit
- [ ] Integration
- [ ] E2E

## Placeholder Assertion
```python
# TODO: implement test for {ac_id}
def test_{ac_id.lower().replace("-", "_")}():
    # Given ...
    # When ...
    # Then ...
    pass
```
"""
            (out / f"{node.id}-{ac_id}.test.md").write_text(stub, encoding="utf-8")


def write_exports(result: DecompositionResult, export_dir: str) -> None:
    """Write JSON exports for downstream skills."""
    out = Path(export_dir)
    out.mkdir(parents=True, exist_ok=True)

    architecture_design = {
        "requirements": [
            {"id": r.id, "text": r.text, "type": r.req_type, "priority": r.priority,
             "constraints": r.definition_of_done, "inferred_nfrs": r.inferred_nfrs}
            for r in result.requirements if not r.ambiguous
        ],
        "constraints": [r.text for r in result.requirements if r.req_type == "non-functional"],
        "priority_order": [r.id for r in sorted(result.requirements, key=lambda x: (x.priority, x.id))],
        "adr_violations": result.adr_violations,
        "inferred_nfrs": result.inferred_nfr_log,
    }
    (out / "architecture_design.json").write_text(json.dumps(architecture_design, indent=2), encoding="utf-8")

    ci_cd = {
        "pipeline_stages": list({n.node_type for n in result.nodes}),
        "deployment_order": [edge[0] for edge in result.dependency_edges],
        "blocked_nodes": [n.id for n in result.nodes if n.status == "blocked"],
    }
    (out / "ci_cd_integrator.json").write_text(json.dumps(ci_cd, indent=2), encoding="utf-8")

    code_tester = {
        "test_targets": [
            {"task": n.id, "criteria": n.acceptance_criteria, "type": n.node_type, "gherkin": n.gherkin_scenario}
            for n in result.nodes if n.node_type in ("task", "story")
        ],
        "coverage_gaps": [
            {"requirement": r.id, "reason": "no acceptance criteria"}
            for r in result.requirements if not r.acceptance_criteria and not r.ambiguous
        ],
        "ambiguous_requirements": [r.id for r in result.requirements if r.ambiguous],
    }
    (out / "code_tester.json").write_text(json.dumps(code_tester, indent=2), encoding="utf-8")

    self_reviewer = {
        "review_scope": [
            {"epic": n.id, "stories": [c.id for c in result.nodes if c.parent_id == n.id]}
            for n in result.nodes if n.node_type == "epic"
        ],
        "completion_criteria": [
            {"task": n.id, "dod": n.definition_of_done, "flagged": n.flagged}
            for n in result.nodes if n.node_type == "task"
        ],
        "mandatory_field_violations": [
            {"task": n.id, "errors": n.validation_errors}
            for n in result.nodes if n.validation_errors
        ],
    }
    (out / "self_reviewer.json").write_text(json.dumps(self_reviewer, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Decompose a markdown spec into Obsidian task nodes.")
    parser.add_argument("spec", help="Path to SPEC.md / PRD.md / REQUIREMENTS.md")
    parser.add_argument("--output-dir", default="./vault/tasks", help="Directory for Obsidian task nodes")
    parser.add_argument("--test-dir", default="./vault/tests", help="Directory for test stubs")
    parser.add_argument("--export-dir", default="./vault/exports", help="Directory for JSON exports")
    parser.add_argument("--adr-dir", default="", help="Directory containing Architecture Decision Record .md files")
    parser.add_argument("--stop-on-ambiguity", action="store_true", help="Exit with error if ambiguities found")
    parser.add_argument("--strict", action="store_true", help="Exit with error if mandatory fields missing or ADR violations found")
    args = parser.parse_args()

    if not Path(args.spec).exists():
        print(f"[ERROR] Spec file not found: {args.spec}")
        return 1

    adrs = load_adr_constraints(args.adr_dir) if args.adr_dir else []
    if args.adr_dir:
        print(f"[INFO] Loaded {len(adrs)} ADR(s) from {args.adr_dir}")

    print(f"[INFO] Parsing {args.spec} ...")
    result = parse_markdown_spec(args.spec, adr_dir=args.adr_dir if args.adr_dir else None)
    print(f"[INFO] Found {len(result.requirements)} requirements")

    if result.ambiguities:
        print(f"[WARN] {len(result.ambiguities)} ambiguous requirement(s) detected:")
        for a in result.ambiguities:
            print(f"  - {a}")
        if args.stop_on_ambiguity:
            print("[ERROR] Stopping because --stop-on-ambiguity was set.")
            return 2

    if result.inferred_nfr_log:
        print(f"[INFO] Inferred NFRs for {len(result.inferred_nfr_log)} requirement(s):")
        for nfr in result.inferred_nfr_log:
            print(f"  - {nfr}")

    print("[INFO] Decomposing into task tree ...")
    result = decompose_requirements(result, adrs=adrs)
    print(f"[INFO] Generated {len(result.nodes)} task nodes")

    if result.adr_violations:
        print(f"[WARN] {len(result.adr_violations)} ADR violation(s) detected:")
        for v in result.adr_violations:
            print(f"  - {v}")

    # Post-decomposition ambiguity check: any story/task still lacking acceptance criteria?
    for node in result.nodes:
        if node.node_type in ("story", "task") and not node.acceptance_criteria:
            amb = f"{node.id}: missing acceptance criteria — task decomposed without extractable AC"
            result.ambiguities.append(amb)
            node.flagged = True
            node.status = "blocked"
            print(f"[WARN] {amb}")

    if args.stop_on_ambiguity and result.ambiguities:
        print("[ERROR] Stopping because --stop-on-ambiguity was set (post-decomposition check).")
        return 2

    print(f"[INFO] Writing Obsidian nodes to {args.output_dir} ...")
    write_obsidian_nodes(result, args.output_dir)

    print(f"[INFO] Writing test stubs to {args.test_dir} ...")
    write_test_stubs(result, args.test_dir)

    print(f"[INFO] Writing downstream exports to {args.export_dir} ...")
    write_exports(result, args.export_dir)

    if args.strict and (result.adr_violations or any(n.flagged for n in result.nodes)):
        print("[ERROR] Strict mode: ADR violations or flagged nodes detected.")
        return 3

    print("[OK] Decomposition complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
