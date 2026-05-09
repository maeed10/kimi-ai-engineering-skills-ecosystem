---
name: policy-version-manager
description: Independent semantic versioning, changelog, and migration management for all policy files. Use when modifying rules, deploying policy updates, rolling back changes, or auditing policy state during incidents. Supports per-file semantic versioning, rollback without orchestrator restart, and compatibility matrices.
---

# Policy Version Manager

## Overview

Manages independent semantic versioning for all policy files (`filesystem.json`, `network.json`, `execution.json`, etc.) with changelogs, migration guides, rollback procedures, and compatibility matrices. This skill treats policy as code: every rule change is versioned, reviewed, and reversible without touching the orchestrator.

## When to Use This Skill

- **Modifying policy rules** in the `policy/` directory — any addition, removal, or edit of an ALWAYS/NEVER rule
- **Deploying policy updates** to production — version bump, changelog update, compatibility check
- **Unblocking tool calls** — when a policy change inadvertently blocks legitimate execution
- **Rolling back policy changes** — revert to a previous policy version without restarting the orchestrator
- **Auditing incidents** — determine which policy version was active during a specific incident

## Workflow Decision Tree

```
Are you modifying a policy file?
├── YES → Is the change breaking (alters existing behavior)?
│   ├── YES → MAJOR bump → Write migration guide → Update compatibility matrix
│   └── NO  → Is it a new rule or capability?
│       ├── YES → MINOR bump
│       └── NO  → PATCH bump (description, fix, comment)
├── NO  → Are you rolling back?
│   ├── YES → Select target version → Validate compatibility → Hot-swap policy
│   └── NO  → Are you auditing an incident?
│       ├── YES → Read policy CHANGELOG for incident timestamp → Report active version
│       └── NO  → Generate diff or review compatibility matrix
```

## Semantic Versioning Rules

Each policy file (`filesystem.json`, `network.json`, `execution.json`, etc.) carries its own independent version in `MAJOR.MINOR.PATCH` format.

| Component | Trigger | Examples |
|-----------|---------|----------|
| **MAJOR** | Breaking behavior change — existing tool calls that previously succeeded now fail, or vice versa | Removing a NEVER rule, tightening an ALWAYS rule that was permissive, renaming a rule key that tooling depends on |
| **MINOR** | New rule added — new capability or restriction that does not affect existing executions | Adding a new NEVER rule for a newly blacklisted domain, adding a new ALWAYS rule for a new tool category |
| **PATCH** | Non-behavioral change — description fixes, comment updates, formatting, typo corrections | Clarifying a rule description, fixing JSON indentation, adding rationale comments |

**Version metadata lives in each policy file as:**
```json
{
  "_meta": {
    "version": "2.1.3",
    "updated_at": "2025-01-15T09:32:00Z",
    "updated_by": "agent-id-or-human"
  }
}
```

## Changelog Format

Every policy file must have a sidecar `CHANGELOG.md` in the same directory with this structure:

```markdown
# Changelog: filesystem.json

## [2.1.3] - 2025-01-15
### Fixed
- PATCH: Clarified description of `filesystem.read.home_dir` rule to specify exact path

## [2.1.2] - 2025-01-12
### Added
- MINOR: Added `filesystem.write.temp_dir` ALWAYS rule for `/tmp/agent-work/`

## [2.0.0] - 2025-01-10
### Changed
- MAJOR: `filesystem.read.etc` changed from ALWAYS to NEVER — blocks `/etc/passwd` reads
### Migration
- See `migrations/filesystem-1.x-to-2.0.0.md`
```

## Migration Procedures

### For MAJOR Version Bumps

1. **Identify all affected tool calls** by running `policy_diff.py` against the previous version
2. **Write migration guide** using `references/migration_template.md`
3. **Update compatibility matrix** — declare which orchestrator/ecosystem versions support this policy
4. **Stage and test** in a non-production environment
5. **Hot-swap procedure**: update the symlink or config pointer; no orchestrator restart required

### Hot-Swap Rollback (No Restart)

```bash
# 1. Identify current active version
cat policy/active/filesystem.json | jq '._meta.version'

# 2. Point symlink to previous known-good version
ln -sf ../versions/filesystem-1.9.0.json policy/active/filesystem.json

# 3. Validate JSON syntax
python -m json.tool policy/active/filesystem.json > /dev/null

# 4. Verify rule count matches expectations
python scripts/policy_diff.py \
  policy/versions/filesystem-2.0.0.json \
  policy/versions/filesystem-1.9.0.json \
  --mode summary
```

## Compatibility Matrix

Maintain a top-level `COMPATIBILITY.md` mapping policy versions to ecosystem versions:

```markdown
| Policy File | Policy Version | Orchestrator | CLI | Compatible |
|-------------|----------------|--------------|-----|------------|
| filesystem  | 2.1.3          | >= 3.2.0     | >= 1.5.0 | ✅ Yes |
| filesystem  | 2.0.0          | >= 3.0.0     | >= 1.4.0 | ✅ Yes |
| filesystem  | 1.9.0          | >= 2.8.0     | >= 1.2.0 | ⚠️ Deprecated |
```

## Scripts & Tools

### `scripts/policy_diff.py`

Generate a human-readable diff between two policy versions:

```bash
# Full diff
python scripts/policy_diff.py \
  policy/versions/filesystem-1.9.0.json \
  policy/versions/filesystem-2.0.0.json

# Summary only (rule counts, version change)
python scripts/policy_diff.py \
  policy/versions/filesystem-1.9.0.json \
  policy/versions/filesystem-2.0.0.json \
  --mode summary

# Check specific rule key
python scripts/policy_diff.py \
  policy/versions/filesystem-1.9.0.json \
  policy/versions/filesystem-2.0.0.json \
  --rule filesystem.read.etc
```

## Policy Audit Procedure

When investigating an incident:

1. **Determine incident timestamp** from logs
2. **Check `policy/CHANGELOG.md`** for the relevant policy file
3. **Find which version was active** at that time (version + timestamp)
4. **Generate diff** between that version and the previous version to see what changed
5. **Report**: "Incident occurred at 2025-01-15T14:22:00Z. Active policy version was filesystem@2.1.2. The only difference from 2.1.1 was the addition of `filesystem.write.temp_dir`."

## Resources

- `references/versioning_rules.md` — Detailed semantic versioning rules for policy files
- `references/migration_template.md` — Template for writing migration guides on MAJOR bumps
- `scripts/policy_diff.py` — Diff generator for policy version comparison
