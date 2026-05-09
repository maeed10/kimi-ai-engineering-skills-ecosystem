---
name: dev-git-workflow
description: Developer-facing Git workflow optimizer with branch strategies, PR templates, code review automation, merge conflict resolution, and conventional commits. Use when setting up repositories, reviewing PRs, resolving conflicts, standardizing commits, or managing releases. Supports Git Flow, trunk-based development, and semantic versioning.
---

# Dev Git Workflow

## Overview

This skill provides comprehensive Git workflow optimization for everyday software engineering. It covers repository setup, branching strategies, pull request automation, code review assistance, merge conflict resolution, commit standardization, history rewriting, release management, and monorepo/submodule handling. Use this skill when you need to establish consistent, team-scale Git practices or resolve complex repository operations.

## Workflow Decision Tree

```
Setting up a new repo?
├── Yes → Choose branching model → Configure branch protection → Set commit standards
│
Reviewing a pull request?
├── Yes → Load review checklist → Analyze diff → Generate review comments
│
Resolving merge conflicts?
├── Yes → Identify conflict pattern → Apply resolution strategy → Verify clean merge
│
Standardizing commits?
├── Yes → Validate conventional format → Suggest scope → Enforce message rules
│
Preparing a release?
├── Yes → Determine semver bump → Tag release → Generate changelog
│
Managing monorepo/submodules?
├── Yes → Apply monorepo branching → Sync submodules → Coordinate cross-repo changes
│
Need history cleanup?
├── Yes → Choose rebase/squash strategy → Execute interactive rebase → Verify linear history
```

## Core Capabilities

### 1. Branch Strategy Setup

Choose and configure the right branching model for your team's delivery cadence and release needs.

| Model | Best For | Release Cadence | Complexity |
|-------|----------|----------------|------------|
| Git Flow | Scheduled releases, multi-version support | Weekly/monthly | High |
| GitHub Flow | Continuous deployment, SaaS products | Daily/multiple per day | Low |
| Trunk-Based | High-velocity teams, feature flags | Continuous | Medium |

**Quick Setup Commands:**

```bash
# Git Flow initialization
git flow init -d
git config gitflow.prefix.feature "feature/"
git config gitflow.prefix.release "release/"
git config gitflow.prefix.hotfix "hotfix/"
git config gitflow.prefix.versiontag "v"

# Branch protection rules (GitHub CLI)
gh api repos/{owner}/{repo}/branches/main/protection \
  --method PUT \
  --input - <<< '{
    "required_status_checks": {"strict": true, "contexts": ["ci/tests"]},
    "enforce_admins": false,
    "required_pull_request_reviews": {
      "required_approving_review_count": 2,
      "dismiss_stale_reviews": true,
      "require_code_owner_reviews": true
    },
    "restrictions": null,
    "allow_force_pushes": false,
    "allow_deletions": false,
    "required_linear_history": true
  }'

# trunk-based: enforce short-lived branches (< 24h)
git config --local branch.autosetuprebase always
```

**Branch Naming Conventions:**
- `feature/{ticket-id}-{short-desc}` — e.g., `feature/TKT-123-add-oauth`
- `bugfix/{ticket-id}-{short-desc}` — e.g., `bugfix/TKT-456-fix-race-condition`
- `hotfix/{version}-{short-desc}` — e.g., `hotfix/2.1.1-memory-leak`
- `release/{version}` — e.g., `release/2.2.0`
- `chore/{short-desc}` — e.g., `chore/update-dependencies`
- `docs/{short-desc}` — e.g., `docs/api-usage-examples`

### 2. PR Template Generation

Generate context-rich pull request templates that reduce review friction and improve traceability.

**Standard PR Template (Markdown):**
```markdown
## Description
<!-- What does this PR do? Why is it needed? -->

## Related Issue(s)
Fixes #<!-- issue number -->

## Type of Change
- [ ] Bug fix (non-breaking)
- [ ] New feature
- [ ] Breaking change
- [ ] Refactor
- [ ] Documentation
- [ ] Performance improvement
- [ ] Security fix

## Checklist
- [ ] Code follows project style guidelines
- [ ] Self-review completed
- [ ] Changes are covered by tests
- [ ] All CI checks pass
- [ ] Documentation updated (if needed)
- [ ] No new warnings or errors introduced

## Testing Evidence
<!-- Screenshots, logs, or test results -->

## Security Considerations
- [ ] No secrets or credentials in code
- [ ] Input validation handled
- [ ] Authorization checks present
- [ ] No SQL injection / XSS vectors

## Deployment Notes
<!-- Migrations, feature flags, environment changes -->
```

**Setup in Repository:**
```bash
# GitHub: create .github/pull_request_template.md
mkdir -p .github
cat > .github/pull_request_template.md << 'EOF'
[template content above]
EOF

# GitLab: create .gitlab/merge_request_templates/default.md
mkdir -p .gitlab/merge_request_templates
cat > .gitlab/merge_request_templates/default.md << 'EOF'
[template content above]
EOF
```

### 3. Code Review Assistant

Analyze pull request diffs systematically for quality, security, performance, and correctness issues.

**Review Process:**
1. Read the full diff before commenting
2. Check architectural consistency
3. Validate error handling paths
4. Look for security-sensitive patterns (auth, input, crypto)
5. Verify test coverage for changed lines
6. Assess performance implications (N+1 queries, unnecessary allocations)
7. Confirm naming clarity and documentation accuracy
8. Flag TODOs or FIXMEs without ticket references

**High-Priority Red Flags:**
- Hardcoded credentials or secrets
- Missing authorization checks on new endpoints
- Unvalidated user input reaching databases or shells
- Race conditions in concurrent code
- Resource leaks (files, connections, memory)
- Incorrect error handling (silent failures, swallowed exceptions)
- Breaking changes without migration path

**Constructive Comment Template:**
```
**[Severity: info|suggestion|concern|blocking]**

Observation: [what you see]
Reasoning: [why it matters]
Suggestion: [concrete improvement or ask a clarifying question]
Example: [optional code snippet]
```

### 4. Merge Conflict Resolution

Identify conflict patterns and apply the appropriate resolution strategy.

**Common Conflict Patterns:**

| Pattern | Cause | Resolution Strategy |
|---------|-------|---------------------|
| Same-line edit | Both branches modified identical lines | Manual merge, preserve both semantics |
| File deleted vs edited | One branch deleted, other modified | Decide if file still needed; restore with edits or delete |
| Rename vs edit | One renamed, other edited | Apply edits to renamed file; `git mv` + merge |
| Submodule pointer | Different submodule commits | Update submodule to intended commit; `git submodule update --init` |
| Binary file | Both branches changed binary | Choose correct version; regenerate if possible |
| Large rebase chain | Multiple commits touching same area | Abort, squash first, then rebase |

**Resolution Workflow:**
```bash
# 1. Identify conflicted files
git status | grep "both modified"

# 2. Inspect conflict markers
git diff --check

# 3. Resolve each file (edit manually or use mergetool)
git mergetool --tool=vimdiff

# 4. Mark resolved
git add <resolved-file>

# 5. Verify no markers remain
grep -rn "<<<<<<<" .

# 6. Complete merge
git merge --continue
# or for rebase:
git rebase --continue
```

**Prevention Strategies:**
- Rebase feature branches frequently against `main`
- Keep branches short-lived (< 2 days)
- Coordinate with teammates on overlapping files
- Use feature flags to avoid long-running branches
- Break large refactors into smaller, incremental PRs

### 5. Commit Message Standardization

Enforce Conventional Commits for automated changelogs, semantic versioning, and clear history.

**Format:**
```
<type>(<scope>): <short summary in imperative mood>

<body: explain what and why, not how>

<footer: BREAKING CHANGE, Closes #123, Co-authored-by>
```

**Types and When to Use Them:**

| Type | Meaning | Example |
|------|---------|---------|
| feat | New feature | `feat(auth): add OAuth2 login with Google` |
| fix | Bug fix | `fix(api): handle null pointer in user serializer` |
| docs | Documentation only | `docs(readme): add setup instructions for M1 Mac` |
| style | Code style (formatting, semicolons) | `style(lint): fix trailing commas` |
| refactor | Code change neither fix nor feature | `refactor(db): extract connection pool logic` |
| perf | Performance improvement | `perf(query): add index on orders.created_at` |
| test | Adding or correcting tests | `test(unit): cover edge case in calculator` |
| chore | Build, deps, tooling | `chore(deps): bump lodash to 4.17.21` |
| ci | CI/CD changes | `ci(github): add matrix build for Node 20` |
| revert | Revert previous commit | `revert(auth): revert OAuth2 due to token leak` |

**Validation Rules:**
- Summary line <= 72 characters
- Use imperative mood ("Add" not "Added" or "Adds")
- Scope is optional but recommended; should match module/package
- Body separated from summary by blank line
- Breaking changes marked with `!` after type/scope or `BREAKING CHANGE:` in footer

**Setup Enforcement:**
```bash
# Husky + commitlint (Node.js projects)
npm install --save-dev @commitlint/{config-conventional,cli} husky
npx husky init
echo "npx --no-install commitlint --edit \$1" > .husky/commit-msg

# Git alias for quick commit
git config --global alias.cm '!f() { git commit -m "$1"; }; f'
git config --global alias.cfeat '!f() { git commit -m "feat: $1"; }; f'
git config --global alias.cfix '!f() { git commit -m "fix: $1"; }; f'
```

### 6. Rebase & Squash Guidance

Maintain a clean, linear, and meaningful commit history.

**When to Rebase vs. Merge:**
- **Rebase**: Personal feature branch before PR; cleans up WIP commits
- **Merge**: Integrating completed feature into mainline; preserves PR context
- **Squash-merge**: Feature branches with many small/debug commits

**Interactive Rebase Workflow:**
```bash
# Start interactive rebase for last N commits
git rebase -i HEAD~5

# Common actions in todo editor:
# pick    = keep commit
# reword  = edit commit message
# squash  = meld into previous commit (keep messages)
# fixup   = meld into previous commit (discard message)
# drop    = remove commit
# edit    = amend commit content

# While rebasing, amend a commit
git commit --amend
git rebase --continue

# Abort if things go wrong
git rebase --abort
```

**Squash Strategy for PR Branches:**
```bash
# Option 1: Squash during merge (GitHub/GitLab UI)
# Select "Squash and merge"

# Option 2: Manual squash before merge
git checkout feature-branch
git reset --soft $(git merge-base HEAD main)
git commit -m "feat(scope): descriptive summary of entire feature"
git push --force-with-lease
```

**History Safety Rules:**
- Never rebase commits already pushed to shared branches (main, release)
- Use `--force-with-lease` instead of `--force` to prevent overwriting others' work
- For public branches, prefer `git revert` over history rewriting
- Tag important commits before major rebases

### 7. Release Tagging

Automate semantic versioning, release notes, and changelog maintenance.

**Semantic Versioning Rules:**
- `MAJOR.MINOR.PATCH` (e.g., `2.1.3`)
- **MAJOR**: Incompatible API changes (`BREAKING CHANGE`)
- **MINOR**: Backward-compatible features (`feat`)
- **PATCH**: Backward-compatible fixes (`fix`)

**Release Workflow:**
```bash
# Determine next version from conventional commits
# If commits since last tag contain:
#   - BREAKING CHANGE → bump MAJOR
#   - feat → bump MINOR
#   - fix → bump PATCH
#   - otherwise → no bump (or PATCH at discretion)

# Create annotated tag
git tag -a v2.2.0 -m "Release v2.2.0 - OAuth2 support and performance improvements"

# Push tag
git push origin v2.2.0

# Generate release notes from commits since last tag
git log $(git describe --tags --abbrev=0)..HEAD --pretty=format:"- %s" > release_notes.md
```

**Changelog Format (Keep a Changelog):**
```markdown
## [2.2.0] - 2024-05-15

### Added
- OAuth2 authentication with Google and GitHub providers
- Rate limiting middleware for API endpoints

### Changed
- Improved database query performance for user listings

### Fixed
- Memory leak in WebSocket connection handler
- Race condition during concurrent profile updates

### Security
- Upgraded dependencies to address CVE-2024-XXXX
```

**Automation with standard-version (Node.js):**
```bash
npm install --save-dev standard-version
npx standard-version --dry-run  # preview
npx standard-version            # bump, tag, changelog
```

### 8. Submodule & Monorepo Management

Coordinate complex repository structures without losing sanity.

**Submodule Best Practices:**
```bash
# Add submodule
git submodule add https://github.com/org/shared-lib.git libs/shared-lib
git commit -m "chore(deps): add shared-lib submodule at v1.2.0"

# Clone with submodules
git clone --recurse-submodules git@github.com:org/monorepo.git

# Update submodules after pull
git pull && git submodule update --init --recursive

# Pin submodule to specific tag
cd libs/shared-lib
git checkout v1.3.0
cd ../..
git add libs/shared-lib && git commit -m "chore(deps): bump shared-lib to v1.3.0"
```

**Monorepo Branching Strategies:**

| Strategy | How It Works | Best For |
|----------|-------------|----------|
| Unified main | Single branch, all packages released together | Tight coupling, same release cycle |
| Split release branches | `release/web@2.1.0`, `release/api@3.0.0` | Independent package versioning |
| Tag-scoped releases | Tags include package name: `web-v2.1.0` | Simple tooling, clear traceability |

**Monorepo Commit Scope Rules:**
```
feat(web/auth): add login page
feat(api/users): add bulk export endpoint
chore(shared/ui): update button component
docs(api): correct OpenAPI schema description
```

**Cross-Package Change Detection:**
```bash
# List files changed in a commit by package
git show --name-only HEAD | grep "^apps/" | cut -d/ -f2 | sort -u
git show --name-only HEAD | grep "^packages/" | cut -d/ -f2 | sort -u

# Check if a package is affected in current branch
git diff --name-only main...HEAD | grep "^packages/core/"
```

## Quick Command Reference

| Task | Command |
|------|---------|
| Stash with untracked files | `git stash push -u -m "description"` |
| Pop specific stash | `git stash pop stash@{1}` |
| Show stash diff | `git stash show -p stash@{0}` |
| Cherry-pick range | `git cherry-pick A^..B` |
| Find commit by message | `git log --all --grep="pattern"` |
| Find commit by content | `git log -S"code_snippet"` |
| Show who last touched each line | `git blame -L 10,20 file.py` |
| Clean local merged branches | `git branch --merged main \| grep -v "main" \| xargs git branch -d` |
| Revert without committing | `git revert --no-commit HEAD` |
| Bisect for regression finding | `git bisect start`, `git bisect bad`, `git bisect good v2.1.0` |

## Resources

### scripts/
- `review_pr.py` — Analyze a PR diff file and emit structured review comments

### references/
- `branching_models.md` — Deep-dive comparison of Git Flow, GitHub Flow, and trunk-based development
- `review_checklist.md` — Per-language and per-concern code review checklists
