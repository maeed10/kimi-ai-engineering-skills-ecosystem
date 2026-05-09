# Trust Scoring Rules and Decay Formulas

## Document Purpose

This reference defines the deterministic rules for computing memory trust scores, applying temporal decay, and enforcing corroboration thresholds in the `memory-guard` system. It is loaded into agent context during all memory write, read, consolidate, and resume operations to ensure scores are never set by LLM inference.

---

## 1. Source Classification

Every memory entry must be classified by exactly one source class at creation time. Classification is immutable for the lifetime of the entry.

| Source Class | Base Score | Rationale |
|--------------|------------|-----------|
| `STRUCTURAL` | `0.9` | Derived directly from parseable, version-controlled codebase artifacts (AST, file tree, dependency graph, test results). Low hallucination risk. |
| `INFERRED`   | `0.6` | Produced by LLM reasoning, pattern extraction, summarization, or synthesis. Moderate hallucination risk; requires verification before promotion. |
| `EXTERNAL`   | `0.3` | Originates from user input, web search, third-party documentation, Stack Overflow, or any unverified external claim. High hallucination/injection risk. |

### Classification Rules

- **Codebase facts** (file exists, function signature, import statement, class hierarchy) → `STRUCTURAL`
- **Agent-derived patterns** ("this project uses Repository pattern", "common error is X") → `INFERRED`
- **User statements, search results, docs** → `EXTERNAL`
- If a fact spans multiple classes, use the **lowest-trust** applicable class.
- The LLM **must not** override classification. The `policy-engine` enforces this.

---

## 2. Composite Trust Score Formula

The composite trust score is a real number in `[0.0, 1.0]` computed as:

```
score = base_score(source_class)
        * corroboration_factor(corroboration_count)
        * verification_factor(verification_status)
        * recency_factor(source_class, sessions_elapsed)
```

All factors are multiplicative. The result is rounded to 4 decimal places and clamped to `[0.0, 1.0]`.

### 2.1 Base Score

```
base_score(source_class) =
    0.9  if source_class == STRUCTURAL
    0.6  if source_class == INFERRED
    0.3  if source_class == EXTERNAL
```

### 2.2 Corroboration Factor

Corroboration counts the number of **independent** sources (distinct sessions, distinct tools, distinct user confirmations) that assert the same fact. Conflicting sources reduce the factor.

```
corroboration_factor(n) =
    1.0  if n >= 2
    0.8  if n == 1
    0.5  if n == 0 or conflicting sources present
```

**Procedural Memory Rule:** `corroboration_count >= 2` is **mandatory** for any entry written to procedural memory. A procedural entry with `n < 2` is rejected by `MemoryGuard.promote_to_semantic()`.

### 2.3 Verification Factor

```
verification_factor(status) =
    1.0  if status == VERIFIED
    0.7  if status == PENDING
    0.5  if status == UNVERIFIED
    0.4  if status == FAILED
```

- `VERIFIED`   — Brownfield SQLite index confirms the pattern exists in the codebase.
- `PENDING`    — Submitted for verification, awaiting Brownfield query result.
- `UNVERIFIED` — Brownfield query returned no match; fact remains in episodic layer only.
- `FAILED`     — Brownfield query returned a conflicting result or the fact was rejected by `ipi-screener.py`.

### 2.4 Recency Factor (Temporal Decay)

The recency factor models loss of confidence over time for non-structural memories.

```
recency_factor(class, sessions_elapsed) =
    1.0 ^ sessions_elapsed                if class == STRUCTURAL   (no decay)
    0.95 ^ sessions_elapsed               if class == INFERRED
    0.90 ^ sessions_elapsed               if class == EXTERNAL
```

Where `sessions_elapsed` is the number of agent sessions since the memory was last **reinforced**.

#### Reinforcement Rule

A memory is reinforced when it is successfully used in a tool execution and the tool output is confirmed correct (e.g., test passes, file write succeeds, compilation succeeds).

```
on_reinforcement(score) = min(max(score, base_score * 0.95), 0.95)
```

Reinforcement resets `sessions_elapsed` to `0` for that memory.

---

## 3. Score Thresholds and Actions

| Threshold | Action |
|-----------|--------|
| `score >= 0.8` | Eligible for procedural memory (with corroboration >= 2) |
| `score >= 0.6` | Eligible for semantic memory promotion |
| `score >= 0.4` | Retained in active episodic search index |
| `score < 0.4` | Flagged low-trust; hidden from default retrieval |
| `score < 0.25` | Auto-archived to `vault/_agent/memory/archived/` |

### Archival Policy

- Archival is **move**, not delete. Full provenance and signature chain are preserved.
- Archived memories are removed from active semantic/episodic search indices.
- They remain in the manifest and can be retrieved for forensic audit.

---

## 4. Obsolescence via Semantic Drift

In addition to score-based archival, `drift-monitor` computes a semantic drift score `d` per memory topic.

```
if days_unused > 30 and drift_score > 0.4:
    archive(memory)
```

- `days_unused` = `now - last_accessed` in calendar days
- `drift_score` = cosine distance between the memory embedding and current codebase embedding for the same topic
- A memory that is both stale and semantically drifted is assumed obsolete.

---

## 5. Determinism Guarantees

To prevent LLM manipulation of trust scores, the following invariants are enforced:

1. **Immutable Classification** — Source class is set once at creation and stored in the entry. It cannot be changed by any subsequent operation.
2. **No LLM Score Override** — The `trust_score` field in any memory JSON is **read-only** after initial computation. Any write attempting to change it is rejected.
3. **Formula Auditability** — All four factors (base, corroboration, verification, recency) are logged in the provenance metadata so the score can be independently recomputed.
4. **Policy Enforcement** — The `policy-engine` validates that every memory write includes the expected score range for its declared source class. Out-of-range scores trigger an integrity alert.

---

## 6. Quick Reference: Score Examples

| Source | Corroboration | Status | Sessions | Reinforced? | Calculation | Score |
|--------|---------------|--------|----------|-------------|-------------|-------|
| STRUCTURAL | 1 | VERIFIED | 0 | No | 0.9 * 0.8 * 1.0 * 1.0 | **0.7200** |
| STRUCTURAL | 2 | VERIFIED | 3 | No | 0.9 * 1.0 * 1.0 * 1.0 | **0.9000** |
| INFERRED   | 1 | PENDING  | 2 | No | 0.6 * 0.8 * 0.7 * 0.95^2 | **0.3032** |
| INFERRED   | 2 | VERIFIED | 5 | Yes | min(0.6 * 1.0 * 1.0 * 0.95^5, 0.95) | **0.4639** |
| EXTERNAL   | 1 | PENDING  | 1 | No | 0.3 * 0.8 * 0.7 * 0.90^1 | **0.1512** |
| EXTERNAL   | 2 | VERIFIED | 4 | No | 0.3 * 1.0 * 1.0 * 0.90^4 | **0.1968** |
| EXTERNAL   | 1 | FAILED   | 0 | No | 0.3 * 0.8 * 0.4 * 1.0 | **0.0960** → **ARCHIVED** |

---

## 7. Integration with Consolidation Pipeline

During `consolidate-memory.py`:

1. For each candidate pattern, call `TrustEngine.compute(...)` with:
   - `source_class` = inferred from origin entries (lowest class wins)
   - `corroboration_count` = number of distinct sessions asserting the pattern
   - `verification_status` = result of Brownfield SQLite query
2. If computed score < 0.6, the candidate is **rejected** for semantic promotion.
3. If source class is `EXTERNAL` and verification status is not `VERIFIED`, the candidate is **rejected** regardless of score.
4. If the candidate is procedural and `corroboration_count < 2`, it is **rejected**.
5. Promoted entries include a `provenance` block with all factor values for later audit.
