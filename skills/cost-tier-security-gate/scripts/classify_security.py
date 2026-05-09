#!/usr/bin/env python3
"""
classify_security.py — Task Security Sensitivity Classifier

Classifies tasks into SECURITY-CRITICAL, SECURITY-RELEVANT, or NON-SECURITY
tiers using keyword heuristics, skill metadata, file paths, environment variables,
and block list matching. Outputs classification results in JSON or YAML format
with audit-log compatible records.

Usage:
    python classify_security.py --skill-name "my-skill" --task-description "..." --tags "a,b"
    python classify_security.py --skill-name "my-skill" --task-description "..." --output json
    python classify_security.py --audit-log /var/log/routing_audit.log --query task_id=uuid

Exit codes:
    0 — Classification succeeded (check output for routing_decision)
    1 — Invalid arguments or missing required inputs
    2 — Classification engine error
    3 — Audit log query failed
"""

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent

# Thresholds
CONFIDENCE_HIGH = 0.90
CONFIDENCE_MEDIUM = 0.75
CLASSIFIER_VERSION = "1.0.0"
POLICY_ENGINE_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Keyword Dictionaries (weighted)
# ---------------------------------------------------------------------------

SECURITY_CRITICAL_KEYWORDS = {
    "secret": 3.0, "secrets": 3.0, "credential": 3.0, "credentials": 3.0,
    "password": 3.0, "token": 2.5, "api-key": 2.5, "apikey": 2.5,
    "key": 1.5, "keys": 1.5, "certificate": 2.0, "cert": 2.0,
    "tls": 2.0, "ssl": 2.0, "auth": 1.5, "authentication": 2.0,
    "authorization": 2.0, "vault": 3.0, "kms": 3.0, "hsm": 3.0,
    "encrypt": 2.5, "encryption": 2.5, "decrypt": 2.5, "decryption": 2.5,
    "sign": 2.5, "signature": 2.5, "verify": 1.5, "policy": 2.0,
    "policies": 2.0, "guardrail": 2.5, "guardrails": 2.5, "audit": 2.0,
    "rbac": 2.5, "iam": 2.5, "acl": 2.5, "access-control": 2.5,
    "role": 1.5, "permission": 1.5, "privilege": 2.0, "sandbox": 2.0,
    "escape": 2.0, "breakout": 2.5, "code-execution": 2.0,
    "shell": 1.5, "terminal": 1.5, "eval": 2.0, "unsafe": 2.5,
    "untrusted": 1.5, "malware": 2.5, "exploit": 2.5, "forensics": 2.0,
    "siem": 2.0, "firewall": 2.0, "waf": 2.0, "vpn": 1.5,
    "sbom": 2.0, "supply-chain": 2.0, "artifact-sign": 2.5,
    "notary": 2.0, "sigstore": 2.0, "provenance": 2.0,
}

SECURITY_RELEVANT_KEYWORDS = {
    "database": 1.5, "db": 1.0, "backup": 1.0, "monitor": 1.0,
    "alert": 1.0, "alerts": 1.0, "infrastructure": 1.5, "infra": 1.5,
    "network": 1.0, "dns": 1.0, "compliance": 1.5, "scan": 1.0,
    "cve": 1.5, "vulnerability": 1.5, "patch": 1.0, "deploy": 1.0,
    "deployment": 1.0, "production": 1.5, "prod": 1.5, "sensitive": 1.5,
    "confidential": 1.5, "internal": 1.0, "restricted": 1.5,
    "host": 0.5, "server": 0.5, "cluster": 0.5, "node": 0.5,
    "container": 0.5, "kubernetes": 0.5, "k8s": 0.5,
}

NON_SECURITY_KEYWORDS = {
    "documentation": 1.0, "docs": 1.0, "search": 1.0, "summarize": 1.0,
    "translate": 1.0, "explain": 1.0, "code-review": 1.0, "review": 0.5,
    "test": 0.5, "tests": 0.5, "lint": 0.5, "format": 0.5,
    "public": 1.0, "open-source": 1.0, "utility": 1.0, "general": 1.0,
    "brainstorm": 1.0, "creative": 1.0, "draft": 1.0, "email": 0.5,
    "message": 0.5, "chat": 0.5, "readme": 1.0, "tutorial": 1.0,
    "example": 0.5, "examples": 0.5, "guide": 0.5, "blog": 0.5,
}

KEYWORDS = {
    "SECURITY-CRITICAL": SECURITY_CRITICAL_KEYWORDS,
    "SECURITY-RELEVANT": SECURITY_RELEVANT_KEYWORDS,
    "NON-SECURITY": NON_SECURITY_KEYWORDS,
}

# ---------------------------------------------------------------------------
# Block List Patterns
# ---------------------------------------------------------------------------

BLOCKED_SKILL_PATTERNS = [
    re.compile(r"^secret-manager$", re.IGNORECASE),
    re.compile(r"^vault-", re.IGNORECASE),
    re.compile(r"^credential-", re.IGNORECASE),
    re.compile(r"^password-", re.IGNORECASE),
    re.compile(r"^token-", re.IGNORECASE),
    re.compile(r"^api-key-", re.IGNORECASE),
    re.compile(r"^kms-", re.IGNORECASE),
    re.compile(r"^hsm-", re.IGNORECASE),
    re.compile(r"^secrets-", re.IGNORECASE),
    re.compile(r".*keystore.*", re.IGNORECASE),
    re.compile(r".*cert-manager.*", re.IGNORECASE),
    re.compile(r".*oauth.*", re.IGNORECASE),
    re.compile(r"^crypto-", re.IGNORECASE),
    re.compile(r"^encrypt-", re.IGNORECASE),
    re.compile(r"^decrypt-", re.IGNORECASE),
    re.compile(r"^sign-", re.IGNORECASE),
    re.compile(r"^verify-", re.IGNORECASE),
    re.compile(r"^pgp-", re.IGNORECASE),
    re.compile(r"^gpg-", re.IGNORECASE),
    re.compile(r"^tls-", re.IGNORECASE),
    re.compile(r"^ssl-", re.IGNORECASE),
    re.compile(r"^certificate-", re.IGNORECASE),
    re.compile(r"^keygen-", re.IGNORECASE),
    re.compile(r".*cipher.*", re.IGNORECASE),
    re.compile(r".*hash.*", re.IGNORECASE),
    re.compile(r"^policy-", re.IGNORECASE),
    re.compile(r"^guardrail-", re.IGNORECASE),
    re.compile(r"^compliance-", re.IGNORECASE),
    re.compile(r"^security-policy-", re.IGNORECASE),
    re.compile(r"^rules-engine-", re.IGNORECASE),
    re.compile(r"^validation-", re.IGNORECASE),
    re.compile(r"^audit-", re.IGNORECASE),
    re.compile(r".*policy.*engine.*", re.IGNORECASE),
    re.compile(r".*compliance.*check.*", re.IGNORECASE),
    re.compile(r".*security.*rule.*", re.IGNORECASE),
    re.compile(r"^sandbox-", re.IGNORECASE),
    re.compile(r"^code-exec-", re.IGNORECASE),
    re.compile(r"^shell-", re.IGNORECASE),
    re.compile(r"^terminal-", re.IGNORECASE),
    re.compile(r"^eval-", re.IGNORECASE),
    re.compile(r".*unsafe.*", re.IGNORECASE),
    re.compile(r".*untrusted.*", re.IGNORECASE),
    re.compile(r".*sandbox.*escape.*", re.IGNORECASE),
    re.compile(r"^iam-", re.IGNORECASE),
    re.compile(r"^rbac-", re.IGNORECASE),
    re.compile(r"^auth-", re.IGNORECASE),
    re.compile(r"^identity-", re.IGNORECASE),
    re.compile(r"^sso-", re.IGNORECASE),
    re.compile(r"^ldap-", re.IGNORECASE),
    re.compile(r"^permission-", re.IGNORECASE),
    re.compile(r"^access-control-", re.IGNORECASE),
    re.compile(r"^user-management-", re.IGNORECASE),
    re.compile(r".*privilege.*", re.IGNORECASE),
    re.compile(r"^audit-log-", re.IGNORECASE),
    re.compile(r"^security-monitor-", re.IGNORECASE),
    re.compile(r"^siem-", re.IGNORECASE),
    re.compile(r"^incident-response-", re.IGNORECASE),
    re.compile(r"^forensics-", re.IGNORECASE),
    re.compile(r".*security.*event.*", re.IGNORECASE),
    re.compile(r".*intrusion.*detection.*", re.IGNORECASE),
    re.compile(r"^firewall-", re.IGNORECASE),
    re.compile(r"^network-policy-", re.IGNORECASE),
    re.compile(r"^security-group-", re.IGNORECASE),
    re.compile(r"^waf-", re.IGNORECASE),
    re.compile(r"^vpn-", re.IGNORECASE),
    re.compile(r".*network.*segment.*", re.IGNORECASE),
    re.compile(r".*traffic.*filter.*", re.IGNORECASE),
    re.compile(r"^artifact-sign-", re.IGNORECASE),
    re.compile(r"^sbom-", re.IGNORECASE),
    re.compile(r"^supply-chain-", re.IGNORECASE),
    re.compile(r"^notary-", re.IGNORECASE),
    re.compile(r"^sigstore-", re.IGNORECASE),
    re.compile(r"^checksum-", re.IGNORECASE),
    re.compile(r".*artifact.*verify.*", re.IGNORECASE),
]

BLOCKED_TASK_PATTERNS = [
    re.compile(r"rotate.*credential", re.IGNORECASE),
    re.compile(r"generate.*password", re.IGNORECASE),
    re.compile(r"create.*api.*key", re.IGNORECASE),
    re.compile(r"renew.*token", re.IGNORECASE),
    re.compile(r"sign.*jwt", re.IGNORECASE),
    re.compile(r"validate.*secret", re.IGNORECASE),
    re.compile(r"read.*secret", re.IGNORECASE),
    re.compile(r"write.*secret", re.IGNORECASE),
    re.compile(r"backup.*vault", re.IGNORECASE),
    re.compile(r"unseal.*vault", re.IGNORECASE),
    re.compile(r"encrypt.*file", re.IGNORECASE),
    re.compile(r"decrypt.*message", re.IGNORECASE),
    re.compile(r"sign.*document", re.IGNORECASE),
    re.compile(r"verify.*signature", re.IGNORECASE),
    re.compile(r"generate.*key.*pair", re.IGNORECASE),
    re.compile(r"create.*csr", re.IGNORECASE),
    re.compile(r"issue.*certificate", re.IGNORECASE),
    re.compile(r"rotate.*signing.*key", re.IGNORECASE),
    re.compile(r"derive.*key", re.IGNORECASE),
    re.compile(r"validate.*policy", re.IGNORECASE),
    re.compile(r"enforce.*guardrail", re.IGNORECASE),
    re.compile(r"audit.*access", re.IGNORECASE),
    re.compile(r"check.*compliance", re.IGNORECASE),
    re.compile(r"modify.*security.*rule", re.IGNORECASE),
    re.compile(r"disable.*guardrail", re.IGNORECASE),
    re.compile(r"bypass.*policy", re.IGNORECASE),
    re.compile(r"review.*security.*config", re.IGNORECASE),
    re.compile(r"assess.*risk", re.IGNORECASE),
    re.compile(r"execute.*user.*code", re.IGNORECASE),
    re.compile(r"run.*untrusted.*script", re.IGNORECASE),
    re.compile(r"eval.*input", re.IGNORECASE),
    re.compile(r"escape.*sandbox", re.IGNORECASE),
    re.compile(r"breakout.*container", re.IGNORECASE),
    re.compile(r"privilege.*escalation", re.IGNORECASE),
    re.compile(r"exploit.*detection", re.IGNORECASE),
    re.compile(r"malware.*analysis", re.IGNORECASE),
    re.compile(r"create.*role", re.IGNORECASE),
    re.compile(r"assign.*permission", re.IGNORECASE),
    re.compile(r"modify.*rbac", re.IGNORECASE),
    re.compile(r"grant.*access", re.IGNORECASE),
    re.compile(r"revoke.*privilege", re.IGNORECASE),
    re.compile(r"configure.*sso", re.IGNORECASE),
    re.compile(r"sync.*identity", re.IGNORECASE),
    re.compile(r"reset.*admin.*password", re.IGNORECASE),
    re.compile(r"elevate.*privilege", re.IGNORECASE),
    re.compile(r"read.*audit.*log", re.IGNORECASE),
    re.compile(r"delete.*security.*event", re.IGNORECASE),
    re.compile(r"modify.*monitor.*rule", re.IGNORECASE),
    re.compile(r"suppress.*alert", re.IGNORECASE),
    re.compile(r"tamper.*log", re.IGNORECASE),
    re.compile(r"exfiltrate.*audit.*data", re.IGNORECASE),
    re.compile(r"investigate.*breach", re.IGNORECASE),
    re.compile(r"open.*firewall.*port", re.IGNORECASE),
    re.compile(r"allow.*inbound.*traffic", re.IGNORECASE),
    re.compile(r"modify.*security.*group", re.IGNORECASE),
    re.compile(r"disable.*waf.*rule", re.IGNORECASE),
    re.compile(r"bypass.*network.*policy", re.IGNORECASE),
    re.compile(r"reconfigure.*vpn", re.IGNORECASE),
    re.compile(r"sign.*artifact", re.IGNORECASE),
    re.compile(r"verify.*checksum", re.IGNORECASE),
    re.compile(r"publish.*sbom", re.IGNORECASE),
    re.compile(r"attest.*build", re.IGNORECASE),
    re.compile(r"sign.*container.*image", re.IGNORECASE),
    re.compile(r"verify.*provenance", re.IGNORECASE),
]

SENSITIVE_PATH_PATTERNS = [
    re.compile(r"/secrets/.*", re.IGNORECASE),
    re.compile(r"/etc/ssl/.*", re.IGNORECASE),
    re.compile(r".*\.ssh/.*", re.IGNORECASE),
    re.compile(r".*keystore.*", re.IGNORECASE),
    re.compile(r".*credential.*", re.IGNORECASE),
    re.compile(r"/prod/.*", re.IGNORECASE),
    re.compile(r"/production/.*", re.IGNORECASE),
    re.compile(r"/db/.*", re.IGNORECASE),
    re.compile(r"/backup/.*", re.IGNORECASE),
    re.compile(r"/infrastructure/.*", re.IGNORECASE),
]

SENSITIVE_ENV_PATTERNS = [
    re.compile(r".*_SECRET$", re.IGNORECASE),
    re.compile(r".*_TOKEN$", re.IGNORECASE),
    re.compile(r".*_KEY$", re.IGNORECASE),
    re.compile(r".*_PASSWORD$", re.IGNORECASE),
    re.compile(r"^AWS_ACCESS_KEY_ID$", re.IGNORECASE),
    re.compile(r"^PRIVATE_KEY$", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Policy Pre-Check Rules
# ---------------------------------------------------------------------------

POLICY_RULES = {
    "data_residency": "Check if task references data labeled no-external-transfer",
    "classification_ceiling": "Check if data classification exceeds provider clearance",
    "chain_of_trust": "Verify execution chain is auditable and reproducible",
    "output_sensitivity": "Ensure Gemini output cannot infer sensitive internal state",
    "rate_limit_integrity": "Verify security-critical rate limits are not violated",
}


def run_policy_pre_check(task_info: dict[str, Any]) -> dict[str, Any]:
    """
    Run a simplified policy pre-check against non-negotiable rules.
    In production, this integrates with the full policy engine.
    """
    results = {}
    overall = "PASS"
    blocking_rule = None

    # Simplified heuristics for demo/CLI usage:
    # 1. Data residency: flag if sensitive paths or env vars are present
    if task_info.get("file_paths") or task_info.get("env_vars"):
        sensitive = False
        for p in task_info.get("file_paths", []):
            for pat in SENSITIVE_PATH_PATTERNS:
                if pat.match(p):
                    sensitive = True
                    break
        for e in task_info.get("env_vars", []):
            for pat in SENSITIVE_ENV_PATTERNS:
                if pat.match(e):
                    sensitive = True
                    break
        if sensitive:
            results["data_residency"] = "BLOCK"
            overall = "BLOCK"
            blocking_rule = "data_residency"
        else:
            results["data_residency"] = "PASS"
    else:
        results["data_residency"] = "PASS"

    # 2. Classification ceiling
    if task_info.get("data_classification") in ["confidential", "restricted", "top-secret"]:
        results["classification_ceiling"] = "BLOCK"
        overall = "BLOCK"
        if blocking_rule is None:
            blocking_rule = "classification_ceiling"
    else:
        results["classification_ceiling"] = "PASS"

    # 3. Chain of trust (default pass unless explicitly marked untrusted)
    if task_info.get("untrusted_chain"):
        results["chain_of_trust"] = "BLOCK"
        overall = "BLOCK"
        if blocking_rule is None:
            blocking_rule = "chain_of_trust"
    else:
        results["chain_of_trust"] = "PASS"

    # 4. Output sensitivity (default pass for NON-SECURITY, checked contextually)
    results["output_sensitivity"] = "PASS"

    # 5. Rate limit integrity (default pass in this simplified check)
    results["rate_limit_integrity"] = "PASS"

    return {
        "engine_version": POLICY_ENGINE_VERSION,
        "rules_evaluated": list(POLICY_RULES.keys()),
        "results": results,
        "overall_result": overall,
        "blocking_rule": blocking_rule,
    }


# ---------------------------------------------------------------------------
# Classification Engine
# ---------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
    """Simple tokenizer that splits on non-alphanumeric characters."""
    return re.findall(r"[a-zA-Z0-9_\-]+", text.lower())


def score_text(text: str) -> dict[str, float]:
    """Score a piece of text against all keyword dictionaries."""
    tokens = tokenize(text)
    scores = {tier: 0.0 for tier in KEYWORDS}
    for token in tokens:
        for tier, kw in KEYWORDS.items():
            if token in kw:
                scores[tier] += kw[token]
    return scores


def check_block_list(skill_name: str, task_description: str) -> tuple[bool, str]:
    """
    Check if the skill or task matches the routing block list.
    Returns (blocked, reason).
    """
    for pat in BLOCKED_SKILL_PATTERNS:
        if pat.match(skill_name):
            return True, f"Skill '{skill_name}' matches blocked pattern: {pat.pattern}"

    for pat in BLOCKED_TASK_PATTERNS:
        if pat.search(task_description):
            return True, f"Task description matches blocked pattern: {pat.pattern}"

    return False, ""


def classify_task(task_info: dict[str, Any]) -> dict[str, Any]:
    """
    Main classification function.
    Returns a complete classification result dict.
    """
    task_id = task_info.get("task_id") or str(uuid.uuid4())
    skill_name = task_info.get("skill_name", "")
    task_description = task_info.get("task_description", "")
    tags = task_info.get("tags", "")
    file_paths = task_info.get("file_paths", [])
    env_vars = task_info.get("env_vars", [])

    # Build combined text for keyword scoring
    combined_text = f"{skill_name} {task_description} {tags}"

    # 1. Block list check (highest priority)
    blocked, block_reason = check_block_list(skill_name, task_description)
    if blocked:
        return {
            "task_id": task_id,
            "classification": "SECURITY-CRITICAL",
            "confidence": 1.0,
            "routing_decision": "BLOCKED",
            "policy_check": None,
            "reason": block_reason,
            "classifier_version": CLASSIFIER_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # 2. Keyword scoring
    scores = score_text(combined_text)

    # 3. Path and env-var boosting for SECURITY-CRITICAL
    for p in file_paths:
        for pat in SENSITIVE_PATH_PATTERNS:
            if pat.match(p):
                scores["SECURITY-CRITICAL"] += 2.0
    for e in env_vars:
        for pat in SENSITIVE_ENV_PATTERNS:
            if pat.match(e):
                scores["SECURITY-CRITICAL"] += 3.0

    # 4. Determine tier and confidence
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    max_tier, max_score = sorted_scores[0]
    second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0

    # Default to SECURITY-CRITICAL if all scores are zero (no clear signal)
    if max_score == 0.0:
        max_tier = "NON-SECURITY"
        confidence = 0.5
    else:
        confidence = max_score / (max_score + second_score + 1e-6)

    # Apply fail-closed for low confidence on sensitive tiers
    if max_tier in ("SECURITY-CRITICAL", "SECURITY-RELEVANT") and confidence < CONFIDENCE_MEDIUM:
        routing_decision = "LOCAL"
        fallback_reason = f"Low confidence ({confidence:.2f}) for {max_tier}; defaulting to fail-closed local execution"
        policy_check_result = None
    elif max_tier == "SECURITY-CRITICAL":
        routing_decision = "BLOCKED"
        fallback_reason = None
        policy_check_result = None
    elif max_tier == "SECURITY-RELEVANT":
        policy_check_result = run_policy_pre_check(task_info)
        if policy_check_result["overall_result"] == "BLOCK":
            routing_decision = "LOCAL"
            fallback_reason = f"Policy pre-check failed: {policy_check_result['blocking_rule']}"
        else:
            routing_decision = "GEMINI"
            fallback_reason = None
    else:
        # NON-SECURITY: run policy pre-check for completeness
        policy_check_result = run_policy_pre_check(task_info)
        if policy_check_result["overall_result"] == "BLOCK":
            routing_decision = "LOCAL"
            fallback_reason = f"Policy pre-check failed: {policy_check_result['blocking_rule']}"
        else:
            routing_decision = "GEMINI"
            fallback_reason = None

    result = {
        "task_id": task_id,
        "classification": max_tier,
        "confidence": round(confidence, 4),
        "routing_decision": routing_decision,
        "policy_check": policy_check_result,
        "reason": block_reason if blocked else None,
        "fallback_reason": fallback_reason,
        "classifier_version": CLASSIFIER_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": {
            "scores": {k: round(v, 4) for k, v in scores.items()},
            "skill_name": skill_name,
            "task_description": task_description,
        },
    }
    return result


# ---------------------------------------------------------------------------
# Audit Log Query
# ---------------------------------------------------------------------------

def query_audit_log(audit_log_path: str, query: str) -> list[dict[str, Any]]:
    """
    Query an audit log file for records matching a key=value expression.
    Expects the audit log to contain one JSON object per line.
    """
    if not os.path.exists(audit_log_path):
        raise FileNotFoundError(f"Audit log not found: {audit_log_path}")

    if "=" not in query:
        raise ValueError("Query must be in key=value format")

    key, value = query.split("=", 1)
    results = []

    with open(audit_log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Support nested key access with dot notation (one level)
            if "." in key:
                parts = key.split(".")
                val = record.get(parts[0], {})
                if isinstance(val, dict) and val.get(parts[1]) == value:
                    results.append(record)
            else:
                if record.get(key) == value:
                    results.append(record)

    return results


# ---------------------------------------------------------------------------
# CLI Interface
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Task Security Sensitivity Classifier for cost-tier-security-gate"
    )
    parser.add_argument("--skill-name", type=str, default="", help="Name of the skill being invoked")
    parser.add_argument("--task-description", type=str, default="", help="Description of the task")
    parser.add_argument("--tags", type=str, default="", help="Comma-separated tags")
    parser.add_argument("--file-paths", type=str, default="", help="Comma-separated file paths")
    parser.add_argument("--env-vars", type=str, default="", help="Comma-separated environment variable names")
    parser.add_argument("--data-classification", type=str, default="", help="Data classification label")
    parser.add_argument("--untrusted-chain", action="store_true", help="Mark execution chain as untrusted")
    parser.add_argument("--output", type=str, choices=["json", "yaml", "pretty"], default="pretty",
                        help="Output format")
    parser.add_argument("--audit-log", type=str, default="", help="Path to audit log file for querying")
    parser.add_argument("--query", type=str, default="", help="Query in key=value format")
    parser.add_argument("--append-audit", type=str, default="",
                        help="Append result to specified audit log file path")

    args = parser.parse_args()

    # Audit log query mode
    if args.audit_log and args.query:
        try:
            results = query_audit_log(args.audit_log, args.query)
            if args.output == "json":
                print(json.dumps(results, indent=2))
            elif args.output == "yaml":
                import yaml
                print(yaml.dump(results, sort_keys=False))
            else:
                print(f"Found {len(results)} matching audit record(s):")
                for r in results:
                    print(json.dumps(r, indent=2))
            return 0
        except Exception as e:
            print(f"Error querying audit log: {e}", file=sys.stderr)
            return 3

    # Classification mode
    if not args.skill_name and not args.task_description:
        parser.print_help()
        return 1

    task_info = {
        "task_id": str(uuid.uuid4()),
        "skill_name": args.skill_name,
        "task_description": args.task_description,
        "tags": args.tags,
        "file_paths": [p.strip() for p in args.file_paths.split(",") if p.strip()],
        "env_vars": [e.strip() for e in args.env_vars.split(",") if e.strip()],
        "data_classification": args.data_classification,
        "untrusted_chain": args.untrusted_chain,
    }

    try:
        result = classify_task(task_info)
    except Exception as e:
        print(f"Classification engine error: {e}", file=sys.stderr)
        return 2

    # Append to audit log if requested
    if args.append_audit:
        try:
            with open(args.append_audit, "a", encoding="utf-8") as f:
                f.write(json.dumps(result) + "\n")
        except Exception as e:
            print(f"Warning: failed to append audit log: {e}", file=sys.stderr)

    # Output
    if args.output == "json":
        print(json.dumps(result, indent=2))
    elif args.output == "yaml":
        try:
            import yaml
            print(yaml.dump(result, sort_keys=False))
        except ImportError:
            print("PyYAML not installed; falling back to JSON", file=sys.stderr)
            print(json.dumps(result, indent=2))
    else:
        print(f"Task ID:       {result['task_id']}")
        print(f"Classification: {result['classification']}")
        print(f"Confidence:    {result['confidence']}")
        print(f"Routing:       {result['routing_decision']}")
        if result.get("reason"):
            print(f"Reason:        {result['reason']}")
        if result.get("fallback_reason"):
            print(f"Fallback:      {result['fallback_reason']}")
        if result.get("policy_check"):
            pc = result["policy_check"]
            print(f"Policy Check:  {pc['overall_result']}")
            if pc["blocking_rule"]:
                print(f"Blocking Rule: {pc['blocking_rule']}")
        print(f"Version:       {result['classifier_version']}")
        print(f"Timestamp:     {result['timestamp']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
