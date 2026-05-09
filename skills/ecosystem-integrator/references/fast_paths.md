# Fast Paths — Shortcut Commands for Experienced Users

Fast paths are user-facing shortcuts that bypass the discovery flow. They STILL route through `skill-orchestrator` and pass through all L0 safety gates. No fast path bypasses any safety layer.

## Command Patterns

### Code & Development
| User Says | Routes to | Phase |
|-----------|-----------|-------|
| "Generate a FastAPI endpoint" | dev-code-generator | EXECUTE |
| "Create a React component" | dev-code-generator | EXECUTE |
| "Write tests for utils.py" | dev-test-automation | VALIDATE |
| "Debug this stack trace" | dev-debug-assistant | VALIDATE |
| "Refactor this function" | refactoring-engine | EXECUTE |

### CI/CD & Deployment
| User Says | Routes to | Phase |
|-----------|-----------|-------|
| "Set up GitHub Actions" | dev-ci-cd-pipeline | DELIVER |
| "Deploy to staging" | canary-orchestrator + dev-ci-cd-pipeline | DELIVER |
| "Build Docker image" | dev-container-builder | EXECUTE |

### Security
| User Says | Routes to | Phase |
|-----------|-----------|-------|
| "Scan for vulnerabilities" | dev-security-scanner | VALIDATE |
| "Check dependencies" | dev-dependency-manager | VALIDATE |

### Operations
| User Says | Routes to | Phase |
|-----------|-----------|-------|
| "Set up monitoring" | dev-observability-setup | DELIVER |
| "Profile performance" | dev-performance-profiler | VALIDATE |
| "Respond to incident" | dev-incident-responder | VALIDATE |

### API & Design
| User Says | Routes to | Phase |
|-----------|-----------|-------|
| "Design REST API" | dev-api-designer | PLAN |
| "Create database migration" | dev-database-migrator | EXECUTE |

### Infrastructure & Docs
| User Says | Routes to | Phase |
|-----------|-----------|-------|
| "Generate Terraform config" | dev-infrastructure-coder | PLAN |
| "Generate README" | dev-docs-maintainer | DELIVER |
| "Review this PR" | dev-git-workflow | VALIDATE |

### Ecosystem Status
| User Says | Routes to | Phase |
|-----------|-----------|-------|
| "Check system health" | ecosystem-integrator (health report) | ANY |

## Important: All Fast Paths Are Still Gated

Every fast path:
1. Routes through `skill-orchestrator` (automatic)
2. Passes through `policy-engine` validation (every tool call)
3. Runs in `sandbox-executor` (all code execution)
4. Has outputs scanned by `ipi-defender` (all external content)
5. Has artifacts verified by `artifact-verifier` (phase transitions)
6. Is recorded in `policy-attestation-layer` (audit trail)

The fast path only skips the DISCOVERY step. It never skips any safety gate.

## Auto-Detect Logic (used by ecosystem-integrator)

The integrator uses these keywords to map user intent to the orchestrator:

```
"generate" OR "create" OR "write" OR "scaffold" → dev-code-generator
"test" OR "coverage" OR "pytest" OR "jest" → dev-test-automation
"debug" OR "error" OR "trace" OR "fail" → dev-debug-assistant
"CI" OR "CD" OR "pipeline" OR "deploy" → dev-ci-cd-pipeline
"Docker" OR "container" → dev-container-builder
"security" OR "vulnerability" OR "CVE" → dev-security-scanner
"profile" OR "performance" OR "slow" → dev-performance-profiler
"monitor" OR "metrics" OR "dashboard" → dev-observability-setup
"API" OR "endpoint" → dev-api-designer
"database" OR "migration" OR "schema" → dev-database-migrator
"Terraform" OR "infrastructure" → dev-infrastructure-coder
"docs" OR "README" → dev-docs-maintainer
"git" OR "commit" OR "branch" OR "PR" → dev-git-workflow
```

This mapping is sent to `skill-orchestrator` which returns the canonical routing. The integrator presents the result to the user.
