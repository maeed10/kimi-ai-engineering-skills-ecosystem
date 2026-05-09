# Error Handling & Recovery — Detailed Reference

## Graceful Degradation

Always implement graceful degradation. When components fail, the system should continue operating with reduced functionality rather than total failure. Identify critical paths versus non-essential features. Design fallback mechanisms for dependency failures. Use circuit breakers for external service calls. Return meaningful partial results when complete fulfillment is impossible.

## Exception Discipline

Never swallow exceptions without logging or appropriate action. Silent failure is the most dangerous failure mode because it masks problems and delays detection. If an exception is caught and not rethrown, it must be logged with context (operation being performed, relevant identifiers, stack trace). The handling must be intentional, not accidental.

## Error Classification

Always distinguish between recoverable and non-recoverable errors:
- **Recoverable**: Retry transient failures (network timeouts, rate limits, temporary unavailability) with exponential backoff and jitter.
- **Non-recoverable**: Fail fast for permanent errors (invalid input, authentication failures, resource exhaustion). Do not retry permanent failures indefinitely.

## Defensive Error Presentation

Never expose internal error details to external consumers. Stack traces, database connection strings, internal file paths, and implementation details leak through error messages. Return user-friendly, actionable error messages externally while logging detailed diagnostics internally. This is the principle of defensive error presentation.

## Correlation Identifiers

Always include correlation identifiers in distributed operations. When a request flows through multiple services, propagate a trace ID or correlation ID. This enables end-to-end debugging and observability. Include this identifier in all logs and error messages related to the operation.

## Concurrency Design

Never assume single-threaded execution unless guaranteed. Design for concurrency where applicable. Use appropriate synchronization for shared state. Prefer lock-free patterns where possible. Document thread-safety guarantees. When using async patterns, avoid deadlocks by not blocking on async operations in synchronous contexts.

## Boundary Validation

Always validate inputs at system boundaries. Input validation is a defense mechanism, not just data quality control. Validate at the outermost layer: API endpoints, message consumers, file parsers. Reject invalid input early before it propagates through the system. Validation rules should be explicit, documented, and consistent.

## Resource Exhaustion

Never ignore resource exhaustion scenarios. Consider memory limits, disk space, connection pool sizes, thread pool saturation, and file descriptor limits. Implement backpressure when throughput exceeds capacity. Monitor resource utilization and alert on thresholds. Design for capacity limits to be reached gracefully rather than catastrophically.

## Error Path Testing

Always test error paths, not just happy paths. Unit tests should cover exception handling branches. Integration tests should verify behavior when dependencies fail. Chaos engineering principles should inform testing strategy. A system that has only been tested under ideal conditions is not production-ready.

## Undefined Behavior

Never rely on undefined behavior or implementation-specific quirks. Code must behave correctly according to documented contracts, not accidentally work due to current runtime behavior. Undefined behavior changes across versions, platforms, and configurations. Relying on it creates brittle systems that fail silently after upgrades.

## Health Checks

Always implement health checks and readiness probes for long-running services:
- **Health checks** verify that the service is operational, not just that the process is running.
- **Readiness checks** confirm that the service can accept work.
- Differentiate between liveness (should restart) and readiness (should not receive traffic) to enable proper orchestration behavior.

## Failure Signatures

Document known failure modes and their signatures. Every system has characteristic ways it fails under stress. Documenting these signatures — specific log patterns, metric thresholds, or behavioral indicators — enables faster diagnosis when they recur. This operational documentation is as valuable as design documentation.
