---
name: calibration-publisher
description: Trust score calibration dataset and methodology publisher. Use when updating calibration parameters, publishing benchmarks for peer review, migrating from preliminary to longitudinal validation, or preparing academic submissions. Releases datasets with ground truth, full protocols, reproducible scripts, and confidence intervals.
---

# calibration-publisher

## Overview

Converts marketing-level trust-score claims (e.g., "99.2 % symbol resolution accuracy", "73 % INFERRED corroboration rate") into independently verifiable calibration artifacts: versioned datasets with ground-truth labels, fully documented evaluation protocols, open-source reproduction scripts, and statistically rigorous confidence intervals.

This skill implements the **Publishing Workflow** for releasing or updating calibration artifacts. It ensures every reported number is traceable to a reproducible computation on a citable dataset.

## When to Use

- **Updating calibration parameters** — trust-score thresholds, accuracy baselines, or corroboration rates have changed and must be re-released with evidence.
- **Publishing benchmarks for peer review** — preparing a dataset + protocol for external scrutiny.
- **Migrating from preliminary to longitudinal validation** — moving from a one-off pilot to a tracked, quarterly-updated benchmark.
- **Responding to skepticism about empirical claims** — an auditor, reviewer, or customer asks "How was this number derived?"
- **Preparing academic or regulatory submission** — creating a Zenodo/figshare deposit with DOI, or a supplemental material package for a paper.

## Workflow Decision Tree

```text
Is this a new calibration release or an update to an existing one?
├── NEW RELEASE
│   ├── 1. Define claim → metric mapping
│   ├── 2. Build / update ground-truth dataset (see references/dataset_requirements.md)
│   ├── 3. Draft evaluation protocol (see references/methodology_template.md)
│   ├── 4. Implement reproduce_benchmark.py
│   ├── 5. Run script & capture outputs
│   ├── 6. Compute confidence intervals & statistical tests
│   ├── 7. Write release notes & changelog
│   └── 8. Deposit dataset to Zenodo/figshare → obtain DOI
│
└── UPDATE EXISTING
    ├── A. Has the dataset changed?
    │   └── YES → bump version, document diff, re-run full protocol
    ├── B. Has the claim changed?
    │   └── YES → update metric definitions, re-run script, verify CI overlap
    ├── C. Is this a longitudinal checkpoint?
    │   └── YES → append quarter to tracking log, run trend analysis
    └── D. Merge results → update DOI metadata & release notes
```

## Core Capabilities

### 1. Dataset Publishing

Every published calibration claim must be backed by a **released dataset** with:

- **Ground-truth labels** produced by an auditable process (expert annotation, consensus adjudication, or gold-standard reference).
- **Unique identifiers** per sample (UUID or deterministic hash) to prevent leakage.
- **Split definitions** (train / calibration / test / holdout) frozen at release time.
- **Metadata** capturing annotator IDs, timestamp, source system version, and any PII redaction flags.
- **Format compliance** with the schema defined in `references/dataset_requirements.md`.

**Release checklist:**
- [ ] Dataset passes schema validation (`validate_dataset.py` stub included in reproduction script).
- [ ] Ground-truth inter-annotator agreement (IAA) >= threshold (default Cohen's Kappa >= 0.80).
- [ ] No PII or sensitive tokens present (verified by automated scan + manual spot-check).
- [ ] Version tag matches semantic versioning (`v1.0.0-calibration`).
- [ ] README.md inside dataset archive explains collection date, source, and license.

### 2. Methodology Documentation

The `references/methodology_template.md` provides a **complete evaluation protocol** that must be filled in for every claim. Key sections:

| Section | Purpose |
|---------|---------|
| Claim definition | Exact sentence being validated |
| Metric operationalization | How the marketing phrase maps to a formula |
| Population & sampling | Frame, inclusion/exclusion, randomization |
| Confounders controlled | List of variables held constant or stratified |
| Statistical model | Test used, significance level, power analysis |
| Reproduction steps | Command-line invocations to regenerate numbers |
| Limitations & threats | External validity risks, dataset bias, temporal drift |

**Rule:** If a claim cannot be expressed as a deterministic formula applied to rows in the dataset, it is not yet ready for publication.

### 3. Reproducible Scripts

The `scripts/reproduce_benchmark.py` is the **source of truth** for published numbers. It must:

1. Load the exact dataset version referenced by DOI.
2. Apply the exact metric formulas from the methodology template.
3. Print point estimates, confidence intervals, sample sizes, and p-values.
4. Produce a machine-readable `results.json` artifact.
5. Fail with a non-zero exit code if any validation step fails.

**Integration with CI:**
- Store `results.json` as a build artifact.
- On every pull request that touches trust-score logic, diff `results.json` against the baseline; flag regressions > 0.5 % absolute.

### 4. Longitudinal Tracking

Calibration parameters are **not static**. This skill mandates quarterly re-evaluation:

- **Quarterly snapshot:** re-run `reproduce_benchmark.py` on the most recent 90 days of held-out data.
- **Trend analysis:** fit a simple linear model (or LOESS) to accuracy / corroboration rate over time.
- **Drift alert:** if a 95 % CI for the current quarter does not overlap the prior quarter's CI, trigger a calibration review.
- **Publication:** append results to `LONGITUDINAL.md` in the dataset repository; update Zenodo record with new file version.

### 5. Confidence Intervals & Statistical Rigor

No claim may be published without:

- **Sample size (n)** — number of independent observations.
- **Point estimate** — mean, proportion, or median as appropriate.
- **Confidence interval** — 95 % CI by default; 99 % CI for safety-critical claims.
- **Test statistic** — e.g., Clopper-Pearson exact binomial CI for proportions; bootstrap BCa for complex ratios.
- **Effect size** — Cohen's h, odds ratio, or AUC depending on metric class.

**Prohibited:** reporting "99.2 %" without CI bounds, sample size, or test name.

### 6. Peer Review Integration

To satisfy academic or regulatory scrutiny:

1. **Deposit dataset** on Zenodo or figshare → obtain DOI.
2. **Deposit reproduction package** (code + environment lock file) on GitHub/GitLab with release tag.
3. **Cite both** in every document that repeats the claim:
   > "Symbol resolution accuracy = 99.2 % (95 % CI [98.9, 99.4], n = 12,847; see Dataset [DOI] and Protocol [tag])."
4. **Request pre-publication review** from at least one statistician or domain expert for new protocols.
5. **Maintain a review log** in `reviews/` directory: date, reviewer, verdict, action items.

## Reproducibility Checklist (Use Before Every Release)

Copy this checklist into the release issue / pull request and tick every box.

### Dataset Integrity
- [ ] Dataset version is tagged and pushed.
- [ ] Ground-truth labels are frozen; no post-hoc edits allowed without version bump.
- [ ] Row count matches methodology sample-size calculation.
- [ ] Schema validation passes (`validate_dataset` function in reproduction script).
- [ ] IAA score recorded and >= 0.80 (or documented exception).

### Methodology
- [ ] Every marketing claim has a 1-to-1 mapping to a computable metric.
- [ ] Confounders are listed and either controlled or acknowledged as open threats.
- [ ] Significance level (alpha) stated; default 0.05.
- [ ] Power analysis included for negative results ("we had 80 % power to detect a 2 % drop").

### Script & Computation
- [ ] `reproduce_benchmark.py` runs in a clean environment (Docker / virtualenv) and produces identical `results.json`.
- [ ] All random seeds are fixed or logged.
- [ ] No hard-coded paths; dataset loaded via DOI URL or local symlink.
- [ ] Script exits non-zero on validation failure.

### Statistical Reporting
- [ ] Every proportion has a Clopper-Pearson or Wilson CI.
- [ ] Every mean has a bootstrap BCa or t-based CI.
- [ ] Sample sizes are reported for every stratum (overall + subgroups).
- [ ] Subgroup analyses are pre-registered or flagged as exploratory.

### Publication
- [ ] Zenodo/figshare record created or updated; DOI inserted into `results.json`.
- [ ] Git tag pushed matching dataset version.
- [ ] Release notes include: what changed, why, and impact on numbers.
- [ ] Review log updated (even if review was internal).

## Resources

### scripts/
- **`reproduce_benchmark.py`** — End-to-end reproduction script. Loads dataset, computes metrics, generates CIs, writes `results.json`, and validates schema. Designed to be run in CI.

### references/
- **`dataset_requirements.md`** — Schema specification for calibration datasets. Covers format (Parquet/CSV/JSON), ground-truth standards, privacy constraints, versioning, and metadata.
- **`methodology_template.md`** — Fill-in-the-blank evaluation protocol. Defines claim-to-metric mapping, sampling plans, confounder controls, statistical models, and limitations.

## Quick Reference: Claim → Metric Mapping Example

| Marketing Claim | Operational Metric | Formula | Dataset Column(s) |
|-----------------|---------------------|---------|-------------------|
| "99.2 % symbol resolution accuracy" | Top-1 exact-match accuracy on held-out symbol test set | `correct / total` where `correct = (pred == ground_truth)` | `symbol_id`, `predicted_symbol`, `true_symbol`, `split` |
| "73 % INFERRED corroboration rate" | Proportion of INFERRED-flagged trust events with >= 1 corroborating source within 24 h | `corroborated_inferred / total_inferred` where `corroborated = (source_count >= 1 AND timedelta <= 24h)` | `trust_event_id`, `inference_flag`, `corroboration_source_count`, `hours_to_corroboration` |

**Usage:** When a stakeholder provides a new marketing number, paste it into the first column and force completion of the remaining three columns before any dataset or script work begins.

## Exit Criteria

A calibration release is complete when:
1. `reproduce_benchmark.py` runs without error and produces `results.json`.
2. `results.json` contains matching numbers for every claim in the release notes.
3. Dataset DOI is active and metadata matches the record.
4. Methodology template is fully filled and signed off by reviewer.
5. Reproducibility checklist above is entirely checked.
