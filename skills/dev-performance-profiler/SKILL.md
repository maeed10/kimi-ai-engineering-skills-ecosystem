---
name: dev-performance-profiler
description: Developer-facing performance profiler that identifies CPU hotspots, memory leaks, I/O bottlenecks, and database query issues. Use when response time degrades, investigating memory leaks, optimizing APIs, analyzing benchmark regressions, or preparing for scale. Generates flame graphs, allocation reports, and ranked optimization recommendations.
---

# Dev Performance Profiler

## Overview

This skill profiles application performance to identify CPU hotspots, memory leaks, I/O bottlenecks, and latency issues. It guides selection of the right profiling tools per language, interprets results, generates flame graphs, and produces ranked optimization recommendations with estimated impact.

Use this skill when:
- Application response time is slow or degrading
- Investigating memory leaks or unexpectedly high memory usage
- Optimizing database queries or API endpoint latency
- Analyzing CI benchmark regressions
- Preparing for high-traffic events or capacity scaling

## Workflow Decision Tree

```
What is the primary symptom?
├── High CPU usage / Slow compute
│   ├── Python → cProfile / py-spy / scalene
│   ├── Go → pprof (CPU profile) / perf
│   ├── Node.js → 0x / Chrome DevTools / clinic doctor
│   ├── Java → async-profiler / JFR
│   └── C/C++/Rust → perf / valgrind callgrind
├── High memory usage / OOM / Leaks
│   ├── Python → tracemalloc / memory_profiler / pympler
│   ├── Go → pprof (heap) / GC trace
│   ├── Node.js → heap snapshots / clinic heapprofiler
│   ├── Java → jmap / JFR Leak Profiler / Eclipse MAT
│   └── C/C++/Rust → heaptrack / valgrind massif / dhat
├── Slow I/O or Network
│   ├── Disk I/O → iostat / strace -e trace=file / bpftrace
│   ├── Network latency → tcpdump / Wireshark / tcprstat
│   └── DNS / Connect → curl -w timings / connect tracing
└── Slow Database Queries
    ├── Slow query log / pg_stat_statements / performance_schema
    ├── EXPLAIN ANALYZE / execution plans
    └── N+1 detection via ORM logging or query log analysis
```

## Step 1: Reproduction & Baseline

Before profiling, establish a reproducible baseline.

1. **Identify the trigger**: specific API endpoint, batch job, user action, or CI benchmark test.
2. **Isolate the environment**: use staging, local production-like build, or a container with resource limits matching production.
3. **Measure baseline metrics**:
   - Latency (p50, p95, p99)
   - Throughput (RPS / jobs per minute)
   - CPU % (user / system / iowait)
   - Memory RSS / heap used
   - Disk I/O (read/write MB/s)
   - Network I/O (bytes/packets)
4. **Document the workload**: payload sizes, concurrency level, dataset size, warm vs cold cache.

## Step 2: Select & Run Profiler

Choose the profiler based on language and symptom. See `references/profiling_tools.md` for setup commands and output formats.

### Quick Language Reference

| Language | CPU Hotspot | Memory Leak | I/O Block | DB Query |
|----------|-------------|-------------|-----------|----------|
| Python | py-spy / cProfile | tracemalloc / memory_profiler | strace / async trace | SQLAlchemy echo / Django Debug Toolbar |
| Go | pprof CPU | pprof heap / allocs | pprof block / mutex / trace | pgx stmt cache / pprof labels |
| Node.js | 0x / clinic doctor | heap snapshots / clinic heap | async_hooks / trace_events | TypeORM logging / Prisma metrics |
| Java | async-profiler / JFR | JFR Old Object Sample / jmap | JFR Socket Read / File I/O | datasource-proxy / p6spy |
| C/C++/Rust | perf / valgrind callgrind | heaptrack / valgrind massif | strace / ioping | libpq / ORM logs |

### Running Profilers

- **CPU**: Capture at least 30–60 seconds of representative load. For sampling profilers, ensure sample rate ≥ 100 Hz.
- **Memory**: Capture heap at peak usage and again after workload completes to detect leaks.
- **I/O**: Correlate syscall traces with application timestamps to identify blocking operations.
- **Database**: Capture slow query logs with `log_min_duration_statement = 100` (PostgreSQL) or `long_query_time = 1` (MySQL).

## Step 3: Generate Flame Graphs

Convert profiling data into interactive flame graphs for visual hotspot identification.

1. **Install FlameGraph tools** (if not bundled):
   ```bash
   git clone https://github.com/brendangregg/FlameGraph.git /opt/FlameGraph
   export PATH=/opt/FlameGraph:$PATH
   ```
2. **Generate from perf** (Linux):
   ```bash
   perf record -F 99 -a -g -- sleep 60
   perf script | stackcollapse-perf.pl | flamegraph.pl > flamegraph.svg
   ```
3. **Generate from py-spy**:
   ```bash
   py-spy record -o flamegraph.svg --pid <PID>
   ```
4. **Generate from Go pprof**:
   ```bash
   go tool pprof -http=:8080 cpu.prof
   # Or export SVG:
   go tool pprof -svg cpu.prof > flamegraph.svg
   ```
5. **Generate from Node.js 0x**:
   ```bash
   0x -o flamegraph.html -- node app.js
   ```
6. **Generate from async-profiler** (Java):
   ```bash
   ./profiler.sh -d 60 -f flamegraph.svg <PID>
   ```

## Step 4: Analyze Results

### CPU Hotspot Analysis
- **Wide plateaus** in flame graph = functions consuming disproportionate time.
- **Tall towers** = deep call stacks; look for recursion or excessive abstraction layers.
- **Kernel time** = system calls, context switches, or lock contention.
- **JIT time** (Java/Node) = deoptimization or GC pressure causing compilation churn.

### Memory Leak Analysis
- **Growth over time** in heap snapshot diffs = leaked objects.
- **Dominant retainers** = largest object trees preventing GC.
- **Allocation site** = constructor / factory most frequently allocating leaked types.
- **Generational promotion** (Java) = short-lived objects escaping to old gen.

### I/O Bottleneck Analysis
- **Blocking read/write** in `strace` = unbuffered or synchronous I/O.
- **High `iowait`** in `top`/`iostat` = disk saturation; consider SSD, batching, or caching.
- **TCP retransmits** in `netstat -s` = network congestion or unstable links.
- **DNS resolution time** in `curl -w` = slow or failing resolver; add caching.

### Database Query Analysis
1. **Sort slow queries** by total_time DESC or count DESC.
2. **Run EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)** on top queries.
3. **Check for**:
   - Seq Scan on large tables → add index or partition
   - Nested Loop with high row counts → enable hash join or rewrite
   - High buffer reads → increase shared_buffers or optimize caching
   - Lock waits → reduce transaction scope or use advisory locks
4. **Detect N+1** by grouping queries: if one query is followed by N similar queries with different IDs, use JOIN / IN / batch loading.

## Step 5: Benchmark Comparison

Compare before/after with statistical rigor.

1. **Run benchmarks** at least 10× per variant (before / after).
2. **Use a consistent harness**: `hyperfine`, `pytest-benchmark`, `Go testing.B`, `JMH`, or `k6`.
3. **Report median and p95/p99**; avoid averaging highly variable latency.
4. **Statistical significance**: use Welch's t-test or Mann-Whitney U; p < 0.05 and effect size > 5% considered meaningful.
5. **CI regression detection**:
   - Store benchmark results as artifacts.
   - Compare current branch vs main with `benchcmp` or custom threshold script.
   - Fail CI if regression > threshold (e.g., +10% latency or +5% memory).

## Step 6: Optimization Recommendations

Rank recommendations by **Impact × Effort** (see `references/optimization_patterns.md`).

### Recommendation Template

```markdown
### 1. [Short Title]
- **Finding**: [What the profiler showed]
- **Impact**: High / Medium / Low
- **Effort**: Small / Medium / Large
- **Action**: [Concrete code / config change]
- **Expected Gain**: [X% latency reduction, Y MB memory saved]
```

### Example Recommendations

1. **Cache repeated database lookups** (Impact: High, Effort: Small)
   - Add Redis or in-process LRU for reference data with 5-min TTL.
   - Expected: 40% reduction in p95 latency for read-heavy endpoints.

2. **Batch insert operations** (Impact: High, Effort: Small)
   - Replace N individual INSERTs with `executemany` or `COPY`.
   - Expected: 10× throughput increase for ingestion pipeline.

3. **Replace synchronous I/O with async** (Impact: Medium, Effort: Medium)
   - Use `aiohttp` / `asyncio` (Python) or async database drivers.
   - Expected: 2× concurrency increase without thread explosion.

4. **Add composite index on (user_id, created_at)** (Impact: High, Effort: Small)
   - Eliminates seq scan on 10M row orders table.
   - Expected: 500 ms → 15 ms query time.

5. **Reduce object allocation in hot loop** (Impact: Medium, Effort: Medium)
   - Reuse buffers, use generators, avoid intermediate lists.
   - Expected: 30% reduction in GC pressure and pause times.

## Step 7: Validation & Regression Guard

1. **Re-run the same profiler** after changes to confirm improvement.
2. **Run load test** (`k6`, `locust`, ` artillery`) at projected peak traffic.
3. **Monitor in production** with APM (Datadog, New Relic, Grafana, OpenTelemetry) for 24–48 h.
4. **Add CI benchmark gate** to prevent regressions; see `scripts/profile_app.py` for automated comparison output.

## Resources

- `references/profiling_tools.md` — Language-specific profiler setup, commands, and output formats
- `references/optimization_patterns.md` — Common optimization patterns with impact/effort rankings
- `scripts/profile_app.py` — Automated profiler launcher, flame graph generator, and recommendation formatter
