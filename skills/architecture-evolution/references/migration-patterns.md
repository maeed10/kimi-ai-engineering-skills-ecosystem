# Migration Patterns Reference

## Decision Matrix

| Pattern | Risk | Speed | Team Size | Uptime Requirement | Data Complexity |
|---|---|---|---|---|---|
| Strangler Fig | Low | Slow | Small–Medium | High | Low–Medium |
| Branch by Abstraction | Low | Medium | Small | High | Medium |
| Parallel Run | Medium | Slow | Medium–Large | Critical | High |
| Big Bang | High | Fast | Large | Low (maintenance window) | Low |

## Pattern Definitions

### Strangler Fig (Incremental Replacement)
**When to use**: Replacing an entire legacy system or large subsystem gradually; route traffic incrementally to the new implementation.

**Mechanism**: Place a routing/facade layer in front of the legacy component. New features and migrated modules run behind the facade; traffic is shifted incrementally.

**Phases**:
1. Install facade/router (no behavior change)
2. Implement new service/module behind facade
3. Route low-risk traffic to new implementation
4. Gradually increase traffic; monitor error rate / latency
5. Deprecate and remove old path when new path reaches 100% SLO

**Pros**: Low risk; easy rollback per route; no big-bang cutover
**Cons**: Long-running; facade adds latency; requires robust observability
**Rollback**: Reverse traffic percentage to 0% for the new path

---

### Branch by Abstraction (Feature Toggle Extraction)
**When to use**: Extracting a module or service where the interface can be abstracted; both old and new implementations coexist behind a single abstraction.

**Mechanism**: Introduce an abstraction (interface/adapter) that delegates to either the old or new implementation based on a feature toggle.

**Phases**:
1. Define abstraction interface matching current behavior
2. Refactor old code to implement the abstraction (no behavior change)
3. Build new implementation behind the abstraction
4. Enable toggle for new implementation in shadow/non-prod
5. Enable toggle for a subset of production traffic
6. Remove old implementation and toggle wiring

**Pros**: Clean cutover toggle; easy A/B testing; interface contract is explicit
**Cons**: Dual maintenance during overlap; toggle debt if not cleaned up
**Rollback**: Flip toggle to `use_legacy=true`

---

### Parallel Run (Dual Implementation Validation)
**When to use**: High correctness requirements (financial, safety-critical); run both implementations and compare outputs before trusting the new path.

**Mechanism**: Execute old and new implementations in parallel; compare outputs; only cut over after statistical confidence.

**Phases**:
1. Build new implementation with identical interface
2. Deploy in shadow mode: call new implementation but discard response (logging only)
3. Compare outputs (diff / probabilistic match); tune until error rate < threshold
4. Promote new implementation to primary, keep old as fallback
5. Run in fallback mode for a confidence window
6. Remove old implementation

**Pros**: Highest correctness confidence; detects subtle behavioral drift
**Cons**: Expensive (2x compute); complex comparison logic; slowest path
**Rollback**: Switch primary designation back to old implementation

---

### Big Bang (Coordinated Cutover)
**When to use**: Small, well-understood scope; maintenance window available; team can execute coordinated deploy with rollback-ready artifacts.

**Mechanism**: Build replacement offline; switch all traffic at once during a maintenance window.

**Phases**:
1. Build and test replacement in isolation
2. Freeze writes to affected data during window
3. Migrate data/state to new system
4. Switch traffic (DNS, load balancer, or code flip)
5. Verify health checks and SLOs

**Pros**: Fastest overall; no dual-maintenance period; no facade/toggle overhead
**Cons**: Highest risk; difficult rollback if data has mutated; all-or-nothing
**Rollback**: Revert traffic switch; restore data snapshot if taken; extend maintenance window

---

## Pattern Selection Heuristics

1. If the system has **no downtime tolerance** → eliminate Big Bang; prefer Strangler Fig or Branch by Abstraction
2. If **correctness is safety-critical** → prefer Parallel Run despite cost
3. If **interface is clear and extractable** → Branch by Abstraction is fastest incremental path
4. If **replacing an entire application** → Strangler Fig is the canonical pattern
5. If **scope is < 3 modules and data is small** → Big Bang may be acceptable with explicit approval
6. If **Blast Radius score > 8 for any phase** → switch to a lower-risk pattern or decompose the phase further

## Anti-Patterns

- **Big Bang by default**: Do not choose Big Bang because it feels "simpler" on a whiteboard. It is rarely simpler in production.
- **Toggle sprawl**: Branch by Abstraction without a scheduled toggle-removal ticket leads to permanent dual-path complexity.
- **Facade without observability**: Strangler Fig without per-route error rate and latency metrics is flying blind.
- **Parallel Run without comparison criteria**: Running dual implementations without an automated diff strategy wastes compute and human attention.

## Data Migration Strategies

| Strategy | When | Risk |
|---|---|---|
| CDC (Change Data Capture) | New service needs legacy data stream | Low; eventual consistency |
| Dual-Write | Both systems must stay in sync during overlap | Medium; write-path complexity |
| Snapshot + Replay | One-time migration with history replay | Medium–High; replay fidelity |
| In-Place Schema Change | Same database, new schema | High; rollback is hard |

**Rule**: Prefer CDC or dual-write over in-place mutation. In-place schema changes are treated as Big Bang-equivalent risk and require human approval.
