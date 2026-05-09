# Semantic Versioning Rules for Policy Files

## Scope

Applies to all files in the `policy/` directory that define ALWAYS/NEVER rules:

- `filesystem.json` — file system access rules
- `network.json` — network access rules
- `execution.json` — code execution rules
- `sandbox.json` — sandbox/container rules
- Any future `*.json` policy file

Each file is versioned **independently**. A change to `network.json` does not bump the version of `filesystem.json`.

## Version Format

```
MAJOR.MINOR.PATCH
```

All components are non-negative integers incremented by exactly 1 per release.

---

## MAJOR Bump (X.y.z → X+1.0.0)

**Definition**: A breaking change that alters whether an existing tool call succeeds or fails.

### Triggers

| Trigger | Example |
|---------|---------|
| Removing an ALWAYS rule | `filesystem.read.home_dir` no longer permitted |
| Removing a NEVER rule | `network.http.localhost` no longer blocked |
| Changing an ALWAYS to NEVER or CONDITIONAL | `execution.python.eval` goes from permitted to blocked |
| Changing a NEVER to ALWAYS or CONDITIONAL | `network.http.internal_api` goes from blocked to permitted |
| Renaming a rule key that external tooling depends on | `filesystem.write.tmp` renamed to `filesystem.write.temp` |
| Removing or renaming a rule category/namespace | Deleting the `network.dns` category |
| Changing default behavior from permissive to restrictive (or vice versa) for unlisted tools | "Default deny" flipped to "default allow" |

### Required Artifacts

- Migration guide at `migrations/<file>-<prev>.x-to-<new>.md`
- Compatibility matrix update
- CHANGELOG entry under `## Changed` or `## Removed`

---

## MINOR Bump (x.Y.z → x.Y+1.0)

**Definition**: New rule or capability added. Existing tool calls are unaffected.

### Triggers

| Trigger | Example |
|---------|---------|
| Adding a new ALWAYS rule | New `filesystem.read.logs_dir` ALWAYS rule |
| Adding a new NEVER rule | New `network.http.malware_domain` NEVER rule |
| Adding a new CONDITIONAL rule | New `execution.shell.admin` with pre-approval requirement |
| Adding a new rule category/namespace | New `network.grpc` section |
| Expanding an existing rule to cover additional sub-paths or parameters without changing existing behavior | `filesystem.read.home_dir` expanded to also cover `/home/shared` |

### Required Artifacts

- CHANGELOG entry under `## Added`

---

## PATCH Bump (x.y.Z → x.y.Z+1)

**Definition**: Non-behavioral change. No tool call outcomes are affected.

### Triggers

| Trigger | Example |
|---------|---------|
| Description or comment changes | Clarifying rule rationale |
| Formatting or whitespace | Re-indenting JSON, trailing commas |
| Typos in non-executed strings | Fixing "recieve" in a description |
| Reordering keys without semantic change | Alphabetizing rules |
| Adding `_meta` fields that are not evaluated | `updated_by`, `rationale_url` |

### Required Artifacts

- CHANGELOG entry under `## Fixed`

---

## Precedence Rules

When a single change could match multiple bump levels, use the **highest** applicable level:

1. If any breaking change is present → **MAJOR**
2. Else if any new rule/capability is present → **MINOR**
3. Else → **PATCH**

## Example Version Lifecycles

### filesystem.json

```
1.0.0 — Initial release
1.0.1 — PATCH: Fix description typos
1.1.0 — MINOR: Add `filesystem.read.logs_dir`
1.2.0 — MINOR: Add `filesystem.write.temp_dir`
2.0.0 — MAJOR: `filesystem.read.etc` changed to NEVER
2.0.1 — PATCH: Update migration guide link in `_meta`
2.1.0 — MINOR: Add `filesystem.read.project_root`
```

### network.json

```
1.0.0 — Initial release
1.0.1 — PATCH: Clarify `network.http.localhost` description
1.1.0 — MINOR: Add `network.dns.block_ad_servers`
2.0.0 — MAJOR: Remove `network.http.internal_api` ALWAYS rule
```

## Version Metadata Schema

Every policy file must include a `_meta` object:

```json
{
  "_meta": {
    "version": "2.1.3",
    "updated_at": "2025-01-15T09:32:00Z",
    "updated_by": "agent-7f8a9b2c",
    "changelog_path": "CHANGELOG-filesystem.md",
    "migration_path": "migrations/filesystem-1.x-to-2.0.0.md"
  }
}
```

- `version` — current semantic version
- `updated_at` — ISO 8601 timestamp of last modification
- `updated_by` — identifier of agent or human who made the change
- `changelog_path` — relative path to the changelog file
- `migration_path` — relative path to the migration guide (only for MAJOR versions; may be omitted otherwise)

## File Naming Conventions

Stored versions use this naming convention:

```
policy/versions/
  filesystem-1.0.0.json
  filesystem-1.1.0.json
  filesystem-2.0.0.json
  network-1.0.0.json
  network-2.0.0.json
```

The active policy is a symlink or config reference:

```
policy/active/filesystem.json -> ../versions/filesystem-2.1.3.json
```

## Tagging and References

When committing policy changes, tag the repository with the policy file and version:

```
policy-filesystem-v2.1.3
policy-network-v1.5.0
```

This enables rapid checkout of a known-good policy state without affecting code.
