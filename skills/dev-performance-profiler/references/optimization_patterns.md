# Optimization Patterns Reference

Common performance optimization patterns with impact ratings, effort estimates, implementation guidance, and applicability per language/runtime.

## Legend

| Symbol | Meaning |
|--------|---------|
| **Impact** | High / Medium / Low — expected magnitude of improvement |
| **Effort** | Small / Medium / Large — implementation and testing cost |
| **Risk** | Low / Medium / High — chance of regressions or bugs |

---

## 1. Caching

### In-Process LRU Cache
- **Impact**: High | **Effort**: Small | **Risk**: Low
- **When to use**: Reference data, computed values, config lookups hit repeatedly in the same process.
- **Python**:
  ```python
  from functools import lru_cache
  @lru_cache(maxsize=1024)
  def get_user_role(user_id: int) -> str: ...
  ```
  Or `cachetools.TTLCache` for TTL eviction.
- **Go**:
  ```go
  import "github.com/hashicorp/golang-lru"
  cache, _ := lru.New(128)
  ```
- **Java**:
  ```java
  Cache<String, User> cache = Caffeine.newBuilder()
      .maximumSize(10_000)
      .expireAfterWrite(5, TimeUnit.MINUTES)
      .build();
  ```
- **Node.js**:
  ```js
  const LRU = require('lru-cache');
  const cache = new LRU({ max: 500, ttl: 1000 * 60 * 5 });
  ```
- **Caution**: Avoid caching mutable objects. Set explicit TTL or max size to prevent unbounded growth.

### Distributed Cache (Redis / Memcached)
- **Impact**: High | **Effort**: Medium | **Risk**: Medium
- **When to use**: Multi-instance deployments, session state, rate-limit counters, heavy DB read queries.
- **Patterns**:
  - **Cache-aside**: App reads cache first; on miss, reads DB and writes cache.
  - **Write-through**: Writes go to cache, which synchronously writes DB.
  - **Write-behind**: Writes go to cache, which asynchronously flushes to DB.
- **Redis tips**:
  - Use `EX` / `PX` for TTL; prefer `Hash` over many keys for related fields.
  - Enable `maxmemory-policy allkeys-lru` for automatic eviction.
  - Pipeline `GET` / `SET` commands to reduce RTT.

### CDN / Edge Caching
- **Impact**: High | **Effort**: Small | **Risk**: Low
- **When to use**: Static assets, API responses with low freshness requirements.
- **Actions**: Set `Cache-Control: public, max-age=31536000` for versioned assets; use stale-while-revalidate for dynamic content.

---

## 2. Batching

### Database Batch Inserts / Updates
- **Impact**: High | **Effort**: Small | **Risk**: Low
- **When to use**: Ingestion pipelines, ETL, bulk imports, queue consumers.
- **Python** (`psycopg3`):
  ```python
  with conn.cursor() as cur:
      cur.executemany("INSERT INTO logs (level, msg) VALUES (%s, %s)", rows)
      # Or for very large loads:
      with cur.copy("COPY logs (level, msg) FROM STDIN") as copy:
          for row in rows:
              copy.write_row(row)
  ```
- **Go** (`pgx`):
  ```go
  copyCount, err := conn.CopyFrom(ctx, pgx.Identifier{"logs"}, []string{"level","msg"}, pgx.CopyFromSlice(len(rows), func(i int) ([]interface{}, error) { ... }))
  ```
- **Node.js** (`pg`):
  ```js
  await pg.query('INSERT INTO logs (level, msg) SELECT * FROM UNNEST($1::text[], $2::text[])', [levels, msgs]);
  ```
- **Expected gain**: 5–20× throughput for bulk operations.

### API Request Batching
- **Impact**: Medium | **Effort**: Medium | **Risk**: Medium
- **When to use**: Microservice chatter, GraphQL N+1 fields, SaaS API limits.
- **Pattern**: Implement a DataLoader-style batching function that coalesces requests within an event loop tick.
- **Example** (GraphQL):
  ```js
  const DataLoader = require('dataloader');
  const userLoader = new DataLoader(async (ids) => {
      const users = await db.users.findMany({ where: { id: { in: ids } } });
      return ids.map(id => users.find(u => u.id === id));
  });
  ```

### Message Queue Batching
- **Impact**: Medium | **Effort**: Small | **Risk**: Low
- **When to use**: Kafka producers, SQS senders, log shippers.
- **Action**: Set `linger.ms` (Kafka) or flush every N messages / T milliseconds rather than per-message.

---

## 3. Async & Concurrency

### Async I/O (Non-blocking Database / HTTP)
- **Impact**: Medium–High | **Effort**: Medium | **Risk**: Medium
- **When to use**: High-concurrency services where threads/processes are the bottleneck.
- **Python**: Use `asyncpg`, `aiohttp`, `httpx` async; migrate from `requests` + threads.
- **Node.js**: Already async by default; avoid `fs.*Sync` and CPU-intensive tasks in the main thread. Offload to worker threads.
- **Go**: Goroutines are cheap; use `errgroup` or worker pools. Avoid excessive goroutine leaks.
- **Java**: Use `CompletableFuture`, reactive stacks (WebFlux, RxJava), or virtual threads (Project Loom, JDK 21+).
- **C++**: Use `asio` or `libuv` for event loops; thread pools for CPU work.

### Connection Pooling
- **Impact**: High | **Effort**: Small | **Risk**: Low
- **When to use**: Any service making repeated DB / cache / HTTP connections.
- **Tuning**:
  - Pool size ≈ `(core_count * 2) + effective_spindle_count` for PostgreSQL (per PG bouncer guidance).
  - Set `max_overflow`, `pool_recycle`, `pool_timeout`.
- **Python** (`SQLAlchemy`, `asyncpg`):
  ```python
  engine = create_engine("postgresql+psycopg2://...", pool_size=20, max_overflow=10, pool_recycle=3600)
  ```
- **Go** (`pgxpool`):
  ```go
  config, _ := pgxpool.ParseConfig("...")
  config.MaxConns = 25
  config.MinConns = 5
  ```

### Worker Pools
- **Impact**: Medium | **Effort**: Medium | **Risk**: Medium
- **When to use**: CPU-bound tasks (image processing, PDF generation, ML inference) that must not block the event loop / request handler.
- **Python**: `ProcessPoolExecutor` for CPU-bound; `ThreadPoolExecutor` for I/O-bound.
- **Node.js**: `worker_threads` or external job queues (Bull, RabbitMQ).
- **Go**: Bounded goroutine worker pool with `make(chan Job, backlog)`.

---

## 4. Database Indexing & Query Optimization

### Composite Indexes
- **Impact**: High | **Effort**: Small | **Risk**: Low
- **When to use**: Queries filtering on multiple columns, especially `WHERE a = ? AND b = ?`.
- **Rule**: Order columns by selectivity (most discriminating first) and equality before range.
- **Example**:
  ```sql
  CREATE INDEX idx_orders_user_created ON orders (user_id, created_at DESC);
  ```
- **Trade-off**: Writes become slower; indexes consume disk and memory. Drop unused indexes (`pg_stat_user_indexes`).

### Covering Indexes
- **Impact**: High | **Effort**: Small | **Risk**: Low
- **When to use**: Frequently run queries selecting a small set of columns from a large table.
- **Example**:
  ```sql
  CREATE INDEX idx_orders_covering ON orders (user_id) INCLUDE (total, status);
  -- PostgreSQL 11+; SQL Server; MySQL cluster index approximations
  ```
- **Effect**: Enables Index-Only Scan, avoiding heap lookups.

### Partial Indexes
- **Impact**: Medium | **Effort**: Small | **Risk**: Low
- **When to use**: Queries target a subset of rows (e.g., `status = 'pending'`).
- **Example**:
  ```sql
  CREATE INDEX idx_pending_orders ON orders (created_at) WHERE status = 'pending';
  ```

### N+1 Query Fix
- **Impact**: High | **Effort**: Small | **Risk**: Low
- **When to use**: ORM loops fetching related entities one by one.
- **Detection**: Query log shows one parent query followed by N identical child queries with different IDs.
- **Fixes**:
  - **Eager loading**: `select_related` (SQL JOIN) or `prefetch_related` (separate batched query) in Django.
  - **JOIN / `IN`**: Rewrite loop to `WHERE id IN (…)`.
  - **DataLoader**: See API batching above.

### Query Plan Optimization
- **Impact**: High | **Effort**: Medium | **Risk**: Medium
- **Actions**:
  - Replace `SELECT *` with specific columns.
  - Add `LIMIT` / pagination (`cursor` or `keyset` pagination for deep pages).
  - Use `EXISTS` instead of `IN` for subqueries with large outer tables.
  - Update table statistics (`ANALYZE`) after bulk loads.
  - Partition very large tables by time or tenant.

---

## 5. Memory Optimization

### Object Pooling & Reuse
- **Impact**: Medium | **Effort**: Medium | **Risk**: Medium
- **When to use**: High-frequency allocation of same-sized buffers (network packets, images, protobuf messages).
- **Go**:
  ```go
  var bufPool = sync.Pool{ New: func() interface{} { return make([]byte, 4096) } }
  buf := bufPool.Get().([]byte)
  defer bufPool.Put(buf)
  ```
- **Rust**: Use `bumpalo` for arena allocation or `bytes` crate for buffer reuse.
- **Java**: `ByteBuffer.allocateDirect` + pool; avoid excessive `byte[]` allocation in hot loops.

### Streaming & Pagination
- **Impact**: High | **Effort**: Small | **Risk**: Low
- **When to use**: Large file processing, large query results, CSV/JSON generation.
- **Python**: Use generators and `json.dump` with file-like streams; avoid `json.dumps` into memory.
- **Node.js**: Pipe streams; use `stream.pipeline` for backpressure-aware flow.
- **Go**: `bufio.Scanner` for line-by-line; `io.Copy` for file transfer.

### Reduce GC Pressure
- **Impact**: Medium | **Effort**: Medium | **Risk**: Medium
- **When to use**: High allocation rate causing frequent GC pauses (seen in profiler).
- **Actions**:
  - Pre-allocate slices/maps with known capacity.
  - Use value types instead of pointers where possible (Go, C#).
  - Avoid boxing in Java/C# hot paths.
  - Tune GC: `GOGC`, `GOMEMLIMIT`, `-XX:+UseG1GC -XX:MaxGCPauseMillis=200`.

---

## 6. Lock Contention & Parallelism

### Fine-Grained Locking
- **Impact**: Medium | **Effort**: Medium | **Risk**: High
- **When to use**: Single global mutex protecting diverse resources; high contention in concurrent workloads.
- **Actions**:
  - Split one big lock into per-bucket / per-shard locks (sharding).
  - Use `RWMutex` or `sync.RWMutex` when reads dominate.
  - Prefer lock-free structures: `ConcurrentHashMap` (Java), `sync.Map` (Go), `crossbeam` channels (Rust).

### Avoid Lock Hold Across I/O
- **Impact**: High | **Effort**: Small | **Risk**: Medium
- **When to use**: Mutex held while calling DB, API, or disk I/O.
- **Action**: Copy needed state, release lock, perform I/O, reacquire if needed to update.

### Transaction Scope Minimization
- **Impact**: Medium | **Effort**: Small | **Risk**: Low
- **When to use**: Long DB transactions holding row/table locks.
- **Action**: Move non-DB work (validation, formatting, external calls) outside the transaction block.

---

## 7. Serialization & Network

### Faster Serialization
- **Impact**: Medium | **Effort**: Small | **Risk**: Low
- **When to use**: High-throughput APIs, inter-service RPC, state caching.
- **Options**:
  - Replace JSON with Protocol Buffers, MessagePack, FlatBuffers, or Cap'n Proto.
  - Use zero-copy parsing where possible (`flatbuffers`, `protobuf` with `Arena`).
- **Expected gain**: 3–10× faster serialization, smaller payload size.

### Compression
- **Impact**: Medium | **Effort**: Small | **Risk**: Low
- **When to use**: Text-heavy responses > 1 KB, batch payloads, log shipping.
- **Actions**:
  - Enable `gzip` / `brotli` at reverse proxy (nginx, Envoy) or application middleware.
  - Use `Content-Encoding: zstd` for internal service mesh if supported.
- **Trade-off**: CPU cost vs bandwidth savings. Skip compression for small or already-compressed payloads (images, video).

### Keep-Alive & HTTP/2 / HTTP/3
- **Impact**: Medium | **Effort**: Small | **Risk**: Low
- **When to use**: High RPS microservices with many small requests.
- **Actions**:
  - Ensure reverse proxy and clients enable connection reuse.
  - Use HTTP/2 multiplexing for parallel streams over one connection.
  - Consider gRPC over HTTP/2 for structured internal APIs.

---

## 8. Compute Optimization

### Algorithmic Improvements
- **Impact**: High | **Effort**: Medium | **Risk**: Medium
- **When to use**: `O(n²)` nested loops over large datasets, repeated scans.
- **Examples**:
  - Use hash maps (`O(1)`) instead of list scans (`O(n)`) for lookups.
  - Sort + two-pointer instead of brute-force combinations.
  - Precompute / memoize expensive deterministic functions.

### Vectorization / SIMD
- **Impact**: High | **Effort**: Large | **Risk**: High
- **When to use**: Numeric hot loops (image processing, ML, signal processing).
- **Python**: NumPy, numba `@jit`, `pandas` vectorized ops.
- **Rust**: `packed_simd` or `auto-vectorization` with `target-cpu=native`.
- **Go**: Limited SIMD; offload to C or assembly for critical paths.

---

## 9. Lazy Loading & Deferred Work

### Lazy Initialization
- **Impact**: Low–Medium | **Effort**: Small | **Risk**: Low
- **When to use**: Expensive resources loaded eagerly but rarely used (heavy libraries, large config maps).
- **Pattern**: Initialize on first access with a `sync.Once` (Go), `Lazy<T>` (C#, Java), or closure.

### Background Jobs & Queues
- **Impact**: Medium | **Effort**: Medium | **Risk**: Medium
- **When to use**: Work that does not need synchronous completion (emails, reports, exports, analytics).
- **Options**: Sidekiq, Celery, Bull, RabbitMQ, Kafka, AWS SQS/SNS, Temporal.
- **Benefit**: Reduces API latency; smooths load spikes.

---

## 10. Regression Prevention

### CI Benchmark Gates
- **Impact**: High | **Effort**: Medium | **Risk**: Low
- **When to use**: Performance-critical paths (search, checkout, ingestion).
- **Pattern**:
  1. Store benchmark results in versioned artifacts.
  2. Compare PR vs main with statistical test (Welch's t-test).
  3. Fail CI if p95 latency increases > 10% or throughput drops > 5%.
- **Tools**: `hyperfine`, `pytest-benchmark`, `Go benchstat`, `JMH`, `k6`, `locust`.

### Production Profiling On-Demand
- **Impact**: Medium | **Effort**: Medium | **Risk**: Low
- **When to use**: Sporadic issues not reproducible in staging.
- **Actions**:
  - Deploy with `py-spy`, `async-profiler`, or `0x` available in containers.
  - Trigger profiles via admin endpoint or feature flag.
  - Ship profiles to object storage (S3) for post-mortem analysis.
