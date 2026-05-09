#!/usr/bin/env python3
"""
generate_runbook.py

Automated failure-mode runbook generator for L0 enforcement-layer skills.

Reads skill metadata, health endpoint schemas, and historical incident fingerprints
to produce standardized per-skill runbooks with severity mapping, cascade analysis,
and PagerDuty / OpsGenie integration stubs.

Usage:
    python generate_runbook.py --skills-dir ./skills --output-dir ./runbooks
    python generate_runbook.py --skill-id authz-engine --skills-dir ./skills --output-dir ./runbooks
    python generate_runbook.py --skills-dir ./skills --output-dir ./runbooks --pagerduty --opsgenie

Exit Codes:
    0 - Success
    1 - Invalid arguments or missing dependencies
    2 - Missing skill metadata or schema files
    3 - Template rendering error
"""

import argparse
import json
import os
import re
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    print("Error: PyYAML is required. Install with: pip install PyYAML", file=sys.stderr)
    sys.exit(1)


DEFAULT_TAXONOMY_PATH = Path(__file__).parent.parent / "references" / "failure_taxonomy.md"
DEFAULT_TEMPLATE_PATH = Path(__file__).parent.parent / "references" / "runbook_template.md"

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class FailureMode:
    """Represents a single failure mode instance for a skill."""

    def __init__(
        self,
        category: str,
        name: str,
        symptoms: list[str],
        log_patterns: list[str],
        metric_queries: list[str],
        detection: dict[str, Any],
        impact: dict[str, Any],
        recovery_steps: list[dict[str, str]],
        verification_checks: list[dict[str, str]],
        severity: str,
        degradation_mode: str,
    ):
        self.category = category
        self.name = name
        self.symptoms = symptoms
        self.log_patterns = log_patterns
        self.metric_queries = metric_queries
        self.detection = detection
        self.impact = impact
        self.recovery_steps = recovery_steps
        self.verification_checks = verification_checks
        self.severity = severity
        self.degradation_mode = degradation_mode


class SkillMetadata:
    """Parsed skill metadata + health schema."""

    def __init__(self, raw: dict[str, Any]):
        self.raw = raw
        self.skill_id = raw.get("id", raw.get("name", "unknown"))
        self.skill_name = raw.get("name", self.skill_id)
        self.version = raw.get("version", "0.0.0")
        self.owner_team = raw.get("owner", "platform-sre")
        self.layer = raw.get("layer", "L0")
        self.purpose = raw.get("description", "")
        self.enforcement_scope = raw.get("enforcement_scope", "")
        self.blast_radius = raw.get("blast_radius", "")
        self.deployment_topology = raw.get("deployment", {}).get("topology", "singleton")
        self.fail_mode = raw.get("deployment", {}).get("fail_mode", "fail-closed")
        self.compensating_control = raw.get("deployment", {}).get("compensating_control", "N/A")
        self.health_endpoint = raw.get("observability", {}).get("health_endpoint", "/healthz")
        self.metrics_prefix = raw.get("observability", {}).get("metrics_prefix", self.skill_id)
        self.hard_dependencies = raw.get("dependencies", {}).get("hard", [])
        self.soft_dependencies = raw.get("dependencies", {}).get("soft", [])
        self.oncall_primary = raw.get("oncall", {}).get("primary", "platform-oncall")
        self.oncall_secondary = raw.get("oncall", {}).get("secondary", "platform-oncall-secondary")
        self.engineering_team = raw.get("oncall", {}).get("engineering_team", "")
        self.sre_escalation = raw.get("oncall", {}).get("sre_escalation", "")
        self.pagerduty_service_key = raw.get("pagerduty", {}).get("service_key", "")
        self.escalation_policy = raw.get("pagerduty", {}).get("escalation_policy", "")
        self.dashboard_url = raw.get("observability", {}).get("dashboard_url", "")
        self.log_platform = raw.get("observability", {}).get("log_platform", "")
        self.namespace = raw.get("deployment", {}).get("namespace", "default")
        self.labels = raw.get("deployment", {}).get("labels", {"app": self.skill_id})
        self.service_name = raw.get("deployment", {}).get("service_name", self.skill_id)
        self.config_validation_cmd = raw.get("deployment", {}).get("config_validation_cmd", "")
        self.restart_cmd = raw.get("deployment", {}).get("restart_cmd", "")
        self.rollback_cmd = raw.get("deployment", {}).get("rollback_cmd", "")
        self.canary_test = raw.get("deployment", {}).get("canary_test", "")
        self.failure_fingerprints: list[dict[str, Any]] = raw.get("failure_fingerprints", [])
        self.downstream_skills: list[str] = raw.get("downstream_skills", [])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(text: str) -> str:
    return re.sub(r"[^\w\-]", "-", text.lower()).strip("-")


def load_yaml(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def save_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def derive_severity(category: str, topology: str, fail_mode: str) -> str:
    """Map failure category + topology to severity using taxonomy rules."""
    if category in ("CRASH", "HANG"):
        return "SEV-1"
    if category == "CORRUPTION":
        return "SEV-1" if fail_mode != "fail-closed" else "SEV-0"
    if category == "RESOURCE":
        return "SEV-1" if topology == "singleton" else "SEV-2"
    if category == "CONFIG":
        return "SEV-2"
    if category == "DEPENDENCY":
        return "SEV-1"
    return "SEV-2"


def derive_degradation_mode(category: str, fail_mode: str) -> str:
    if category in ("CRASH", "HANG"):
        return fail_mode.upper().replace("-", "_")
    if category == "CORRUPTION":
        return "FAIL_ALERT"
    if category == "RESOURCE":
        return "FAIL_PARTIAL"
    if category == "CONFIG":
        return "FAIL_ALERT"
    if category == "DEPENDENCY":
        return "FAIL_FIXED"
    return "FAIL_ALERT"


def build_failure_modes(meta: SkillMetadata) -> list[FailureMode]:
    """Generate FailureMode instances from metadata fingerprints + taxonomy defaults."""
    modes: list[FailureMode] = []

    # If the skill metadata defines explicit failure fingerprints, use them.
    if meta.failure_fingerprints:
        for fp in meta.failure_fingerprints:
            cat = fp.get("category", "UNKNOWN")
            modes.append(
                FailureMode(
                    category=cat,
                    name=fp.get("name", f"{cat} Failure"),
                    symptoms=fp.get("symptoms", []),
                    log_patterns=fp.get("log_patterns", []),
                    metric_queries=fp.get("metric_queries", []),
                    detection=fp.get("detection", {}),
                    impact=fp.get("impact", {}),
                    recovery_steps=fp.get("recovery_steps", []),
                    verification_checks=fp.get("verification_checks", []),
                    severity=fp.get("severity", derive_severity(cat, meta.deployment_topology, meta.fail_mode)),
                    degradation_mode=fp.get("degradation_mode", derive_degradation_mode(cat, meta.fail_mode)),
                )
            )
        return modes

    # Otherwise, synthesize standard failure modes from the taxonomy defaults.
    taxonomy_defaults: dict[str, dict[str, Any]] = {
        "CRASH": {
            "name": "Process Crash / Fatal Exit",
            "symptoms": ["Health endpoint connection refused", "Pod in CrashLoopBackOff", "Process absent from process table"],
            "log_patterns": ["panic:", "fatal:", "SIGSEGV", "SIGKILL", "exited with code"],
            "metric_queries": ['up{job="' + meta.metrics_prefix + '"} == 0'],
        },
        "HANG": {
            "name": "Process Hang / Event Loop Stall",
            "symptoms": ["Health endpoint times out", "Request latency p99 at timeout ceiling", "Zero throughput despite queued work"],
            "log_patterns": ["timeout", "deadlock detected", "goroutine leak"],
            "metric_queries": [
                'histogram_quantile(0.99, rate(' + meta.metrics_prefix + '_request_duration_seconds_bucket[5m])) > 30'
            ],
        },
        "CORRUPTION": {
            "name": "State or Policy Corruption",
            "symptoms": ["Drift between expected and running config hash", "Canary requests return unexpected decisions"],
            "log_patterns": ["checksum mismatch", "config drift", "staleness"],
            "metric_queries": [
                meta.metrics_prefix + '_config_drift_detected == 1',
                meta.metrics_prefix + '_canary_mismatch_total > 0',
            ],
        },
        "RESOURCE": {
            "name": "Resource Exhaustion",
            "symptoms": ["OOMKilled", "CPU throttling", "Disk full", "File descriptor exhaustion"],
            "log_patterns": ["OutOfMemory", "too many open files", "no space left on device", "throttled"],
            "metric_queries": [
                'container_memory_working_set_bytes{pod=~"' + meta.labels.get("app", meta.skill_id) + '-.*"} / container_spec_memory_limit_bytes > 0.9'
            ],
        },
        "CONFIG": {
            "name": "Configuration Error / Hot-Reload Failure",
            "symptoms": ["Config validation fails on startup", "Config version hash mismatch after reload"],
            "log_patterns": ["config validation failed", "reload failed", "invalid config"],
            "metric_queries": [
                'rate(' + meta.metrics_prefix + '_config_reload_failures_total[5m]) > 0'
            ],
        },
        "DEPENDENCY": {
            "name": "Critical Dependency Failure",
            "symptoms": ["Dependency health check unhealthy", "Circuit breaker open", "Retry loop saturation"],
            "log_patterns": ["dependency unhealthy", "circuit breaker open", "connection refused"],
            "metric_queries": [
                meta.metrics_prefix + '_dependency_health_check{status="unhealthy"} == 1'
            ],
        },
    }

    for cat, defaults in taxonomy_defaults.items():
        modes.append(
            FailureMode(
                category=cat,
                name=defaults["name"],
                symptoms=defaults["symptoms"],
                log_patterns=defaults["log_patterns"],
                metric_queries=defaults["metric_queries"],
                detection={
                    "health_endpoint": meta.health_endpoint,
                    "log_alert": " | ".join(defaults["log_patterns"]),
                },
                impact={
                    "immediate": f"{meta.skill_name} enforcement decisions may be delayed or incorrect.",
                    "scope": "single-node" if meta.deployment_topology != "global" else "global",
                    "cascade_risk": meta.downstream_skills[:3],
                },
                recovery_steps=[
                    {"title": "Acknowledge & Triage", "duration": "0-2 min", "commands": f"curl -sf http://localhost{meta.health_endpoint}"},
                    {"title": "Immediate Mitigation", "duration": "2-10 min", "commands": meta.restart_cmd or "kubectl rollout restart deployment/" + meta.skill_id},
                ],
                verification_checks=[
                    {"check": "Health endpoint green", "command": f"curl -sf http://localhost{meta.health_endpoint}"},
                    {"check": "Canary pass", "command": meta.canary_test or "echo 'manual canary required'"},
                ],
                severity=derive_severity(cat, meta.deployment_topology, meta.fail_mode),
                degradation_mode=derive_degradation_mode(cat, meta.fail_mode),
            )
        )

    return modes


# ---------------------------------------------------------------------------
# Template rendering (simple placeholder substitution)
# ---------------------------------------------------------------------------

def render_template(template: str, variables: dict[str, str]) -> str:
    result = template
    for key, val in variables.items():
        placeholder = "{" + key + "}"
        result = result.replace(placeholder, str(val))
    return result


def render_failure_section(mode: FailureMode, meta: SkillMetadata) -> str:
    """Render a single 2.x failure mode section."""
    lines: list[str] = []
    lines.append(f"### 2.x {mode.category} — {mode.name}")
    lines.append("")
    lines.append("#### Symptom")
    lines.append("- **Observed Behavior:** " + "; ".join(mode.symptoms))
    lines.append("- **Log Signature (exact grep / filter):** `" + " | ".join(mode.log_patterns) + "`")
    lines.append("- **Metric Signature:** `" + "; ".join(mode.metric_queries) + "`")
    lines.append("")
    lines.append("#### Detection")
    lines.append("| Source | Query / Check | Threshold | Polling Interval |")
    lines.append("|--------|---------------|-----------|-----------------|")
    for src, query in mode.detection.items():
        lines.append(f"| {src} | `{query}` | TBD | 10s |")
    lines.append("")
    lines.append("**PagerDuty / OpsGenie Integration:**")
    lines.append(f"- **Service Key:** `{meta.pagerduty_service_key}`")
    lines.append(f"- **Alert Name:** `{meta.skill_id}_{slugify(mode.name)}`")
    lines.append(f"- **Severity:** {mode.severity}")
    lines.append(f"- **Escalation Policy:** `{meta.escalation_policy}`")
    lines.append("")
    lines.append("#### Impact Assessment")
    lines.append(f"- **Immediate Impact:** {mode.impact.get('immediate', 'Unknown')}")
    lines.append(f"- **Degradation Mode Entered:** {mode.degradation_mode}")
    lines.append(f"- **Scope of Impact:** {mode.impact.get('scope', 'Unknown')}")
    cascade = mode.impact.get("cascade_risk", [])
    lines.append(f"- **Cascade Trigger Risk:** {', '.join(cascade) if cascade else 'None identified'}")
    lines.append("")
    lines.append("#### Recovery")
    lines.append("")
    lines.append("**Step-by-Step Procedure:**")
    lines.append("")
    for idx, step in enumerate(mode.recovery_steps, start=1):
        lines.append(f"{idx}. **{step['title']} ({step.get('duration', '')})**")
        lines.append(f"   ```bash")
        lines.append(f"   {step['commands']}")
        lines.append(f"   ```")
        lines.append("")
    lines.append("")
    lines.append("#### Verification")
    lines.append("")
    for check in mode.verification_checks:
        lines.append(f"- **{check['check']}:** `{check['command']}`")
    lines.append("")
    lines.append("#### Post-Incident")
    lines.append(f"- **Incident Ticket Label:** `l0-failure/{meta.skill_id}`")
    lines.append(f"- **Post-Mortem Required:** {'Yes' if mode.severity in ('SEV-0', 'SEV-1') else 'No (unless duration > 30 min)'}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Integration outputs
# ---------------------------------------------------------------------------

def generate_pagerduty_integration(meta: SkillMetadata, modes: list[FailureMode]) -> dict[str, Any]:
    """Generate a PagerDuty service + event rules JSON stub."""
    service = {
        "service": {
            "name": f"{meta.skill_name} — L0 Enforcement",
            "description": f"Auto-generated runbook service for {meta.skill_id} (v{meta.version})",
            "escalation_policy": {
                "id": meta.escalation_policy,
                "type": "escalation_policy_reference",
            },
            "alert_creation": "create_alerts_and_incidents",
        },
        "event_rules": [],
    }
    for mode in modes:
        rule = {
            "rule_name": f"{meta.skill_id}_{slugify(mode.name)}",
            "condition": {
                "and": [
                    {"substring": {"path": "payload.custom_details.skill_id", "value": meta.skill_id}},
                    {"substring": {"path": "payload.summary", "value": mode.category}},
                ]
            },
            "actions": {
                "severity": {"value": mode.severity.lower().replace("sev-", "")},
                "annotate": {"value": f"Runbook: {meta.skill_id} — Section 2.x {mode.category} / {mode.name}"},
            },
        }
        service["event_rules"].append(rule)
    return service


def generate_opsgenie_integration(meta: SkillMetadata, modes: list[FailureMode]) -> dict[str, Any]:
    """Generate an OpsGenie alert policy YAML stub."""
    policies = []
    for mode in modes:
        policies.append({
            "name": f"{meta.skill_id}_{slugify(mode.name)}",
            "enabled": True,
            "ownerTeam": meta.owner_team,
            "priority": mode.severity.replace("SEV-", "P").replace("0", "1"),  # SEV-0 -> P1
            "filter": {
                "and": [
                    {"field": "message", "operation": "contains", "expectedValue": meta.skill_id},
                    {"field": "message", "operation": "contains", "expectedValue": mode.category},
                ]
            },
            "actions": [
                {"type": "create", "user": meta.oncall_primary},
            ],
        })
    return {"alert_policies": policies}


def generate_cascade_analysis(all_skills: dict[str, SkillMetadata]) -> dict[str, Any]:
    """Cross-skill cascade analysis: build adjacency list of downstream impacts."""
    graph: dict[str, list[dict[str, str]]] = {}
    for skill_id, meta in all_skills.items():
        downstream = []
        for ds_id in meta.downstream_skills:
            ds_meta = all_skills.get(ds_id)
            if ds_meta:
                downstream.append({
                    "downstream_skill_id": ds_id,
                    "downstream_layer": ds_meta.layer,
                    "downstream_name": ds_meta.skill_name,
                    "impact": f"{meta.skill_name} failure may starve or misconfigure {ds_meta.skill_name}",
                })
        graph[skill_id] = downstream
    return graph


# ---------------------------------------------------------------------------
# Main generation pipeline
# ---------------------------------------------------------------------------

def generate_runbook(meta: SkillMetadata, template_text: str, cascade_graph: dict[str, Any]) -> str:
    """Produce the final runbook markdown for a single skill."""
    modes = build_failure_modes(meta)

    # Build failure sections
    failure_sections: list[str] = []
    for idx, mode in enumerate(modes, start=1):
        section = render_failure_section(mode, meta)
        # Renumber heading
        section = section.replace("### 2.x", f"### 2.{idx}")
        failure_sections.append(section)

    # Base variables from metadata
    variables: dict[str, str] = {
        "skill_name": meta.skill_name,
        "skill_id": meta.skill_id,
        "owner_team": meta.owner_team,
        "generation_timestamp": now_iso(),
        "runbook_version": meta.version,
        "skill_version": meta.version,
        "one_sentence_purpose": meta.purpose,
        "what_this_skill_enforces": meta.enforcement_scope,
        "blast_radius_description": meta.blast_radius,
        "deployment_topology": meta.deployment_topology,
        "fail_mode": meta.fail_mode,
        "compensating_control_or_n/a": meta.compensating_control,
        "hard_dependency_list": ", ".join(meta.hard_dependencies) or "none",
        "soft_dependency_list": ", ".join(meta.soft_dependencies) or "none",
        "health_endpoint": meta.health_endpoint,
        "skill_metric_prefix": meta.metrics_prefix,
        "namespace": meta.namespace,
        "skill_label": meta.labels.get("app", meta.skill_id),
        "service_name": meta.service_name,
        "config_validation_command": meta.config_validation_cmd or "# not configured",
        "restart_command": meta.restart_cmd or f"kubectl rollout restart deployment/{meta.skill_id} -n {meta.namespace}",
        "rollback_command": meta.rollback_cmd or "# not configured",
        "canary_command": meta.canary_test or "# not configured",
        "expected_canary_result": "PASS",
        "grafana_or_cloudwatch_dashboard_url": meta.dashboard_url or "# not configured",
        "log_platform_query_example": meta.log_platform or "# not configured",
        "primary_oncall_rotation": meta.oncall_primary,
        "secondary_oncall_rotation": meta.oncall_secondary,
        "engineering_team_contact": meta.engineering_team,
        "sre_escalation_contact": meta.sre_escalation,
        "pagerduty_service_key": meta.pagerduty_service_key,
        "escalation_policy_name": meta.escalation_policy,
        "status_dashboard_url": meta.dashboard_url or "# not configured",
        "runbook_link": f"./{meta.skill_id}_runbook.md",
        "dashboard_link": meta.dashboard_url or "# not configured",
    }

    # Render template
    runbook = render_template(template_text, variables)

    # Inject failure sections into the 2.1 placeholder area
    # We replace the first occurrence of the generic 2.1 placeholder with our real sections.
    failure_block = "\n".join(failure_sections)
    placeholder_start = runbook.find("### 2.1 {Failure Mode:")
    if placeholder_start != -1:
        placeholder_end = runbook.find("---", placeholder_start + 1)
        # Find the next "### 2.2 {Next Failure Mode}"
        next_placeholder = runbook.find("### 2.2 {Next Failure Mode}", placeholder_start)
        if next_placeholder != -1:
            runbook = runbook[:placeholder_start] + failure_block + "\n\n" + runbook[next_placeholder:]
        else:
            runbook = runbook[:placeholder_start] + failure_block + runbook[placeholder_end:]

    # Strip remaining unrendered placeholder sections (2.2, 2.N)
    lines = runbook.splitlines()
    cleaned: list[str] = []
    skip = False
    for line in lines:
        if re.match(r"^### 2\.\d+ \{Next|Final Failure Mode", line):
            skip = True
            continue
        if skip and line.startswith("---"):
            skip = False
            continue
        if skip:
            continue
        cleaned.append(line)
    runbook = "\n".join(cleaned)

    # Append cascade analysis if present
    downstream = cascade_graph.get(meta.skill_id, [])
    if downstream:
        runbook += "\n\n---\n\n## Appendix A: Downstream Cascade Analysis\n\n"
        runbook += "| Downstream Skill | Layer | Cascade Impact |\n"
        runbook += "|------------------|-------|----------------|\n"
        for ds in downstream:
            runbook += f"| {ds['downstream_name']} ({ds['downstream_skill_id']}) | {ds['downstream_layer']} | {ds['impact']} |\n"

    return runbook


def discover_skills(skills_dir: Path) -> dict[str, SkillMetadata]:
    """Walk skills_dir and find `skill.yaml` or `metadata.yaml` files."""
    skills: dict[str, SkillMetadata] = {}
    for path in skills_dir.rglob("*"):
        if path.is_file() and path.name in ("skill.yaml", "metadata.yaml", "skill.json", "metadata.json"):
            raw = load_yaml(path) if path.suffix in (".yaml", ".yml") else json.loads(path.read_text())
            meta = SkillMetadata(raw)
            skills[meta.skill_id] = meta
    return skills


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate L0 enforcement-layer runbooks.")
    parser.add_argument("--skills-dir", required=True, type=Path, help="Directory containing skill metadata files.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory to write generated runbooks.")
    parser.add_argument("--skill-id", type=str, default="", help="Generate for a single skill instead of all.")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE_PATH, help="Path to runbook template markdown.")
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY_PATH, help="Path to failure taxonomy markdown (reference only).")
    parser.add_argument("--pagerduty", action="store_true", help="Emit PagerDuty integration JSON per skill.")
    parser.add_argument("--opsgenie", action="store_true", help="Emit OpsGenie integration YAML per skill.")
    parser.add_argument("--cascade-analysis", type=Path, default=None, help="Write cross-skill cascade graph to JSON file.")
    args = parser.parse_args(argv)

    if not args.template.exists():
        print(f"Error: Template not found: {args.template}", file=sys.stderr)
        return 2

    if not args.taxonomy.exists():
        print(f"Warning: Taxonomy not found: {args.taxonomy} (proceeding anyway)", file=sys.stderr)

    if not args.skills_dir.exists():
        print(f"Error: Skills directory not found: {args.skills_dir}", file=sys.stderr)
        return 2

    template_text = load_text(args.template)
    all_skills = discover_skills(args.skills_dir)

    if not all_skills:
        print(f"Error: No skill metadata found under {args.skills_dir}", file=sys.stderr)
        return 2

    if args.skill_id and args.skill_id not in all_skills:
        print(f"Error: Skill ID '{args.skill_id}' not found.", file=sys.stderr)
        return 2

    targets = {args.skill_id: all_skills[args.skill_id]} if args.skill_id else all_skills
    cascade_graph = generate_cascade_analysis(all_skills)

    generated: list[Path] = []

    for skill_id, meta in targets.items():
        runbook_md = generate_runbook(meta, template_text, cascade_graph)
        out_path = args.output_dir / f"{skill_id}_runbook.md"
        save_text(out_path, runbook_md)
        generated.append(out_path)
        print(f"Generated runbook: {out_path}")

        if args.pagerduty:
            pd_json = generate_pagerduty_integration(meta, build_failure_modes(meta))
            pd_path = args.output_dir / f"{skill_id}_pagerduty.json"
            save_text(pd_path, json.dumps(pd_json, indent=2))
            generated.append(pd_path)
            print(f"Generated PagerDuty config: {pd_path}")

        if args.opsgenie:
            og_yaml = generate_opsgenie_integration(meta, build_failure_modes(meta))
            og_path = args.output_dir / f"{skill_id}_opsgenie.yaml"
            save_text(og_path, yaml.safe_dump(og_yaml, sort_keys=False))
            generated.append(og_path)
            print(f"Generated OpsGenie config: {og_path}")

    if args.cascade_analysis:
        save_text(args.cascade_analysis, json.dumps(cascade_graph, indent=2))
        generated.append(args.cascade_analysis)
        print(f"Generated cascade analysis: {args.cascade_analysis}")

    print(f"\nDone. {len(generated)} file(s) generated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
