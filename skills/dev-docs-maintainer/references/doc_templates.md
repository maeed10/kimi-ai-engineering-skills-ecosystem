# Documentation Templates

Reference file containing fill-in-the-blank templates for common developer documentation artifacts. Use as starting points and customize per project.

---

## README Template

```markdown
# {{PROJECT_NAME}}

{{ONE_LINE_DESCRIPTION}}

[![CI](https://img.shields.io/github/actions/workflow/status/{{OWNER}}/{{REPO}}/ci.yml?branch=main)](https://github.com/{{OWNER}}/{{REPO}}/actions)
[![Version](https://img.shields.io/github/v/release/{{OWNER}}/{{REPO}})](https://github.com/{{OWNER}}/{{REPO}}/releases)
[![License](https://img.shields.io/github/license/{{OWNER}}/{{REPO}})](LICENSE)

## Overview

{{2-3_SENTENCES_DESCRIBING_WHAT_IT_DOES_AND_WHY}}

## Features

- {{Feature 1}}
- {{Feature 2}}
- {{Feature 3}}

## Installation

### Requirements

- {{Language/runtime}} {{version}}
- {{Dependency}} {{version}}

### Install

```bash
{{COPY_PASTE_INSTALL_COMMAND}}
```

## Quick Start

```{{language}}
{{MINIMAL_WORKING_EXAMPLE}}
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `{{VAR}}` | `{{default}}` | {{Description}} |

## Project Structure

```
{{PROJECT_NAME}}/
├── src/               # Source code
├── tests/             # Test suite
├── docs/              # Documentation
├── scripts/           # Automation scripts
└── README.md          # This file
```

## API Documentation

See [API_REFERENCE.md](docs/API_REFERENCE.md) or run `{{DOC_GENERATION_COMMAND}}`.

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions and coding standards.

## License

{{LICENSE_NAME}} — see [LICENSE](LICENSE) for details.
```

### Fill-in Prompts
- `PROJECT_NAME`: repo or package name, Title Case or sentence case per convention
- `ONE_LINE_DESCRIPTION`: under 120 characters, suitable for package registry
- `OWNER/REPO`: GitHub/GitLab owner and repository slug
- `COPY_PASTE_INSTALL_COMMAND`: exact command from package manager (npm/pip/cargo/go get)
- `MINIMAL_WORKING_EXAMPLE`: runnable code that demonstrates core value in <15 lines

---

## API Documentation Template

```markdown
# API Reference

Generated from source comments. Last updated: {{DATE}}.

## Table of Contents

- [{{ModuleA}}](#modulea)
- [{{ModuleB}}](#moduleb)

---

## {{ModuleA}}

### `{{functionName}}({{params}}) → {{returnType}}`

{{DESCRIPTION}}

**Parameters**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `{{param}}` | `{{type}}` | `{{default}}` | {{Description}} |

**Returns**

| Type | Description |
|------|-------------|
| `{{type}}` | {{Description}} |

**Throws**

| Error | Condition |
|-------|-----------|
| `{{ErrorType}}` | {{When it throws}} |

**Example**

```{{language}}
{{CODE_EXAMPLE}}
```

**See also**
- [{{relatedFunction}}](#relatedfunction)

---

## {{ModuleB}}

### `{{className}}`

{{Class description}}

#### Constructor: `new {{className}}({{params}})`

{{Constructor description}}

#### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `{{method}}({{params}})` | `{{type}}` | {{Description}} |

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `{{prop}}` | `{{type}}` | {{Description}} |
```

### Fill-in Prompts
- Group functions by module or namespace; use anchored headings for TOC linking
- Include at least one runnable example per public function
- Mark deprecated functions with `> **Deprecated since {{version}}.** {{Migration note}}`
- Add `Since: {{version}}` for APIs introduced after initial release

---

## Changelog Template (Keep a Changelog format)

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- {{New feature description}} ([#{{PR}}](https://github.com/{{OWNER}}/{{REPO}}/pull/{{PR}}))

### Changed
- {{Change description}} ([#{{PR}}])

### Deprecated
- {{Deprecation description}} ([#{{PR}}])

### Removed
- {{Removal description}} ([#{{PR}}])

### Fixed
- {{Fix description}} ([#{{PR}}])

### Security
- {{Security fix description}} ([#{{PR}}])

## [{{VERSION}}] - {{YYYY-MM-DD}}

### Added
- {{Feature}} ([#{{PR}}])

### Fixed
- {{Fix}} ([#{{PR}}])

## [{{PREVIOUS_VERSION}}] - {{YYYY-MM-DD}}

...

[Unreleased]: https://github.com/{{OWNER}}/{{REPO}}/compare/v{{VERSION}}...HEAD
[{{VERSION}}]: https://github.com/{{OWNER}}/{{REPO}}/compare/v{{PREVIOUS_VERSION}}...v{{VERSION}}
```

### Fill-in Prompts
- Always keep an `Unreleased` section at the top
- Link every entry to a PR or commit SHA
- Write for consumers of the project, not implementers
- Group breaking changes under `Changed` and add `**BREAKING**` prefix with migration note

---

## ADR Template

```markdown
# ADR-{{NUMBER}}: {{TITLE}}

- Status: {{proposed | accepted | deprecated | superseded by ADR-NNNN}}
- Date: {{YYYY-MM-DD}}
- Deciders: {{@githubHandles or team names}}
- Tags: {{#topic #topic}}

## Context and Problem Statement

{{Describe the problem or opportunity. What forces are at play?}}

## Decision Drivers

- {{Driver 1: constraint, requirement, or goal}}
- {{Driver 2}}
- {{Driver 3}}

## Considered Options

### Option 1: {{Name}}

{{Description}}

- **Pros**: {{...}}
- **Cons**: {{...}}

### Option 2: {{Name}}

{{Description}}

- **Pros**: {{...}}
- **Cons**: {{...}}

### Option 3: {{Name}}

{{Description}}

- **Pros**: {{...}}
- **Cons**: {{...}}

## Decision Outcome

**Chosen option: {{Option N}}**

{{Rationale. Why it best satisfies the decision drivers.}}

### Positive Consequences

- {{...}}
- {{...}}

### Negative Consequences / Risks

- {{...}}
- {{...}}

## Mitigation

{{How risks or negative consequences will be addressed.}}

## Links

- {{Related ADR}}
- {{RFC or design doc}}
- {{Tracking issue}}
```

### Fill-in Prompts
- Use sequential numbering (0001, 0002, ...) for sortability
- File name: `docs/adr/{{NUMBER}}-{{short-kebab-title}}.md`
- Keep to 1-2 pages; link to deeper docs if elaboration needed
- Update status rather than editing body text once accepted

---

## Contribution Guide Template

```markdown
# Contributing to {{PROJECT_NAME}}

Thank you for your interest! This document guides you through setup, development workflow, and coding standards.

## Getting Started

### Prerequisites

- {{runtime}} {{version}}
- {{package manager}} {{version}}
- Git {{version}}

### Setup

```bash
git clone https://github.com/{{OWNER}}/{{REPO}}.git
cd {{REPO}}
{{INSTALL_COMMAND}}
```

### Verify

```bash
{{TEST_COMMAND}}
```

All tests should pass before you open a PR.

## Making Changes

1. **Create a branch**: `git checkout -b {{BRANCH_NAMING_CONVENTION}}`
2. **Make edits**: follow coding standards below
3. **Add tests**: cover new logic and edge cases
4. **Update docs**: README, API reference, or ADRs if needed
5. **Run checks locally**: lint, typecheck, tests
6. **Commit**: use [Conventional Commits](https://www.conventionalcommits.org/)
   - `feat: add user authentication`
   - `fix: correct pagination offset`
   - `docs: update API examples`
   - `refactor: simplify query builder`
7. **Push**: `git push origin {{branch}}`

## Submitting Changes

- Open a Pull Request against `main`
- Fill out the PR template
- Ensure CI passes (lint, test, build)
- Request review from maintainers
- Address feedback and squash fix commits if requested

## Coding Standards

### Style

- {{Formatter config}}: `{{CONFIG_FILE}}`
- Run `{{LINT_COMMAND}}` before committing

### Tests

- Minimum coverage: {{XX}}%
- Unit tests for logic; integration tests for endpoints
- Naming: `describe('{{module}}', () => { it('should {{behavior}}', ...) })`

### Types / Contracts

- {{Type system rules}}
- Public APIs must be documented with doc comments

### Documentation

- Update `README.md` if behavior changes for end users
- Update `CHANGELOG.md` under `Unreleased`
- Add ADR for architectural decisions

## Reporting Issues

Use the [issue templates](https://github.com/{{OWNER}}/{{REPO}}/issues/new/choose). Include:

- Steps to reproduce
- Expected vs actual behavior
- Environment (OS, runtime version)
- Minimal code sample or repository

## Questions?

Open a [Discussion](https://github.com/{{OWNER}}/{{REPO}}/discussions) or reach out in {{CHANNEL}}.
```

### Fill-in Prompts
- Replace `BRANCH_NAMING_CONVENTION` with project standard (e.g., `feat/description`, `issue-123-description`)
- Include exact commands for install, lint, test, and typecheck
- Add PR template path if repo uses `.github/pull_request_template.md`
- Define "definition of done" explicitly

---

## Release Notes Template (per version)

```markdown
## Release {{VERSION}} — {{TITLE}}

**Date**: {{YYYY-MM-DD}}

### Highlights

- {{Bullet for end users / stakeholders}}
- {{Bullet}}

### New Features

- {{Feature}} ([#{{PR}}](...))

### Improvements

- {{Improvement}} ([#{{PR}}])

### Bug Fixes

- {{Fix}} ([#{{PR}}])

### Breaking Changes

- {{Change}} ([#{{PR}}])
  **Migration**: {{instructions}}

### Deprecations

- {{Deprecation}} ([#{{PR}}])
  **Replacement**: {{alternative}}

### Contributors

Thanks to {{@contributor1}}, {{@contributor2}} for this release.
```

### Fill-in Prompts
- Write highlights for non-technical stakeholders (product, management)
- Always include migration instructions for breaking changes
- Credit external contributors by handle

---

## Quick Reference: Template Selection

| Need | Template Section |
|------|-----------------|
| New project README | README Template |
| API reference from code | API Documentation Template |
| Preparing a release | Changelog Template + Release Notes Template |
| Recording a tech decision | ADR Template |
| Onboarding contributors | Contribution Guide Template |
