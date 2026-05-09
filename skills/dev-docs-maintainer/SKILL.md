---
name: dev-docs-maintainer
description: Developer-facing documentation maintenance skill that generates READMEs, API docs, architecture diagrams, changelogs, and contribution guides. Use when creating project docs, maintaining changelogs, generating diagrams, or syncing docs with code changes. Supports Mermaid, PlantUML, conventional commits, and multi-format export.
---

# Dev Docs Maintainer

## Overview

A documentation maintenance skill for everyday software engineering in Kimi CLI. Generates, updates, and synchronizes project documentation including READMEs, API docs, architecture diagrams, changelogs, and contribution guides. Detects code-to-doc drift and proposes updates to keep documentation accurate as code evolves.

## Workflow Decision Tree

```
What do you need?
├── New project setup or README missing
│   └── → README Generation
├── Code comments exist, API docs missing/outdated
│   └── → API Documentation Extraction
├── Need to visualize system structure or data flow
│   └── → Architecture Diagram Generation
├── Release planned or changelog outdated
│   └── → Changelog Maintenance
├── Major technical decision made
│   └── → ADR Documentation
├── Contributing process unclear or onboarding friction
│   └── → Contribution Guide Generation
├── Docs exist but may be stale after code changes
│   └── → Code-to-Doc Sync Check
└── Docs need conversion for another platform
    └── → Multi-Format Export
```

## README Generation

### When to Use
- Bootstrapping a new repository
- Existing README is incomplete, outdated, or missing key sections
- Project has evolved and README no longer reflects reality

### Process
1. **Analyze project structure**: detect language, build system, entry points, test setup
2. **Extract metadata**: package.json, pyproject.toml, Cargo.toml, go.mod, etc.
3. **Identify badges**: CI status, version, license, code coverage
4. **Write sections**:
   - Title + one-line description
   - Badges row
   - Features / Overview
   - Installation (per environment)
   - Quick Start / Usage
   - API / Configuration (if applicable)
   - Project Structure
   - Contributing link
   - License
5. **Apply conventions**: keep under 150 lines where possible, anchor links for long docs

### Tips
- Use `tree`-style structure blocks for project layout
- Include copy-paste ready install and run commands
- Add troubleshooting subsection for common gotchas
- Link to generated API docs instead of duplicating reference material

## API Documentation

### When to Use
- Generating docs from JSDoc, TSDoc, Python docstrings, Go doc comments, Rust rustdoc, Java Javadoc
- Updating existing API reference after function/endpoint changes
- Creating OpenAPI/Swagger summaries from code annotations

### Process
1. **Scan source files** for doc comments (language-aware)
2. **Parse annotations**: `@param`, `@returns`, `@throws`, `@example`, `@deprecated`, `@since`
3. **Build symbol tree**: modules → classes → methods/functions → properties
4. **Cross-link references**: resolve internal `{@link}` or backtick mentions
5. **Generate output**: Markdown tables or HTML with anchored headings
6. **Flag undocumented public APIs** for coverage gaps

### Language-Specific Extraction

| Language | Comment Style | Key Annotations |
|----------|--------------|-----------------|
| JavaScript/TypeScript | `/** ... */` | `@param`, `@returns`, `@example`, `@deprecated` |
| Python | `"""..."""` | `:param`, `:return`, `:raises`, `:type` |
| Go | `// ...` | Function comment precedes declaration |
| Rust | `/// ...` | `#[doc = "..."]`, `/// # Examples` |
| Java | `/** ... */` | `@param`, `@return`, `@throws`, `@since` |

### Tips
- Group overloaded functions under a single heading with variant tables
- Include runnable code examples fenced with correct language tag
- Mark deprecated APIs with strikethrough and migration notes
- Sort public API surface alphabetically unless logical grouping is stronger

## Architecture Diagrams

### When to Use
- Onboarding docs that need system overview visuals
- Design reviews requiring diagram representation
- Documenting data flow, request lifecycle, or deployment topology
- Entity-relationship models for database schemas

### Supported Formats
- **Mermaid**: GitHub/GitLab native rendering, Markdown embeddable
- **PlantUML**: richer diagram types, requires renderer but better layout control

### Diagram Types by Use Case

| Goal | Mermaid Type | PlantUML Type |
|------|-------------|---------------|
| Service topology | `graph` / `flowchart` | `component` / `deployment` |
| Request lifecycle | `sequence` | `sequence` |
| Database schema | `erDiagram` | `class` (entity style) |
| State machine | `stateDiagram` | `state` |
| CI/CD pipeline | `graph` (DAG style) | `activity` |
| Class hierarchy | `classDiagram` | `class` |

### Process
1. **Identify scope**: single service, multi-service interaction, or full system
2. **List nodes**: services, databases, queues, external APIs, clients
3. **Map edges**: sync/async, protocol, direction
4. **Annotate**: add notes for critical paths, failure modes, or latency expectations
5. **Generate**: output fenced Mermaid or PlantUML block
6. **Validate**: ensure all nodes connect and no orphaned components exist

### Tips
- Keep diagrams under 30 nodes for readability; split into multiple diagrams if needed
- Use consistent naming: service names match repo names or DNS names
- Color-code by environment or criticality (Mermaid `classDef`)
- Add diagram source as a file in `docs/diagrams/` so it versions with code

## Changelog Maintenance

### When to Use
- Preparing a release and need release notes
- Changelog has not been updated since last release
- Converting commit history into human-readable changes

### Process
1. **Detect versioning scheme**: SemVer, CalVer, or custom
2. **Collect changes since last tag**:
   - Option A: parse conventional commits (`feat:`, `fix:`, `BREAKING CHANGE:`)
   - Option B: summarize PR descriptions / merge commits
   - Option C: manual categorization with user input
3. **Categorize**:
   - Added
   - Changed
   - Deprecated
   - Removed
   - Fixed
   - Security
4. **Format**: Keep a Changelog 1.1.0 style or project-specific format
5. **Prepend** to `CHANGELOG.md` or append to release draft

### Conventional Commit Mapping

```
feat:     → Added
fix:      → Fixed
docs:     → Changed (documentation)
style:    → Changed (formatting)
refactor: → Changed
perf:     → Changed (performance)
test:     → Changed (testing)
chore:    → Changed (maintenance)
BREAKING CHANGE: → highlight at top with migration notes
```

### Tips
- Link each entry to PR/commit SHA for traceability
- Write for users, not developers: "Added dark mode toggle" not "Added ThemeProvider"
- Group breaking changes prominently with migration examples
- Maintain an `Unreleased` section at the top for ongoing work

## ADR Documentation

### When to Use
- After making a significant technology choice (framework, database, protocol)
- When rejecting an alternative that may be revisited later
- Onboarding context for why the codebase looks the way it does

### Process
1. **Assign number**: sequential (e.g., `0001-use-postgres.md`)
2. **Record context**: problem statement, constraints, drivers
3. **List options**: alternatives considered, pros/cons table
4. **State decision**: the chosen approach and rationale
5. **Describe consequences**: positive, negative, risks, mitigation
6. **Set status**: `proposed` → `accepted` → `deprecated` → `superseded`
7. **Store**: `docs/adr/` or `adr/` at repo root

### ADR Template Fields
- Title, Date, Status
- Context and Problem Statement
- Decision Drivers
- Considered Options
- Decision Outcome
- Positive Consequences
- Negative Consequences / Risks
- Mitigation
- Links (related ADRs, RFCs, issues)

### Tips
- Keep ADRs concise (2 pages max); link to deeper design docs if needed
- Update status rather than editing content once accepted
- Reference superseded ADRs in newer ones to maintain decision chains
- Use for reversible decisions; irreversible ones may need RFC process

## Code-to-Doc Sync

### When to Use
- After a large refactor, rename, or deletion
- CI check fails because docs reference removed APIs
- Routine maintenance to detect doc drift

### Process
1. **Diff check**: compare current file tree and public API surface against README / API docs
2. **Reference scan**: grep docs for function names, paths, config keys
3. **Flag stale entries**:
   - Functions documented but no longer exported
   - File paths changed in docs but not in code
   - Config examples using old schema
   - Dependency versions in install instructions mismatched with lockfile
4. **Propose patches**: inline edits or TODO comments with `<!-- TODO(doc): ... -->`
5. **Coverage report**: ratio of documented public symbols to total public symbols

### Common Drift Patterns

| Code Change | Doc Impact |
|-------------|-----------|
| Function renamed | Update all references and examples |
| Signature changed | Update parameter tables and type annotations |
| Module moved | Update import paths and project structure diagrams |
| Dependency added/removed | Update install instructions and requirements lists |
| New public API added | Add new section or flag for documentation |
| Config schema changed | Update example configs and environment variable tables |

### Tips
- Run sync checks before releases, not just after
- Pin doc examples to tagged versions to reduce permalink drift
- Automate badge and version string updates where possible
- Maintain a `docs/TODO.md` for manual doc debt tracking

## Contribution Guide Generation

### When to Use
- Open-sourcing a project or expanding a team
- Contributor onboarding friction reported
- Coding standards not written down or inconsistently enforced

### Process
1. **Setup**: clone, install dependencies, run tests, pre-commit hooks
2. **Workflow**: branch naming, commit message conventions, PR template
3. **Standards**: lint rules, formatter, test coverage minimums, typing requirements
4. **Review process**: reviewer assignment, CI gates, merge requirements
5. **Release process**: versioning, tagging, changelog updates
6. **Communication**: issue templates, discussion channels, Code of Conduct reference

### Generated Sections
- Getting Started (environment requirements)
- Making Changes (branch, edit, test, commit)
- Submitting Changes (PR template, checks)
- Coding Standards (style, tests, docs required)
- Reporting Issues (bug report template)
- Questions & Support

### Tips
- Include copy-paste ready commands for setup and test
- Link to lint/style configs (`.eslintrc`, `pyproject.toml`, etc.)
- Provide example commit messages for conventional commit learners
- Define "definition of done" for PRs explicitly

## Multi-Format Export

### When to Use
- Docs need to be published to Confluence, Notion, or a static site
- PDF required for offline distribution or compliance
- HTML needed for branded hosting

### Supported Formats and Transformations

| Target | Strategy | Notes |
|--------|----------|-------|
| Markdown (default) | Identity / lint with `mdformat` | Native for most dev platforms |
| HTML | `markdown` + template / `mkdocs` | Add custom CSS for branding |
| PDF | `pandoc` + LaTeX or `mdpdf` | Best for release snapshots |
| Confluence | Convert to XHTML with `confluence-glue` macros | Handle Mermaid as attached images |
| Notion | Import Markdown via API | Flatten nested headings if needed |
| OpenAPI | Aggregate endpoint docs into `openapi.yaml` | From code annotations or existing specs |

### Process
1. **Select output format** and validate toolchain availability
2. **Resolve relative links** for target platform (anchor behavior differs)
3. **Handle diagrams**: Mermaid can render to SVG/PNG for non-Markdown targets
4. **Apply template**: header, footer, CSS, or branding tokens
5. **Generate and validate**: check for broken internal links or missing assets
6. **Deliver**: write to `dist/docs/` or publish via API

### Tips
- Keep source of truth in Markdown; export is a build step
- Use CI to auto-publish docs on merge to main
- For Confluence/Notion, consider incremental sync (only changed pages)
- Embed diagrams as files rather than platform-specific embeds for portability

## Resources

### scripts/
`scripts/generate_docs.py` — Executable script for scanning codebases, extracting doc comments, building symbol trees, and generating Markdown or HTML documentation. Can be run standalone or invoked by the skill.

### references/
- `references/doc_templates.md` — Templates for README, API doc, changelog, ADR, and contribution guides with boilerplate and fill-in prompts.
- `references/diagram_patterns.md` — Common Mermaid and PlantUML patterns for architecture, sequence, ER, class, and state diagrams with copy-pasteable starting points.

### assets/
Not used by this skill. Documentation artifacts are generated on demand and output to the user's project directory.
