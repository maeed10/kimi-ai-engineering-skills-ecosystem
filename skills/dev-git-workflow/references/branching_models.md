# Branching Model Comparison

## Overview

This reference compares the three most common branching strategies for software teams: **Git Flow**, **GitHub Flow**, and **Trunk-Based Development**. Use this to select, justify, and configure the right model for your team's size, release cadence, and risk tolerance.

## Comparison Matrix

| Dimension | Git Flow | GitHub Flow | Trunk-Based Development |
|-----------|----------|-------------|------------------------|
| **Release cadence** | Scheduled (weekly/monthly) | Continuous deployment | Continuous deployment |
| **Branch count** | Many (main, develop, feature, release, hotfix) | Minimal (main + feature) | Minimal (main + short-lived branches) |
| **Branch lifetime** | Days to weeks | Hours to days | Minutes to hours (< 24h target) |
| **Release branches** | Yes, dedicated | No | No, tags on main |
| **Hotfix capability** | Formal hotfix branches | Emergency PR to main | Cherry-pick or rollback |
| **Team size** | Medium to large | Small to medium | Medium to large |
| **Complexity** | High | Low | Medium |
| **CI/CD fit** | Requires release pipeline | Native | Native with feature flags |
| **Rollback ease** | Revert release merge | Revert PR | Feature flag off or revert |
| **Versioning** | Semantic on release branches | Calver or semver via tags | Semantic on tags |

## Git Flow

### Branch Structure

```
main          ●────●────●────●────●────●────● (production releases)
              ↑    ↑    ↑    ↑
release/2.1   ●────●────● (release stabilization)
              ↑
develop       ●────●────●────●────●────●────●────● (integration)
              ↑    ↑         ↑              ↑
feature/A     ●────●         ●────●       (merged)
feature/B          ●────●────●              (merged)
hotfix/2.0.1            ●────● (emergency patch to main)
```

### Setup

```bash
# Install git-flow extension (optional but helpful)
# macOS: brew install git-flow-avh
# Linux: apt-get install git-flow

# Initialize in repository
git flow init -d

# Custom prefix configuration
git config gitflow.branch.master main
git config gitflow.branch.develop develop
git config gitflow.prefix.feature feature/
git config gitflow.prefix.bugfix bugfix/
git config gitflow.prefix.release release/
git config gitflow.prefix.hotfix hotfix/
git config gitflow.prefix.versiontag v
git config gitflow.prefix.support support/
```

### Workflow Commands

```bash
# Start a feature
git flow feature start TKT-123-oauth-login
# → creates feature/TKT-123-oauth-login from develop

# Finish a feature
git flow feature finish TKT-123-oauth-login
# → merges into develop, deletes feature branch

# Start a release
git flow release start 2.1.0
# → creates release/2.1.0 from develop

# Finish a release
git flow release finish 2.1.0
# → merges into main and develop, tags v2.1.0

# Hotfix
git flow hotfix start 2.0.1
# → creates hotfix/2.0.1 from main
# Edit, commit, then:
git flow hotfix finish 2.0.1
# → merges into main and develop, tags v2.0.1
```

### When to Use

- **Scheduled releases** with QA/staging gates
- **Multi-version support** (maintaining 1.x while building 2.x)
- **Regulated environments** requiring release sign-off
- **Teams with dedicated release managers**

### Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Long-running develop/main divergence | Force regular merges from main to develop after hotfixes |
| Release branch staleness | Cut release branches closer to release date |
| Merge conflicts in long-lived features | Rebase feature branches against develop weekly |
| Complexity for new developers | Document workflow in onboarding; provide scripts/aliases |

---

## GitHub Flow

### Branch Structure

```
main          ●────●────●────●────●────●────●────●────● (deployable at all times)
              ↑    ↑         ↑              ↑    ↑
feature/A     ●────● (PR → review → merge → deploy)
feature/B          ●────●────● (PR → review → merge → deploy)
hotfix                  ●────● (PR → expedited review → merge → deploy)
```

### Setup

```bash
# Single main branch, everything else is short-lived
git checkout -b main
git push -u origin main

# Protect main branch via platform settings:
# - Require PR reviews (1-2 approvers)
# - Require status checks (CI pass)
# - No direct pushes
# - Allow force pushes: disabled
```

### Workflow Commands

```bash
# Create feature branch
git checkout -b feature/TKT-123-add-search

# Push and create PR
git push -u origin feature/TKT-123-add-search
gh pr create --title "feat(search): add full-text search" \
  --body "Closes #123. Implements Elasticsearch-backed search."

# Address review feedback
# ... edit, commit, push ...
git push

# Merge after approval and CI pass
gh pr merge --squash --delete-branch
# or --merge to preserve commits, --rebase for linear history
```

### When to Use

- **SaaS/continuously deployed** products
- **Small to medium teams** with high trust
- **Fast iteration** cycles with automated testing
- **GitHub/GitLab/Azure DevOps** native workflows

### Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Main branch breaks | Require CI gates before merge; use deploy previews |
| Incomplete features on main | Feature flags, dark launches, or branch-by-abstraction |
| No release isolation | Use tags for rollback points; practice canary deployments |
| Review bottleneck | Automate trivial checks (lint, format, tests) to focus human review |

---

## Trunk-Based Development

### Branch Structure

```
main          ●────●────●────●────●────●────●────●────● (single source of truth)
              ↑    ↑    ↑    ↑    ↑    ↑    ↑
feature/A     ●────● (short-lived, < 24h)
feature/B          ●────● (short-lived, < 24h)
feature/C               ●────● (short-lived, < 24h)
release-branch              ●────● (optional, for patching)
```

### Setup

```bash
# Enforce short-lived branches with automation or policy
git checkout main

# Enable rebase-by-default for cleaner history
git config --local branch.autosetuprebase always

# Optional: release branches only for hotfixing released versions
git checkout -b release/2024-q2
```

### Workflow Commands

```bash
# Start work directly from main
git checkout main
git pull origin main
git checkout -b feature/TKT-456-optimize-query

# Commit frequently (small, safe changes)
git commit -m "perf(db): add composite index on orders"

# Push to remote for CI and optional PR/review
git push -u origin feature/TKT-456-optimize-query

# Merge quickly (hours, not days)
gh pr create --draft=false
git push origin main  # if pair-programming or high trust

# After merge, delete branch immediately
git branch -d feature/TKT-456-optimize-query
```

### Key Practices

| Practice | Purpose |
|----------|---------|
| **Feature flags** | Merge incomplete features safely; enable at runtime |
| **Branch by abstraction** | Replace implementations behind an interface |
| **Pair/mob programming** | Real-time code review, reduces need for async PRs |
| **Fast feedback CI** | Sub-10-minute builds to support rapid iteration |
| **Read-only release branches** | Only for emergency patches; no active development |

### When to Use

- **High-velocity teams** releasing multiple times per day
- **Microservices** with independent deployment pipelines
- **Mature CI/CD** with comprehensive automated testing
- **Feature flag infrastructure** available

### Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Unstable main | Comprehensive test suites; pre-merge validation |
| Large changes difficult | Break into incremental PRs behind abstractions/flags |
| Requires discipline | Team agreements; CI enforcement; pair programming |
| Feature flag accumulation | Scheduled flag cleanup sprints; automated flag removal alerts |

---

## Decision Guide

```
Do you release on a fixed schedule (weekly/monthly)?
├── Yes → Do you maintain multiple production versions?
│   ├── Yes → Git Flow
│   └── No  → Git Flow (simplified) or GitHub Flow with release branches
│
└── No → Do you deploy multiple times per day?
    ├── Yes → Do you have feature flags + fast CI?
    │   ├── Yes → Trunk-Based Development
    │   └── No  → GitHub Flow (adopt flags and speed CI first)
    └── No  → GitHub Flow
```

## Hybrid Configurations

Many teams blend these models. Common hybrids:

### GitHub Flow + Release Branches
- Daily merges to `main`
- Cut `release/{version}` branch at release time
- Cherry-pick critical fixes from main to release
- Tag release branch when ready

### Trunk-Based + Git Flow for Legacy
- New services: trunk-based
- Legacy monolith: Git Flow for scheduled releases
- Unify where possible; accept divergence during transition

### Monorepo Variants
- **Unified releases**: Git Flow with single release branch
- **Independent releases**: GitHub Flow per package; tags scoped by package name
- **Mixed**: Core library uses Git Flow; apps use GitHub Flow

## Branch Protection Templates

### Git Flow Protection

| Branch | Rules |
|--------|-------|
| `main` | No direct push; PR required; 2+ approvals; CI pass; no force push |
| `develop` | PR required; 1+ approval; CI pass; no force push |
| `release/*` | PR required; 2+ approvals; full test suite pass; release manager approval |
| `hotfix/*` | PR required; 1+ approval; expedited CI; security review if touches auth |

### GitHub Flow Protection

| Branch | Rules |
|--------|-------|
| `main` | No direct push; PR required; 1-2 approvals; CI pass; linear history required |

### Trunk-Based Protection

| Branch | Rules |
|--------|-------|
| `main` | No direct push; PR or pair-commit required; CI pass; auto-deploy after merge |
| `release/*` | Read-only; cherry-pick only with release manager approval |
