# Cross-Skill Integration Matrix

Reference document for the Skill Orchestrator's optional cross-skill integration hooks. Each hook bridges two skills in a workflow, passing data from an upstream skill (trigger phase) to a downstream skill (action). All hooks are **disabled by default** and require explicit user opt-in.

---

## Hook Registry

### Hook 1: `graphify->brownfield` (Graph Index)

| Attribute | Detail |
|---|---|
| **Trigger** | Phase 1 (UNDERSTAND) completes — Graphify has built the knowledge graph |
| **Action** | Brownfield Intelligence indexes graph nodes into SQLite for deterministic querying |
| **Prerequisites** | Graphify has generated a valid graph (tree-sitter parse succeeded) |
| **Downstream skill** | `brownfield-intelligence` (~8,400 tokens) |

**What it does step-by-step**:
1. Takes Graphify's node/edge output (modules, functions, imports)
2. Feeds it into Brownfield's SQLite indexer (`schema.sql` + `insert_nodes.py`)
3. Produces a queryable SQLite database at `.kimi/brownfield.db`

**Safety constraints**:
- Never overwrites an existing database without confirmation (append mode preferred)
- Read-only on source files — only writes to the `.kimi/` directory
- Validates graph structure before indexing (rejects empty or cyclic-only graphs)

**Token cost estimate**: ~500 additional tokens for the hook bridge logic (on top of Brownfield's ~8,400 token skill load). Total: ~8,900 tokens.

**Failure modes & fallbacks**:
| Failure | Fallback |
|---|---|
| Graph has zero valid nodes | Report: "Graph empty; indexing skipped. Run Graphify with --verbose?" |
| SQLite write permission denied | Report: "Cannot write to .kimi/. Check permissions." Offer manual path. |
| Brownfield schema version mismatch | Report: "Schema vX expected, vY found. Run brownfield --migrate?" |

---

### Hook 2: `blast-radius->code-tester` (Characterization Tests)

| Attribute | Detail |
|---|---|
| **Trigger** | Phase 3 (ASSESS) completes — impact analysis has identified affected modules |
| **Action** | Code Tester auto-generates characterization tests for modules flagged as high-impact |
| **Prerequisites** | Blast Radius has produced an impact report with module list; Code Tester source context loaded |
| **Downstream skill** | `code-tester` (~5,800 tokens) |

**What it does step-by-step**:
1. Extracts the "affected modules" list from Blast Radius output
2. For each high-impact (score > 0.7) module, generates a characterization test that captures current behavior
3. Writes tests to `test_characterization_<module>.py` in the project's test directory
4. Reports: "Generated N characterization tests for modules: [list]. Review before running?"

**Safety constraints**:
- **Never auto-executes generated tests** — writes files only, user runs them
- **Never modifies production code** — writes only to test files
- Appends "AUTO-GENERATED" header to every test file so team knows origin
- Characterization tests are pinned (assert exact current output) — they will fail if behavior changes, which is intentional

**Token cost estimate**: ~800 additional tokens for test template generation (on top of Code Tester's ~5,800). Total: ~6,600 tokens per affected module batch.

**Failure modes & fallbacks**:
| Failure | Fallback |
|---|---|
| No modules scored > 0.7 | Report: "No high-impact modules found. Characterization tests not needed." |
| Source-under-test not loaded | Report: "Cannot generate tests — source context missing. Load source first." |
| Test directory not found | Report: "No test/ or tests/ directory found. Suggest path?" |
| Generated test has syntax error | Report syntax error; do not write file; offer to regenerate |

---

### Hook 3: `architecture->boundary` (Boundary Compliance Check)

| Attribute | Detail |
|---|---|
| **Trigger** | Phase 2 (PLAN) completes — Architecture Design has produced a design document |
| **Action** | Boundary Enforcer validates the new design against existing bounded context constraints |
| **Prerequisites** | Architecture Design has produced PLAN.md; Boundary Enforcer has DDD boundaries configured |
| **Downstream skill** | `boundary-enforcer` (~5,500 tokens) |

**What it does step-by-step**:
1. Parses the new design document for module/service boundaries and cross-domain references
2. Compares each proposed import/call against the boundary enforcement rules (allowed_crossings.csv or equivalent)
3. Flags any violations: "Proposed import X→Y crosses bounded context Z. Rule: [rule]. Severity: [block/warn]."
4. Reports a compliance score (0-100%) and lists violations with severity

**Safety constraints**:
- **Hard blocks are reported, not enforced** by the hook — the Orchestrator logs them for human decision
- **Never modifies the design document** — read-only analysis
- If Boundary Enforcer would hard-block, the hook reports: "BLOCK detected at [location]. Manual review required."
- The user can override with `/override boundary` but the hook logs the override

**Token cost estimate**: ~600 additional tokens for boundary cross-referencing (on top of Boundary Enforcer's ~5,500). Total: ~6,100 tokens.

**Failure modes & fallbacks**:
| Failure | Fallback |
|---|---|
| No boundary rules configured | Report: "Boundary rules not found. Run boundary-enforcer --init?" |
| Design document parse error | Report: "Cannot parse PLAN.md. Is it valid Markdown?" |
| Circular dependency detected | Report: "Circular reference found in design. Manual review required." |

---

### Hook 4: `code-tester->style` (Commit Message Suggestion)

| Attribute | Detail |
|---|---|
| **Trigger** | Phase 4 (EXECUTE) completes — all tests have passed |
| **Action** | Style Enforcer suggests a commit message summarizing the test work |
| **Prerequisites** | Code Tester reports passing tests; git diff is available (or test file changes are tracked) |
| **Downstream skill** | `style-enforcer` (~6,200 tokens) |

**What it does step-by-step**:
1. Reads the test output summary (tests added, modified, passing count)
2. Reads the team's commit convention from git log analysis
3. Generates a commit message in the team's style: type(scope): summary
4. Presents: "Suggested commit message: [message]. Use this? Edit? Skip?"

**Safety constraints**:
- **Never auto-commits** — suggestion only, user must confirm
- **Never reads beyond test output and git log** — no source code analysis for commit messages
- If Style Enforcer is already active, the hook reuses the loaded skill (no additional token cost)

**Token cost estimate**: ~0 additional tokens if Style Enforcer already loaded; ~400 tokens if loaded fresh (skill budget impact: ~6,200). Style Enforcer may already be active in Phase 5 (DELIVER), in which case this hook is effectively free.

**Failure modes & fallbacks**:
| Failure | Fallback |
|---|---|
| Tests not all passing | Report: "Tests not passing. Commit message suggestion deferred until all green." |
| No git repo detected | Report: "Not a git repository. Commit message suggestion skipped." |
| Team convention unclear | Report: "Could not determine team convention. Suggest: `test(scope): description`" |

---

## Global Hook Behavior

### Opt-in Model
- All hooks default to **disabled**
- Enable individually: user confirms at offer time
- Enable permanently: `/hooks enable <hook-name>`
- Disable: `/hooks disable <hook-name>`
- List: `/hooks` shows all hooks with enabled/disabled status

### Budget Safety
- Each hook reports its **token cost before loading** the downstream skill
- If the hook would exceed the 25K ceiling, it is **deferred, not skipped silently**
- The Orchestrator offers: "Hook [name] requires [X] tokens but budget has [Y]. Defer to next phase?"

### Safety Invariants (Non-Negotiable)
1. **Never auto-merge** — no hook ever merges code, commits, or PRs
2. **Never auto-delete** — no hook deletes files, branches, or data
3. **Never auto-push** — no hook pushes to remotes
4. **Never override hard blocks** — Boundary Enforcer hard blocks are reported, not bypassed
5. **Never cascade failures** — a failing hook is isolated; it does not break the parent phase

### Hook Failure Isolation
If a hook fails (downstream skill errors, budget exceeded, prerequisite missing):
1. The hook is marked FAILED in the session log
2. The parent phase continues normally
3. The user is informed: "Hook [name] failed: [reason]. Phase continues."
4. The hook can be retried manually with `/hook retry <name>`

---

**Document version:** 1.0 | **Part of:** skill-orchestrator v2.0
