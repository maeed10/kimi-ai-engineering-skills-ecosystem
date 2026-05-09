# Kimi AI Engineering Skills Ecosystem

> **Version:** 4.2.1  
> **License:** MIT

A modular AI agent framework for software engineering built on the Kimi Code CLI skill system. It replaces unstructured code generation with a governed pipeline: tasks flow through seven phases, every tool call is audited against machine-readable policies, and all execution happens inside isolated sandboxes.

This is not a product from a company. It is a single research project that grew from a handful of skills into a 100-skill ecosystem with policy engines, phase controllers, sandbox orchestration, and adversarial test suites. The architecture is documented, the rules are codified, and the tests pass — but it has not undergone independent security audit, and some documented features exist as design specifications rather than fully automated implementations.

---

## What This Actually Does

When you ask the agent to "refactor this codebase" or "add a caching layer," the ecosystem does not just prompt an LLM and paste the output. It:

1. **Decomposes** the request into atomic tasks via `spec-decomposer`
2. **Validates** architectural decisions via `trade-off-analyzer` (with mandatory alternatives)
3. **Calculates blast radius** before touching any file
4. **Enforces** 148 safety rules via `policy-engine` before every tool call
5. **Runs** all code generation, tests, and security scans inside Docker sandboxes
6. **Verifies** output integrity via `artifact-verifier`
7. **Logs** every decision with hash-chained attestation for audit

This is architectural intent, not magic. The skills are defined by `SKILL.md` files that the orchestrator interprets. Some skills have full automation scripts; others define behavior that the LLM follows via structured prompting.

---

## Repository Structure

```
.
├── skills/                  # 100 skill definitions
│   ├── skill-orchestrator/       # Task routing and context management
│   ├── policy-engine/            # Rule enforcement + attestation
│   ├── phase-controller/         # 7-phase finite state machine
│   ├── tool-execution-gateway/   # Tool call validation + IPC
│   ├── sandbox-executor/         # Docker isolation + resource governance
│   ├── ipi-defender/             # Indirect prompt injection defense
│   ├── memory-guard/             # Trust-scored memory integrity
│   ├── drift-monitor/            # Behavioral anomaly detection
│   ├── graphify/                 # Codebase knowledge graph generation
│   ├── code-tester/              # Automated test generation
│   ├── architecture-design/      # Pattern selection + ADR generation
│   ├── trade-off-analyzer/       # Weighted decision matrices
│   └── ... 88 more
├── policy/                  # 10 JSON policy files (148 rules)
│   ├── manifest.json             # Integrity registry + SHA-256 hashes
│   ├── execution.json            # Resource limits, sandbox profiles
│   ├── secrets.json              # Secret handling + entropy detection
│   ├── filesystem.json           # Path restrictions
│   ├── network.json              # Network access controls
│   ├── mcp.json                  # MCP server governance
│   ├── gemini.json               # External model routing
│   ├── tool_calls.json           # Tool execution constraints
│   ├── skill_registry.json       # Skill lifecycle rules
│   └── telemetry.json            # Telemetry collection policy
├── k8s-sandboxes/           # Kubernetes manifests for sandbox isolation
├── scripts/                 # Daemon starters + MCP wrappers
├── config/                  # Example configuration files
├── tests/                   # pytest validation suite
└── docs/                    # Operational documentation
```

---

## Numbers That Are Real

| Metric | Value | Notes |
|--------|-------|-------|
| Skills | 100 | All have `SKILL.md`; ~40 have automation scripts |
| Policy Rules | 148 | 59 ALWAYS, 89 NEVER; 31 CRITICAL severity |
| Test Cases | 199 | All passing (`pytest`) |
| Pipeline Phases | 7 | INGEST → UNDERSTAND → PLAN → ASSESS → EXECUTE → DELIVER → VALIDATE → REMEMBER |
| Attack Cases | 100+ | Across 10 categories in adversarial test suite |
| K8s Manifests | 9 | Namespace, RBAC, network policies, seccomp |

---

## The Safety Architecture

The ecosystem attempts defense-in-depth through five overlapping gates:

**Gate 0 — Content Sanitization:** `ipi-defender` scans all external content before LLM ingestion. Uses pattern matching, Shannon entropy analysis, embedding divergence detection, and behavioral probes. Quarantines content exceeding threat threshold.

**Gate 1 — Policy Validation:** `policy-engine` intercepts every proposed tool call against 148 deterministic rules. Rules are machine-readable JSON, not natural-language prompts. Enforcement is external to the LLM.

**Gate 2 — Phase Control:** `phase-controller` enforces a finite state machine. The LLM cannot skip, jump, or retroactively complete phases. Every transition requires hash-verified completion artifacts.

**Gate 3 — Skill Lifecycle:** `skill-registry` controls which skills are ACTIVE. Only active skills enter the prompt context. Skills can be loaded, unloaded, or purged based on task requirements.

**Gate 4 — Execution Isolation:** `sandbox-executor` runs all subprocesses inside Docker containers with network isolation, read-only source mounts, writable tmpfs at `/tmp`, and tiered resource profiles (light / standard / heavy).

These are **architectural designs with passing tests**, not independently verified security guarantees.

---

## Known Limitations (Honest)

1. **Self-Integrity Bootstrap Problem.** The policy engine computes its own SHA-256 at startup and compares against `manifest.json`. If an attacker replaces the script, they can replace the manifest too. The Ed25519 signature helps, but the verification logic lives in the replaceable file. This is a known limitation of local attestation.

2. **Not All Skills Are Fully Automated.** The 100 skills are documented capabilities. Some (like `code-tester`, `validate_config.py`) have full scripts. Others (like `architecture-design`, `trade-off-analyzer`) define structured behavior that the orchestrator and LLM execute collaboratively.

3. **Cost-Tier Routing Is Experimental.** The `multi-model-router` can dispatch tasks to Gemini CLI for cost savings, but the economic model has not been validated at production scale.

4. **Adversarial Tests Validate Design, Not Security.** The 100+ attack cases test whether the *design* handles known vectors. They do not constitute formal security proof or penetration testing.

5. **Memory Persistence Is Single-User.** The four-layer memory architecture and Obsidian vault integration work for one user on one machine. Federated memory across instances is documented but not stress-tested.

6. **Daemon Deployment Varies.** The policy engine, phase controller, and tool gateway can run as standalone processes (with Unix sockets) or as libraries within the CLI. The architecture prefers separation, but the exact topology depends on your environment.

---

## Quick Start

### Prerequisites

- Python 3.10+
- Docker (for sandbox execution)
- Node.js 18+ (optional, for Gemini CLI routing)

### Validate The Installation

```bash
git clone https://github.com/YOUR_ORG/kimi-ai-engineering-skills-ecosystem.git
cd kimi-ai-engineering-skills-ecosystem

# Validate all 148 policy rules
python tests/validate_config.py
# Expected: ALL CHECKS PASSED (148 rules, 10 files)

# Run the test suite
pytest tests/ -v
# Expected: 199 passed
```

### Configure

```bash
# Copy examples — never commit real credentials
cp config/config.toml.example ~/.kimi/config.toml
cp config/mcp.json.example ~/.kimi/mcp.json

# Add your API keys to ~/.kimi/config.toml
# Add your MCP server configuration to ~/.kimi/mcp.json
```

### Start Core Services

```powershell
# Windows PowerShell
.\scripts\start-daemons.ps1

# Or start individually
python skills/policy-engine/scripts/policy-engine-server.py `
  --policy-dir ./policy `
  --manifest ./policy/manifest.json `
  --port 9100 --host 127.0.0.1
```

---

## Kubernetes Sandbox Deployment

```bash
kubectl apply -f k8s-sandboxes/01-namespace.yaml
kubectl apply -f k8s-sandboxes/02-rbac.yaml
kubectl apply -f k8s-sandboxes/03-network-policies.yaml
kubectl apply -f k8s-sandboxes/04-configmaps.yaml
kubectl apply -f k8s-sandboxes/05-sandbox-job-template.yaml
kubectl apply -f k8s-sandboxes/06-resource-governance.yaml
```

Features: dedicated namespace, deny-all network policy, non-root execution, read-only root filesystem, resource quotas, seccomp-default profile.

---

## Observability

Structured JSONL logging is built into every daemon:

| Log | Content |
|-----|---------|
| `logs/policy-engine/policy-audit.jsonl` | Every allow/block/escalate decision |
| `logs/gateway/gateway-audit.jsonl` | Every tool call with hash-chain linkage |
| `logs/phase-controller/transitions.jsonl` | Hash-verified phase transitions |
| `logs/sandbox-executor.log` | Container lifecycle + resource usage |

Monitoring scripts (`scripts/kimi-alert-monitor.ps1` and `.py`) implement 11 alerting rules covering block-rate spikes, health-check failures, secret leakage detection, and hash-chain breaks.

---

## Documentation

- [`docs/ECOSYSTEM-OPERATIONS.md`](docs/ECOSYSTEM-OPERATIONS.md) — 1700+ line operational guide covering daemon setup, health checks, incident response, the complete rule registry, and observability configuration.
- Each `skills/<name>/SKILL.md` contains triggers, dependencies, inputs/outputs, safety boundaries, and usage examples.

---

## Contributing

This project welcomes contributions, security reviews, and independent validation.

1. Fork the repository
2. Create a feature branch
3. Ensure `validate_config.py` passes
4. Open a pull request

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

If you discover a security issue, please open an issue rather than exploiting it. This is a defensive security project.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

Individual skills may reference their own licenses within their `SKILL.md` files.

---

## What This Is Not

- **Not a company product.** There is no paid support, no SLA, and no roadmap beyond what the community builds.
- **Not a security framework.** The safety mechanisms are documented architecture with passing tests. They have not undergone independent third-party security audit.
- **Not a replacement for engineering judgment.** The ecosystem assists with code generation, architecture review, and testing. Human oversight is required.
- **Not magic.** It is a structured layer of governance, validation, and isolation around LLM code generation. The hard parts of software engineering remain hard.
