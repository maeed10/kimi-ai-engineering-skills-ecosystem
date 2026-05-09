---
name: api-version-guard
description: API backward compatibility validation skill that detects breaking changes in OpenAPI specs using OpenAPI-diff and contract testing. Use when modifying APIs, before deploying API changes, during VALIDATE for API-related work, or when architecture-evolution proposes API modifications. Gates breaking changes behind HITL approval and generates consumer migration guides.
---

# API Version Guard

Validate OpenAPI spec changes for backward compatibility before they propagate to consumers.

## Workflow Decision Tree

```
New or modified OpenAPI spec detected?
├── YES: Is there a previous version to compare against?
│   ├── YES: Run OpenAPI-diff comparison
│   │   ├── Breaking changes found? → HITL gate + migration guide
│   │   ├── Only non-breaking changes? → Log, proceed
│   │   └── No changes? → Skip
│   └── NO: Establish baseline, skip compatibility check
└── NO: Skip this skill
```

## Step 1: Detect and Load Specs

Locate the current and previous OpenAPI specs:

1. **Current spec**: The modified `.yaml`/`.json` file in the working tree
2. **Previous spec**: From `git show HEAD:<path>` or a tagged baseline in `refs/baselines/openapi/<service-name>.yaml`

If no previous spec exists, establish the current as baseline and skip to Step 4.

## Step 2: Run Compatibility Check

Execute `scripts/check_compatibility.py`:

```bash
python scripts/check_compatibility.py \
  --old <previous-spec> \
  --new <current-spec> \
  --output compatibility-report.json
```

The script wraps OpenAPI-diff and classifies each change per `references/breaking_change_catalog.md`.

## Step 3: Evaluate Results

Parse `compatibility-report.json`:

| Field | Rule |
|---|---|
| `breaking` array non-empty | **BLOCK** — require HITL approval |
| `breaking` empty, `nonBreaking` non-empty | **ALLOW** — log changes, proceed |
| Both empty | **SKIP** — no API changes detected |

### HITL Gate for Breaking Changes

When breaking changes are detected:

1. **STOP** the deployment pipeline
2. Generate a migration guide (see Step 4)
3. Present to operator:
   - Summary of breaking changes
   - Affected consumers (from code search for endpoint references)
   - Migration guide draft
4. **Require explicit approval** to proceed with a major version bump

## Step 4: Generate Compatibility Report

Produce `COMPATIBILITY_REPORT.md` in the service directory:

```markdown
# API Compatibility Report: <service-name>

| | |
|---|---|
| Base Version | `<old-version>` |
| New Version | `<new-version>` |
| Date | `<ISO-8601>` |
| Status | `BREAKING` / `NON_BREAKING` / `NO_CHANGE` |

## Breaking Changes (REQUIRE MAJOR VERSION BUMP)

| # | Change | Severity | Migration Required |
|---|--------|----------|-------------------|
| 1 | `DELETE /api/v1/users/{id}` | Critical | Use `PATCH /api/v2/users/{id}/status` |

## Non-Breaking Changes

| # | Change | Impact |
|---|--------|--------|
| 1 | Added `GET /api/v1/users/search` | New capability |

## Consumer Migration Guide

### From <old-version> to <new-version>

1. **[Change description]**
   - Before: `<code example>`
   - After: `<code example>`
   - Timeline: Consumers have 30 days to migrate
```

## Step 5: Version Bump Rules

| Change Type | Version Action | Consumer Notification |
|---|---|---|
| Breaking | MAJOR (`v1` → `v2`) | Required: migration guide + 30-day notice |
| Non-breaking additive | MINOR (`v1.0` → `v1.1`) | Optional: changelog entry |
| Bug fix / docs | PATCH (`v1.0.0` → `v1.0.1`) | None |

## Breaking vs Non-Breaking Reference

Load `references/breaking_change_catalog.md` when classifying changes.

Quick reference:

**Always Breaking:**
- Removing an endpoint
- Removing a required request parameter
- Changing a parameter type
- Removing/renaming a response field
- Changing response status codes
- Adding a new required request header/body field

**Always Non-Breaking:**
- Adding a new endpoint
- Adding an optional parameter
- Adding a response field
- Adding a new enum value (unless `enum` is strictly validated downstream)
- Relaxing constraints (e.g., `maxLength` increase)

**Conditionally Breaking:**
- Changing default values (breaking if consumers rely on implicit behavior)
- Adding `required` to existing request body fields
- Narrowing constraints (e.g., reducing `maxLength`, adding `pattern`)

## Integration with Other Skills

| Skill | Integration Point |
|---|---|
| `api-contract-tester` | Feed compatibility report into contract test generation |
| `architecture-evolution` | When proposing API changes, run this skill first |
| `deployment-guardian` | Block deployment if compatibility check fails HITL gate |
| `security-review` | Breaking changes in auth/endpoints trigger security review |

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | No changes or only non-breaking changes |
| 1 | Breaking changes detected — HITL required |
| 2 | Tool error (invalid spec, missing dependency) |