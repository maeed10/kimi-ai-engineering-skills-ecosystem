# Error Catalog

Common error patterns organized by language, framework, and domain. Each entry includes:
- **Symptom**: The observable error message or behavior
- **Typical Cause**: Why it happens
- **Diagnostic**: How to confirm the root cause
- **Fix Pattern**: The usual remediation

---

## Python

### NoneType AttributeError
- **Symptom**: `AttributeError: 'NoneType' object has no attribute 'x'`
- **Typical Cause**: Function returned `None` unexpectedly; API response missing field; ORM query returned no result
- **Diagnostic**: Trace which assignment set variable to `None`; check upstream function contracts
- **Fix Pattern**: Add explicit `if x is None: raise ValueError(...)` or use walrus/optional chaining pattern; add default with `x.attr if x else default`

### KeyError / IndexError
- **Symptom**: `KeyError: 'user_id'` or `IndexError: list index out of range`
- **Typical Cause**: Missing dictionary key; list shorter than expected; DataFrame column renamed
- **Diagnostic**: Print `keys()` or `len()` at failure point; validate schema of input data
- **Fix Pattern**: Use `.get()` with default; check bounds before indexing; validate schema at entry point

### ImportError / ModuleNotFoundError
- **Symptom**: `ModuleNotFoundError: No module named 'xxx'`
- **Typical Cause**: Missing dependency; virtualenv not activated; name shadowing (local file named `json.py`)
- **Diagnostic**: Run `pip list | grep xxx`; check `sys.path`; inspect `__file__` of imported module
- **Fix Pattern**: Install missing package; delete/rename shadowing file; use absolute imports

### RecursionError
- **Symptom**: `RecursionError: maximum recursion depth exceeded`
- **Typical Cause**: Missing base case; mutual recursion; `__getattr__`/`__getattribute__` infinite loop
- **Diagnostic**: Inspect call stack depth; look for property delegating to itself
- **Fix Pattern**: Add base case; convert to iteration; fix `__getattr__` to raise `AttributeError` before recursing

### TypeError: unsupported operand type
- **Symptom**: `TypeError: unsupported operand type(s) for +: 'int' and 'str'`
- **Typical Cause**: Dynamic typing surprise; API changed return type; deserialized JSON mixing types
- **Diagnostic**: Check `type()` of operands; review recent API changes
- **Fix Pattern**: Explicit cast/validation before operation; use dataclasses/Pydantic for strict typing

### MemoryError / OOM Killed
- **Symptom**: `MemoryError` or container exit code 137
- **Typical Cause**: Loading entire dataset into RAM; infinite generator accumulation; large object in loop
- **Diagnostic**: `tracemalloc` snapshot; `sys.getsizeof()` on suspect objects; memory profiler
- **Fix Pattern**: Streaming/chunked processing; generators instead of lists; `del` large objects when done

---

## JavaScript / TypeScript

### Cannot read property of undefined
- **Symptom**: `TypeError: Cannot read properties of undefined (reading 'foo')`
- **Typical Cause**: Missing API field; async data not loaded yet; optional chain not used
- **Diagnostic**: Check data fetch status; inspect object at failure point
- **Fix Pattern**: Optional chaining `obj?.foo`; nullish coalescing `obj?.foo ?? default`; add loading guards

### undefined is not a function
- **Symptom**: `TypeError: x is not a function`
- **Typical Cause**: Named import mismatch; prototype pollution; variable reassigned; CommonJS/ESM interop
- **Diagnostic**: `console.log(typeof x)`; verify import path and export name
- **Fix Pattern**: Fix import name; bind method in constructor/class field; check bundler config

### UnhandledPromiseRejection
- **Symptom**: `UnhandledPromiseRejectionWarning: ...`
- **Typical Cause**: Missing `.catch()` or `try/catch` in async function; fire-and-forget promise
- **Diagnostic**: Search for `new Promise`, `async` functions without `await` in call chain
- **Fix Pattern**: Add `await` and `try/catch`; use `.catch()` on floating promises; central error handler

### ReferenceError: x is not defined
- **Symptom**: `ReferenceError: x is not defined`
- **Typical Cause**: Temporal dead zone (let/const); misspelled variable; scope closure issue; Node/Browser API mismatch
- **Diagnostic**: Check declaration location vs. usage; verify environment (Node vs. browser)
- **Fix Pattern**: Hoist declaration; fix spelling; pass variable explicitly into closure; add polyfill

### ECONNREFUSED / ECONNRESET
- **Symptom**: `Error: connect ECONNREFUSED 127.0.0.1:3000`
- **Typical Cause**: Server not running; wrong port; firewall; connection pool exhausted
- **Diagnostic**: `curl` the endpoint; check process list; verify env vars for host/port
- **Fix Pattern**: Start dependency service; use correct config; add retry/backoff; close connections properly

---

## Java / Kotlin

### NullPointerException
- **Symptom**: `java.lang.NullPointerException: Cannot invoke ... because "x" is null`
- **Typical Cause**: Unboxing null `Integer` to `int`; missing `Optional.orElse()`; stream returned null element
- **Diagnostic**: Enable detailed NPE messages (`-XX:+ShowCodeDetailsInExceptionMessages`); inspect autoboxing sites
- **Fix Pattern**: Use `Objects.requireNonNull()`; `Optional.ofNullable()`; null-safe Kotlin `?.`; validate at boundary

### ClassNotFoundException / NoClassDefFoundError
- **Symptom**: `ClassNotFoundException: com.example.Foo` or `NoClassDefFoundError`
- **Typical Cause**: Missing dependency in classpath; version conflict; shading/relocation issue; provided scope
- **Diagnostic**: `mvn dependency:tree -Dincludes=com.example`; check fat JAR contents
- **Fix Pattern**: Add dependency; resolve version conflict with `<exclusions>`; fix build packaging

### ConcurrentModificationException
- **Symptom**: `ConcurrentModificationException`
- **Typical Cause**: Modifying collection while iterating; multi-threaded mutation without synchronization
- **Diagnostic**: Review iterator usage; check thread safety of shared collections
- **Fix Pattern**: Use `Iterator.remove()`; `CopyOnWriteArrayList`; `ConcurrentHashMap`; synchronize block

### OutOfMemoryError: Java heap space
- **Symptom**: `OutOfMemoryError: Java heap space`
- **Typical Cause**: Large result set loaded fully; memory leak in cache/listener; insufficient heap for workload
- **Diagnostic**: Heap dump + MAT/Eclipse analyzer; `-XX:+HeapDumpOnOutOfMemoryError`; `jmap -histo`
- **Fix Pattern**: Streaming/iterator pattern; clear caches; fix listener registration leaks; increase `-Xmx` if legitimate

### IllegalArgumentException / IllegalStateException
- **Symptom**: `IllegalArgumentException` or `IllegalStateException`
- **Typical Cause**: Precondition violation; state machine in wrong state; builder missing required field
- **Diagnostic**: Read exception message carefully; trace state transitions leading to call
- **Fix Pattern**: Add validation at entry point; state checks before operations; builder defaults

---

## Go

### panic: runtime error: invalid memory address or nil pointer dereference
- **Symptom**: `panic: runtime error: invalid memory address or nil pointer dereference`
- **Typical Cause**: Calling method on nil struct pointer; uninitialized interface; closed channel misuse
- **Diagnostic**: Check pointer initialization; verify struct construction with `&T{}` vs `new(T)`
- **Fix Pattern**: Add `if x == nil { return ... }` guard; ensure constructor functions initialize all fields

### goroutine leak
- **Symptom**: Goroutine count grows unbounded; memory climbs; `-race` may not detect
- **Typical Cause**: Blocked channel send/receive without receiver; infinite `for` with `time.Sleep`; missing `ctx.Done()` check
- **Diagnostic**: `runtime.NumGoroutine()` over time; `pprof` goroutine profile
- **Fix Pattern**: Use `context.WithCancel`; buffered channels; ensure every `go` has an exit path; `select` on `ctx.Done()`

### data race
- **Symptom**: `-race` detector: `WARNING: DATA RACE`
- **Typical Cause**: Unsynchronized map write+read; closure capturing loop variable; non-atomic pointer swap
- **Diagnostic**: Run with `-race` in CI; read race report for conflicting goroutine stacks
- **Fix Pattern**: `sync.Mutex`; `sync.Map`; atomic operations; channel-based ownership transfer

### error not checked
- **Symptom**: Silent failure; unexpected zero values; `errcheck` linter warning
- **Typical Cause**: `_ = someCall()` ignoring error; deferred close without error check
- **Diagnostic**: Enable `errcheck`, `golangci-lint`; audit all `_` error assignments
- **Fix Pattern**: Always handle errors explicitly; return early on error; log with context

---

## Rust

### borrow checker errors
- **Symptom**: `error[E0502]: cannot borrow ... as mutable because it is also borrowed as immutable`
- **Typical Cause**: Overlapping lifetimes; holding reference while mutating; self-referential structs
- **Diagnostic**: Read compiler note for lifetime spans; use `cargo explain E0xxx`
- **Fix Pattern**: Restructure to smaller scopes; clone data; use `Rc<RefCell<T>>` or `Arc<Mutex<T>>`; redesign ownership

### unwrap() / expect() panic
- **Symptom**: `thread 'main' panicked at 'called `Option::unwrap()` on a `None` value'`
- **Typical Cause**: Assumption about API result; missing error handling in prototyping
- **Diagnostic**: `RUST_BACKTRACE=1` to find exact unwrap line; replace with `match`/`if let` to inspect
- **Fix Pattern**: Use `?` operator with `Result` propagation; `ok_or_else()` for context; `unwrap_or/default`

### lifetime mismatch in closures
- **Symptom**: `expected a closure that implements 'static`, captured variable does not live long enough
- **Typical Cause**: Closure captured stack reference; async block holding non-static reference
- **Diagnostic**: Identify captured variables; check if thread/async spawn requires `'static`
- **Fix Pattern**: Move (`clone`) data into closure; use `Arc` for shared data; restructure async lifetime

---

## SQL / Databases

### Connection pool exhausted
- **Symptom**: `FATAL: sorry, too many clients already` (PostgreSQL); timeout acquiring connection
- **Typical Cause**: Connections not released; pool size too small; long-running transaction holding connection
- **Diagnostic**: `pg_stat_activity`; connection pool metrics; check for uncommitted transactions
- **Fix Pattern**: Ensure `defer conn.Close()` / `using` / context-scoped connections; tune pool max size; reduce transaction scope

### Deadlock
- **Symptom**: `ERROR: deadlock detected` (PostgreSQL); `1213` (MySQL)
- **Typical Cause**: Two transactions lock rows in opposite order; missing index causing table locks
- **Diagnostic**: Database deadlock logs; lock monitoring tables; transaction isolation level
- **Fix Pattern**: Consistent lock ordering; retry with exponential backoff; add covering index to reduce lock granularity

### N+1 Query
- **Symptom**: Many similar queries in logs; slow response for lists
- **Typical Cause**: ORM loop fetching related entity per iteration
- **Diagnostic**: SQL log analysis; `EXPLAIN` plans; ORM query logging
- **Fix Pattern**: Eager loading (`select_related`, `join fetch`, `@EntityGraph`); batch queries; denormalize if needed

### Unique constraint violation
- **Symptom**: `duplicate key value violates unique constraint`
- **Typical Cause**: Race condition in application-level check-then-insert; retry after prior failure left partial state
- **Diagnostic**: Check for `UPSERT`/`ON CONFLICT` usage; review unique constraint fields
- **Fix Pattern**: Use `INSERT ... ON CONFLICT` (PostgreSQL) / `INSERT IGNORE` / `REPLACE`; idempotency key

---

## Containers / CI/CD

### Exit Code 137
- **Symptom**: Container killed, exit code 137
- **Typical Cause**: OOMKilled by orchestrator; memory limit too low; memory leak
- **Diagnostic**: `kubectl describe pod` shows `OOMKilled`; container memory metrics
- **Fix Pattern**: Increase memory limit; fix leak; add memory profiling; tune GC

### Exit Code 1 / Build Failures
- **Symptom**: Generic failure in CI step; `make` or test runner exits 1
- **Typical Cause**: Test assertion failed; compilation error; lint failure; missing env var
- **Diagnostic**: Read CI log carefully; reproduce locally with same env vars; check recent changes
- **Fix Pattern**: Fix root cause locally; run same CI steps in container locally; ensure env vars in CI config

### ImagePullBackOff / ErrImagePull
- **Symptom**: Kubernetes pod stuck; image cannot be pulled
- **Typical Cause**: Wrong image tag; registry auth expired; network policy blocks registry; image doesn't exist
- **Diagnostic**: `kubectl describe pod`; manual `docker pull` with same credentials; verify tag in registry
- **Fix Pattern**: Fix image tag; refresh `imagePullSecrets`; check network policy; rebuild/push image

### Timeout / DeadlineExceeded
- **Symptom**: CI job times out; gRPC `DeadlineExceeded`; HTTP 504
- **Typical Cause**: Infinite loop; missing await; downstream service slow; resource starvation
- **Diagnostic**: Add granular timing logs; trace request latency; check CPU throttling
- **Fix Pattern**: Add timeouts to all external calls; fix infinite loops; optimize hot path; scale resources

---

## Networking / Distributed Systems

### DNS resolution failure
- **Symptom**: `getaddrinfo ENOTFOUND`; `no such host`
- **Typical Cause**: Typo in hostname; service not deployed; DNS cache staleness; VPC misconfiguration
- **Diagnostic**: `nslookup` / `dig`; check service discovery registry; verify network connectivity
- **Fix Pattern**: Fix hostname; ensure service registered; flush DNS; check security groups / firewall rules

### TLS / Certificate errors
- **Symptom**: `certificate verify failed`; `x509: certificate has expired`
- **Typical Cause**: Expired cert; wrong SAN; self-signed cert not trusted; clock skew
- **Diagnostic**: `openssl s_client -connect host:port`; check cert validity dates; verify system time
- **Fix Pattern**: Renew certificate; add CA to trust store; fix SAN; sync NTP

### Circuit breaker open
- **Symptom**: `429 Too Many Requests`; fallback responses; `breaker is open`
- **Typical Cause**: Downstream failure rate exceeded threshold; retry storm; cascading overload
- **Diagnostic**: Check downstream health; error rate metrics; review retry configuration
- **Fix Pattern**: Fix downstream root cause; add jittered exponential backoff; tune breaker thresholds; bulkhead isolation
