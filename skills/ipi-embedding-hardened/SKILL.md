---
name: ipi-embedding-hardened
description: Hardens IPI defense against adversarial embedding attacks via ensemble embeddings across multiple models, behavioral probe layer, and adversarial robustness testing. Use when upgrading ipi-defender, evaluating prompt injection defenses, or when semantic shift detection needs protection against adversarial examples and glitch tokens.
---

# IPI Embedding Hardened

Hardens the IPI defender's semantic shift detection layer (Layer 3) against adversarial examples and glitch tokens that bypass single-model embedding checks. This skill provides the fourth defense layer supplementing pattern scanning (Layer 1), entropy analysis (Layer 2), and semantic shift (Layer 3).

## Defense Layer Architecture

The IPI defender uses a layered defense model. This skill addresses Layer 4:

```
Layer 1: Pattern Scanning      — Regex/static signature matching for known payloads
Layer 2: Entropy Analysis      — Statistical anomaly detection in token distribution
Layer 3: Semantic Shift        — Single-model embedding divergence detection
Layer 4: Ensemble + Probe      — Multi-model consensus + behavioral validation (THIS SKILL)
```

Layer 4 only executes when Layer 3 flags content as potentially anomalous but inconclusive. Layer 4 is the final gate before content reaches the protected LLM.

## Key Principles

- **No single point of failure**: One compromised embedding model cannot bypass the defense
- **Defense in depth**: Layer 4 supplements, never replaces, Layers 1-3
- **Behavioral ground truth**: Probe layer validates semantic classification with actual LLM behavior
- **Continuous validation**: Regular adversarial testing ensures robustness over time

## Layer 4: Ensemble Embedding + Behavioral Probe

### 4.1 Ensemble Embedding Consensus

When Layer 3 (single-model semantic shift) raises a flag, compute divergence across **3 or more independent embedding models**. Flag content as safe **only if ALL models agree on low divergence**.

```pseudocode
function ensembleEvaluate(content, baseline):
    divergences = []
    for model in ensemble_models:
        emb_content = model.encode(content)
        emb_baseline = model.encode(baseline)
        div = cosineDistance(emb_content, emb_baseline)
        divergences.append(div)

    # Consensus: flag if ANY model reports high divergence
    flags = [d > threshold_model for d, threshold_model in zip(divergences, thresholds)]

    if any(flags):
        return {decision: "BLOCK", divergences: divergences, flagged_by: flags}
    else:
        return {decision: "PASS", divergences: divergences}
```

**Consensus rule**: `BLOCK if ANY( divergence_i > threshold_i )`. Never use averaging or majority voting — an adversarial example may fool multiple models but not all.

### 4.2 Behavioral Probe Layer

Feed suspected content to an **isolated probe LLM** (sandboxed, no tool access, lower privilege). Detect anomalous output patterns that indicate prompt injection success.

**Probe signals**:
1. **Refusal rate drop**: Probe LLM refuses benign content at rate R_baseline; flag if refusal rate drops below `R_baseline - delta` for injected content
2. **Output entropy spike**: Measure Shannon entropy of probe outputs; anomalous spikes indicate jailbreak-induced chaos
3. **Instruction leakage**: Detect if probe output contains fragments of system prompts or hidden instructions
4. **Tool call anomalies**: If probe LLM has sandboxed tool access, flag unexpected tool invocations or argument patterns

```pseudocode
function probeEvaluate(content):
    outputs = []
    for trial in 1..N_TRIALS:
        output = probeLLM.generate(content, temperature=0.7)
        outputs.append(output)

    signals = {
        refusal_drop: measureRefusalRate(outputs) < REFUSAL_BASELINE - DELTA,
        entropy_spike: shannonEntropy(outputs) > ENTROPY_THRESHOLD,
        instruction_leak: containsInstructionFragments(outputs),
        tool_anomaly: detectUnexpectedToolCalls(outputs)
    }

    # Flag if 2+ signals fire
    if countTrue(signals.values()) >= PROBE_SIGNAL_THRESHOLD:
        return {decision: "BLOCK", signals: signals}
```

### 4.3 Model Independence Requirements

The ensemble gains no advantage from redundant models. Select models with:

- **Different architectures**: Transformer-based (e.g., sentence-transformers), contrastive (e.g., E5), and autoregressive (e.g., OpenAI embedding)
- **Different training data**: Models trained on disjoint corpora prevent shared blind spots
- **Different tokenizers**: Byte-pair, WordPiece, SentencePiece, or Unigram — adversarial tokens optimized for one tokenizer fail on others
- **Different vendors**: At least 2 different providers to prevent supply-chain correlated failures

See `references/ensemble_config.md` for specific model selection criteria and scoring matrices.

## Adversarial Robustness Testing

Run this test suite weekly and after any embedding model update:

### Test 1: Universal Adversarial Triggers

Evaluate against known universal triggers (prompts that jailbreak diverse LLMs):

```
Test: Inject known universal adversarial suffixes into benign content.
Pass criteria: Layer 4 BLOCKS ≥ 95% of triggers even when Layer 3 passes them.
```

### Test 2: Glitch Token Battery

Test against tokens known to cause anomalous model behavior:

```
Test: Embed glitch tokens (e.g., SolidGoldMagikarp-class tokens, repeated
      special tokens,超长无意义序列) in benign-appearing content.
Pass criteria: No model in the ensemble crashes, hangs, or produces
      undefined embeddings. Layer 4 BLOCKS or safely handles all cases.
```

### Test 3: Adaptive Attack Simulation

Simulate an attacker with knowledge of the ensemble:

```
Test: Run 100 iterations of gradient-based adversarial optimization
      targeting the ensemble's weakest model, then verify other models catch it.
Pass criteria: Attack success rate < 5% against full ensemble.
```

### Test 4: Cross-Model Transfer

Verify adversarial examples don't transfer between ensemble models:

```
Test: Generate adversarial examples optimized for each model individually.
      Test transfer rate to other ensemble models.
Pass criteria: Transfer success rate < 10% between any pair.
```

See `references/adversarial_test_cases.md` for the full test case catalog.

## Integration with ipi-defender

```pseudocode
function ipiDefenderScan(content):
    # Layer 1: Pattern scanning (fastest, highest precision)
    if patternScan(content) == BLOCK:
        return BLOCK

    # Layer 2: Entropy analysis
    if entropyAnalysis(content) == BLOCK:
        return BLOCK

    # Layer 3: Single-model semantic shift
    l3_result = semanticShift(content, baseline)
    if l3_result == BLOCK:
        return BLOCK

    # Layer 4: Ensemble + probe (this skill)
    # Only triggered when Layer 3 is inconclusive or content is borderline
    if l3_result == SUSPICIOUS:
        ensemble_result = ensembleEvaluate(content, baseline)
        if ensemble_result.decision == BLOCK:
            return BLOCK

        probe_result = probeEvaluate(content)
        if probe_result.decision == BLOCK:
            return BLOCK

    return PASS
```

**Performance note**: Layer 4 is expensive. Gate it behind Layer 3's `SUSPICIOUS` classification, not `PASS`. Do not run ensemble + probe on every request.

## Scoring and Threshold Calibration

Calibrate thresholds using a validation set containing:
- 10,000 benign samples (false positive calibration)
- 1,000 known adversarial samples (true positive calibration)
- 100 glitch token cases (edge case calibration)

Procedure:
1. Run ensemble on validation set
2. Set per-model thresholds at 99th percentile of benign divergence
3. Verify this yields < 0.1% false positive rate and > 95% true positive rate
4. If not, adjust thresholds or add models to ensemble

## Incident Response

If Layer 4 blocks content that Layers 1-3 missed:
1. Log full divergence vectors from all ensemble models
2. Capture probe LLM outputs for forensic analysis
3. Generate new adversarial test case from the blocked content
4. Retrain/update embedding models if attack represents novel attack class
5. Alert security team with full chain-of-evidence package

## Production Implementation

This skill includes production-ready Python scripts in `scripts/`:

### `scripts/ensemble_evaluate.py`

Full ensemble embedding consensus implementation supporting:
- **Local models** via `sentence-transformers` (E5, MPNet, MiniLM)
- **Cloud models** via OpenAI API (`text-embedding-3-small`, `text-embedding-3-large`)
- **Mock/test mode** for CI/CD without model dependencies
- Per-model threshold configuration via JSON
- Conservative failure bias: unavailable models default to `threshold × 1.5` (BLOCK)
- Insufficient coverage gate: 2+ model failures force BLOCK

```bash
# Evaluate content against baseline
python scripts/ensemble_evaluate.py --content "suspicious text" --baseline "normal text"

# Run Tier 1 adversarial tests in mock mode
python scripts/ensemble_evaluate.py --test-mode --run-tier1-tests

# Custom ensemble config
python scripts/ensemble_evaluate.py --config ensemble_config.json --content-file payload.txt
```

### `scripts/probe_evaluate.py`

Behavioral probe layer with four signal detectors:
1. **Refusal rate drop** — measures refusal keyword frequency across N trials
2. **Entropy spike** — Shannon entropy analysis of probe outputs
3. **Instruction leakage** — regex detection of system prompt fragments and override markers
4. **Tool call anomaly** — detection of unexpected tool invocation patterns

Supports backends: `mock` (deterministic), `openai` (cloud), `ollama` (local HTTP).

```bash
# Probe content with OpenAI backend
python scripts/probe_evaluate.py --content "suspicious text" --backend openai --model gpt-3.5-turbo

# Run Tier 1 probe tests
python scripts/probe_evaluate.py --backend mock --run-tier1-tests
```

### `scripts/run_adversarial_tests.py`

Orchestrates both ensemble and probe layers against the full adversarial test catalog.
Produces machine-readable JSON reports for CI/CD gating.

```bash
# Run all tiers in test mode
python scripts/run_adversarial_tests.py --all-tiers --test-mode --output report.json

# Run Tier 1 only (critical — all must BLOCK)
python scripts/run_adversarial_tests.py --tier 1 --test-mode
```

### Installation

```bash
pip install -r scripts/requirements.txt
```

## References

- `references/ensemble_config.md` — Model selection matrix, divergence consensus rules, scoring thresholds
- `references/adversarial_test_cases.md` — Universal adversarial triggers, glitch token test battery, adaptive attack templates
