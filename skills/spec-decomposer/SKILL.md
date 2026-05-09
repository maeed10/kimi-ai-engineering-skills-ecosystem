---
name: spec-decomposer
description: Reads SPEC.md/PRD.md/REQUIREMENTS.md and decomposes them into atomic, trackable task nodes in the Obsidian vault. Triggers when a markdown spec file is detected, when the user asks to "break down requirements", "create tasks from spec", or before Architecture Design work begins. Bridges high-level requirements to executable engineering work. v4.0 adds mandatory Gherkin/BDD mode, non-functional requirement inference, ADR cross-reference, and mandatory field validation.
---

# Spec Decomposer

## What it does
Reads specification documents and decomposes them into atomic, trackable task nodes stored in the Obsidian vault. Maintains bidirectional traceability from spec sections through requirements to individual tasks, and exports structured requirements for downstream engineering skills. **v4.0** introduces Gherkin/BDD acceptance-criteria parsing, non-functional requirement inference from context, Architecture Decision Record (ADR) cross-reference, and mandatory field validation to prevent low-quality decompositions.

## When to use
- User drops a SPEC.md, PRD.md, or REQUIREMENTS.md file into context
- User asks to "break down" or "decompose" requirements into tasks
- Before invoking Architecture Design — spec-decomposer feeds it structured requirements + ADR constraints
- Before sprint planning when a living task tree is needed
- When acceptance criteria need to be converted to test case stubs (including Gherkin scenarios)
- When requirements have changed and the task tree needs updating
- When dependencies between features need to be mapped before scheduling
- When a spec lacks explicit non-functional requirements and inferred NFRs must be surfaced

## Key capabilities

### Core capabilities (retained from v3.x)
- **Spec ingestion** — Parse markdown specs; extract functional/non-functional requirements, user stories, acceptance criteria, constraints
- **Atomic decomposition** — Break requirements into task tree levels: spec → epics → stories → tasks → subtasks
- **Dependency mapping** — Identify ordering constraints, data dependencies, external API/blocker dependencies
- **Status tracking** — Track implementation state: `pending → in-progress → blocked → review → complete`
- **Export interfaces** — Feed Architecture Design, CI/CD Integrator, Code Tester, and Self-Reviewer with scoped data

### v4.0 new capabilities

#### 1. Gherkin / BDD acceptance criteria mode
- Parse `Given/When/Then` blocks from spec files (native `.feature` files and markdown-embedded Gherkin)
- Extract acceptance criteria as structured test stubs with trace IDs
- Validate every Scenario has at least one Given, one When, and one Then
- Flag specs missing acceptance criteria as **"ambiguous — requires clarification"**
- Emit Gherkin scenarios into task node frontmatter (`gherkin_scenario`) and test stub files
- Map Gherkin scenario IDs to task acceptance criteria for end-to-end traceability

#### 2. Non-functional requirement (NFR) inference
- Infer performance requirements from context (e.g., "auth module" → latency < 100ms, token refresh < 50ms)
- Infer security requirements from context (e.g., "payment" → PCI-DSS SAQ-A, end-to-end encryption, audit logging)
- Infer scalability requirements from user count mentions (e.g., "1M DAU" → horizontal scaling, read replicas, CDN)
- Append inferred NFRs to `definition_of_done` and `inferred_nfrs` frontmatter arrays
- Log all inferences in `spec-index.md` for human review; never silently drop them

#### 3. ADR cross-reference
- Read Architecture Design ADRs from a specified directory (`--adr-dir`)
- Extract constraints, consequences, and NFRs from each ADR
- Flag tasks that violate ADR constraints (e.g., task mentions MongoDB but ADR-003 forbids NoSQL for financial data)
- Propagate ADR non-functionals into task `definition_of_done` and `acceptance_criteria`
- Populate `adr_references` on every affected task node for navigation

#### 4. Mandatory fields validation
- Every task node at story level or below **MUST** have:
  - `description` (non-empty body)
  - `acceptance_criteria` (at least one item)
  - `definition_of_done` (at least one item)
  - `estimate` (non-empty, ≤ 8h for tasks, ≥ 15min for subtasks)
- Reject decomposition if any required field is missing: node is set to `status: blocked`, `flagged: true`, and error is appended to `validation_errors`
- `--strict` CLI flag exits with error code 3 if any mandatory field violation or ADR violation is detected

## Workflow

### 1. Ingest
Read the spec document (SPEC.md, PRD.md, or REQUIREMENTS.md). Identify sections, headers, and requirement blocks.
- Parse frontmatter if present (priority, target date, owner, version)
- Extract numbered requirements, user stories, and Gherkin scenarios
- Capture non-functional requirements (performance, security, reliability) verbatim

### 2. Extract Gherkin / BDD acceptance criteria
Run the Gherkin parser (`scripts/gherkin-parser.py`) over the spec:
- Pull `Scenario` / `Scenario Outline` / `Background` blocks from markdown fences or inline text
- Validate each scenario has Given + When + Then
- Emit `AcceptanceCriterion` objects with `id`, `text`, `gherkin`, `testable`, and `validation_errors`
- If **zero** acceptance criteria are found, flag the spec as ambiguous and STOP decomposition

### 3. Infer non-functional requirements
Apply the NFR inference engine to every spec section:
- Match keywords against context patterns (auth → security/performance; payment → PCI-DSS; real-time → scalability)
- Produce `inferred_nfrs: ["[INFERRED] Latency < 100ms at p99", "[INFERRED] OWASP ASVS Level 2"]`
- Attach inferred NFRs to the requirement and log them in `spec-index.md`
- **Never silently drop** inferred NFRs; always surface them for human confirmation

### 4. Load ADR constraints
If `--adr-dir` is provided:
- Read every `*.md` file in the directory as an ADR
- Parse frontmatter or body sections for Decision, Constraints, Consequences, and NFRs
- Store as `ADRConstraint` objects with `id`, `title`, `decision`, `constraints`, `consequences`, `nfrs`

### 5. Validate
For every requirement, verify it has:
- A clear, testable acceptance criterion (or Gherkin scenario)
- A stated or inferable "definition of done"
- No direct conflict with another requirement in the same spec
- **At least one acceptance criterion** extracted or inferred; otherwise flag as ambiguous

If a requirement fails validation, flag it in the `ambiguities` block and STOP decomposition on that branch until clarified. Do not guess.

### 6. Decompose
Build a task tree with four levels:
| Level | Scope | Estimate heuristic |
|-------|-------|-------------------|
| Epic | Major feature area or deliverable | Days–weeks |
| Story | User-facing increment | Hours–days |
| Task | Engineering unit | 1–8 hours |
| Subtask | Implementation step | 15 min–2 hours |

Rules:
- A Task MUST NOT exceed one work day. If it does, split it.
- A Subtask MUST represent at least 15 minutes of work. If smaller, roll it into its parent Task.
- Every node MUST inherit the source requirement ID and spec section heading.
- **Every story/task/subtask MUST have ≥1 acceptance criterion.** If not, the node is blocked.

### 7. Cross-reference ADRs
After initial decomposition:
- Run `validate_adr_compliance(nodes, adrs)` to detect keyword-based violations
- Run `propagate_adr_nfrs_to_tasks(nodes, adrs)` to inject ADR-derived acceptance criteria into `definition_of_done`
- Populate `adr_references` and `validation_errors` on affected nodes

### 8. Validate mandatory fields
Run `validate_mandatory_fields(nodes)` to enforce:
- `description` / `body` non-empty
- `acceptance_criteria` length ≥ 1
- `definition_of_done` length ≥ 1
- `estimate` non-empty and within bounds

Any failure sets `status: blocked`, `flagged: true`, and appends to `ambiguities`.

### 9. Map dependencies
For each node, determine:
- **Hard dependencies** — Cannot start until predecessor is complete (data model → API → UI)
- **Soft dependencies** — Can proceed in parallel but needs coordination (shared component consumers)
- **External blockers** — Third-party APIs, legal review, vendor provisioning
- **Parallel branches** — Group nodes that share no hard dependencies for sprint scheduling

Store dependency edges as `depends_on: [node-id-1, node-id-2]`.

### 10. Write task nodes
Write each node to `vault/tasks/` as an Obsidian markdown file with YAML frontmatter.

Frontmatter schema (v4.0):
```yaml
---
id: REQ-001-T03
type: task | subtask | story | epic
parent: REQ-001
title: Implement user authentication endpoint
status: pending | in-progress | blocked | review | complete
priority: P0 | P1 | P2 | P3
source_spec: SPEC.md
source_section: "## 3. Authentication"
source_requirement: REQ-001
acceptance_criteria: ["AC-1", "AC-2"]
definition_of_done:
  - Unit tests pass
  - API documented in OpenAPI
  - Security scan clean
dependencies: []
blocks: []
assignee: ""
estimate: 4h
gherkin_scenario: |
  Given a registered user with valid credentials
  When they POST /api/v1/login
  Then they receive a 200 response with a JWT access token
adr_references: ["ADR-001", "ADR-003"]
inferred_nfrs:
  - "[INFERRED] Latency < 100ms at p99"
  - "[INFERRED] OWASP ASVS Level 2 compliance"
security_tags: ["owasp", "rate-limit", "encryption"]
flagged: false
---
```

### 11. Generate test stubs
For each acceptance criterion, emit a test stub file to `vault/tests/`:
- Filename: `{node-id}-{ac-id}.test.md`
- Contents: criterion text, Gherkin scenario (if available), suggested test type (unit | integration | e2e), and a placeholder assertion

### 12. Export summaries
Produce structured exports for downstream skills:
- **Architecture Design**: `{ "requirements": [...], "constraints": [...], "priority_order": [...], "adr_violations": [...], "inferred_nfrs": [...] }`
- **CI/CD Integrator**: `{ "pipeline_stages": [...], "deployment_order": [...], "blocked_nodes": [...] }`
- **Code Tester**: `{ "test_targets": [...], "coverage_gaps": [...], "ambiguous_requirements": [...] }`
- **Self-Reviewer**: `{ "review_scope": [...], "completion_criteria": [...], "mandatory_field_violations": [...] }`

## Safety highlights

### Existing rules (retained)
- ALWAYS validate acceptance criteria are testable before creating any task node. Untestable criteria must be flagged and returned for rewrite.
- ALWAYS flag ambiguous requirements (missing acceptance criteria, conflicting constraints, unspecified scope) before decomposition. Never infer silently.
- ALWAYS maintain bidirectional traceability: every task node MUST reference its source spec file, section heading, and requirement ID.
- ALWAYS include a definition of done for every task node at the story level or below. Nodes without one are rejected.
- ALWAYS preserve non-functional requirements as first-class nodes. Do not drop performance, security, or reliability requirements.
- ALWAYS write a `spec-index.md` at `vault/tasks/` that maps spec sections to epic nodes for navigation.

- NEVER decompose a spec without first running the validation step. No exceptions.
- NEVER create task nodes for requirements that lack clear acceptance criteria or a definition of done.
- NEVER silently drop requirements that do not fit the decomposition template. Flag them as `unclassified` and request human decision.
- NEVER over-decompose simple tasks below 15 minutes of work. A subtask must represent meaningful, reviewable progress.
- NEVER emit task nodes without dependency edges when dependencies are detectable from the spec text.
- NEVER mutate previously written task nodes during a re-decomposition without logging the change in the node's history section.

### v4.0 new safety rules (mandatory)
- **NEVER** decompose a spec without extracting at least one acceptance criterion per task. If a task cannot be linked to an AC, block it and flag for clarification.
- **NEVER** silently drop non-functional requirements (performance, security, compliance). Infer from context if absent in spec, log the inference, and append to `definition_of_done`.
- **ALWAYS** cross-reference with Architecture Design ADRs before accepting decomposition. Load ADRs from `--adr-dir`, validate compliance, and propagate ADR NFRs into task acceptance criteria.
- **ALWAYS** flag ambiguous requirements for human clarification rather than guessing. If Gherkin parsing yields zero scenarios, NFR inference is uncertain, or ADR compliance cannot be determined, mark the node `flagged: true` and `status: blocked`.

## Integration with other skills

| Downstream skill | What is provided | Format |
|-----------------|------------------|--------|
| Architecture Design | Structured requirements list + constraints + priority order + ADR violations + inferred NFRs | JSON export; prerequisite for ADR creation |
| CI/CD Integrator | Pipeline stage ordering based on dependency map + blocked nodes | `{deployment_order}` list |
| Code Tester | Acceptance criteria → test case stubs (including Gherkin scenarios) | `vault/tests/*.test.md` files |
| Self-Reviewer | Task completion criteria + review scope + mandatory field violations | `{review_scope}` per epic |
| Performance-Validator | NFR nodes with performance targets embedded + inferred latency/throughput specs | Tagged `type: nfr` nodes |
| Security-Auditor | Security requirement nodes + acceptance criteria + `security_tags` | Tagged `type: security` nodes |
| Gherkin-Parser (internal) | Standalone acceptance-criteria extraction and validation | Called during Ingest step |

## References
- `references/task-templates.md` — Full YAML schema and Obsidian markdown templates for epic, story, task, subtask, NFR, security, and flagged nodes (v4.0)

## Scripts
- `scripts/decompose-spec.py` — Parses markdown spec files, runs Gherkin extraction, NFR inference, ADR cross-reference, validates requirements, builds the task tree with dependencies, enforces mandatory fields, and emits Obsidian-ready markdown files to `vault/tasks/` (v4.0)
- `scripts/gherkin-parser.py` — Standalone Gherkin / BDD acceptance-criteria parser. Extracts `Given/When/Then` blocks, validates scenario completeness, flags ambiguous specs, and outputs structured criteria for consumption by `decompose-spec.py` (v4.0)
