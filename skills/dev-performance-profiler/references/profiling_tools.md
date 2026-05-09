# Profiling Tools Reference

Comprehensive guide to language-specific profiling tools, installation, commands, and interpreting their output formats.

## Table of Contents

- [Python](#python)
- [Go](#go)
- [Node.js](#nodejs)
- [Java / JVM](#java--jvm)
- [C / C++ / Rust](#c--c--rust)
- [I/O & Network Profiling](#io--network-profiling)
- [Database Profiling](#database-profiling)
- [Universal Visualization](#universal-visualization)

---

## Python

### CPU Profiling

#### cProfile (stdlib)
- **Setup**: built-in; no install.
- **Run**:
  ```bash
  python -m cProfile -o profile.stats script.py
  ```
- **Analyze**:
  ```python
  import pstats
  p = pstats.Stats('profile.stats')
  p.sort_stats('cumulative').print_stats(20)
  ```
- **Output format**: Binary `.stats` file; text table with `ncalls`, `tottime`, `cumtime`, `filename:lineno(function)`.
- **Best for**: Exact call counts; deterministic profiling. High overhead (~10–20%).

#### py-spy (sampling)
- **Setup**: `pip install py-spy` or `cargo install py-spy`.
- **Run**:
  ```bash
  py-spy top --pid <PID>
  py-spy record -o flamegraph.svg --pid <PID>
  py-spy dump --pid <PID>
  ```
- **Output formats**: Terminal live view; SVG flame graph; JSON dump.
- **Best for**: Low-overhead (<5%) production sampling; no code changes.

#### scalene (CPU + Memory)
- **Setup**: `pip install scalene`.
- **Run**:
  ```bash
  scalene script.py
  ```
- **Output**: HTML report with Python vs native time, memory timeline, and copy volume.
- **Best for**: Identifying Python vs C time and memory per line.

### Memory Profiling

#### tracemalloc (stdlib, Py3.4+)
- **Setup**: built-in.
- **Run**:
  ```python
  import tracemalloc
  tracemalloc.start()
  # ... workload ...
  snapshot = tracemalloc.take_snapshot()
  top_stats = snapshot.statistics('lineno')
  for stat in top_stats[:10]:
      print(stat)
  ```
- **Output format**: Python objects with size, count, traceback.
- **Best for**: Exact allocation site tracking in test scripts.

#### memory_profiler
- **Setup**: `pip install memory_profiler`.
- **Run**:
  ```bash
  python -m memory_profiler script.py
  # or per-function decorator
  from memory_profiler import profile
  @profile
  def my_func():
      ...
  ```
- **Output format**: Line-by-line RSS increment (`MiB`, `Increment`, `Line Contents`).
- **Best for**: Pinpointing memory growth line by line.

#### pympler
- **Setup**: `pip install pympler`.
- **Run**:
  ```python
  from pympler import tracker, muppy, summary
  tr = tracker.SummaryTracker()
  tr.print_diff()
  ```
- **Best for**: Object growth summaries over time.

### Async / I/O Profiling
- **austin**: `pip install austin` — C-level sampling for asyncio; handles event loop stalls.
- **strace**:
  ```bash
  strace -f -e trace=file,desc,network -o trace.log python script.py
  ```

---

## Go

### CPU Profiling

#### net/http/pprof
- **Setup**: import `_ "net/http/pprof"` and expose an HTTP port.
- **Run**:
  ```bash
  curl -o cpu.prof http://localhost:6060/debug/pprof/profile?seconds=30
  go tool pprof -http=:8080 cpu.prof
  ```
- **Output formats**: protobuf profile; pprof CLI (text, graph, flamegraph, SVG, Web UI).
- **Best for**: Integrated, low-overhead sampling; compatible with `go test -bench`.

### Memory Profiling

#### pprof heap
- **Run**:
  ```bash
  curl -o heap.prof http://localhost:6060/debug/pprof/heap
  go tool pprof -http=:8080 heap.prof
  ```
- **Views**: `inuse_space`, `inuse_objects`, `alloc_space`, `alloc_objects`.
- **Best for**: Finding what is retained vs what was ever allocated.

#### GC Trace
- **Run**:
  ```bash
  GODEBUG=gctrace=1 go run main.go
  ```
- **Output**: Stderr lines showing GC pause, heap size, CPU fraction.

### Goroutine / Block / Mutex
- **Goroutine dump**: `curl http://localhost:6060/debug/pprof/goroutine?debug=2`
- **Block profile**: `curl -o block.prof http://localhost:6060/debug/pprof/block`
- **Mutex profile**: `curl -o mutex.prof http://localhost:6060/debug/pprof/mutex`
- **Trace**: `curl -o trace.out http://localhost:6060/debug/pprof/trace?seconds=5 && go tool trace trace.out`

---

## Node.js

### CPU Profiling

#### 0x (flame graph)
- **Setup**: `npm install -g 0x`.
- **Run**:
  ```bash
  0x -o flamegraph.html -- node app.js
  0x --collect-only -- node app.js && 0x --visualize-only <PID>
  ```
- **Output**: Self-contained HTML flame graph with V8 and C++ stacks.
- **Best for**: Zero-config flame graphs; production-safe with `--kernel-tracing`.

#### Chrome DevTools
- **Run**:
  ```bash
  node --inspect-brk app.js
  # Open chrome://inspect → Profile → Take CPU profile
  ```
- **Output**: `.cpuprofile` JSON; load into DevTools or `speedscope`.

#### clinic doctor (diagnosis)
- **Setup**: `npm install -g clinic`.
- **Run**:
  ```bash
  clinic doctor -- node app.js
  clinic doctor --autocannon [ / ] -- node app.js
  ```
- **Output**: HTML report with Event Loop, CPU, Memory, GC graphs.
- **Best for**: Quick health check and bottleneck categorization.

### Memory Profiling

#### Heap Snapshots
- **Run**:
  ```bash
  node --inspect app.js
  # DevTools → Memory → Take heap snapshot
  ```
- **Or programmatically**:
  ```js
  const inspector = require('inspector');
  const session = new inspector.Session();
  session.connect();
  session.post('HeapProfiler.takeHeapSnapshot');
  ```
- **Output**: `.heapsnapshot` JSON; analyze in DevTools or `chrome-devtools-frontend`.

#### clinic heapprofiler
- **Run**:
  ```bash
  clinic heapprofiler -- node app.js
  ```
- **Output**: Allocation timeline + retained size by constructor.

#### memwatch-next (leak detection)
- **Setup**: `npm install memwatch-next`.
- **Use**:
  ```js
  const memwatch = require('memwatch-next');
  memwatch.on('leak', (info) => console.log(info));
  ```

### Async I/O Profiling
- **`node --trace-event-categories node.async_hooks`** generates trace events.
- **`strace -f -e trace=network,desc node app.js`** for syscall-level analysis.

---

## Java / JVM

### CPU Profiling

#### async-profiler
- **Setup**: Download release from GitHub; no agent recompilation required.
- **Run**:
  ```bash
  ./profiler.sh -d 60 -f flamegraph.svg <PID>
  ./profiler.sh -d 60 -f profile.jfr <PID>
  ./profiler.sh -e itimer -d 60 -f flamegraph.svg <PID>  # for containers without perf_events
  ```
- **Output formats**: SVG flame graph, JFR, collapsed stacks, HTML.
- **Best for**: Very low overhead (<1%); includes Java + native + kernel stacks.

#### Java Flight Recorder (JFR) — OpenJDK 11+
- **Run**:
  ```bash
  java -XX:StartFlightRecording=duration=60s,filename=recording.jfr ...
  # or at runtime:
  jcmd <PID> JFR.start duration=60s filename=recording.jfr
  ```
- **Analyze**:
  ```bash
  jfr print --events MethodProfiling,Allocation recording.jfr
  ```
- **Best for**: Built-in, comprehensive events (CPU, memory, I/O, exceptions, locks).

#### VisualVM / JConsole
- **Setup**: Bundled with JDK (`$JAVA_HOME/bin/jvisualvm` or `jconsole`).
- **Best for**: Quick visual inspection of CPU, heap, threads, GC.

### Memory Profiling

#### jmap / jcmd
- **Run**:
  ```bash
  jcmd <PID> GC.heap_dump filename=heap.hprof
  jmap -dump:live,format=b,file=heap.hprof <PID>
  ```
- **Analyze**: Eclipse MAT, VisualVM, or `jhat`.

#### JFR Old Object Sample
- **Run**:
  ```bash
  java -XX:StartFlightRecording=settings=profile,filename=... -XX:FlightRecorderOptions=stackdepth=128 ...
  ```
- **Best for**: Finding leak candidates without heap dump overhead.

### Lock / I/O Profiling
- **JFR Java Monitor Wait / Lock** events for contention.
- **JFR Socket Read / File Read** events for I/O latency.

---

## C / C++ / Rust

### CPU Profiling

#### perf (Linux)
- **Setup**: `sudo apt install linux-tools-common linux-tools-generic`.
- **Run**:
  ```bash
  perf record -F 99 -g -- ./binary
  perf report
  perf script | stackcollapse-perf.pl | flamegraph.pl > flamegraph.svg
  ```
- **Output formats**: `perf.data` binary; `perf report` TUI; FlameGraph SVG.
- **Rust**: Build with `debug = true` and `lto = false` for symbols. Use `cargo flamegraph` (wraps perf).
- **Best for**: System-wide or per-process sampling; minimal overhead.

#### valgrind callgrind
- **Setup**: `sudo apt install valgrind`.
- **Run**:
  ```bash
  valgrind --tool=callgrind --collect-jumps=yes ./binary
  kcachegrind callgrind.out.<PID>
  ```
- **Output**: `callgrind.out.*` with exact instruction counts.
- **Best for**: Deterministic, exact analysis; high overhead (10–50× slower).

### Memory Profiling

#### heaptrack (KDE)
- **Setup**: `sudo apt install heaptrack`.
- **Run**:
  ```bash
  heaptrack ./binary
  heaptrack_gui heaptrack.binary.<PID>.zst
  ```
- **Output**: Allocations over time, peak, leaked memory, call stacks.
- **Best for**: Fast, low-overhead alternative to valgrind; includes flame graph.

#### valgrind massif
- **Run**:
  ```bash
  valgrind --tool=massif ./binary
  ms_print massif.out.<PID>
  ```
- **Output**: Heap snapshots over time with detailed allocation trees.

#### dhat (valgrind / rustc integration)
- **Rust nightly**: `-Zsanitizer=address` or `cargo dhat`.
- **Best for**: Allocation counts and lifetimes, not just size.

#### AddressSanitizer (ASan)
- **Run** (C/C++):
  ```bash
  clang -fsanitize=address -g -O1 main.c -o main && ./main
  ```
- **Run** (Rust):
  ```bash
  RUSTFLAGS="-Z sanitizer=address" cargo +nightly run -Zbuild-std --target x86_64-unknown-linux-gnu
  ```
- **Best for**: Detecting use-after-free, leaks, buffer overflows at runtime.

---

## I/O & Network Profiling

### strace
- **Run**:
  ```bash
  strace -f -T -tt -e trace=file,desc,network -o trace.log -p <PID>
  ```
- **Output**: Syscalls with timestamps and durations. Filter with `grep` for slow calls.
- **Best for**: Identifying blocking file reads, excessive `stat` calls, network `recvfrom` stalls.

### iostat / iotop / pidstat
- **Run**:
  ```bash
  iostat -xz 1
  pidstat -d 1
  ```
- **Output**: Device utilization (`%util`), queue depth (`aqu-sz`), throughput (`kB_read/s`).
- **Best for**: Disk saturation and per-process I/O.

### tcpdump / tshark
- **Run**:
  ```bash
  tcpdump -i any -w capture.pcap host <TARGET_IP>
  tshark -r capture.pcap -q -z io,stat,1,"tcp.analysis.retransmission"
  ```
- **Output**: PCAP for Wireshark analysis; retransmission counts; latency breakdown.

### Wireshark Analysis Tips
- **Statistics → TCP Stream Graphs → Round Trip Time Graph** for latency spikes.
- **Analyze → Expert Info** for retransmissions, window full, duplicate ACKs.

### bpftrace / eBPF
- **Run** (one-liners):
  ```bash
  bpftrace -e 'kprobe:vfs_read { @[comm] = count(); }'
  bpftrace -e 'tracepoint:syscalls:sys_enter_read /pid == <PID>/ { @start[tid] = nsecs; } tracepoint:syscalls:sys_exit_read /@start[tid]/ { @us[comm] = hist((nsecs - @start[tid]) / 1000); delete(@start[tid]); }'
  ```
- **Best for**: Kernel-level tracing with near-zero overhead; requires root and BCC.

---

## Database Profiling

### PostgreSQL

#### Slow Query Log
- **Config** (`postgresql.conf`):
  ```
  log_min_duration_statement = 100
  log_line_prefix = '%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h '
  ```
- **Analyze**:
  ```bash
  pg_badger /var/log/postgresql/postgresql-*.log -o report.html
  ```

#### pg_stat_statements
- **Enable**: `shared_preload_libraries = 'pg_stat_statements'`.
- **Query**:
  ```sql
  SELECT query, calls, mean_exec_time, stddev_exec_time, rows
  FROM pg_stat_statements
  ORDER BY mean_exec_time DESC
  LIMIT 10;
  ```

#### EXPLAIN ANALYZE
- **Run**:
  ```sql
  EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT ...;
  ```
- **Look for**: Seq Scan, high `Buffers: shared read=`, Nested Loops with high actual rows.

### MySQL / MariaDB

#### Slow Query Log
- **Config**:
  ```ini
  slow_query_log = 1
  long_query_time = 1
  log_queries_not_using_indexes = 1
  ```
- **Analyze**: `pt-query-digest /var/log/mysql/slow.log > digest.txt`

#### Performance Schema
- **Query**:
  ```sql
  SELECT DIGEST_TEXT, SCHEMA_NAME, COUNT_STAR, AVG_TIMER_WAIT
  FROM performance_schema.events_statements_summary_by_digest
  ORDER BY AVG_TIMER_WAIT DESC
  LIMIT 10;
  ```

### MongoDB

#### Database Profiler
- **Enable**:
  ```js
  db.setProfilingLevel(1, { slowms: 100 })
  ```
- **Query**:
  ```js
  db.system.profile.find().sort({ millis: -1 }).limit(10)
  ```
- **Use `.explain("executionStats")`** on slow queries to check `docsExamined` vs `nReturned`.

---

## Universal Visualization

### FlameGraph
- **Repo**: https://github.com/brendangregg/FlameGraph
- **Usage**:
  ```bash
  git clone https://github.com/brendangregg/FlameGraph.git /opt/FlameGraph
  export PATH=/opt/FlameGraph:$PATH
  perf script | stackcollapse-perf.pl | flamegraph.pl > fg.svg
  ```

### speedscope
- **Setup**: `npm install -g speedscope` or use https://www.speedscope.app/.
- **Supports**: `.cpuprofile`, `pprof`, `stackcollapse` text, JSON.
- **Run**:
  ```bash
  speedscope profile.json
  ```

### Hotspot (Linux GUI for perf)
- **Setup**: `sudo apt install hotspot`.
- **Usage**: `hotspot --input perf.data`.
