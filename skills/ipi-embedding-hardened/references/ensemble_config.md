# Ensemble Configuration Reference

## Model Selection Matrix

Select exactly 3 models from distinct rows. Minimum viable ensemble: one from Architecture A, one from B, one from C.

| ID | Architecture | Example Models | Tokenizer | Vendor Diversity |
|----|-------------|----------------|-----------|-----------------|
| A | Bi-encoder (sentence-transformers) | `all-MiniLM-L6-v2`, `all-mpnet-base-v2` | WordPiece | HuggingFace |
| B | Contrastive (E5 family) | `e5-large-v2`, `e5-mistral-7b-instruct` | Byte-Pair | Microsoft |
| C | Autoregressive embeddings | `text-embedding-3-small`, `text-embedding-3-large` | BPE (OpenAI) | OpenAI |
| D | Late-interaction (ColBERT) | `colbertv2.0` | WordPiece | Stanford |

### Selection Rules

1. **No two models from the same architecture family** — shared architecture implies correlated failure modes
2. **No two models from the same vendor** — supply-chain attacks or coordinated updates can blind multiple models
3. **At least one local/offline model** — prevent cloud latency from blocking the defense path; `all-MiniLM-L6-v2` or `e5-large-v2` serve this role
4. **Embedding dimensionality independence** — models may project to different dims (384, 768, 1024, 1536); normalization handles cross-dimension comparison

### Recommended Production Ensemble (3-model)

| Position | Model | Architecture | Dim | Role |
|----------|-------|-------------|-----|------|
| Primary (local) | `e5-large-v2` | Contrastive | 1024 | Fast path, offline-capable |
| Secondary (cloud) | `text-embedding-3-small` | Autoregressive | 1536 | Cloud diversity |
| Tertiary (local) | `all-mpnet-base-v2` | Bi-encoder | 768 | Architecture diversity |

### Recommended High-Security Ensemble (4-model)

Add `colbertv2.0` as Position 4 for late-interaction diversity. Use when Layer 3 false negative rate exceeds 1%.

## Divergence Consensus Rules

### Distance Metric

Use **cosine distance** (not similarity) for all comparisons:

```
cosine_distance(u, v) = 1 - (u · v) / (||u|| * ||v||)
```

Range: [0, 2] where 0 = identical direction, 2 = opposite direction.

### Per-Model Thresholds

Each model has its own threshold — do not share thresholds across models.

| Model | Dim | Recommended Threshold | Rationale |
|-------|-----|----------------------|-----------|
| `e5-large-v2` | 1024 | 0.15 | Trained with hard negatives; tight cluster |
| `text-embedding-3-small` | 1536 | 0.18 | OpenAI embeddings are more diffuse |
| `all-mpnet-base-v2` | 768 | 0.16 | mpnet has stronger semantic compression |
| `colbertv2.0` | 128 (per token) | MaxTokenDiv > 0.25 | Late-interaction uses token-level comparison |

### Consensus Logic

```python
def ensemble_decision(divergences: list[float], thresholds: list[float]) -> dict:
    """
    BLOCK if ANY model reports divergence above its threshold.
    Never average. Never vote.
    """
    flags = [d > t for d, t in zip(divergences, thresholds)]

    if any(flags):
        return {
            "decision": "BLOCK",
            "confidence": max(d/t for d, t in zip(divergences, thresholds) if flags),
            "flagged_by": [i for i, f in enumerate(flags) if f],
            "divergences": divergences
        }

    return {
        "decision": "PASS",
        "confidence": max(d/t for d, t in zip(divergences, thresholds)),
        "divergences": divergences
    }
```

### Edge Case: Missing Model

If a model is unavailable (timeout, error, quota exceeded):

1. **Local models**: Retry once with 500ms backoff; if still failing, treat as `divergence = threshold * 1.5` (conservative bias toward BLOCK)
2. **Cloud models**: Retry once with 1s backoff; if still failing, same conservative bias
3. **If 2+ models fail**: Return `BLOCK` — insufficient ensemble coverage for safe classification

## Scoring Methodology

### Ensemble Confidence Score

The confidence score measures how close the decision is to the threshold:

```
confidence = max(divergence_i / threshold_i) for all i
```

- `confidence < 0.5`: Very safe, far from threshold
- `0.5 <= confidence < 1.0`: Approaching threshold, monitor
- `1.0 <= confidence < 1.5`: Clear BLOCK, moderate confidence
- `confidence >= 1.5`: Strong BLOCK, high confidence attack

### Composite Risk Score

Combine ensemble and probe layer outputs into a single risk score:

```
risk_score = w_ensemble * confidence + w_probe * signal_count

where:
  w_ensemble = 0.6
  w_probe = 0.4
  signal_count = number of probe signals that fired (0-4)
```

| Risk Score | Action |
|-----------|--------|
| 0.0 - 0.5 | PASS, no logging needed |
| 0.5 - 1.0 | PASS, log for audit |
| 1.0 - 1.5 | BLOCK, log with medium priority |
| 1.5 - 2.0 | BLOCK, log with high priority, alert security |
| > 2.0 | BLOCK, immediate security alert, quarantine content |

### Calibration Schedule

Recalibrate thresholds monthly using the latest 30 days of:
- Confirmed benign traffic (bottom 90% by divergence)
- Confirmed adversarial samples from incident response
- Synthetic adversarial examples from red team exercises

### Baseline Drift Detection

Track the distribution of `divergences` over time. Alert if:
- Mean divergence of benign traffic shifts by > 10% from baseline
- Any model's 95th percentile divergence shifts by > 15%
- Cross-model correlation of divergences increases (models converging = losing independence)
