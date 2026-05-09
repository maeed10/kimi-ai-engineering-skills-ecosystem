# Refactoring Engine — Codemod Patterns & Reference

Extended reference for AST transformation tools, patterns, and implementation details.

---

## Tool Deep-Dive Reference

### jscodeshift (JavaScript/TypeScript)

**Architecture**: Parse → Transform → Print. Built on Recast for style preservation.

**Basic codemod structure**:
```javascript
export default function transform(file, { jscodeshift: j }) {
  const root = j(file.source);
  root.find(j.ImportDeclaration)
    .filter(path => path.value.source.value === 'old-lib')
    .forEach(path => {
      path.value.source.value = 'new-lib';
    });
  return root.toSource();
}
```

**Key APIs**:
- `j(file.source)` — parse into AST
- `root.find(j.NodeType)` — query nodes
- `root.replaceWith()` — replace matched nodes
- `root.toSource()` — print back to code with preserved style

**Best practices**:
- Compose smaller transforms via higher-order functions (`createTransformer()`)
- Each transform standalone, testable, independently tuneable
- Test on real codebase subset before full run

### LibCST (Python)

**Architecture**: Concrete Syntax Tree preserving all whitespace and comments.

**Basic transformer**:
```python
import libcst as cst

class RenameTransformer(cst.CSTTransformer):
    def leave_Name(self, original_node, updated_node):
        if updated_node.value == "old_name":
            return updated_node.with_changes(value="new_name")
        return updated_node

tree = cst.parse_module(source)
modified = tree.visit(RenameTransformer())
print(modified.code)
```

**Key APIs**:
- `cst.parse_module(source)` — parse into CST
- `CSTTransformer` — base class for transformations
- `leave_*` methods — modify nodes during traversal
- `with_changes()` — immutable node updates

### Comby (Multi-Language)

**Structural matching syntax**:
```
comby 'import :[lib] from "old-lib"' 'import :[lib] from "new-lib"' -in-place
```

**Key features**:
- `:[hole]` wildcards match arbitrary balanced code
- Respects balanced brackets automatically
- Skips comments and strings unless specified
- Dry-run by default; `-in-place` required for mutation

### ast-grep (Multi-Language)

**Rule-based search and replace**:
```yaml
id: replace-deprecated
language: python
rule:
  pattern: old_function($$$ARGS)
fix: new_function($$$ARGS)
```

**Key features**:
- Rust-based performance
- Tree-sitter grammar support for 40+ languages
- Interactive editing mode for review

### OpenRewrite (Java / Multi-Language)

**Recipe structure**:
```java
public class MigrateToSpringBoot3 extends Recipe {
    @Override
    public String getDisplayName() {
        return "Migrate to Spring Boot 3";
    }
    // Define visitors for specific transformations
}
```

**Key features**:
- Lossless Semantic Tree (LST) — compiler-accurate representation
- 5,000+ community recipes for Java, Python, YAML, Terraform
- Recipes composable and testable

---

## Codemod Composition Patterns

### Pattern 1: Chained Transforms
Build higher-order functions that chain smaller, reusable transforms:
```javascript
const createTransformer = (...transforms) => (file, api) => {
  return transforms.reduce((src, t) => t({ ...api, source: src }), file.source);
};
```

### Pattern 2: Conditional Application
Apply transforms only when preconditions pass:
```javascript
if (root.find(j.ImportDeclaration).filter(matchesOldLib).size() > 0) {
  applyTransform(root);
}
```

### Pattern 3: Import Variation Handling
Handle all import styles in one codemod:
- Default import: `import React from 'react'`
- Named import: `import { useState } from 'react'`
- Renamed import: `import { useState as useSt } from 'react'`
- Namespace import: `import * as React from 'react'`

### Pattern 4: Test Mock Synchronization
When transforming library APIs, update corresponding test mocks in the same codemod run.

---

## Validation Pyramid Implementation

### Level 1: Compilation
- JS/TS: `tsc --noEmit`
- Python: `mypy --strict`
- Java: `mvn compile` / `gradle build`

### Level 2: Unit Tests
- JS: `jest --coverage --changedSince=main`
- Python: `pytest --cov --cov-report=xml`
- Java: `mvn test`

### Level 3: Linting
- JS: `eslint --max-warnings=0`
- Python: `black --check && flake8 && isort --check`

### Level 4: Static Analysis
- Security: `bandit` (Python), `eslint-security` (JS), `SonarQube` (multi)
- Dependency: `oasdiff` for API drift, `pip-audit` / `npm audit`

### Level 5: Integration
- Run contract tests (see api-contract-tester skill)
- Database migration dry-run
- End-to-end smoke tests

---

## Multi-Agent Orchestration Patterns

### State Machine
```
Plan → [Architect reviews] → Analyze → [Blast Radius OK?] → Transform → [Dry-run approved?] → Validate → [All green?] → Commit → [PR merged?] → Done
         ↓ No                        ↓ No                      ↓ No
      Re-plan                    Escalate human          Rollback batch
```

### Shared State Format
Persist to JSON/YAML files, not conversational memory:
```yaml
migration_state:
  id: "express-4-to-5-2026-04"
  current_phase: "Transform"
  current_batch: 3
  total_batches: 8
  files_touched: 127
  validation_status:
    compile: PASS
    unit_tests: PASS
    lint: PASS
    static_analysis: PASS
    integration: PENDING
  rollback_tag: "pre-express-migration"
```

---

## Safety Checklist (Pre-Flight)

- [ ] Blast Radius analysis complete and reviewed
- [ ] Tool selected and tested on representative file subset
- [ ] Dry-run mode configured and producing readable diffs
- [ ] Backup branch created from current HEAD
- [ ] Validation pyramid scripts executable and passing on current code
- [ ] Rollback procedure documented and tested in staging
- [ ] Batch sizing ≤ 50 files or one module boundary
- [ ] Human reviewer assigned for ambiguous semantic changes
- [ ] CI/CD pipeline configured to run validation on PR
- [ ] Stakeholders notified of migration window

---

**Reference version:** 1.0 | **Last updated:** April 2026
