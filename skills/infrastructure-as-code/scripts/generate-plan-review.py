#!/usr/bin/env python3
"""
generate-plan-review.py — Human-readable Terraform plan review artifact generator.

Parses Terraform plan JSON, Checkov reports, and cost estimates to produce a structured
PLAN_REVIEW.md document containing:
  - Plan summary (create / modify / destroy)
  - Cost estimate (absolute and delta)
  - Risk assessment / blast radius
  - Checkov security scan summary
  - Tagging compliance check
  - State locking verification
  - Rollback procedure

Usage:
  terraform plan -out=plan.tfplan
  terraform show -json plan.tfplan > plan.json
  checkov --framework terraform -d . -o json > checkov.json || true
  infracost breakdown --path . --format json > infracost.json || true

  python scripts/generate-plan-review.py \
    --plan-json plan.json \
    --checkov-json checkov.json \
    --infracost-json infracost.json \
    --project myapp \
    --env prod \
    --owner team-platform \
    --cost-center cc-1234 \
    --output ./PLAN_REVIEW.md

The script is intended to be called by the Kimi agent during Step 9 of the IaC workflow.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ────────────────────────────── constants ──────────────────────────────

MANDATORY_TAGS = ["environment", "owner", "cost-center", "project"]

RISK_WEIGHTS = {
    "destroy": 3,
    "replace": 3,
    "update": 1,
    "create": 0,
}

BLAST_RADIUS_THRESHOLD = {
    "low": 5,
    "medium": 15,
    "high": 30,
}

CHECKOV_CRITICAL_SEVERITIES = {"CRITICAL", "HIGH"}

DEFAULT_ROLLBACK_PROCEDURE = """### Rollback Procedure
1. **Capture current state backup** (if not already done):
   ```bash
   terraform state pull > state-backup-{timestamp}.json
   ```
2. **If apply failed mid-way**:
   - Identify partially created resources via `terraform state list`
   - Targeted destroy of incomplete resources: `terraform destroy -target=<resource>`
3. **If post-apply issues detected**:
   - Revert to previous known-good Terraform code version in VCS
   - Run `terraform plan` against the previous version to assess reversion impact
   - Apply the reversion plan using the same external approval gate
4. **State recovery** (if state corruption suspected):
   - Restore from latest state backup in backup bucket/container
   - Run `terraform refresh` to reconcile remote state
5. **Validation after rollback**:
   - Run smoke tests against infrastructure endpoints
   - Verify SLOs and alerting pipelines are healthy
   - Confirm database connections and replication status
"""


# ────────────────────────────── helpers ──────────────────────────────


def _load_json(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path or not Path(path).exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _count_resources(plan: Optional[Dict[str, Any]]) -> Tuple[int, int, int]:
    """Return (create, update, destroy) counts from Terraform plan JSON."""
    if not plan:
        return 0, 0, 0
    changes = plan.get("resource_changes", [])
    create_count = 0
    update_count = 0
    destroy_count = 0
    for rc in changes:
        change = rc.get("change", {})
        actions = change.get("actions", [])
        if "create" in actions and "delete" in actions:
            destroy_count += 1
            create_count += 1
        elif "create" in actions:
            create_count += 1
        elif "delete" in actions:
            destroy_count += 1
        elif "update" in actions:
            update_count += 1
    return create_count, update_count, destroy_count


def _extract_resource_changes(plan: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract detailed resource changes from plan JSON."""
    if not plan:
        return []
    results: List[Dict[str, Any]] = []
    for rc in plan.get("resource_changes", []):
        change = rc.get("change", {})
        actions = change.get("actions", [])
        action_str = "/".join(actions)
        results.append({
            "address": rc.get("address", "unknown"),
            "type": rc.get("type", "unknown"),
            "name": rc.get("name", "unknown"),
            "module": rc.get("module_address") or "root",
            "action": action_str,
            "actions": actions,
        })
    return results


def _calculate_blast_radius_score(resources: List[Dict[str, Any]]) -> int:
    """Calculate a heuristic blast-radius score."""
    score = 0
    for r in resources:
        for action in r.get("actions", []):
            score += RISK_WEIGHTS.get(action, 0)
    return score


def _blast_radius_level(score: int) -> str:
    if score >= BLAST_RADIUS_THRESHOLD["high"]:
        return "HIGH"
    elif score >= BLAST_RADIUS_THRESHOLD["medium"]:
        return "MEDIUM"
    elif score >= BLAST_RADIUS_THRESHOLD["low"]:
        return "LOW"
    return "NONE"


def _summarize_checkov(checkov: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize Checkov JSON output."""
    if not checkov:
        return {
            "summary": "No Checkov report provided.",
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "critical_count": 0,
            "high_count": 0,
            "findings": [],
        }

    summary = checkov.get("summary", {})
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    skipped = summary.get("skipped", 0)

    findings: List[Dict[str, Any]] = []
    critical_count = 0
    high_count = 0

    for result in checkov.get("results", {}).get("failed_checks", []):
        severity = result.get("severity", "UNKNOWN").upper()
        finding = {
            "check_id": result.get("check_id", "UNKNOWN"),
            "check_name": result.get("check_name", "UNKNOWN"),
            "resource": result.get("resource", "UNKNOWN"),
            "file_path": result.get("file_path", "UNKNOWN"),
            "severity": severity,
        }
        findings.append(finding)
        if severity in {"CRITICAL"}:
            critical_count += 1
        elif severity in {"HIGH"}:
            high_count += 1

    # Fallback: if severity not present in JSON, infer from check_id patterns or count all as high
    if not findings and failed > 0:
        high_count = failed

    return {
        "summary": f"Passed: {passed}, Failed: {failed}, Skipped: {skipped}",
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "critical_count": critical_count,
        "high_count": high_count,
        "findings": findings,
    }


def _extract_cost(infracost: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract cost estimate from infracost JSON."""
    if not infracost:
        return {
            "total_monthly": "N/A (infracost not available)",
            "delta_monthly": "N/A",
            "currency": "USD",
            "breakdown": [],
        }

    total = infracost.get("totalMonthlyCost", "0")
    past_total = infracost.get("pastTotalMonthlyCost", "0")
    delta = infracost.get("diffTotalMonthlyCost", "0")
    currency = infracost.get("currency", "USD")

    breakdown = []
    for project in infracost.get("projects", []):
        for resource in project.get("breakdown", {}).get("resources", []):
            breakdown.append({
                "name": resource.get("name", "unknown"),
                "monthly_cost": resource.get("monthlyCost", "0"),
                "resource_type": resource.get("resourceType", "unknown"),
            })

    return {
        "total_monthly": total,
        "delta_monthly": delta,
        "past_total_monthly": past_total,
        "currency": currency,
        "breakdown": breakdown[:20],  # limit to top 20
    }


def _check_tagging_compliance(plan: Optional[Dict[str, Any]],
                               expected_tags: List[str]) -> Dict[str, Any]:
    """Heuristic check for mandatory tags in planned values."""
    if not plan:
        return {"status": "UNKNOWN", "missing_tags": [], "details": []}

    # Extract planned_values.configuration root_module resources
    config = plan.get("configuration", {})
    root_module = config.get("root_module", {})
    resources = root_module.get("resources", [])
    # Also include child modules
    child_modules = root_module.get("module_calls", {})

    all_resources = list(resources)
    for mod_name, mod_info in child_modules.items():
        mod_resources = mod_info.get("module", {}).get("resources", [])
        all_resources.extend(mod_resources)

    compliant = True
    details: List[Dict[str, Any]] = []
    for res in all_resources:
        expr = res.get("expressions", {})
        tags_expr = expr.get("tags", {}) or expr.get("labels", {}) or expr.get("default_tags", {})
        # Heuristic: if tags expression exists, assume compliance; otherwise flag if taggable
        # In a real implementation, static analysis or provider schema would be used.
        # Here we do a best-effort string-match on the raw resource JSON.
        res_str = json.dumps(res)
        missing = []
        for tag in expected_tags:
            if tag not in res_str:
                missing.append(tag)
        if missing:
            compliant = False
            details.append({
                "resource": res.get("address", res.get("name", "unknown")),
                "missing_tags": missing,
            })

    return {
        "status": "PASS" if compliant else "FAIL",
        "missing_tags_count": len(details),
        "details": details[:10],  # limit output
    }


def _verify_state_locking(plan: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Heuristic verification that backend locking is configured."""
    if not plan:
        return {"status": "UNKNOWN", "message": "No plan JSON available."}

    backend = plan.get("backend", {})
    backend_type = backend.get("type", "unknown")
    config = backend.get("config", {})

    locking_enabled = False
    issues: List[str] = []

    if backend_type == "s3":
        if config.get("dynamodb_table"):
            locking_enabled = True
        else:
            issues.append("S3 backend missing dynamodb_table for state locking.")
        if not config.get("encrypt"):
            issues.append("S3 backend encryption not explicitly enabled.")
    elif backend_type == "gcs":
        # GCS does not need a separate lock table; Object Admin handles it.
        locking_enabled = True
    elif backend_type == "azurerm":
        # Azure Blob lease-based locking is implicit when using standard backend.
        locking_enabled = True
    elif backend_type == "remote":
        # Terraform Cloud / Enterprise handles locking.
        locking_enabled = True
    else:
        issues.append(f"Backend type '{backend_type}' locking status unknown.")

    return {
        "status": "PASS" if locking_enabled else "FAIL",
        "backend_type": backend_type,
        "locking_enabled": locking_enabled,
        "issues": issues,
    }


# ────────────────────────────── markdown builder ──────────────────────────────


def _build_markdown(
    plan: Optional[Dict[str, Any]],
    checkov: Optional[Dict[str, Any]],
    infracost: Optional[Dict[str, Any]],
    project: str,
    env: str,
    owner: str,
    cost_center: str,
    timestamp: str,
) -> str:
    resources = _extract_resource_changes(plan)
    create, update, destroy = _count_resources(plan)
    score = _calculate_blast_radius_score(resources)
    level = _blast_radius_level(score)

    checkov_summary = _summarize_checkov(checkov)
    cost = _extract_cost(infracost)
    tagging = _check_tagging_compliance(plan, MANDATORY_TAGS)
    locking = _verify_state_locking(plan)

    # Build resource tables
    create_rows = []
    update_rows = []
    destroy_rows = []
    for r in resources:
        row = f"| `{r['address']}` | {r['type']} | {r['module']} |"
        if "delete" in r["actions"] and "create" in r["actions"]:
            destroy_rows.append(row)
            create_rows.append(row)
        elif "delete" in r["actions"]:
            destroy_rows.append(row)
        elif "create" in r["actions"]:
            create_rows.append(row)
        elif "update" in r["actions"]:
            update_rows.append(row)

    resource_tables = ""
    if create_rows:
        resource_tables += f"""#### Resources to Create ({len(create_rows)})
| Resource | Type | Module |
|----------|------|--------|
{"\n".join(create_rows)}

"""
    if update_rows:
        resource_tables += f"""#### Resources to Update ({len(update_rows)})
| Resource | Type | Module |
|----------|------|--------|
{"\n".join(update_rows)}

"""
    if destroy_rows:
        resource_tables += f"""#### Resources to Destroy / Replace ({len(destroy_rows)})
| Resource | Type | Module |
|----------|------|--------|
{"\n".join(destroy_rows)}

**WARNING**: Destructive changes detected. Ensure backups exist and rollback plan is reviewed.

"""

    # Checkov findings table
    checkov_findings_table = ""
    if checkov_summary["findings"]:
        rows = []
        for f in checkov_summary["findings"]:
            rows.append(f"| `{f['check_id']}` | {f['check_name']} | `{f['resource']}` | {f['severity']} |")
        checkov_findings_table = f"""| Check ID | Check Name | Resource | Severity |
|----------|------------|----------|----------|
{"\n".join(rows)}
"""
    else:
        checkov_findings_table = "_No individual findings parsed (Checkov may have passed or report format differed)._"

    # Cost breakdown table
    cost_table = ""
    if cost["breakdown"]:
        rows = []
        for item in cost["breakdown"]:
            rows.append(f"| {item['name']} | {item['resource_type']} | {item['monthly_cost']} |")
        cost_table = f"""| Resource | Type | Monthly Cost ({cost['currency']}) |
|----------|------|-----------------------------------|
{"\n".join(rows)}
"""
    else:
        cost_table = "_No detailed cost breakdown available._"

    # Tagging details
    tagging_details = ""
    if tagging["details"]:
        rows = []
        for d in tagging["details"]:
            rows.append(f"| `{d['resource']}` | {', '.join(d['missing_tags'])} |")
        tagging_details = f"""| Resource | Missing Tags |
|----------|--------------|
{"\n".join(rows)}
"""
    else:
        tagging_details = "_All inspected resources appear to carry mandatory tags._"

    # State locking details
    locking_details = ""
    if locking["issues"]:
        locking_details = f"""**Issues found**:
{"\n".join(f"- {i}" for i in locking["issues"])}
"""
    else:
        locking_details = f"Backend type: `{locking['backend_type']}`. State locking appears properly configured."

    # Rollback procedure
    rollback = DEFAULT_ROLLBACK_PROCEDURE.format(timestamp=timestamp)

    # Approval gate notice
    approval_notice = """## External Approval Required

> **SEC-8.2 Compliance**: This plan was generated by an automated agent. The same agent **CANNOT**
> approve its own plan. Approval must come from one of the following external sources:
> 1. A human reviewer with infrastructure approval authority, OR
> 2. A CI-native protected-environment gate (e.g., GitHub Environment with `required_reviewers: 1`)
>
> **Do not proceed to apply until external approval is explicitly recorded.**
"""

    md = f"""# Terraform Plan Review — {project} ({env})

**Generated**: {timestamp}  
**Project**: {project}  
**Environment**: {env}  
**Owner**: {owner}  
**Cost Center**: {cost_center}  
**Plan Artifact**: `plan.tfplan` (binary plan required for apply)

---

## 1. Plan Summary

| Action | Count |
|--------|-------|
| Create | {create} |
| Update | {update} |
| Destroy / Replace | {destroy} |
| **Total Changes** | **{create + update + destroy}** |

{resource_tables}

---

## 2. Cost Estimate

| Metric | Value |
|--------|-------|
| Total Monthly Cost | {cost['total_monthly']} {cost['currency']} |
| Previous Monthly Cost | {cost['past_total_monthly']} {cost['currency']} |
| Delta (Change) | {cost['delta_monthly']} {cost['currency']} |

{cost_table}

---

## 3. Risk Assessment & Blast Radius

**Blast Radius Score**: {score}  
**Risk Level**: {level}

| Factor | Assessment |
|--------|------------|
| Destructive changes | {"Yes — review rollback plan carefully" if destroy > 0 else "None"} |
| Data-loss potential | {"HIGH — persistent storage or databases affected" if any('rds' in r['type'].lower() or 'sql' in r['type'].lower() or 's3' in r['type'].lower() or 'bucket' in r['type'].lower() for r in resources if 'delete' in r['actions']) else "Low / None"} |
| Affected services | {len(set(r['module'] for r in resources))} module(s) |
| State locking | {"Verified" if locking['status'] == "PASS" else "ISSUE DETECTED — see below"} |

**Recommendation**:  
- If Risk Level is **HIGH**, require extended peer review and explicit SLO impact sign-off.  
- If Risk Level is **MEDIUM**, require standard external approval.  
- If Risk Level is **LOW**, standard approval gate still applies.

---

## 4. Checkov Security Scan Summary

**Status**: {"PASS" if checkov_summary['critical_count'] == 0 and checkov_summary['high_count'] == 0 else "BLOCKED — CRITICAL/HIGH findings detected"}

| Metric | Count |
|--------|-------|
| Passed | {checkov_summary['passed']} |
| Failed | {checkov_summary['failed']} |
| Skipped | {checkov_summary['skipped']} |
| Critical Findings | {checkov_summary['critical_count']} |
| High Findings | {checkov_summary['high_count']} |

{checkov_findings_table}

**Gate Rule**: If Critical Findings > 0, the workflow MUST halt and require remediation before any apply.

---

## 5. Tagging Compliance Check

**Status**: {tagging['status']}  
**Missing Tags Count**: {tagging['missing_tags_count']}

{tagging_details}

---

## 6. State Locking Verification

**Status**: {locking['status']}

{locking_details}

**State Backup Procedure**:
```bash
# Run this before any apply
cd <terraform-directory>
terraform state pull > state-backup-{timestamp}.json
# Upload to versioned backup bucket/container
```

---

## 7. Rollback Procedure

{rollback}

---

## 8. Required Confirmations Checklist

- [ ] **Plan reviewed** by infrastructure owner or designated peer
- [ ] **Checkov scan** passed or all CRITICAL/HIGH findings remediated/accepted with justification
- [ ] **Cost delta** approved by budget owner (if >20% increase)
- [ ] **State backup** captured and stored in versioned backup location
- [ ] **Rollback procedure** read and understood by on-call engineer
- [ ] **SLO impact** assessed for production changes
- [ ] **External approval** recorded (human signature or CI-native environment gate)
- [ ] **Change window** honored for non-emergency production changes

---

{approval_notice}

---

*This document was auto-generated by `scripts/generate-plan-review.py`. Do not edit manually — regenerate if plan changes.*
"""
    return md


# ────────────────────────────── main ──────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a human-readable Terraform plan review artifact (PLAN_REVIEW.md)."
    )
    parser.add_argument("--plan-json", required=True, help="Path to terraform show -json plan.tfplan output")
    parser.add_argument("--checkov-json", default=None, help="Path to Checkov JSON report (optional)")
    parser.add_argument("--infracost-json", default=None, help="Path to infracost JSON output (optional)")
    parser.add_argument("--project", required=True, help="Project name")
    parser.add_argument("--env", required=True, help="Environment name (dev/staging/prod)")
    parser.add_argument("--owner", required=True, help="Team or individual owner")
    parser.add_argument("--cost-center", required=True, help="Cost center / billing code")
    parser.add_argument("--output", default="./PLAN_REVIEW.md", help="Output file path")
    parser.add_argument("--timestamp", default=None, help="Override timestamp (ISO 8601)")

    args = parser.parse_args()

    plan = _load_json(args.plan_json)
    checkov = _load_json(args.checkov_json)
    infracost = _load_json(args.infracost_json)

    timestamp = args.timestamp or datetime.now(timezone.utc).isoformat()

    if not plan:
        print(f"ERROR: Plan JSON not found or invalid: {args.plan_json}", file=sys.stderr)
        return 1

    md = _build_markdown(
        plan=plan,
        checkov=checkov,
        infracost=infracost,
        project=args.project,
        env=args.env,
        owner=args.owner,
        cost_center=args.cost_center,
        timestamp=timestamp,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")

    print(f"Generated plan review artifact: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
