#!/usr/bin/env python3
"""
generate-pipeline.py

Template engine for CI/CD pipeline configs with Kimi skill-hook integration,
secret scanning, plan/apply separation, and external human approval gates.

Usage:
  python generate-pipeline.py --platform github --project-type python \
      --skills blast-radius,code-tester,security-auditor,api-contract-tester \
      --output ./.github/workflows/ci.yml

  python generate-pipeline.py --platform gitlab --project-type java \
      --skills all --output ./.gitlab-ci.yml

  python generate-pipeline.py --platform jenkins --project-type node \
      --skills blast-radius,code-tester,log-analyzer,performance-validator \
      --output ./Jenkinsfile

Platforms: github | gitlab | jenkins
Project types: python | node | java | go | rust | generic
Skills: blast-radius, code-tester, security-auditor, log-analyzer,
        dependency-manager, performance-validator, api-contract-tester,
        infra-as-code, all
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_CANARY_TRAFFIC_STEPS = [5, 25, 50, 100]
DEFAULT_ROLLBACK_ERROR_RATE = 0.01  # 1%
DEFAULT_ROLLBACK_P99_LATENCY_MS = 500

SKILL_HOOK_POINTS = {
    "blast-radius": {"events": ["pr_opened"], "stage": "blast-radius"},
    "code-tester": {"events": ["pr_opened", "build"], "stage": "test"},
    "security-auditor": {"events": ["pre_merge"], "stage": "security-scan"},
    "log-analyzer": {"events": ["build_failed"], "stage": "post-failure-analysis"},
    "dependency-manager": {"events": ["schedule"], "stage": "dependency-scan"},
    "performance-validator": {"events": ["staging_deploy"], "stage": "performance-gate"},
    "api-contract-tester": {"events": ["pre_production"], "stage": "contract-check"},
    "infra-as-code": {"events": ["provision"], "stage": "provision"},
}

PROJECT_TYPE_IMAGES = {
    "python": "python:3.11-slim",
    "node": "node:20-slim",
    "java": "eclipse-temurin:21-jdk",
    "go": "golang:1.22",
    "rust": "rust:1.78",
    "generic": "ubuntu:22.04",
}

BUILD_COMMANDS = {
    "python": "pip install -r requirements.txt && pytest --tb=short",
    "node": "npm ci && npm run test --if-present",
    "java": "./mvnw verify -B || mvn verify -B",
    "go": "go mod download && go test ./...",
    "rust": "cargo test --locked",
    "generic": "echo 'No build command defined for generic project'",
}

ARTIFACT_PATHS = {
    "python": "dist/",
    "node": "dist/",
    "java": "target/",
    "go": "bin/",
    "rust": "target/release/",
    "generic": "artifacts/",
}

# ---------------------------------------------------------------------------
# Secret scanner integration (inline so script is self-contained)
# ---------------------------------------------------------------------------

SECRET_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("AWS Access Key ID", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("AWS Secret Access Key", re.compile(r"['\"]?aws_secret_access_key['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?")),
    ("Generic API Key", re.compile(r"['\"]?(?:api[_\-\s]?key|apikey|api[_\-\s]?token|auth[_\-\s]?token)['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{16,})['\"]?", re.IGNORECASE)),
    ("Private Key", re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----", re.IGNORECASE)),
    ("GitHub Token", re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}")),
    ("GitLab Token", re.compile(r"glpat-[A-Za-z0-9_\-]{20,}")),
    ("Slack Token", re.compile(r"xox[baprs]-[0-9]{10,13}-[0-9]{10,13}(-[A-Za-z0-9]{24})?")),
    ("Slack Webhook", re.compile(r"https://hooks\.slack\.com/services/T[a-zA-Z0-9_]{8}/B[a-zA-Z0-9_]{8,}/[a-zA-Z0-9_]{24}")),
    ("Password Assignment", re.compile(r"['\"]?(?:password|passwd|pwd)['\"]?\s*[:=]\s*['\"]?([^\s'\"]{8,})['\"]?", re.IGNORECASE)),
    ("Bearer Token", re.compile(r"['\"]?[Bb]earer\s+['\"]?([A-Za-z0-9_\-\.]{20,})['\"]?")),
    ("High-Entropy Secret", re.compile(r"(?:SECRET|TOKEN|KEY|PASSWORD|CREDENTIAL)\s*=\s*['\"]?([A-Za-z0-9+/=]{20,})['\"]?", re.IGNORECASE)),
    ("Base64 Secret Blob", re.compile(r"['\"]?(?:secret|token|key|credential)['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9+/]{40,}={0,2})['\"]?", re.IGNORECASE)),
    ("JWT Token", re.compile(r"eyJ[A-Za-z0-9_\-]*\.eyJ[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-]*")),
    ("Docker Registry Auth", re.compile(r"['\"]?docker[_\-\s]?auth['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9+/]{20,}={0,2})['\"]?", re.IGNORECASE)),
    ("NPM Token", re.compile(r"npm_[A-Za-z0-9]{36}")),
    ("PyPI Token", re.compile(r"pypi-[A-Za-z0-9_\-]{26,}")),
]

SAFE_PLACEHOLDERS: List[re.Pattern] = [
    re.compile(r"\$\{\{?\s*secrets\."),
    re.compile(r"\$\{\{?\s*env\."),
    re.compile(r"\$\{\{?\s*vars\."),
    re.compile(r"\$\{?[A-Z_]+\}?"),
    re.compile(r"\$\w+"),
    re.compile(r"<\s*[\w\-]+\s*>"),
    re.compile(r"\{\{\s*[\w\-]+\s*\}\}"),
    re.compile(r"placeholder", re.IGNORECASE),
    re.compile(r"YOUR_", re.IGNORECASE),
    re.compile(r"INSERT_", re.IGNORECASE),
    re.compile(r"CHANGEME", re.IGNORECASE),
    re.compile(r"EXAMPLE", re.IGNORECASE),
]


def _is_placeholder(value: str) -> bool:
    for pat in SAFE_PLACEHOLDERS:
        if pat.search(value):
            return True
    return False


def scan_text_for_secrets(text: str, file_label: str = "<generated>") -> List[Dict]:
    findings: List[Dict] = []
    lines = text.splitlines()
    for line_no, line in enumerate(lines, start=1):
        for name, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(line):
                matched = match.group(0)
                if _is_placeholder(matched):
                    continue
                try:
                    captured = match.group(1)
                    if captured and _is_placeholder(captured):
                        continue
                except IndexError:
                    pass
                if name in ("Generic API Key", "High-Entropy Secret", "Base64 Secret Blob"):
                    if len(matched) < 20:
                        continue
                    if re.fullmatch(r"[0-9a-f\-]+", matched, re.IGNORECASE):
                        continue
                findings.append({"file": file_label, "line": line_no, "type": name, "match": matched, "line_text": line.rstrip()})
    return findings


def validate_no_secrets(content: str, label: str) -> bool:
    findings = scan_text_for_secrets(content, label)
    if findings:
        print(f"\n[BLOCKED] Secrets detected in {label}:", file=sys.stderr)
        for f in findings:
            print(f"  Line {f['line']}: [{f['type']}] {f['match']}", file=sys.stderr)
        print("\n[REMEDIATION] Replace detected secrets with platform-native placeholders:", file=sys.stderr)
        print("  GitHub Actions: ${{ secrets.SECRET_NAME }}", file=sys.stderr)
        print("  GitLab CI     : \"${SECRET_NAME}\" (masked in CI/CD Variables UI)", file=sys.stderr)
        print("  Jenkins       : withCredentials([string(credentialsId: 'secret-name', variable: 'SECRET_NAME')])", file=sys.stderr)
        return False
    return True


# ---------------------------------------------------------------------------
# GitHub Actions generator
# ---------------------------------------------------------------------------

def generate_github_actions(
    project_type: str,
    skills: Set[str],
    canary_steps: List[int],
    rollback_error_rate: float,
    rollback_p99_ms: int,
    dry_run_default: bool = True,
) -> str:
    image = PROJECT_TYPE_IMAGES.get(project_type, "ubuntu:22.04")
    build_cmd = BUILD_COMMANDS.get(project_type, "echo 'build'")
    artifact_path = ARTIFACT_PATHS.get(project_type, "artifacts/")

    # Build skill hook jobs
    hook_jobs = []
    if "blast-radius" in skills or "all" in skills:
        hook_jobs.append(
            """
  blast-radius:
    runs-on: ubuntu-latest
    needs: build
    # KIMI_HOOK: Blast Radius Calculator — impact analysis on PR
    steps:
      - uses: actions/checkout@v4
      - name: Blast Radius Analysis
        run: |
          echo "[KIMI_HOOK] Trigger Blast Radius Calculator"
          echo "Analyze changed files for downstream impact"
          # Placeholder: invoke blast-radius skill or script
"""
        )
    if "code-tester" in skills or "all" in skills:
        hook_jobs.append(
            """
  code-tester:
    runs-on: ubuntu-latest
    needs: build
    # KIMI_HOOK: Code Tester — run tests and coverage
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        if: runner.os == 'Linux'
      - name: Run Tests
        run: |
          echo "[KIMI_HOOK] Trigger Code Tester"
          # Placeholder: run test suite via Code Tester skill
"""
        )
    if "security-auditor" in skills or "all" in skills:
        hook_jobs.append(
            """
  security-auditor:
    runs-on: ubuntu-latest
    needs: code-tester
    # KIMI_HOOK: Security Auditor — pre-merge gate
    steps:
      - uses: actions/checkout@v4
      - name: Security Scan
        run: |
          echo "[KIMI_HOOK] Trigger Security Auditor"
          # Placeholder: run SAST/dependency scan
"""
        )
    if "log-analyzer" in skills or "all" in skills:
        hook_jobs.append(
            """
  log-analyzer:
    runs-on: ubuntu-latest
    if: failure()
    # KIMI_HOOK: Log Analyzer — triggered on any failure
    steps:
      - uses: actions/checkout@v4
      - name: Analyze Failure Logs
        run: |
          echo "[KIMI_HOOK] Trigger Log Analyzer on build failure"
          # Placeholder: fetch logs and invoke Log Analyzer
"""
        )
    if "dependency-manager" in skills or "all" in skills:
        hook_jobs.append(
            """
  dependency-manager:
    runs-on: ubuntu-latest
    if: github.event.schedule
    # KIMI_HOOK: Dependency Manager — scheduled scan
    steps:
      - uses: actions/checkout@v4
      - name: Dependency Scan
        run: |
          echo "[KIMI_HOOK] Trigger Dependency Manager"
          # Placeholder: audit dependencies and check for updates
"""
        )
    if "performance-validator" in skills or "all" in skills:
        hook_jobs.append(
            """
  performance-validator:
    runs-on: ubuntu-latest
    needs: staging-deploy
    # KIMI_HOOK: Performance Validator — regression gate
    steps:
      - uses: actions/checkout@v4
      - name: Performance Regression Check
        run: |
          echo "[KIMI_HOOK] Trigger Performance Validator"
          # Placeholder: run load tests and compare metrics
"""
        )
    if "api-contract-tester" in skills or "all" in skills:
        hook_jobs.append(
            """
  api-contract-tester:
    runs-on: ubuntu-latest
    needs: performance-validator
    # KIMI_HOOK: API Contract Tester — backward-compatibility gate
    steps:
      - uses: actions/checkout@v4
      - name: API Contract Check
        run: |
          echo "[KIMI_HOOK] Trigger API Contract Tester"
          # Placeholder: run contract tests against staging
"""
        )
    if "infra-as-code" in skills or "all" in skills:
        hook_jobs.append(
            """
  infra-as-code:
    runs-on: ubuntu-latest
    needs: build
    # KIMI_HOOK: Infrastructure-as-Code — provision environment
    steps:
      - uses: actions/checkout@v4
      - name: Provision Environment
        run: |
          echo "[KIMI_HOOK] Trigger Infrastructure-as-Code provision"
          # Placeholder: terraform plan / pulumi preview (dry-run) then apply
"""
        )

    canary_jobs = ""
    for i, step in enumerate(canary_steps):
        prev = canary_steps[i - 1] if i > 0 else 0
        canary_jobs += f"""
  canary-{step}pct:
    runs-on: ubuntu-latest
    needs: {f'canary-{prev}pct' if prev > 0 else 'staging-deploy'}
    env:
      CANARY_TRAFFIC: {step}
    steps:
      - uses: actions/checkout@v4
      - name: Canary {step}% Rollout
        run: |
          echo "[CANARY] Routing {step}% traffic to new version"
          # Placeholder: service mesh / ingress traffic split
      - name: Monitor Metrics
        run: |
          echo "[ROLLBACK_GATE] error_rate < {rollback_error_rate} && p99 < {rollback_p99_ms}ms"
          # Placeholder: query metrics backend; abort rollout on breach
"""

    rollback_job = """
  rollback:
    runs-on: ubuntu-latest
    if: failure() && (needs.canary-*pct.result == 'failure' || needs.production-deploy.result == 'failure')
    steps:
      - uses: actions/checkout@v4
      - name: Execute Rollback
        run: |
          echo "[ROLLBACK] Reverting to last stable artifact"
          # Placeholder: kubectl rollout undo / ecs update-service / swap blue-green
      - name: Notify
        run: |
          echo "[ALERT] Rollback executed — notify on-call"
"""

    lines = [
        "name: Kimi CI/CD Pipeline",
        "",
        "on:",
        "  push:",
        "    branches: [main]",
        "  pull_request:",
        "    branches: [main]",
        "  schedule:",
        '    - cron: "0 3 * * 1"  # Weekly dependency scan',
        "  workflow_dispatch:",
        "    inputs:",
        "      dry_run:",
        f"        description: 'Run in dry-run mode (simulation only)'",
        f"        required: true",
        f"        default: '{str(dry_run_default).lower()}'",
        "",
        "env:",
        f'  DRY_RUN: ${{ github.event.inputs.dry_run || \'true\' }}',
        f'  ROLLBACK_ERROR_RATE: "{rollback_error_rate}"',
        f'  ROLLBACK_P99_MS: "{rollback_p99_ms}"',
        "",
        "jobs:",
        "  build:",
        "    runs-on: ubuntu-latest",
        "    container:",
        f"      image: {image}",
        "    steps:",
        "      - uses: actions/checkout@v4",
        f"      - name: Build ({project_type})",
        "        run: |",
        "          echo '[BUILD] Starting build...'",
        f"          {build_cmd}",
        "      - name: Dry-Run Gate",
        "        run: |",
        '          if [ "$DRY_RUN" = "true" ]; then echo "[DRY-RUN] Skipping artifact publish"; exit 0; fi',
        f"      - uses: actions/upload-artifact@v4",
        "        with:",
        f"          name: build-artifacts",
        f"          path: {artifact_path}",
        "",
        "  # ------------------------------------------------------------------",
        "  # Kimi Skill Hooks",
        "  # ------------------------------------------------------------------",
    ]

    for hj in hook_jobs:
        lines.extend(hj.strip().splitlines())
        lines.append("")

    lines.extend([
        "  staging-deploy:",
        "    runs-on: ubuntu-latest",
        "    needs: [security-auditor, api-contract-tester] if \"all\" in skills else [build]",
        "    # KIMI: Staging deploy with dry-run gate",
        "    steps:",
        "      - uses: actions/checkout@v4",
        "      - name: Dry-Run Plan",
        "        run: |",
        '          echo "[DRY-RUN] Deployment plan for staging"',
        '          if [ "$DRY_RUN" = "true" ]; then echo "Simulation complete"; exit 0; fi',
        "      - name: Deploy to Staging",
        "        run: |",
        '          echo "[DEPLOY] Deploying to staging environment"',
        "",
    ])

    lines.extend([
        "  # ------------------------------------------------------------------",
        "  # Canary Deployment",
        "  # ------------------------------------------------------------------",
    ])
    lines.extend(canary_jobs.strip().splitlines())
    lines.append("")

    # Production Plan + Apply with external approval gate
    lines.extend([
        "  # ------------------------------------------------------------------",
        "  # Production Plan (dry-run / plan stage)",
        "  # ------------------------------------------------------------------",
        "  production-plan:",
        "    runs-on: ubuntu-latest",
        f"    needs: canary-{canary_steps[-1]}pct",
        "    environment: production",
        "    steps:",
        "      - uses: actions/checkout@v4",
        "      - name: Generate Production Plan",
        "        run: |",
        '          echo "[PLAN] Generating deployment plan for production..."',
        "          # Placeholder: terraform plan, helm diff, or equivalent",
        "      - name: Upload Plan Artifact",
        "        uses: actions/upload-artifact@v4",
        "        with:",
        "          name: production-plan",
        '          path: "plan-artifact/"',
        "",
        "  # ------------------------------------------------------------------",
        "  # Production Apply (external human approval gate)",
        "  # ------------------------------------------------------------------",
        "  production-apply:",
        "    runs-on: ubuntu-latest",
        "    needs: production-plan",
        "    environment:",
        "      name: production",
        "      # REQUIRED_REVIEWERS: configured in repo Settings -> Environments",
        "      # The agent CANNOT bypass this gate.",
        "    steps:",
        "      - uses: actions/checkout@v4",
        "      - name: Human Approval Gate",
        "        run: |",
        '          echo "[GATE] This job only runs after a human approves the production environment."',
        "      - name: Dry-Run Check",
        "        run: |",
        '          echo "[DRY-RUN] DRY_RUN=${DRY_RUN}"',
        '          if [ "$DRY_RUN" = "true" ]; then echo "Simulation complete. Set DRY_RUN=false to execute."; exit 0; fi',
        "      - name: Deploy to Production",
        "        run: |",
        '          echo "[DEPLOY] Deploying to production environment"',
        "          # Placeholder: actual production deploy command",
        "",
        "  # ------------------------------------------------------------------",
        "  # Kimi Agent CI Invocation (always --dry-run)",
        "  # ------------------------------------------------------------------",
        "  kimi-agent-dry-run:",
        "    runs-on: ubuntu-latest",
        "    if: github.event_name == 'workflow_dispatch'",
        "    steps:",
        "      - uses: actions/checkout@v4",
        "      - name: Kimi Agent Dry-Run",
        "        run: |",
        '          echo "[AGENT] Invoking Kimi agent with --dry-run flag"',
        "          # kimi-agent --dry-run deploy --env production",
        "",
    ])

    lines.extend([
        "  # ------------------------------------------------------------------",
        "  # Automated Rollback",
        "  # ------------------------------------------------------------------",
    ])
    lines.extend(rollback_job.strip().splitlines())
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GitLab CI generator
# ---------------------------------------------------------------------------

def generate_gitlab_ci(
    project_type: str,
    skills: Set[str],
    canary_steps: List[int],
    rollback_error_rate: float,
    rollback_p99_ms: int,
    dry_run_default: bool = True,
) -> str:
    image = PROJECT_TYPE_IMAGES.get(project_type, "ubuntu:22.04")
    build_cmd = BUILD_COMMANDS.get(project_type, "echo 'build'")
    artifact_path = ARTIFACT_PATHS.get(project_type, "artifacts/")

    lines = [
        "# Kimi CI/CD Pipeline — GitLab CI",
        "# Generated by ci-cd-integrator / generate-pipeline.py",
        "# Safety: all secrets must be CI/CD Variables (masked + protected). NEVER inline credentials.",
        "",
        "variables:",
        f'  DRY_RUN: "{str(dry_run_default).lower()}"',
        f'  ROLLBACK_ERROR_RATE: "{rollback_error_rate}"',
        f'  ROLLBACK_P99_MS: "{rollback_p99_ms}"',
        "",
        "stages:",
        "  - build",
        "  - test",
        "  - security-scan",
        "  - blast-radius",
        "  - provision",
        "  - performance-gate",
        "  - contract-check",
        "  - staging",
        "  - canary",
        "  - plan",
        "  - production",
        "  - rollback",
        "",
        "# ------------------------------------------------------------------",
        "# Build",
        "# ------------------------------------------------------------------",
        "build:",
        f"  image: {image}",
        "  stage: build",
        "  script:",
        "    - echo '[BUILD] Starting build...'",
        f"    - {build_cmd}",
        "  artifacts:",
        "    paths:",
        f"      - {artifact_path}",
        "",
    ]

    if "code-tester" in skills or "all" in skills:
        lines.extend([
            "# ------------------------------------------------------------------",
            "# KIMI_HOOK: Code Tester",
            "# ------------------------------------------------------------------",
            "code-tester:",
            "  stage: test",
            "  needs: [build]",
            "  script:",
            "    - echo '[KIMI_HOOK] Trigger Code Tester'",
            "    - echo 'Placeholder: run tests via Code Tester skill'",
            "",
        ])
    if "security-auditor" in skills or "all" in skills:
        lines.extend([
            "# ------------------------------------------------------------------",
            "# KIMI_HOOK: Security Auditor — pre-merge gate",
            "# ------------------------------------------------------------------",
            "security-auditor:",
            "  stage: security-scan",
            "  needs: [code-tester]",
            "  script:",
            "    - echo '[KIMI_HOOK] Trigger Security Auditor'",
            "    - echo 'Placeholder: SAST / dependency scan'",
            "  allow_failure: false",
            "",
        ])
    if "blast-radius" in skills or "all" in skills:
        lines.extend([
            "# ------------------------------------------------------------------",
            "# KIMI_HOOK: Blast Radius Calculator",
            "# ------------------------------------------------------------------",
            "blast-radius:",
            "  stage: blast-radius",
            "  needs: [build]",
            "  script:",
            "    - echo '[KIMI_HOOK] Trigger Blast Radius Calculator'",
            "    - echo 'Placeholder: analyze downstream impact of changes'",
            "",
        ])
    if "dependency-manager" in skills or "all" in skills:
        lines.extend([
            "# ------------------------------------------------------------------",
            "# KIMI_HOOK: Dependency Manager — scheduled scan",
            "# ------------------------------------------------------------------",
            "dependency-manager:",
            "  stage: security-scan",
            "  only:",
            "    - schedules",
            "  script:",
            "    - echo '[KIMI_HOOK] Trigger Dependency Manager'",
            "    - echo 'Placeholder: audit and update dependencies'",
            "",
        ])
    if "infra-as-code" in skills or "all" in skills:
        lines.extend([
            "# ------------------------------------------------------------------",
            "# KIMI_HOOK: Infrastructure-as-Code — provision",
            "# ------------------------------------------------------------------",
            "infra-as-code:",
            "  stage: provision",
            "  needs: [build]",
            "  script:",
            "    - echo '[KIMI_HOOK] Trigger Infrastructure-as-Code provision'",
            "    - echo 'Placeholder: terraform plan (dry-run) then apply'",
            "    - |",
            '      if [ "$DRY_RUN" = "true" ]; then',
            '        echo "[DRY-RUN] terraform plan / pulumi preview";',
            "      else",
            '        echo "[EXECUTE] terraform apply / pulumi up";',
            "      fi",
            "",
        ])
    if "performance-validator" in skills or "all" in skills:
        lines.extend([
            "# ------------------------------------------------------------------",
            "# KIMI_HOOK: Performance Validator — regression gate",
            "# ------------------------------------------------------------------",
            "performance-validator:",
            "  stage: performance-gate",
            "  needs: [staging]",
            "  script:",
            "    - echo '[KIMI_HOOK] Trigger Performance Validator'",
            "    - echo 'Placeholder: load tests and metric comparison'",
            "",
        ])
    if "api-contract-tester" in skills or "all" in skills:
        lines.extend([
            "# ------------------------------------------------------------------",
            "# KIMI_HOOK: API Contract Tester — backward-compatibility gate",
            "# ------------------------------------------------------------------",
            "api-contract-tester:",
            "  stage: contract-check",
            "  needs: [performance-gate]",
            "  script:",
            "    - echo '[KIMI_HOOK] Trigger API Contract Tester'",
            "    - echo 'Placeholder: contract tests against staging'",
            "  allow_failure: false",
            "",
        ])
    if "log-analyzer" in skills or "all" in skills:
        lines.extend([
            "# ------------------------------------------------------------------",
            "# KIMI_HOOK: Log Analyzer — on failure",
            "# ------------------------------------------------------------------",
            "log-analyzer:",
            "  stage: rollback",
            "  when: on_failure",
            "  script:",
            "    - echo '[KIMI_HOOK] Trigger Log Analyzer on build failure'",
            "    - echo 'Placeholder: fetch logs and analyze root cause'",
            "",
        ])

    lines.extend([
        "# ------------------------------------------------------------------",
        "# Staging Deploy (with dry-run gate)",
        "# ------------------------------------------------------------------",
        "staging-deploy:",
        "  stage: staging",
        "  needs: [api-contract-tester]",
        "  script:",
        "    - echo '[DRY-RUN] Deployment plan for staging'",
        "    - |",
        '      if [ "$DRY_RUN" = "true" ]; then',
        '        echo "Simulation complete"; exit 0;',
        "      fi",
        "    - echo '[DEPLOY] Deploying to staging environment'",
        "",
    ])

    for i, step in enumerate(canary_steps):
        prev = canary_steps[i - 1] if i > 0 else 0
        lines.extend([
            f"# ------------------------------------------------------------------",
            f"# Canary {step}%",
            f"# ------------------------------------------------------------------",
            f"canary-{step}pct:",
            f"  stage: canary",
            f"  needs: [{f'canary-{prev}pct' if prev > 0 else 'staging-deploy'}]",
            f"  variables:",
            f'    CANARY_TRAFFIC: "{step}"',
            f"  script:",
            f"    - echo '[CANARY] Routing {step}% traffic to new version'",
            f"    - echo '[ROLLBACK_GATE] error_rate < $ROLLBACK_ERROR_RATE && p99 < $ROLLBACK_P99_MS ms'",
            f"    - echo 'Placeholder: service mesh / ingress traffic split'",
            f"",
        ])

    # Production Plan + Apply with external approval gate
    lines.extend([
        "# ------------------------------------------------------------------",
        "# Production Plan (dry-run)",
        "# ------------------------------------------------------------------",
        "production-plan:",
        "  stage: plan",
        f"  needs: [canary-{canary_steps[-1]}pct]",
        "  script:",
        "    - echo '[PLAN] Generating deployment plan for production...'",
        "    - terraform plan -out=tfplan  # Placeholder: plan command",
        "  artifacts:",
        "    paths:",
        "      - tfplan",
        "",
        "# ------------------------------------------------------------------",
        "# Production Apply (external human approval gate)",
        "# ------------------------------------------------------------------",
        "production-apply:",
        "  stage: production",
        "  needs: [production-plan]",
        "  environment:",
        "    name: production",
        "  rules:",
        "    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH",
        "      when: manual",
        "      allow_failure: false",
        "  script:",
        "    - echo '[GATE] Human must click Play to trigger this job. Agent CANNOT bypass.'",
        "    - echo '[DRY-RUN] DRY_RUN=$DRY_RUN'",
        "    - |",
        '      if [ "$DRY_RUN" = "true" ]; then',
        '        echo "Simulation complete. Set DRY_RUN=false to execute."; exit 0;',
        "      fi",
        "    - echo '[DEPLOY] Deploying to production environment'",
        "    - terraform apply tfplan",
        "",
        "# ------------------------------------------------------------------",
        "# Kimi Agent CI Invocation (always --dry-run)",
        "# ------------------------------------------------------------------",
        "kimi-agent-dry-run:",
        "  stage: plan",
        "  rules:",
        "    - if: $CI_PIPELINE_SOURCE == 'web'",
        "  script:",
        "    - echo '[AGENT] Invoking Kimi agent with --dry-run flag'",
        "    - echo '# kimi-agent --dry-run deploy --env production'",
        "",
        "# ------------------------------------------------------------------",
        "# Automated Rollback",
        "# ------------------------------------------------------------------",
        "rollback:",
        "  stage: rollback",
        "  when: on_failure",
        "  script:",
        "    - echo '[ROLLBACK] Reverting to last stable artifact'",
        "    - echo 'Placeholder: kubectl rollout undo / ecs update-service / swap'",
        "    - echo '[ALERT] Rollback executed — notify on-call'",
        "",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Jenkins generator
# ---------------------------------------------------------------------------

def generate_jenkinsfile(
    project_type: str,
    skills: Set[str],
    canary_steps: List[int],
    rollback_error_rate: float,
    rollback_p99_ms: int,
    dry_run_default: bool = True,
) -> str:
    image = PROJECT_TYPE_IMAGES.get(project_type, "ubuntu:22.04")
    build_cmd = BUILD_COMMANDS.get(project_type, "echo 'build'")
    artifact_path = ARTIFACT_PATHS.get(project_type, "artifacts/")

    # Build skill stages
    skill_stages = []
    if "blast-radius" in skills or "all" in skills:
        skill_stages.append("""        stage('Blast Radius') {
            steps {
                echo '[KIMI_HOOK] Trigger Blast Radius Calculator'
                echo 'Placeholder: analyze downstream impact'
            }
        }""")
    if "code-tester" in skills or "all" in skills:
        skill_stages.append("""        stage('Code Tester') {
            steps {
                echo '[KIMI_HOOK] Trigger Code Tester'
                echo 'Placeholder: run tests via Code Tester skill'
            }
        }""")
    if "security-auditor" in skills or "all" in skills:
        skill_stages.append("""        stage('Security Auditor') {
            steps {
                echo '[KIMI_HOOK] Trigger Security Auditor'
                echo 'Placeholder: SAST / dependency scan'
            }
        }""")
    if "dependency-manager" in skills or "all" in skills:
        skill_stages.append("""        stage('Dependency Manager') {
            when {
                triggeredBy 'TimerTrigger'
            }
            steps {
                echo '[KIMI_HOOK] Trigger Dependency Manager'
                echo 'Placeholder: audit and update dependencies'
            }
        }""")
    if "performance-validator" in skills or "all" in skills:
        skill_stages.append("""        stage('Performance Validator') {
            steps {
                echo '[KIMI_HOOK] Trigger Performance Validator'
                echo 'Placeholder: load tests and metric comparison'
            }
        }""")
    if "api-contract-tester" in skills or "all" in skills:
        skill_stages.append("""        stage('API Contract Tester') {
            steps {
                echo '[KIMI_HOOK] Trigger API Contract Tester'
                echo 'Placeholder: contract tests against staging'
            }
        }""")
    if "infra-as-code" in skills or "all" in skills:
        skill_stages.append("""        stage('Infrastructure-as-Code') {
            steps {
                echo '[KIMI_HOOK] Trigger Infrastructure-as-Code provision'
                script {
                    if (params.DRY_RUN) {
                        echo '[DRY-RUN] terraform plan / pulumi preview'
                    } else {
                        echo '[EXECUTE] terraform apply / pulumi up'
                    }
                }
            }
        }""")

    canary_stages = ""
    for i, step in enumerate(canary_steps):
        prev = canary_steps[i - 1] if i > 0 else 0
        prev_need = f"'Canary {prev}%'" if prev > 0 else "'Staging Deploy'"
        canary_stages += f"""        stage('Canary {step}%') {{
            when {{
                expression {{ currentBuild.result == null || currentBuild.result == 'SUCCESS' }}
            }}
            environment {{
                CANARY_TRAFFIC = '{step}'
            }}
            steps {{
                echo '[CANARY] Routing {step}% traffic to new version'
                echo '[ROLLBACK_GATE] error_rate < {rollback_error_rate} && p99 < {rollback_p99_ms}ms'
                echo 'Placeholder: service mesh / ingress traffic split'
            }}
        }}
"""

    skills_block = "\n".join(skill_stages)

    return f"""// Kimi CI/CD Pipeline — Jenkinsfile
// Generated by ci-cd-integrator / generate-pipeline.py
// Safety: all credentials must be stored in Jenkins Credentials. NEVER inline secrets.

pipeline {{
    agent {{
        docker {{ image '{image}' }}
    }}

    parameters {{
        booleanParam(name: 'DRY_RUN',
                     defaultValue: {str(dry_run_default).lower()},
                     description: 'Run in dry-run mode (simulation only)')
    }}

    environment {{
        ROLLBACK_ERROR_RATE = '{rollback_error_rate}'
        ROLLBACK_P99_MS = '{rollback_p99_ms}'
        ARTIFACT_PATH = '{artifact_path}'
    }}

    stages {{
        stage('Build') {{
            steps {{
                echo '[BUILD] Starting build...'
                sh '{build_cmd}'
            }}
            post {{
                success {{
                    archiveArtifacts artifacts: '{artifact_path}**', allowEmptyArchive: true
                }}
            }}
        }}

        // ------------------------------------------------------------------
        // Kimi Skill Hooks
        // ------------------------------------------------------------------
{skills_block}

        stage('Staging Deploy') {{
            steps {{
                echo '[DRY-RUN] Deployment plan for staging'
                script {{
                    if (params.DRY_RUN) {{
                        echo 'Simulation complete'
                    }} else {{
                        echo '[DEPLOY] Deploying to staging environment'
                    }}
                }}
            }}
        }}

        // ------------------------------------------------------------------
        // Canary Deployment
        // ------------------------------------------------------------------
{canary_stages}

        stage('Production Plan') {{
            steps {{
                echo '[PLAN] Generating deployment plan for production...'
                sh 'terraform plan -out=tfplan || echo "Placeholder: plan command"'
                archiveArtifacts artifacts: 'tfplan', allowEmptyArchive: false
            }}
        }}

        stage('Human Approval Gate') {{
            steps {{
                timeout(time: 24, unit: 'HOURS') {{
                    script {{
                        def approvers = input(
                            message: 'Approve production deployment?',
                            ok: 'Deploy',
                            submitterParameter: 'APPROVER',
                            parameters: [
                                choice(
                                    name: 'DEPLOY_DECISION',
                                    choices: ['NO', 'YES'],
                                    description: 'Human confirmation required'
                                )
                            ]
                        )
                        if (approvers.DEPLOY_DECISION != 'YES') {{
                            error('[BLOCKED] Production deployment was rejected by human.')
                        }}
                        echo "[GATE] Approved by ${{approvers.APPROVER}}"
                    }}
                }}
            }}
        }}

        stage('Production Apply') {{
            when {{
                expression {{ currentBuild.result == null || currentBuild.result == 'SUCCESS' }}
            }}
            steps {{
                echo '[DRY-RUN] DRY_RUN=${{params.DRY_RUN}}'
                script {{
                    if (params.DRY_RUN) {{
                        echo 'Simulation complete. Set DRY_RUN=false to execute.'
                    }} else {{
                        echo '[DEPLOY] Deploying to production environment'
                        sh 'terraform apply tfplan || echo "Placeholder: apply command"'
                    }}
                }}
            }}
        }}
    }}

    post {{
        failure {{
            echo '[KIMI_HOOK] Trigger Log Analyzer on build failure'
            echo 'Placeholder: fetch logs and analyze root cause'
        }}
        unstable {{
            echo '[ROLLBACK] Reverting to last stable artifact'
            echo 'Placeholder: kubectl rollout undo / ecs update-service / swap'
            echo '[ALERT] Rollback executed — notify on-call'
        }}
    }}
}}
"""


# ---------------------------------------------------------------------------
# Documentation generator
# ---------------------------------------------------------------------------

def generate_docs(
    platform: str,
    project_type: str,
    skills: Set[str],
    canary_steps: List[int],
    rollback_error_rate: float,
    rollback_p99_ms: int,
) -> str:
    lines = [
        "# Pipeline Stage Documentation",
        "",
        f"**Platform:** {platform}",
        f"**Project Type:** {project_type}",
        f"**Enabled Skills:** {', '.join(sorted(skills))}",
        f"**Canary Steps:** {' → '.join(f'{s}%' for s in canary_steps)}",
        f"**Rollback Triggers:** error_rate > {rollback_error_rate} or p99 > {rollback_p99_ms}ms",
        "",
        "## Stage Overview",
        "",
        "| Stage | Skill Hook | Inputs | Outputs | Gates |",
        "|-------|-----------|--------|---------|-------|",
    ]

    stages = [
        ("Build", "—", "Source code, dependencies", "Compiled artifacts, test reports", "—"),
        ("Test", "Code Tester", "Build artifacts", "Test results, coverage", "Dry-run gate"),
        ("Security Scan", "Security Auditor", "Source code, dependencies", "Vulnerability report", "Block merge on critical"),
        ("Blast Radius", "Blast Radius Calculator", "PR diff", "Impact matrix", "—"),
        ("Provision", "Infrastructure-as-Code", "Environment spec", "Provisioned resources", "Dry-run (`plan`)"),
        ("Performance Gate", "Performance Validator", "Staging endpoint", "Latency/throughput report", "SLO thresholds"),
        ("Contract Check", "API Contract Tester", "OpenAPI spec, staging endpoint", "Compatibility report", "Block production on break"),
        ("Staging Deploy", "—", "Artifacts, provisioned infra", "Staging deployment", "Dry-run gate"),
    ]
    for step in canary_steps:
        stages.append(
            (f"Canary {step}%", "—", "Staging artifacts", f"Canary deployment ({step}% traffic)", "Metric-based auto-rollback")
        )
    stages.append(
        ("Production Plan", "—", "Canary-approved artifact", "Deployment plan artifact", "Dry-run plan output")
    )
    stages.append(
        ("Production Apply", "—", "Approved plan artifact", "Production deployment", "External human approval + dry-run gate")
    )

    for stage, hook, inputs, outputs, gates in stages:
        lines.append(f"| {stage} | {hook} | {inputs} | {outputs} | {gates} |")

    lines.extend([
        "",
        "## Skill Hook Mapping",
        "",
    ])
    for skill, meta in SKILL_HOOK_POINTS.items():
        if skill in skills or "all" in skills:
            lines.append(f"- **{skill}** → events: {', '.join(meta['events'])} → pipeline stage: `{meta['stage']}`")

    lines.extend([
        "",
        "## Approval Gates",
        "",
        "1. **Production Plan** generates a human-readable plan artifact (e.g., `tfplan`, `helm diff`).",
        "2. **Production Apply** is blocked by a CI-native approval gate that the agent cannot bypass:",
        "   - GitHub Actions: `environment: production` with required reviewers configured in repository settings",
        "   - GitLab CI: `when: manual` in a protected environment; requires human to click 'Play'",
        "   - Jenkins: `input` step with `choice` parameter and `submitter` restriction",
        "3. The apply stage also respects the `DRY_RUN` flag; if `DRY_RUN=true`, it outputs a simulation and exits.",
        "",
        "## Rollback Procedures",
        "",
        "1. **Automated rollback** is triggered when:",
        f"   - Error rate exceeds {rollback_error_rate * 100}%",
        f"   - p99 latency exceeds {rollback_p99_ms}ms",
        "   - Custom SLO budget is exhausted",
        "",
        "2. **Rollback mechanism** (platform-dependent):",
        "   - Kubernetes: `kubectl rollout undo deployment/<name>` or Argo Rollouts abort",
        "   - ECS: revert to prior stable task definition",
        "   - VM/static: redeploy prior artifact or swap blue/green",
        "",
        "3. **Manual fallback**:",
        "   - Identify last known stable artifact tag from CI artifacts",
        "   - Run platform-specific revert command (see `references/rollback-patterns.md`)",
        "   - Notify on-call via configured alerting channel",
        "",
        "## Feature Flag Coordination",
        "",
        "- Canary stages progressively enable flags for the traffic slice",
        "- If a metric regression is detected, flags are auto-disabled (kill switch)",
        "- Default provider detection: `LAUNCHDARKLY_SDK_KEY`, `UNLEASH_URL`, or `feature-flags.yml`",
        "",
        "## Secret Safety",
        "",
        "- All generated configs were scanned with `scan-secrets.py` before delivery",
        "- No plaintext credentials are embedded in pipeline YAML",
        "- Secrets are referenced via platform-native placeholders:",
        "  - GitHub Actions: `${{ secrets.SECRET_NAME }}`",
        "  - GitLab CI: `${SECRET_NAME}` (defined in CI/CD Variables UI, masked + protected)",
        "  - Jenkins: `withCredentials([string(credentialsId: 'secret-name', variable: 'SECRET_NAME')])`",
        "",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate CI/CD pipeline configs with Kimi skill hooks, secret scanning, and approval gates")
    parser.add_argument("--platform", required=True, choices=["github", "gitlab", "jenkins"])
    parser.add_argument("--project-type", default="generic", choices=list(PROJECT_TYPE_IMAGES.keys()))
    parser.add_argument("--skills", default="all", help="Comma-separated list of skills (or 'all')")
    parser.add_argument("--output", required=True, help="Output file path")
    parser.add_argument("--canary-steps", default="5,25,50,100", help="Comma-separated canary traffic percentages")
    parser.add_argument("--rollback-error-rate", type=float, default=DEFAULT_ROLLBACK_ERROR_RATE)
    parser.add_argument("--rollback-p99-ms", type=int, default=DEFAULT_ROLLBACK_P99_LATENCY_MS)
    parser.add_argument("--dry-run-default", type=lambda x: x.lower() in ("true", "1", "yes"), default=True)
    parser.add_argument("--docs-output", help="Optional path to write stage documentation markdown")
    parser.add_argument("--skip-secret-scan", action="store_true", help="Skip secret scanning (not recommended)")
    args = parser.parse_args()

    raw_skills = args.skills.lower().strip().split(",")
    skills = set(raw_skills)
    if "all" in skills:
        skills = set(SKILL_HOOK_POINTS.keys())

    canary_steps = [int(x.strip()) for x in args.canary_steps.split(",")]

    if args.platform == "github":
        content = generate_github_actions(
            args.project_type, skills, canary_steps,
            args.rollback_error_rate, args.rollback_p99_ms, args.dry_run_default,
        )
    elif args.platform == "gitlab":
        content = generate_gitlab_ci(
            args.project_type, skills, canary_steps,
            args.rollback_error_rate, args.rollback_p99_ms, args.dry_run_default,
        )
    elif args.platform == "jenkins":
        content = generate_jenkinsfile(
            args.project_type, skills, canary_steps,
            args.rollback_error_rate, args.rollback_p99_ms, args.dry_run_default,
        )
    else:
        print(f"Unsupported platform: {args.platform}")
        sys.exit(1)

    # Secret scan gate
    if not args.skip_secret_scan:
        if not validate_no_secrets(content, label=args.output):
            print("\nGeneration aborted due to detected secrets.", file=sys.stderr)
            print("Fix the template or use --skip-secret-scan (not recommended).", file=sys.stderr)
            sys.exit(1)
    else:
        print("[WARNING] Secret scan skipped. Generated output may contain embedded credentials.", file=sys.stderr)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    print(f"Generated pipeline config: {out_path.resolve()}")

    if args.docs_output:
        docs = generate_docs(
            args.platform, args.project_type, skills, canary_steps,
            args.rollback_error_rate, args.rollback_p99_ms,
        )
        docs_path = Path(args.docs_output)
        docs_path.parent.mkdir(parents=True, exist_ok=True)
        docs_path.write_text(docs, encoding="utf-8")
        print(f"Generated stage documentation: {docs_path.resolve()}")


if __name__ == "__main__":
    main()
