# Evaluation Methodology Template

**Instructions:** Copy this template for every calibration claim or benchmark. Fill in all bracketed sections. Do not publish a claim until every mandatory field is completed.

---

## Metadata

| Field | Value |
|-------|-------|
| Methodology ID | `[METHOD-YYYY-MM-DD-N]` e.g., `METHOD-2024-06-15-01` |
| Claim being validated | `[Exact marketing or system claim, e.g., "99.2 % symbol resolution accuracy on held-out data"]` |
| Dataset name & version | `[Name, e.g., trust-score-symbol-calibration v1.0.0]` |
| Dataset DOI | `[10.5281/zenodo.xxxxxxx]` |
| Reproduction script tag | `[Git tag, e.g., v1.0.0-calibration-release]` |
| Author(s) | `[Name, affiliation, ORCID if available]` |
| Reviewer(s) | `[Name, affiliation, review date, verdict]` |
| Last updated | `[YYYY-MM-DD]` |

---

## 1. Claim Definition

### 1.1 Exact Claim Text
> `[Paste the exact sentence as it appears in marketing materials, UI copy, or regulatory filings.]`

### 1.2 Interpretation Notes
- **Scope:** `[What domain, time period, and population does the claim cover?]`
- **Exclusions:** `[What is explicitly NOT covered? (e.g., non-Latin scripts, deprecated tickers)]`
- **Ambiguities resolved:** `[Any clarifications negotiated with stakeholders before operationalization.]`

---

## 2. Metric Operationalization

### 2.1 Primary Metric

| Property | Specification |
|----------|-------------|
| Metric name | `[e.g., Top-1 Exact-Match Accuracy]` |
| Mathematical definition | `[LaTeX or plain formula, e.g., Accuracy = (1/n) Σ_i 1[pred_i == true_i]]` |
| Unit | `[Proportion (0-1) or Percentage (0-100)]` |
| Direction of better | `[Higher is better / Lower is better]` |
| Minimal clinically / practically significant difference | `[e.g., 0.5 percentage points]` |

### 2.2 Secondary Metrics (Mandatory)

At minimum, report the following alongside the primary metric:

| Metric | Why Required |
|--------|-------------|
| Precision (positive predictive value) | Accuracy alone is uninformative under class imbalance. |
| Recall (sensitivity / true positive rate) | Completeness of capture. |
| F1 score | Harmonic mean for imbalanced settings. |
| False Discovery Rate | Critical for trust-score calibration where false positives erode trust. |
| Calibration error (ECE or ACE) | Measures whether predicted probabilities match empirical frequencies. |

### 2.3 Subgroup Metrics

Pre-specify subgroups for disaggregated reporting:

| Subgroup | Rationale | Stratification variable(s) |
|----------|-----------|------------------------------|
| `[e.g., High-frequency symbols]` | `[Most user-facing value]` | `[frequency_quintile]` |
| `[e.g., INFERRED vs EXPLICIT]` | `[Corroboration pipeline differs]` | `inference_flag` |
| `[e.g., Symbol length > 5 chars]` | `[Long tokens are harder]` | `symbol_length` |

**Rule:** If a subgroup contains < 100 samples, report the count but do not report a separate CI (risk of instability). Instead, pool into a broader category.

---

## 3. Population & Sampling

### 3.1 Sampling Frame

- **Universe:** `[All possible observations that could theoretically be included.]`
- **Source system:** `[Pipeline name, database, API.]`
- **Time window:** `[YYYY-MM-DD to YYYY-MM-DD]`
- **Inclusion criteria:** `[Conditions that MUST be true for a sample to enter the dataset.]`
- **Exclusion criteria:** `[Conditions that REMOVE a sample from eligibility.]`

### 3.2 Sampling Method

| Property | Value |
|----------|-------|
| Design | `[Simple random / Stratified random / Systematic / Convenience / Census]` |
| Stratification variables | `[If stratified, list variables and target proportions.]` |
| Random seed | `[Integer; record even for "pseudo-random" designs.]` |
| Target sample size | `[n]` |
| Justification for n | `[Power analysis, margin-of-error calculation, or regulatory mandate.]` |

### 3.3 Power Analysis (Mandatory for Negative Results)

If the claim is a comparison ("new system is not worse than old by more than X"), document power:

- **Null hypothesis (H₀):** `[e.g., accuracy_new - accuracy_old <= -0.02]`
- **Alternative hypothesis (H₁):** `[e.g., accuracy_new - accuracy_old > -0.02]`
- **Alpha:** `[0.05]`
- **Desired power (1-β):** `[0.80]`
- **Minimum detectable effect:** `[0.02]`
- **Calculated required n:** `[Use G*Power, statsmodels, or simulation.]`
- **Actual n achieved:** `[If actual < required, flag as under-powered.]`

---

## 4. Confounders Controlled

### 4.1 Confounder Register

List every variable that could plausibly distort the metric if left uncontrolled:

| ID | Confounder | Expected Direction of Bias | Control Strategy | Status |
|----|------------|---------------------------|------------------|--------|
| C1 | `[e.g., Temporal leakage (future data in training)]` | `[Inflates accuracy]` | `[Enforce strict date cutoff; no samples after cutoff in train]` | Controlled |
| C2 | `[e.g., Annotator fatigue (later samples lower quality)]` | `[Deflates IAA]` | `[Randomize presentation order; monitor IAA by decile]` | Controlled |
| C3 | `[e.g., Class imbalance (common symbols over-represented)]` | `[Inflates accuracy]` | `[Stratified sampling; report macro-F1]` | Acknowledged |

**Definitions:**
- **Controlled:** Active design or analytic step removes or measures the bias.
- **Acknowledged:** Bias is discussed as a limitation; no statistical adjustment possible.
- **Ignored:** Only acceptable with explicit justification and reviewer sign-off.

### 4.2 Temporal Validity & Drift

- **Data collection period:** `[Start date]` to `[End date]`
- **Evaluation period:** `[Start date]` to `[End date]` (must be after collection or a held-out slice)
- **Drift monitoring:** `[How will this claim be re-evaluated quarterly? Reference longitudinal tracking protocol.]`
- **Decay assumption:** `[Estimated shelf-life of the claim; e.g., "Expected valid for 90 days post-release."]`

---

## 5. Statistical Model & Inference

### 5.1 Confidence Intervals

For every reported proportion or mean, specify:

| Claim Type | Recommended CI Method | Rationale |
|------------|----------------------|-----------|
| Proportion (binary outcome) | Clopper-Pearson exact | Conservative; never undercoverages. |
| Proportion (near boundary, e.g., 0.99+) | Wilson score with continuity correction | Better near 0 or 1 than Wald. |
| Mean (normal-ish, n > 30) | t-based (Wald) | Standard; report with SD and n. |
| Mean (skewed or small n) | Bootstrap BCa (10,000 resamples) | Robust to non-normality. |
| Difference of proportions | Newcombe (score-based) | Better coverage than Wald diff. |
| Ratio or complex composite | Bootstrap BCa or parametric bootstrap | Account for covariance structure. |

**Reporting format:**
> Point estimate = 99.2 % (95 % CI [98.94 %, 99.43 %], n = 12,847, method = Clopper-Pearson exact).

### 5.2 Hypothesis Tests

If comparing to a baseline or competitor:

| Element | Value |
|---------|-------|
| Test name | `[e.g., Two-proportion z-test, McNemar's test, paired t-test]` |
| Null hypothesis | `[Formal statement]` |
| Test statistic | `[z = 2.14]` |
| p-value | `[0.032]` |
| Effect size | `[Cohen's h = 0.11]` |
| Decision | `[Reject / Fail to reject H₀ at α = 0.05]` |

**Preference:** Use McNemar's test for paired binary classifications (same test set, two models). Use two-proportion z-test only for independent samples.

### 5.3 Multiple Comparisons

If reporting > 1 subgroup or > 1 metric:

- **Family-wise error control:** `[Bonferroni / Holm-Bonferroni / Benjamini-Hochberg]`
- **Pre-registration:** `[Are subgroup analyses pre-registered? If not, flag as exploratory.]`

---

## 6. Reproduction Steps

### 6.1 Environment

```bash
# 1. Clone reproduction repository
git clone https://github.com/org/calibration-benchmarks.git
cd calibration-benchmarks
git checkout [TAG]

# 2. Create environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt  # pinned hashes

# 3. Download dataset via DOI (or symlink local copy)
python scripts/fetch_dataset.py --doi [DOI] --output ./data/

# 4. Run reproduction
python scripts/reproduce_benchmark.py \
  --dataset ./data/symbol_resolution_test.parquet \
  --split test \
  --output ./results.json

# 5. Inspect
 cat ./results.json | jq '.primary_metrics.accuracy'
```

### 6.2 Expected Runtime

| Step | Approx. Duration | Hardware |
|------|-----------------|----------|
| Dataset download | `[e.g., 2 min]` | Network-bound |
| Metric computation | `[e.g., 30 s]` | CPU-bound; single core sufficient |
| CI computation | `[e.g., 2 min]` | CPU-bound; 4 cores recommended for bootstrap |
| Total | `[e.g., < 5 min]` | — |

### 6.3 Verification

After running, verify:
- [ ] `results.json` SHA-256 matches the value published in the methodology.
- [ ] Row count in `results.json` matches `metadata.json` split count.
- [ ] Confidence interval width is plausible given sample size and proportion.

---

## 7. Limitations & Threats to Validity

### 7.1 Internal Validity

| Threat | Severity | Mitigation |
|--------|----------|------------|
| `[e.g., Label noise from Tier C ground truth]` | Medium | Spot-check 10 % with Tier B adjudication; sensitivity analysis. |
| `[e.g., Train/test leakage via duplicate symbols]` | High | Deduplicated on `symbol_id` before split; hash verification. |

### 7.2 External Validity

| Threat | Severity | Mitigation |
|--------|----------|------------|
| `[e.g., Dataset over-represents US equities]` | High | Acknowledge in claim scope; plan geographic stratification for v2.0.0. |
| `[e.g., Evaluation on static snapshots misses real-time latency errors]` | Medium | Separate latency benchmark; do not conflate with accuracy claim. |

### 7.3 Construct Validity

| Threat | Severity | Mitigation |
|--------|----------|------------|
| `[e.g., "Accuracy" ignores semantic equivalence (IBM vs International Business Machines)]` | Medium | Secondary metric: fuzzy match accuracy; report both. |

---

## 8. Review Log

| Date | Reviewer | Focus Area | Verdict | Action Items |
|------|----------|------------|---------|--------------|
| `[YYYY-MM-DD]` | `[Name, role]` | `[Statistical rigor / Ground truth / Privacy]` | `[Pass / Pass with edits / Fail]` | `[List]` |

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| **Calibration error (ECE)** | Expected Calibration Error: bin predictions, measure |accuracy - confidence| per bin, weight by bin size. |
| **Clopper-Pearson exact CI** | Conservative confidence interval for a binomial proportion based on the F distribution. |
| **Cohen's Kappa** | Inter-annotator agreement statistic correcting for chance agreement. |
| **IAA** | Inter-Annotator Agreement. |
| **MCAR / MAR / MNAR** | Missing Completely At Random / Missing At Random / Missing Not At Random. |
| **Subgroup analysis** | Metric computed on a subset defined by a covariate; must be pre-registered or flagged exploratory. |

## Appendix B: Quick-Start Checklist

Before finalizing this template, confirm:
- [ ] Every marketing claim is mapped to exactly one metric formula.
- [ ] Sample size is justified by power analysis or margin-of-error calculation.
- [ ] All proportions have exact or score-based CIs (never Wald-only for boundary proportions).
- [ ] Confounders are listed; none are silently ignored.
- [ ] Reproduction command produces identical `results.json` on a second machine.
- [ ] Review log contains at least one independent reviewer.
