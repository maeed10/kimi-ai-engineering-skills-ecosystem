---
name: gemini-router
description: >
  BACKWARD COMPATIBILITY STUB. Delegates all operations to multi-model-router
  with provider locked to gemini. Use multi-model-router directly for new
  integrations.
license: MIT
compatibility: Kimi Code CLI v1.0+
type: standard
---

# gemini-router — Compatibility Stub

This skill is a **backward-compatibility stub**. All functionality has been migrated to `multi-model-router` (v1.0.0).

## Behavior

When activated, `gemini-router` immediately delegates to `multi-model-router` with:
- `provider: gemini`
- `model: gemini-2.5-flash-lite`
- All other settings inherited from `multi-model-router.yaml`

## Deprecation Timeline

| Date | Action |
|------|--------|
| 2026-05-07 | Stub created; multi-model-router becomes canonical |
| 2026-08-07 | Warning logged on every gemini-router activation |
| 2026-11-07 | gemini-router removed; all callers must use multi-model-router |

## Migration

Replace any reference to `gemini-router` with `multi-model-router` and specify `provider: gemini` in configuration.
