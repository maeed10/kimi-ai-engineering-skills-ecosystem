---
name: hybrid-code-analyzer
description: 4-layer protocol that augments static AST analysis with runtime profiling to produce complete call graphs for codebases using dependency injection, dynamic imports, and reflection. Use when brownfield-intelligence produces incomplete graphs, before blast-radius-calculator impact analysis, or when graphify flags high-ambiguity regions. Runs inside sandbox-executor during code-tester execution.
---

# Hybrid Code Analyzer

## Overview

Merges static call graphs (from `brownfield-intelligence` / `graphify`) with dynamic execution traces to resolve edges hidden by DI, reflection, dynamic imports, and runtime bytecode generation. Produces a unified call graph where every edge is tagged `STATIC`, `DYNAMIC`, or `BOTH`, with confidence scores and anomaly flags.

## When to Activate

- `brownfield-intelligence` emits a call graph with `< 90%` edge confidence for a module
- Target codebase uses Spring/Angular/Guice, Python `__import__` / `importlib`, JS `import()`, Java reflection / `MethodHandle`, Go `plugin.Open`
- `graphify` flags a region as `high-ambiguity` (unresolved call targets)
- Before `blast-radius-calculator` runs — incomplete graphs produce false-negative impact
- During `code-tester` integration test execution in `sandbox-executor`

## 4-Layer Protocol

```
Layer 1: COLLECT  — run dynamic profiler during integration tests
Layer 2: MERGE    — unify static + dynamic edges (see merge_algorithm.md)
Layer 3: CLASSIFY — tag edges, flag anomalies
Layer 4: VALIDATE — threshold checks before downstream consumption
```

### Layer 1: COLLECT — Dynamic Profiling

Per-language profiler selection:

| Language | Static Tool | Dynamic Profiler | Output Format |
|----------|-------------|------------------|---------------|
| Python | `ast`, `jedi` | `sys.settrace` / `sys.monitoring` | JSON lines: `{"caller": "M", "callee": "N", "ts": T}` |
| Java | `javac -proc`, `soot` | JVMTI / ByteBuddy agent | JSON lines via agent JAR |
| JS/TS | `typescript`, `babel` | V8 coverage / `inspector` protocol | CDP `Profiler.takePreciseCoverage` |
| Go | `go/ast`, `golang.org/x/tools/ssa` | `runtime/trace` + `runtime/pprof` | Custom trace parser |

Steps:
1. Detect language from repo manifest (`pom.xml`, `package.json`, `go.mod`, `requirements.txt`)
2. Inject profiler into `sandbox-executor` test run (see `references/language_profilers.md`)
3. Capture trace output to `.hybrid/traces/{lang}_trace.jsonl`
4. If tests have `< 60%` coverage, warn: dynamic edges may be incomplete

### Layer 2: MERGE — Graph Union with Edge Tags

Run `scripts/merge_call_graph.py`:

```bash
python scripts/merge_call_graph.py \
  --static .brownfield/call_graph.json \
  --dynamic .hybrid/traces/py_trace.jsonl \
  --output .hybrid/merged_graph.json \
  --lang python
```

Merge rules (see `references/merge_algorithm.md` for full spec):
- Edge exists only statically → tag `STATIC`
- Edge exists only dynamically → tag `DYNAMIC`, flag `SURPRISING_RUNTIME_EDGE`
- Edge exists in both → tag `BOTH`
- Static node has zero dynamic outgoing edges → flag `DEAD_STATIC_SUBGRAPH` (investigate for dead code or untested paths)

### Layer 3: CLASSIFY — Anomaly Detection

After merge, compute per-edge confidence:

```
confidence(e) =
  1.0                         if tag == BOTH
  0.6                         if tag == STATIC only, no tests cover caller
  0.4                         if tag == DYNAMIC only (reflection/DI likely)
  min(1.0, dynamic_hits/10)   if tag == DYNAMIC only, repeated observation
```

Flag thresholds:
- `SURPRISING_RUNTIME_EDGE`: DYNAMIC-only edge where caller has > 5 static outgoing edges — possible hidden control flow
- `DEAD_STATIC_EDGE`: STATIC-only edge in a function executed > 10 times at runtime — the static edge was never taken, possible config-gated path
- `INCOMPLETE_TRACES`: test coverage < 60% — dynamic data may miss edges

### Layer 4: VALIDATE — Gate for Downstream Tools

Before writing `.hybrid/merged_graph.json`, enforce:

```yaml
max_surprising_ratio: 0.15   # fail if > 15% edges are DYNAMIC-only
min_coverage_warn: 0.60       # warn if test coverage < 60%
min_coverage_fatal: 0.30      # abort merge if coverage < 30%
min_both_ratio: 0.20          # warn if < 20% edges are BOTH (low validation)
```

If validation fails, emit diagnostic report instead of merged graph. Upstream tool (`blast-radius-calculator`) must check for existence of `.hybrid/merged_graph.json` before consumption.

## Output Schema

`.hybrid/merged_graph.json`:

```json
{
  "meta": {
    "static_source": "brownfield-intelligence",
    "dynamic_source": "sys.monitoring",
    "test_coverage": 0.72,
    "timestamp": "2024-01-15T09:00:00Z"
  },
  "nodes": [ { "id": "pkg.module.Func", "type": "function" } ],
  "edges": [
    {
      "source": "pkg.module.FuncA",
      "target": "pkg.module.FuncB",
      "tag": "BOTH",
      "confidence": 1.0,
      "dynamic_hits": 14,
      "flags": []
    },
    {
      "source": "pkg.module.FuncA",
      "target": "pkg.hidden.DynamicallyLoaded",
      "tag": "DYNAMIC",
      "confidence": 0.45,
      "dynamic_hits": 3,
      "flags": ["SURPRISING_RUNTIME_EDGE"]
    }
  ],
  "diagnostics": {
    "surprising_edge_count": 3,
    "dead_static_edge_count": 7,
    "warnings": ["Test coverage 72% — some dynamic edges may be missing"]
  }
}
```

## Integration with Other Skills

| Skill | Direction | Trigger |
|-------|-----------|---------|
| `brownfield-intelligence` | Input | consumes static call graph |
| `graphify` | Input | consumes ambiguity report to target profiling |
| `sandbox-executor` | Host | runs profiler during test execution |
| `code-tester` | Orchestrator | invokes this skill after tests pass |
| `blast-radius-calculator` | Output | reads merged graph for impact analysis |

## Quick Start

1. Confirm static graph exists: `ls .brownfield/call_graph.json`
2. Run tests with profiler: `cd .hybrid && python scripts/merge_call_graph.py --collect --lang auto`
3. Merge: `python scripts/merge_call_graph.py --static .brownfield/call_graph.json --dynamic .hybrid/traces/*_trace.jsonl --output .hybrid/merged_graph.json`
4. Check diagnostics in output JSON; if `warnings` non-empty, re-run with broader tests
5. Pass `.hybrid/merged_graph.json` to `blast-radius-calculator`
