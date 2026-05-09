# Weaving Patterns

Per-language weaving patterns for injecting cross-cutting concerns. Select the pattern matching the target language and use the templates as AST transformation guides.

## Python: Decorators + Context Managers

### Aspect Decorator Stack Pattern

```python
# Weaving order: security → logging → metrics → resilience → business logic

from functools import wraps
from typing import Callable, Any
import time
import logging

# --- Security decorator ---
def require_auth(roles: list[str] = None):
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = kwargs.get("request") or args[0]
            principal = await authenticate(request)
            if not principal:
                raise AuthenticationError("Invalid credentials")
            if roles and not any(r in principal.roles for r in roles):
                raise AuthorizationError(f"Required: {roles}")
            kwargs["_principal"] = principal
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# --- Logging decorator ---
def log_operation(operation: str = None):
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            op = operation or func.__name__
            correlation_id = get_correlation_id()
            logger.info(f"[{correlation_id}] Enter {op}")
            try:
                result = await func(*args, **kwargs)
                logger.info(f"[{correlation_id}] Exit {op} — OK")
                return result
            except Exception as e:
                logger.error(f"[{correlation_id}] Exit {op} — ERROR: {e}")
                raise
        return wrapper
    return decorator

# --- Metrics decorator ---
def timed_metric(name: str = None, labels: dict = None):
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            metric_name = name or func.__name__
            start = time.monotonic()
            try:
                result = await func(*args, **kwargs)
                histogram_observe(f"{metric_name}_duration_seconds",
                                  time.monotonic() - start,
                                  labels={**(labels or {}), "status": "success"})
                counter_inc(f"{metric_name}_total",
                            labels={**(labels or {}), "status": "success"})
                return result
            except Exception as e:
                histogram_observe(f"{metric_name}_duration_seconds",
                                  time.monotonic() - start,
                                  labels={**(labels or {}), "status": "error"})
                counter_inc(f"{metric_name}_total",
                            labels={**(labels or {}), "status": "error"})
                raise
        return wrapper
    return decorator

# --- Resilience decorator ---
def resilient(
    timeout: float = 5.0,
    max_retries: int = 3,
    circuit_breaker: str = None,
    fallback: Callable = None
):
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cb = get_circuit_breaker(circuit_breaker or func.__name__)
            if cb.is_open():
                if fallback:
                    return await fallback(*args, **kwargs)
                raise CircuitBreakerOpenError()
            for attempt in range(max_retries + 1):
                try:
                    with timeout_context(timeout):
                        result = await func(*args, **kwargs)
                        cb.record_success()
                        return result
                except RetryableError as e:
                    if attempt < max_retries:
                        await backoff_sleep(attempt)
                        continue
                    cb.record_failure()
                    raise
                except Exception as e:
                    cb.record_failure()
                    raise
        return wrapper
    return decorator

# --- Composed aspect application ---
def api_handler(operation: str, roles: list[str] = None):
    """Compose all aspects for an HTTP API handler."""
    def decorator(func: Callable) -> Callable:
        return (
            require_auth(roles=roles)(
                log_operation(operation=operation)(
                    timed_metric(name=operation)(
                        resilient(timeout=10.0, max_retries=2)(
                            func
                        )
                    )
                )
            )
        )
    return decorator

# --- Usage ---
@api_handler(operation="create_order", roles=["user", "admin"])
async def create_order(request, _principal=None):
    # Business logic only — aspects handled by decorator stack
    ...
```

### Context Manager Pattern (for non-function scopes)

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def transaction_scope(connection, correlation_id: str):
    tx_start = time.monotonic()
    audit_log.begin(correlation_id, "transaction")
    try:
        async with connection.transaction() as tx:
            yield tx
            audit_log.commit(correlation_id, "transaction",
                             duration=time.monotonic() - tx_start)
    except Exception as e:
        audit_log.rollback(correlation_id, "transaction", error=str(e))
        raise
```

---

## Java: Annotations + AOP

### Annotation-Based Aspect Definition

```java
// --- Security annotation ---
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface Secured {
    String[] roles() default {};
    boolean requireAuth() default true;
}

// --- Logging annotation ---
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface LogOperation {
    String value() default "";
    LogLevel level() default LogLevel.INFO;
}

// --- Metrics annotation ---
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface Timed {
    String value();
    String[] extraTags() default {};
}

// --- Resilience annotation ---
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface Resilient {
    long timeoutMs() default 5000;
    int maxRetries() default 3;
    String circuitBreaker() default "";
    Class<? extends Throwable>[] retryFor() default {TimeoutException.class, IOException.class};
}

// --- Composed annotation ---
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
@Secured
@LogOperation
@Timed
@Resilient
public @interface ApiHandler {
    String operation();
    String[] roles() default {};
    long timeoutMs() default 10000;
}
```

### Aspect Implementation (Spring AOP)

```java
@Aspect
@Component
public class CrossCuttingAspect {

    @Around("@annotation(apiHandler)")
    public Object aroundApiHandler(ProceedingJoinPoint pjp, ApiHandler apiHandler) throws Throwable {
        // Aspect ordering: security → logging → metrics → resilience → business logic
        String operation = apiHandler.operation();
        String correlationId = MDC.get("correlationId");
        Timer.Sample sample = Timer.start(meterRegistry);

        try {
            // Security check
            Authentication auth = SecurityContextHolder.getContext().getAuthentication();
            if (auth == null || !hasRequiredRoles(auth, apiHandler.roles())) {
                throw new AccessDeniedException("Insufficient privileges");
            }

            // Execute with resilience
            Object result = executeWithResilience(pjp, apiHandler);

            // Success logging + metrics
            log.info("[{}] {} — success", correlationId, operation);
            sample.stop(meterRegistry.timer("api.request", "operation", operation, "status", "success"));

            return result;
        } catch (Exception e) {
            log.error("[{}] {} — error: {}", correlationId, operation, e.getMessage());
            sample.stop(meterRegistry.timer("api.request", "operation", operation, "status", "error"));
            throw e;
        }
    }
}
```

---

## JavaScript / TypeScript: Middleware + Higher-Order Functions

### Middleware Stack Pattern (Express/Fastify)

```typescript
// --- Security middleware ---
function requireAuth(roles?: string[]): RequestHandler {
    return async (req, res, next) => {
        const token = req.headers.authorization?.replace("Bearer ", "");
        const principal = await authenticate(token);
        if (!principal) return res.status(401).json({ error: "Unauthorized" });
        if (roles && !roles.some(r => principal.roles.includes(r))) {
            return res.status(403).json({ error: "Forbidden" });
        }
        req.principal = principal;
        next();
    };
}

// --- Logging middleware ---
function logRequest(operation: string): RequestHandler {
    return (req, res, next) => {
        const correlationId = req.headers["x-correlation-id"] || uuid();
        const start = Date.now();
        logger.info({ correlationId, operation, method: req.method, path: req.path }, "Request started");

        res.on("finish", () => {
            const duration = Date.now() - start;
            logger.info({
                correlationId, operation, statusCode: res.statusCode, duration
            }, res.statusCode >= 400 ? "Request failed" : "Request completed");
        });
        next();
    };
}

// --- Metrics middleware ---
function timedMetric(name: string): RequestHandler {
    return (req, res, next) => {
        const start = process.hrtime.bigint();
        res.on("finish", () => {
            const duration = Number(process.hrtime.bigint() - start) / 1e9;
            metrics.histogram(`${name}_duration_seconds`, duration, {
                status: res.statusCode.toString()
            });
            metrics.counter(`${name}_total`, 1, {
                status: res.statusCode.toString()
            });
        });
        next();
    };
}

// --- Resilience wrapper ---
function withResilience<T>(
    operation: string,
    fn: () => Promise<T>,
    opts: { timeout?: number; retries?: number; fallback?: () => T } = {}
): Promise<T> {
    const cb = circuitBreakers.get(operation) || new CircuitBreaker(operation);
    if (cb.isOpen()) {
        if (opts.fallback) return opts.fallback();
        throw new CircuitBreakerOpenError(operation);
    }
    return pRetry(
        () => pTimeout(fn(), { milliseconds: opts.timeout || 5000 }),
        { retries: opts.retries || 3, onFailedAttempt: e => cb.recordFailure() }
    ).then(r => { cb.recordSuccess(); return r; });
}

// --- Route registration with aspect weaving ---
function createRoute(
    app: Express,
    method: "get" | "post" | "put" | "delete",
    path: string,
    operation: string,
    handler: RequestHandler,
    options: { roles?: string[]; timeout?: number } = {}
) {
    const middlewares: RequestHandler[] = [
        logRequest(operation),
        timedMetric(operation),
        ...(options.roles ? [requireAuth(options.roles)] : []),
    ];
    app[method](path, ...middlewares, handler);
}

// --- Usage ---
createRoute(app, "post", "/orders", "create_order", async (req, res) => {
    const result = await withResilience("create_order",
        () => orderService.create(req.body, req.principal),
        { timeout: 10000, retries: 2 }
    );
    res.json(result);
}, { roles: ["user", "admin"] });
```

---

## Go: Middleware Chains + Struct Embedding

### Middleware Chain Pattern

```go
package middleware

import (
    "context"
    "net/http"
    "time"
)

// --- Authentication middleware ---
func Auth(roles ...string) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            principal, err := authenticate(r)
            if err != nil {
                http.Error(w, "Unauthorized", http.StatusUnauthorized)
                return
            }
            if len(roles) > 0 && !hasAnyRole(principal.Roles, roles) {
                http.Error(w, "Forbidden", http.StatusForbidden)
                return
            }
            ctx := context.WithValue(r.Context(), "principal", principal)
            next.ServeHTTP(w, r.WithContext(ctx))
        })
    }
}

// --- Logging middleware ---
func LogOperation(operation string) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            correlationID := r.Header.Get("X-Correlation-ID")
            if correlationID == "" {
                correlationID = uuid.New().String()
            }
            ctx := context.WithValue(r.Context(), "correlationID", correlationID)
            start := time.Now()

            wrapped := &responseWriter{ResponseWriter: w, statusCode: 200}
            next.ServeHTTP(wrapped, r.WithContext(ctx))

            logger.Info().
                Str("correlation_id", correlationID).
                Str("operation", operation).
                Int("status", wrapped.statusCode).
                Dur("duration", time.Since(start)).
                Msg("request completed")
        })
    }
}

// --- Metrics middleware ---
func TimedMetric(name string) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            start := time.Now()
            wrapped := &responseWriter{ResponseWriter: w, statusCode: 200}
            next.ServeHTTP(wrapped, r)
            duration := time.Since(start).Seconds()
            metrics.HistogramObserve(name+"_duration_seconds", duration,
                metrics.Labels{"status": strconv.Itoa(wrapped.statusCode)})
            metrics.CounterInc(name + "_total")
        })
    }
}

// --- Resilience wrapper ---
func WithResilience(ctx context.Context,
    operation string,
    fn func() error,
    opts ResilienceOptions) error {
    cb := circuitBreaker.Get(operation)
    if cb.IsOpen() {
        return ErrCircuitBreakerOpen
    }
    return retry.Do(ctx, func(ctx context.Context) error {
        done := make(chan error, 1)
        go func() { done <- fn() }()
        select {
        case <-ctx.Done():
            return ctx.Err()
        case err := <-done:
            if err == nil {
                cb.RecordSuccess()
            } else if opts.Retryable(err) {
                cb.RecordFailure()
                return retry.RetryableError(err)
            } else {
                cb.RecordFailure()
            }
            return err
        }
    }, retry.Attempts(uint(opts.MaxRetries+1)), retry.Delay(opts.BackoffDelay))
}

// --- Route registration with aspect weaving ---
func RegisterHandler(mux *http.ServeMux, pattern string, handler http.HandlerFunc, aspects Aspects) {
    h := http.Handler(handler)
    // Order: logging (outer) → metrics → auth → resilience → business logic (inner)
    if aspects.Log {
        h = LogOperation(aspects.Operation)(h)
    }
    if aspects.Metrics {
        h = TimedMetric(aspects.Operation)(h)
    }
    if len(aspects.Roles) > 0 {
        h = Auth(aspects.Roles...)(h)
    }
    mux.Handle(pattern, h)
}
```

### Struct Embedding for Service Aspects

```go
type Service struct {
    ResilienceConfig ResilienceOptions
    Logger           zerolog.Logger
    Metrics          MetricsCollector
}

type OrderService struct {
    Service          // embed shared cross-cutting concerns
    orderRepo OrderRepository
}

func (s *OrderService) CreateOrder(ctx context.Context, req CreateOrderRequest) (*Order, error) {
    correlationID := ctx.Value("correlationID").(string)
    s.Logger.Info().Str("correlation_id", correlationID).Msg("creating order")

    var order *Order
    err := WithResilience(ctx, "create_order", func() error {
        var err error
        order, err = s.orderRepo.Create(ctx, req)
        return err
    }, s.ResilienceConfig)

    if err != nil {
        s.Metrics.Inc("order_create_errors_total")
        return nil, err
    }
    s.Metrics.Inc("order_created_total")
    return order, nil
}
```

---

## C#: Attributes + Middleware

### Attribute-Based Weaving

```csharp
// --- Security attribute ---
[AttributeUsage(AttributeTargets.Method)]
public class SecuredAttribute : Attribute
{
    public string[] Roles { get; }
    public SecuredAttribute(params string[] roles) => Roles = roles;
}

// --- Logging attribute ---
[AttributeUsage(AttributeTargets.Method)]
public class LogOperationAttribute : Attribute
{
    public string Operation { get; }
    public LogOperationAttribute(string operation) => Operation = operation;
}

// --- Metrics attribute ---
[AttributeUsage(AttributeTargets.Method)]
public class TimedMetricAttribute : Attribute
{
    public string Name { get; }
    public TimedMetricAttribute(string name) => Name = name;
}

// --- Resilience attribute ---
[AttributeUsage(AttributeTargets.Method)]
public class ResilientAttribute : Attribute
{
    public int TimeoutMs { get; set; } = 5000;
    public int MaxRetries { get; set; } = 3;
    public string CircuitBreakerName { get; set; } = "";
}

// --- Middleware/Filter implementation ---
public class CrossCuttingFilter : IAsyncActionFilter
{
    public async Task OnActionExecutionAsync(ActionExecutingContext ctx, ActionExecutionDelegate next)
    {
        var method = ctx.Controller.GetType()
            .GetMethod(ctx.ActionDescriptor.ActionName);

        // Security
        var secured = method.GetCustomAttribute<SecuredAttribute>();
        if (secured != null && !await AuthorizeAsync(ctx, secured.Roles))
        {
            ctx.Result = new ForbidResult();
            return;
        }

        // Logging + Metrics
        var logOp = method.GetCustomAttribute<LogOperationAttribute>();
        var timed = method.GetCustomAttribute<TimedMetricAttribute>();
        var correlationId = ctx.HttpContext.TraceIdentifier;
        var stopwatch = Stopwatch.StartNew();

        _logger.LogInformation("[{CorrelationId}] Enter {Operation}",
            correlationId, logOp?.Operation ?? method.Name);

        var result = await next();
        stopwatch.Stop();

        _logger.LogInformation("[{CorrelationId}] Exit {Operation} — {Status} in {Ms}ms",
            correlationId, logOp?.Operation ?? method.Name,
            result.Exception != null ? "ERROR" : "OK", stopwatch.ElapsedMilliseconds);

        if (timed != null)
        {
            _metrics.RecordHistogram($"{timed.Name}_duration_seconds",
                stopwatch.Elapsed.TotalSeconds,
                new KeyValuePair<string, object>("status",
                    result.Exception != null ? "error" : "success"));
        }
    }
}

// --- Usage on controller ---
[ApiController]
[Route("api/orders")]
public class OrderController : ControllerBase
{
    [HttpPost]
    [Secured("user", "admin")]
    [LogOperation("create_order")]
    [TimedMetric("create_order")]
    [Resilient(TimeoutMs = 10000, MaxRetries = 2)]
    public async Task<IActionResult> CreateOrder([FromBody] CreateOrderRequest request)
    {
        // Business logic only
        var order = await _orderService.CreateAsync(request);
        return Ok(order);
    }
}
```

---

## Aspect Ordering Reference

All languages must maintain this nesting order (outermost → innermost):

```
1. Security      (authn/authz — gatekeeper, must be first)
2. Logging       (enter/exit logging with correlation ID)
3. Metrics       (timing starts after logging, stops before logging exit)
4. Resilience    (timeout/retry/circuit breaker — closest to business logic)
5. Business Logic (the actual function implementation)
```

**Rationale:**
- **Security first** — reject unauthorized requests before doing any work
- **Logging second** — capture all attempts including those that fail auth
- **Metrics third** — measure time inside the try/catch, excluding logging overhead
- **Resilience last** — wrap the actual operation being protected

## Anti-Patterns to Avoid

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| String concatenation for aspect injection | Brittle, breaks on code changes | AST-based transformation |
| Swallowing exceptions in aspects | Hides errors, breaks error handling | Log + re-raise or use `throw;` |
| Aspects calling each other directly | Tight coupling, hard to test | Compose via decorator/middleware chain |
| Global mutable state for context | Race conditions, test pollution | Thread-local / context propagation |
| Hard-coded aspect config | Inflexible across environments | External configuration schema |
| Aspects only on "important" methods | Inconsistent coverage, gaps | Systematic joinpoint scanning |
