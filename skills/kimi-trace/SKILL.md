---
name: kimi-trace
description: >
  Session replay and visualization tool for the Kimi AI Engineering Skills
  Ecosystem. Reads telemetry-aggregator session JSON files and renders
  terminal-friendly ASCII phase timelines, token waterfalls, and error
  attribution. Supports HTML export and Obsidian vault sync. Integrates with
  skill-orchestrator for post-session replay offers.
license: MIT
compatibility: Kimi Code CLI v1.0+
type: standard
---

# kimi-trace — Session Replay & Visualization

## Overview

`kimi-trace` is the LangSmith-equivalent observability tool for Kimi. It consumes session telemetry produced by `telemetry-aggregator` and renders human-readable session replays: phase timelines, per-skill duration bars, token waterfalls, and error attribution.

## When to Use

- After session completion: review which phase consumed the most tokens
- During incident response: identify which skill failed and why
- For capacity planning: analyze token usage patterns across sessions
- For debugging: trace the exact sequence of skill activations and phase transitions
- For presentations: export HTML session summary for stakeholders

## Input

`kimi-trace` reads `~/.kimi/logs/session-{id}-telemetry.json` files produced by `telemetry-aggregator`.

## Modes

### Terminal Replay (Default)

```bash
$ kimi-trace replay session-abc123

Session: session-abc123
Duration: 24.4s | Tokens: 16,660 | Exit: SUCCESS

Phase timeline:
INGEST    ████░░░░░░  2.1s   1,240 tok
PLAN      ████████░░  4.8s   3,820 tok
ASSESS    ██░░░░░░░░  1.2s     890 tok
EXECUTE   ██████████ 12.4s   8,100 tok ← bottleneck
VALIDATE  ████░░░░░░  3.1s   2,200 tok
REMEMBER  █░░░░░░░░░  0.8s     410 tok

Skill breakdown:
code-tester              12.4s   8,100 tok  4 tool calls  ✓
architecture-design       4.8s   3,820 tok  0 tool calls  ✓
security-auditor          3.1s   2,200 tok  2 tool calls  ✓
obsidian-setup            0.8s     410 tok  0 tool calls  ✓

Errors: none
```

### HTML Export

```bash
$ kimi-trace export --html session-abc123 --output report.html
```

Generates an interactive HTML page with:
- Clickable phase timeline
- Token usage pie chart
- Skill activation Gantt chart
- Error detail expansion panels

### Obsidian Vault Sync

```bash
$ kimi-trace vault-sync --vault-path ~/obsidian/kimi-sessions
```

Appends session trace as a new markdown note with:
- Frontmatter: session_id, duration, tokens, exit_status
- Body: phase timeline, skill breakdown, error details
- Wikilinks: `[[session-{id}]]` for cross-referencing

### Batch Analysis

```bash
$ kimi-trace analyze --last 7d --metric tokens_per_session

Last 7 days (42 sessions):
  Mean tokens/session: 14,230
  P95 tokens/session:  28,100
  Max tokens/session:  41,500  (session-def456 on 2026-05-06)
  Slowest skill: code-tester (mean 8.2s)
  Most error-prone: security-auditor (3 failures)
```

## Integration Points

| Component | Integration |
|-----------|-------------|
| `telemetry-aggregator` | Reads `session-*-telemetry.json` |
| `skill-orchestrator` | Offered after session completion: "View session trace?" |
| `obsidian-setup` | Vault sync for persistent session history |
| `drift-monitor` | Batch analysis feeds into drift baselines |

## Scripts

- `scripts/kimi-trace.py` — Core CLI with replay, export, vault-sync, and analyze subcommands
- `scripts/render_timeline.py` — ASCII and HTML timeline rendering engine

## References

- `references/telemetry-schema.md` — Expected JSON schema for session telemetry input

## Changelog

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-05-07 | Initial release — terminal replay, HTML export, Obsidian sync, batch analysis |
