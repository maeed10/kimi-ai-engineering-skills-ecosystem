# Strategy Matrix

Risk-to-strategy mapping used by `canary-orchestrator` to select a progressive delivery approach.

## Matrix

| Risk Score | Strategy | Initial Traffic | Observation Window | Max Step Size | Rationale |
|-----------|----------|----------------|-------------------|---------------|-----------|
| 0–2 | `direct` | 100% | 5 min | N/A | Low risk. Standard deployment with short post-deploy monitoring. |
| 3–4 | `direct` | 100% | 5 min | N/A | Moderate-low risk. Still within direct-deploy tolerance; monitoring catches regressions. |
| 5–6 | `blue-green` | 0% → 100% cutover | 30 min | N/A | Moderate risk. Parallel environment eliminates blast radius; instant rollback if health fails after cutover. |
| 7–8 | `blue-green` | 0% → 100% cutover | 30 min | N/A | High-moderate risk. Same blue-green mechanics, longer observation ensures stability before decommissioning old environment. |
| 9–10 | `canary` | 1% | 15 min per step | +49 pp (1→5→25→50→100) | Maximum risk. SLO-gated stepwise ramp catches failures at minimal exposure. Each gate must clear before advancing. |

## Dimensions That Elevate Strategy

Certain `blast-radius-calculator` dimensions always push the strategy up by one tier:

| Dimension | Minimum Score to Elevate | Effect |
|-----------|-------------------------|--------|
| `data_integrity` | 7 | Force `blue-green` minimum |
| `security_surface` | 6 | Force `blue-green` minimum |
| `regulatory_exposure` | 5 | Force `blue-green` minimum |
| `multi_tenant_isolation` | 8 | Force `canary` minimum |

If a dimension elevates the strategy, use the elevated strategy regardless of the aggregate risk score. Log the overriding dimension in the audit trail.

## Edge Cases

- **Score exactly 5 or 8**: Use the higher-risk bucket (`blue-green` for 5, `blue-green` for 8). The boundary is inclusive on the conservative side.
- **Missing score**: Block deployment. Do not infer.
- **Score > 10**: Cap at 10, treat as `canary`, log warning.
- **Negative score**: Block deployment. Invalid input.
- **Confidence < 0.6**: If `blast-radius-calculator` reports low confidence, bump strategy up one tier. A score of 3 with confidence 0.4 becomes `blue-green` instead of `direct`.
