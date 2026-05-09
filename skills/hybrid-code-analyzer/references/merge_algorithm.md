# Graph Merge Algorithm

## Definitions

- **Static graph** `G_s = (V_s, E_s)` from `brownfield-intelligence` / `graphify`
- **Dynamic graph** `G_d = (V_d, E_d)` from runtime profiler
- **Merged graph** `G_m = (V_m, E_m)` where `V_m = V_s ∪ V_d` and `E_m` is tagged

## Node Normalization

Before merge, canonicalize node identifiers to handle language-specific naming gaps:

| Language | Static Format | Dynamic Format | Normalization Rule |
|----------|--------------|----------------|-------------------|
| Python | `pkg.module.func` | `/path/pkg/module.py:func` | Strip `.py`, map file path to module via `sys.path` |
| Java | `pkg.Class.method` | `pkg.Class.method` | Identical (no transform) |
| JS/TS | `file:line:func` | `file:func` | Resolve via source map to original TS name |
| Go | `pkg.Func` | `pkg.Func` | Identical (no transform) |

Normalization is the #1 source of merge errors. If `> 10%` of dynamic edges fail to resolve to static nodes, emit `NORM_FAILURE` warning and fall back to raw-file+line identifiers.

## Merge Algorithm

```python
def merge(G_static: Graph, G_dynamic: Graph, lang: str) -> MergedGraph:
    V_m = normalize_nodes(G_static.nodes | G_dynamic.nodes, lang)
    E_m = []
    diagnostics = Diagnostics()

    # Build lookup sets
    static_edges = {(normalize(e.source, lang), normalize(e.target, lang))
                    for e in G_static.edges}
    dynamic_edges = defaultdict(int)  # (src, tgt) -> hit count
    for e in G_dynamic.edges:
        key = (normalize(e.source, lang), normalize(e.target, lang))
        dynamic_edges[key] += e.hits or 1

    all_pairs = static_edges | set(dynamic_edges.keys())

    for pair in all_pairs:
        src, tgt = pair
        in_static = pair in static_edges
        in_dynamic = pair in dynamic_edges
        hits = dynamic_edges.get(pair, 0)

        if in_static and in_dynamic:
            tag = "BOTH"
            confidence = 1.0
            flags = []
        elif in_static and not in_dynamic:
            tag = "STATIC"
            confidence = 0.6 if is_tested(src) else 0.3
            flags = ["DEAD_STATIC_EDGE"] if is_executed(src) else []
        else:  # DYNAMIC only
            tag = "DYNAMIC"
            confidence = min(1.0, hits / 10.0) if hits > 0 else 0.4
            flags = ["SURPRISING_RUNTIME_EDGE"]

        E_m.append(Edge(src, tgt, tag, confidence, hits, flags))

        if "SURPRISING_RUNTIME_EDGE" in flags:
            diagnostics.surprising_edge_count += 1
        if "DEAD_STATIC_EDGE" in flags:
            diagnostics.dead_static_edge_count += 1

    # Subgraph-level dead code detection
    for node in V_m:
        static_out = {e for e in static_edges if e[0] == node}
        dynamic_out = {e for e in dynamic_edges if e[0] == node}
        if static_out and not dynamic_out and is_executed(node):
            diagnostics.dead_subgraph_nodes.append(node)

    diagnostics.warnings = _validate(E_m, diagnostics)
    return MergedGraph(V_m, E_m, diagnostics)
```

## Confidence Scoring

```
confidence(e) =
  ├─ 1.0                         if tag == BOTH
  ├─ 0.6                         if tag == STATIC  and caller has test coverage
  ├─ 0.3                         if tag == STATIC  and caller has no test coverage
  ├─ min(1.0, hits / 10)         if tag == DYNAMIC and hits > 0
  └─ 0.4                         if tag == DYNAMIC and hits == 0 (fallback)
```

`hits` is the number of times the dynamic profiler observed the call. A call observed `>= 10` times gets full dynamic confidence.

## Validation Thresholds

```yaml
max_surprising_ratio: 0.15   # > 15% DYNAMIC-only edges → investigation needed
min_coverage_warn: 0.60       # coverage 30-60% → warning
min_coverage_fatal: 0.30      # coverage < 30% → abort merge
min_both_ratio: 0.20          # < 20% BOTH edges → low cross-validation confidence
max_norm_failure: 0.10        # > 10% dynamic edges fail normalization → warning
```

Validation produces one of:

| Result | Condition | Action |
|--------|-----------|--------|
| `PASS` | all thresholds met | write merged graph |
| `WARN` | non-fatal thresholds breached | write graph + diagnostics |
| `FAIL` | fatal threshold breached | write diagnostics only, no graph |

## Edge Case Handling

### Unresolved Dynamic Targets
Dynamic traces may show calls to stdlib / framework internals not in the static graph. These are **retained** in `G_m` with tag `DYNAMIC` and a `FRAMEWORK_EDGE` flag. Downstream tools can filter them out.

### Async / Callback Edges
For async calls (Python `asyncio`, JS `Promise`, Java `CompletableFuture`), the runtime stack may show the event loop as caller rather than the originating coroutine. Use language-specific async-aware tracers (see `language_profilers.md`) to resolve the true caller.

### Native / JNI Edges
Java→native calls via JNI appear as `DYNAMIC-only` edges to `native_method`. Tag with `NATIVE_EDGE` flag.

### Polymorphic Dispatch
Static analysis may resolve `obj.method()` to interface type; dynamic trace shows concrete type. Merge creates an edge from caller to concrete callee AND retains the interface edge, flagging the concrete edge as `DYNAMIC` and interface edge as `STATIC`.

## Complexity

- Node normalization: `O(|V_s| + |V_d|)`
- Edge merge: `O(|E_s| + |E_d|)`
- Subgraph scan: `O(|V_s| + |E_s| + |E_d|)`
- Overall: linear in graph size — suitable for million-edge codebases
