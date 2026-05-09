# Trust Attenuation Model

Trust score decay formula, hop limits, and conflict resolution rules for the Federated Memory Mesh.

## Trust Decay Formula

The effective trust of a pattern at the consuming node is:

```
trust_effective = trust_original × (attenuation_factor ^ hop_count)

where:
  attenuation_factor = 0.8
  max_hops = 3
  min_acceptable_trust = 0.5
```

### Decay Table

| Hops | Formula | Effective Trust (from 1.0) | Status |
|---|---|---|---|
| 0 | 1.0 × (0.8^0) | 1.000 | Origin |
| 1 | 1.0 × (0.8^1) | 0.800 | Direct peer |
| 2 | 1.0 × (0.8^2) | 0.640 | Extended mesh |
| 3 | 1.0 × (0.8^3) | 0.512 | Mesh boundary |
| 4 | 1.0 × (0.8^4) | 0.410 | **Rejected** |

### Reverse: Finding Maximum Original Trust for a Given Hop

```
trust_original_min = min_acceptable_trust / (0.8 ^ hop_count)
```

| To survive hop | Minimum original trust required |
|---|---|
| 1 | 0.50 / 0.80 = **0.625** |
| 2 | 0.50 / 0.64 = **0.781** |
| 3 | 0.50 / 0.512 = **0.977** |

A pattern with original trust `0.90` will be rejected at hop 3 because `0.90 × 0.512 = 0.461 < 0.5`.

## Hop Count Rules

1. **Origin node** sets `hop_count = 0` on all shared patterns
2. **Each forwarding node** increments `hop_count` by 1 before re-sharing
3. **Ingress gate** rejects any pattern with `hop_count > 3` regardless of trust score
4. **Query responses** include the actual hop count so the consumer can apply their own attenuation
5. Hop count is an **integer**; no fractional hops

## Conflict Resolution Algorithm

Triggered when `memory-guard` detects two or more patterns with the same `pattern_id` but different `content` hashes.

### Resolution Order

```python
def resolve_conflict(candidates: list[Pattern]) -> Pattern:
    """
    candidates: list of {source, trust_score, hop_count, content_hash, is_local}
    Returns: winning pattern
    """
    # Step 1: Compute effective trust for all candidates
    for c in candidates:
        c.effective_trust = c.trust_score * (0.8 ** c.hop_count)
    
    # Step 2: Filter below threshold
    viable = [c for c in candidates if c.effective_trust >= 0.5]
    if not viable:
        raise RejectAllCandidates()
    
    # Step 3: Sort by (effective_trust desc, is_local desc, hop_count asc)
    viable.sort(key=lambda c: (-c.effective_trust, -c.is_local, c.hop_count))
    
    winner = viable[0]
    
    # Step 4: If top two are within 0.05 effective trust, prefer local
    if len(viable) >= 2:
        runner_up = viable[1]
        if abs(winner.effective_trust - runner_up.effective_trust) <= 0.05:
            if runner_up.is_local and not winner.is_local:
                winner = runner_up  # Local preference tiebreaker
    
    return winner
```

### Winner Determination Summary

| Scenario | Winner | Reason |
|---|---|---|
| A(0.85e/0h/local) vs B(0.72e/1h/remote) | A | Higher effective trust |
| A(0.80e/1h/remote) vs B(0.79e/0h/local) | B | Within 0.05; local preference |
| A(0.64e/2h/remote-X) vs B(0.64e/2h/remote-Y) | A | Identical trust and hops; first-seen (stable sort) |
| A(0.82e/0h/local) vs B(0.82e/0h/local) | — | Exact duplicate; merge silently |
| A(0.48e/3h/remote) alone | — | Rejected; below 0.5 threshold |

### Post-Resolution Actions

After a winner is selected:

1. **Winner** is stored in Layer 4 with `status: active`
2. **Losers** are stored with `status: conflicted`, `superseded_by: {winner.pattern_id}`, and `conflict_reason: {reason}`
3. **Conflicted patterns are not deleted** — they remain queryable for audit purposes
4. **Resolution event** is logged: `{timestamp, pattern_id, winner_source, loser_sources, reason}`
5. If the winner is later removed (e.g., its source node departs), the highest-ranked conflicted pattern is promoted to active

## Trust Score Assignment Guidelines

When authoring a procedural pattern for sharing, assign `trust_score` using these heuristics:

| Source of pattern | Recommended trust_score | Rationale |
|---|---|---|
| Production-tested for > 30 days with no incidents | 0.90–1.00 | High confidence |
| Production-tested for 7–30 days | 0.75–0.89 | Moderate confidence |
| Staging-tested only | 0.60–0.74 | Lower confidence |
| New pattern, peer-reviewed | 0.70–0.85 | Review adds confidence |
| New pattern, unreviewed | 0.50–0.69 | Minimum viable for sharing |
| Inherited from external source | 0.50–0.70 | Distrust by default |

Never assign trust_score < 0.5 — such patterns are rejected at ingress and cannot propagate.

## Topology Anti-Patterns

Avoid these mesh topologies:

### Diamond Routing Loops
```
    A
   / \
  B   C
   \ /
    D
```
If B and C both forward A's pattern to D, D receives two copies. Deduplication by `pattern_id + provenance` prevents double-counting, but prefer tree topologies.

### Long Chains
```
A → B → C → D → E
```
At hop 3 (D→E), even a 1.0 trust pattern has effective trust 0.512. If D's original trust was 0.90, E sees `0.90 × 0.512 = 0.461` — rejected. Keep chains short; use fan-out instead.

### Mesh Partitioning Without Bridges
If two segments have no shared context, they cannot exchange patterns. This is by design — do not bridge unrelated contexts.

## Trust Revocation

If a source node is compromised or its patterns are found to be erroneous:

1. Mesh admin issues a revocation for the node's SPIFFE identity
2. All patterns with `provenance == {revoked_node}` have their trust scores set to `0.0`
3. These patterns are immediately excluded from queries
4. Conflicted patterns that were superseded by the revoked node are re-evaluated; winners are promoted
5. Revocation propagates via gossip within 30 seconds
