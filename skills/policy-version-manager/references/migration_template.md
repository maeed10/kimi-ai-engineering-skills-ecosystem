# Migration Guide Template

## Use This Template When

- A policy file undergoes a **MAJOR** version bump (`X.y.z` → `X+1.0.0`)
- You need to document what behavior changes and how consumers should adapt

## File Naming

```
migrations/<policy-file>-<prev-major>.x-to-<new-major>.0.0.md
```

Examples:
- `migrations/filesystem-1.x-to-2.0.0.md`
- `migrations/network-2.x-to-3.0.0.md`
- `migrations/execution-1.x-to-2.0.0.md`

---

## Template

```markdown
# Migration Guide: <PolicyName> <PrevVersion> → <NewVersion>

## Summary

One-sentence description of the breaking change.

## Breaking Changes

### 1. <Rule Key or Category>
**Before**: Describe prior behavior (e.g., "`filesystem.read.etc` was ALWAYS allowed")
**After**: Describe new behavior (e.g., "`filesystem.read.etc` is now NEVER allowed")
**Impact**: Which tool calls are affected? (e.g., "Any `read_file` call targeting `/etc/passwd` will now fail")
**Action Required**: What must the consumer do? (e.g., "Update scripts to use `getent passwd` instead of reading `/etc/passwd` directly")

### 2. <Next Breaking Change...>

## Affected Tool Calls

| Tool | Previous Behavior | New Behavior | Required Change |
|------|-------------------|--------------|---------------|
| `tool_name_1` | Succeeded | Fails with policy error | Use alternative `tool_name_alt` |
| `tool_name_2` | Succeeded with warning | Fails unconditionally | Remove call or request exception |

## Rollback Path

If this migration causes unexpected issues:

1. Run the hot-swap rollback procedure:
   ```bash
   ln -sf ../versions/<policy-file>-<prev-stable>.json policy/active/<policy-file>.json
   python -m json.tool policy/active/<policy-file>.json > /dev/null
   ```
2. Verify the previous version is active:
   ```bash
   cat policy/active/<policy-file>.json | jq '._meta.version'
   ```
3. No orchestrator restart is required; new tool calls will use the reverted policy immediately.

## Testing Checklist

Before deploying this MAJOR update:

- [ ] Run `policy_diff.py` between old and new versions and review every difference
- [ ] Execute a representative tool call from each affected category in a staging environment
- [ ] Verify that expected-success calls still succeed
- [ ] Verify that expected-fail calls now fail with a clear error message
- [ ] Confirm the changelog and compatibility matrix are updated
- [ ] Tag the repository with `policy-<file>-v<newversion>`

## Compatibility

| Ecosystem Component | Minimum Version | Notes |
|---------------------|-----------------|-------|
| Orchestrator | x.y.z | Required for `<specific feature>` support |
| CLI | a.b.c | Required for new error message format |

## Timeline

- **Release Date**: YYYY-MM-DD
- **Deprecation Date** (if applicable): YYYY-MM-DD — previous MAJOR version enters deprecation
- **End-of-Life Date** (if applicable): YYYY-MM-DD — previous MAJOR version no longer supported

## Contact

- **Author**: @username or agent-id
- **Review Thread**: <link to PR or discussion>
```

---

## Example Completed Migration

```markdown
# Migration Guide: filesystem 1.x → 2.0.0

## Summary

The filesystem policy now blocks direct reads of `/etc/passwd` and requires using identity-service APIs instead.

## Breaking Changes

### 1. filesystem.read.etc
**Before**: `filesystem.read.etc` was ALWAYS allowed. Any tool could read `/etc/passwd`, `/etc/shadow`, etc.
**After**: `filesystem.read.etc` is now NEVER allowed.
**Impact**: All `read_file` and `file_exists` calls targeting `/etc/*` will fail with policy error `POLICY_VIOLATION: filesystem.read.etc`.
**Action Required**: Update scripts to use `getent passwd <user>` or the identity-service API instead of reading `/etc/passwd`.

## Affected Tool Calls

| Tool | Previous Behavior | New Behavior | Required Change |
|------|-------------------|--------------|---------------|
| `read_file` | `/etc/passwd` readable | Fails with `POLICY_VIOLATION` | Use `getent` or identity API |
| `file_exists` | `/etc/hosts` checkable | Fails with `POLICY_VIOLATION` | Use DNS lookup instead |

## Rollback Path

```bash
ln -sf ../versions/filesystem-1.9.0.json policy/active/filesystem.json
python -m json.tool policy/active/filesystem.json > /dev/null
cat policy/active/filesystem.json | jq '._meta.version'
```

No orchestrator restart required.

## Testing Checklist

- [x] Diff reviewed: `python scripts/policy_diff.py versions/filesystem-1.9.0.json versions/filesystem-2.0.0.json`
- [x] Staging test: `read_file /etc/passwd` correctly fails
- [x] Staging test: `getent passwd root` succeeds as alternative
- [x] Changelog updated
- [x] Compatibility matrix updated
- [x] Tagged: `policy-filesystem-v2.0.0`

## Compatibility

| Ecosystem Component | Minimum Version | Notes |
|---------------------|-----------------|-------|
| Orchestrator | >= 3.0.0 | New error code `POLICY_VIOLATION` introduced |
| CLI | >= 1.4.0 | Displays policy violation details in stderr |

## Timeline

- **Release Date**: 2025-01-10
- **Deprecation Date**: 2025-04-10 — filesystem 1.x enters deprecation
- **End-of-Life Date**: 2025-07-10 — filesystem 1.x no longer supported

## Contact

- **Author**: @security-team
- **Review Thread**: https://github.com/org/repo/pull/442
```
