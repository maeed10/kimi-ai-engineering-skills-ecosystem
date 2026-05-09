# Staleness Metrics and Scoring Formulas

Definitions and formulas for quantifying how much runtime topology has diverged from the static architecture map.

## Raw Diff Vectors

Given:
- `G_static = (C, E_static)` — context-level graph from static map
- `G_runtime = (C, E_runtime)` — context-level graph from traces/logs

Where `C` = set of bounded contexts and `E` = set of directed context-to-context edges.

### Edge Classification

```yaml
edge_types:
  preserved:   E_static ∩ E_runtime           # edges present in both
  missing:     E_static \ E_runtime           # static edges absent from runtime
  new:         E_runtime \ E_static           # runtime edges not in static map
  direction_reversed:
    condition: (a→b) ∈ E_static ∧ (b→a) ∈ E_runtime
    note:      counted separately from missing/new
```

---

## Individual Metrics

### M1: New Edge Ratio (NER)

Ratio of newly observed edges to the static baseline.

```
NER = |E_runtime \ E_static| / max(|E_static|, 1)
```

| Range | Interpretation |
|-------|---------------|
| 0.0 | No new context-to-context edges observed |
| 0.0–0.3 | Minor growth; likely acceptable |
| 0.3–0.6 | Significant new coupling; review needed |
| > 0.6 | Major architectural drift; trigger re-understanding |

### M2: Missing Edge Ratio (MER)

Ratio of expected edges that disappeared from runtime.

```
MER = |E_static \ E_runtime| / max(|E_static|, 1)
```

| Range | Interpretation |
|-------|---------------|
| 0.0 | All static edges observed in runtime |
| 0.0–0.3 | Low traffic or sampling; usually acceptable |
| 0.3–0.6 | Many static edges missing; possible decomposition or removal |
| > 0.6 | Static map likely heavily outdated |

**Sampling caveat:** Low-traffic allowed crossings may legitimately have `MER > 0` in a 24h window. Extend lookback to 7d before flagging.

### M3: Direction Mismatch Ratio (DMR)

Edges whose direction reversed vs. static definition.

```
DMR = count({(a,b) | (a→b) ∈ E_static ∧ (b→a) ∈ E_runtime}) / max(|E_static|, 1)
```

Direction reversal is **always suspicious** for explicitly allowed crossings — it may indicate a callback pattern was replaced by direct coupling.

### M4: Weight Deviation Score (WDS)

Measures traffic volume changes on preserved edges.

```
For each preserved edge e:
  w_static  = expected_call_count  (from static map annotation, or historical mean)
  w_runtime = observed_call_count  (from traces)

  If w_static exists:
    z_e = |w_runtime - w_static| / max(w_static, 1)
  Else:
    z_e = 0   # no baseline, skip

WDS = mean(z_e) across all preserved edges with baseline
```

| WDS | Interpretation |
|-----|---------------|
| 0.0 | All preserved edges match expected volume |
| 0.0–1.0 | Normal variance |
| 1.0–3.0 | Elevated; investigate outliers |
| > 3.0 | Order-of-magnitude change; possible circuit-breaker bypass or DDoS |

---

## Composite Staleness Score

Weighted combination of individual metrics into a single `[0.0, 1.0]` score.

```
staleness_score = clamp(
    0.40 * NER +
    0.30 * MER +
    0.20 * DMR +
    0.10 * sigmoid(WDS - 1)
)
```

Where:
- `clamp(x)` = `min(1.0, max(0.0, x))`
- `sigmoid(t) = 1 / (1 + exp(-t))` — smooth step, maps weight deviation to [0,1]

### Rationale for weights

| Weight | Metric | Reason |
|--------|--------|--------|
| 0.40 | NER | New coupling is the strongest signal of architectural drift |
| 0.30 | MER | Missing edges indicate decomposition or staleness |
| 0.20 | DMR | Direction reversal breaks dependency discipline |
| 0.10 | WDS | Volume changes supplement structural signals |

### Thresholds

| staleness_score | Action |
|-----------------|--------|
| 0.0 – 0.3 | HEALTHY — no action |
| 0.3 – 0.6 | WARNING — note in report, schedule map review |
| 0.6 – 1.0 | CRITICAL — trigger re-understanding of boundary-enforcer |

---

## Forbidden Crossing Penalty

Forbidden crossings (`forbidden_crossings` list in static map) detected in runtime are **always** escalated to severity CRITICAL, regardless of staleness score.

```
If any forbidden crossing observed:
  staleness_score = max(staleness_score, 0.8)   # force into CRITICAL band
  mandatory_reunderstand = true
```

This prevents a low staleness score (few edges overall) from masking a serious policy violation.

---

## Context-Level vs Service-Level Scoring

The primary staleness score is computed at **bounded-context level** (coarse). An optional **service-level** score can be computed for detailed diagnostics:

```yaml
service_level:
  purpose: Identify which specific services within a context are responsible for drift
  method: Compute NER/MER/DMR at service graph level (G_runtime) before collapsing to contexts
  output: Per-context staleness sub-score in BOUNDARY_VIOLATIONS.md
```

Use service-level scoring only when context-level score is > 0.3 and the specific services need identification.
