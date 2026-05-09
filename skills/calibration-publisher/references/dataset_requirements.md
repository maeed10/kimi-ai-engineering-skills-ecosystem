# Dataset Requirements for Calibration Publishing

This document specifies the mandatory format, quality standards, privacy constraints, and versioning rules for any dataset released as ground truth for trust-score calibration claims.

## 1. Format Specification

### 1.1 Supported File Formats

| Format | Use Case | Required Compression |
|--------|----------|-------------------|
| Parquet | Primary; recommended for all tabular data | Snappy or Zstd |
| CSV | Fallback for maximum interoperability | Gzip (`.csv.gz`) |
| JSON Lines | Nested or variable-schema records | Gzip (`.jsonl.gz`) |

**Rule:** Parquet is the default. Only use CSV or JSON Lines when the target journal or regulator explicitly requires it.

### 1.2 Schema Requirements

Every calibration dataset MUST contain the following columns / fields at the top level:

| Field Name | Type | Nullability | Description |
|------------|------|-------------|-------------|
| `sample_id` | `string` (UUIDv4 or CUID) | NOT NULL | Unique, immutable identifier for the observation. |
| `dataset_version` | `string` (SemVer) | NOT NULL | Version of this dataset release (e.g., `v1.0.0-calibration`). |
| `collection_timestamp` | `timestamp[us, UTC]` | NOT NULL | When the sample was originally collected. |
| `split` | `string` | NOT NULL | One of `train`, `calibration`, `test`, `holdout`, `unused`. |
| `ground_truth` | subtype depends on task | NOT NULL | The canonical label (see §2 Ground Truth Standards). |
| `model_prediction` | same as `ground_truth` | NULL allowed | The system's output at evaluation time. Required for accuracy metrics. |
| `inference_flag` | `string` or `null` | NULL allowed | e.g., `EXPLICIT`, `INFERRED`, `DERIVED`. Required for corroboration-rate metrics. |
| `source_system_version` | `string` | NOT NULL | Git tag or build ID of the pipeline that produced the sample. |
| `annotator_id` | `string` or `array<string>` | NULL allowed | Identifier of the human(s) or automated adjudicator that assigned ground truth. |
| `annotation_timestamp` | `timestamp[us, UTC]` | NULL allowed | When ground truth was finalized. |
| `iaa_score` | `float` | NULL allowed | Inter-annotator agreement for this sample (if multiple annotators). |

**Additional task-specific columns** (examples):
- Symbol resolution: `symbol_text`, `predicted_symbol`, `context_window_hash`
- Corroboration: `corroboration_source_count`, `hours_to_first_corroboration`, `corroboration_source_types`

### 1.3 Metadata Sidecar

Every dataset archive MUST include a `metadata.json` file with:

```json
{
  "dataset_name": "trust-score-symbol-resolution-calibration",
  "dataset_version": "1.0.0",
  "release_date": "2024-06-15",
  "description": "Held-out test set for symbol resolution accuracy benchmarking.",
  "total_samples": 12847,
  "split_counts": {"test": 12847, "train": 0, "calibration": 0},
  "ground_truth_method": "expert_consensus",
  "iaa_metric": "cohens_kappa",
  "iaa_aggregate_score": 0.87,
  "license": "CC-BY-4.0",
  "privacy_level": "public_redacted",
  "piir_scan_passed": true,
  "piir_scan_tool": "presidio_analyzer_v2.2",
  "source_system_version": "v3.4.1",
  "columns": [
    {"name": "sample_id", "dtype": "string", "nullable": false}
  ],
  "doi": "10.5281/zenodo.1234567",
  "changelog": "Initial release."
}
```

## 2. Ground Truth Standards

### 2.1 Ground Truth Hierarchy

Ground truth quality is tiered. The tier must be recorded in `metadata.json`.

| Tier | Name | Definition | Minimum IAA |
|------|------|------------|-------------|
| A | Expert Adjudicated | ≥ 2 domain experts reviewed; disagreements resolved by senior arbiter. | Kappa ≥ 0.90 |
| B | Expert Consensus | ≥ 2 experts independently annotated; majority vote or consensus meeting. | Kappa ≥ 0.80 |
| C | Single Expert | 1 expert annotated; spot-check by second expert on 10 % sample. | Kappa ≥ 0.70 on spot-check |
| D | Automated Gold | Verified against an external gold-standard database (e.g., SEC EDGAR, PubMed). | Exact-match accuracy ≥ 99 % on validation sample |

**Publication rule:**
- Claims with safety or regulatory impact MUST use Tier A or B.
- Tier C is acceptable for exploratory / internal-only releases.
- Tier D requires documented provenance of the external database and its own accuracy audit.

### 2.2 Annotation Protocol Documentation

For every dataset, maintain an `ANNOTATION_PROTOCOL.md` inside the archive:

1. **Annotator recruitment:** qualifications, training materials, blind-test passage criteria.
2. **Annotation interface:** screenshot or description of the UI (to assess priming effects).
3. **Adjudication rules:** how conflicts are resolved, reference materials permitted.
4. **Iteration policy:** whether annotators were allowed to revise their own labels after discussion (and if so, how this is flagged).
5. **Bias controls:** randomization of order, blinding to model predictions, counterbalancing of categories.

### 2.3 Temporal Validity

Ground truth can become stale. Define an **expiration policy**:

- **Static symbols (e.g., chemical elements):** no expiration.
- **Dynamic entities (e.g., stock tickers, CEO names):** re-verify ground truth every 12 months.
- **Event-dependent inferences:** re-verify within 30 days of a major structural change (merger, rebrand, delisting).

Flag expired samples in `metadata.json` under `expired_sample_ids` and exclude them from active benchmarks unless a "historical accuracy" metric is explicitly requested.

## 3. Privacy Constraints

### 3.1 PII Redaction & Anonymization

Before publication, the dataset MUST pass through:

1. **Automated scan:** Microsoft Presidio, Google DLP, or equivalent; configured with high-recall rules.
2. **Manual spot-check:** 5 % of flagged rows reviewed by a human; false-positive rate recorded.
3. **K-anonymity check:** for any remaining quasi-identifiers (zip code, birth year, gender), verify k ≥ 5 within the released split.

**Allowed transformations:**
- Replacement of names with `PERSON_001`, `PERSON_002`.
- Truncation of exact dates to month/year or year only.
- Hashing of internal database IDs with a salted, deterministic hash (record salt in private registry, NOT in public archive).

**Prohibited:**
- Releasing raw user IDs, email addresses, IP addresses, or free-text queries that contain self-disclosing content.
- Releasing exact timestamps that could enable timing attacks or session reconstruction.

### 3.2 Differential Privacy (Optional but Encouraged)

For datasets where k-anonymity cannot be achieved:

- Apply **(ε, δ)-differential privacy** at the aggregation stage in `reproduce_benchmark.py`, NOT to the raw dataset.
- Report ε and δ in the methodology template.
- Default: ε = 1.0, δ = 1e-5 for classification metrics; ε = 0.1 for individual record release.

### 3.3 License & Access Control

| Privacy Level | License Example | Access |
|---------------|-----------------|--------|
| `public_redacted` | CC-BY-4.0 | Open download via DOI |
| `restricted_aggregates` | CC-BY-NC-4.0 | Raw data by request; aggregates public |
| `private` | N/A | Internal use only; no DOI issued |

**Rule:** If any row in the dataset is `private`, the entire dataset MUST be `private` or `restricted_aggregates`. Do not mix privacy levels within a single published archive.

## 4. Versioning

### 4.1 Semantic Versioning for Calibration Datasets

Use `MAJOR.MINOR.PATCH-calibration`:

- **MAJOR:** ground-truth labels changed for > 5 % of samples, or inclusion criteria changed.
- **MINOR:** new samples added (< 5 % label change), new columns added, metadata enriched.
- **PATCH:** documentation fixes, compression change, typo corrections in metadata.

### 4.2 Changelog Format

Maintain `CHANGELOG.md`:

```markdown
## [1.1.0] - 2024-09-10
### Added
- 3,200 new samples from Q3 2024 pipeline.
### Changed
- Updated `source_system_version` from v3.4.1 to v3.5.0.
### Fixed
- Corrected 14 ground-truth labels where ticker symbol had changed post-merger (Tier B re-adjudication).
```

### 4.3 Immutability

Published versions are immutable. Zenodo/figshare do not allow file replacement without a new version. Enforce this locally:

- Git-tag the dataset repository before upload.
- Compute a SHA-256 checksum of every file in the archive.
- Store checksums in `checksums.txt` inside the archive AND in the Git tag release notes.

## 5. Validation & Compliance

### 5.1 Automated Validation

Every dataset must pass the following checks (implemented in `scripts/reproduce_benchmark.py`):

| Check | Severity | Description |
|-------|----------|-------------|
| Schema compliance | ERROR | All required columns present with correct dtypes. |
| Null check | ERROR | `sample_id`, `dataset_version`, `collection_timestamp`, `split`, `ground_truth` are non-null. |
| UUID uniqueness | ERROR | `sample_id` values are unique. |
| Split balance | WARN | No split is empty if claimed in metadata. |
| IAA threshold | WARN | Aggregate IAA below tier minimum flagged. |
| Temporal bounds | WARN | `collection_timestamp` outside declared collection window. |

### 5.2 Pre-Release Sign-Off

Before a dataset receives a DOI, two independent reviewers must confirm:

1. Ground-truth labels match the annotation protocol for 20 randomly sampled rows.
2. PII scan report is attached and false-positive rate is documented.
3. Changelog accurately reflects all changes since last version.
4. Checksums match the generated archive.

## 6. Example: Minimum Viable Dataset Archive

```
trust-score-symbol-calibration-v1.0.0/
├── data/
│   └── symbol_resolution_test.parquet
├── metadata.json
├── ANNOTATION_PROTOCOL.md
├── CHANGELOG.md
├── checksums.txt
└── README.md
```

**Size guidance:**
- Target ≥ 5,000 samples for proportion estimates with ±1 % margin at 95 % confidence.
- Target ≥ 1,000 samples per subgroup if disaggregated reporting is required.
- Archive size ≤ 2 GB for Zenodo free tier; split into shards if larger.
