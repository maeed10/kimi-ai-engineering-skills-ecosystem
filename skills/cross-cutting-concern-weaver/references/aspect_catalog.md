# Aspect Catalog

Pre-defined cross-cutting aspects with weaving rules, configuration schemas, and joinpoint requirements.

## Aspect: Security

**Id:** `security`
**Description:** Authentication, authorization, input validation, and secrets management.

### Weaving Rules
- **All entry points** (HTTP handlers, gRPC methods, message consumers, CLI commands) must have authentication checks
- **All operations on protected resources** must have authorization checks
- **All external inputs** must pass validation before processing
- **Secrets** must never appear in logs or error messages

### Required Joinpoints
```yaml
joinpoints:
  - http_handler:       [authn_middleware, input_validation]
  - grpc_method:        [authn_interceptor, input_validation]
  - message_consumer:   [authn, input_validation]
  - database_query:     [parameterized_queries, secrets_injection]
  - external_api_call:  [tls_verification, secrets_injection]
  - file_operation:     [path_traversal_guard]
```

### Configuration Schema
```yaml
security:
  authn:
    method: jwt | oauth2 | mTLS | api_key | session
    required: bool
    exclude_paths: [str]          # health, metrics endpoints
  authz:
    model: rbac | abac | policy
    default_deny: true
  input_validation:
    schema: pydantic | json_schema | bean_validation | joi
    fail_fast: true
  secrets:
    source: env | vault | aws_secrets_manager | azure_keyvault
    rotation_days: 90
```

---

## Aspect: Logging

**Id:** `logging`
**Description:** Structured logging, log levels, correlation IDs, and log redaction.

### Weaving Rules
- **Every function entry/exit** at DEBUG level
- **Every significant event** at INFO level
- **Every error** at ERROR level with full context
- **Correlation ID** propagated across all async boundaries
- **Sensitive fields redacted** before logging

### Required Joinpoints
```yaml
joinpoints:
  - http_request:       [request_log, correlation_id]
  - http_response:      [response_log, timing]
  - function_entry:     [entry_log]
  - function_exit:      [exit_log, timing]
  - exception:          [error_log, stack_trace]
  - external_call:      [call_log, correlation_id_propagation]
```

### Configuration Schema
```yaml
logging:
  format: json | text
  level: DEBUG | INFO | WARN | ERROR
  fields:
    - timestamp
    - level
    - correlation_id
    - service_name
    - operation
    - duration_ms
    - result
  redaction:
    fields: [password, token, secret, ssn, credit_card, email]
    pattern: '(?i)(password|token|secret|authorization)'
  sampling:
    rate: 1.0    # 1.0 = log all, 0.1 = 10% sampling for high-traffic
```

---

## Aspect: Metrics

**Id:** `metrics`
**Description:** Counters, histograms, gauges, and health checks for observability.

### Weaving Rules
- **All HTTP endpoints** emit request count + latency histogram
- **All external calls** emit call count + latency + error rate
- **All business events** emit domain-specific counters
- **Health checks** exposed on `/health` and `/ready`

### Required Joinpoints
```yaml
joinpoints:
  - http_endpoint:
      - counter:  http_requests_total{method, path, status}
      - histogram: http_request_duration_seconds{method, path}
  - external_call:
      - counter:  external_calls_total{service, method, status}
      - histogram: external_call_duration_seconds{service, method}
  - business_event:
      - counter:  events_total{event_type}
  - queue_depth:
      - gauge:    queue_depth{queue_name}
```

### Configuration Schema
```yaml
metrics:
  backend: prometheus | statsd | cloudwatch | datadog
  port: 9090
  path: /metrics
  buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]
  labels:
    service: required
    environment: required
    version: optional
  health:
    enabled: true
    path: /health
    checks: [database, cache, external_apis]
```

---

## Aspect: Resilience

**Id:** `resilience`
**Description:** Circuit breakers, retries, bulkheads, timeouts, and fallbacks.

### Weaving Rules
- **Every external call** has a timeout (default 5s)
- **Every idempotent external call** has retry with exponential backoff (max 3)
- **Every external service dependency** has a circuit breaker
- **Resource-intensive operations** have concurrency limits (bulkhead)
- **Critical paths** have fallback strategies

### Required Joinpoints
```yaml
joinpoints:
  - external_http_call:   [timeout, retry, circuit_breaker]
  - database_query:       [timeout, circuit_breaker, retry(readonly)]
  - cache_operation:      [timeout, fallback]
  - message_publish:      [timeout, retry]
  - message_consume:      [timeout, retry]
  - file_io:              [timeout]
  - cpu_intensive_task:   [bulkhead]
```

### Configuration Schema
```yaml
resilience:
  timeout:
    default: 5s
    overrides:
      database_query: 10s
      file_upload: 30s
  retry:
    max_attempts: 3
    backoff: exponential
    base_delay: 100ms
    max_delay: 30s
    jitter: true
    retryable_errors: [timeout, 5xx, connection_error]
  circuit_breaker:
    failure_threshold: 5
    success_threshold: 3
    timeout: 30s
    half_open_max_calls: 3
  bulkhead:
    max_concurrent: 10
    max_queue: 100
  fallback:
    cache_ttl: 300s
    default_response: null
```

---

## Aspect: Compliance

**Id:** `compliance`
**Description:** Audit trails, PII handling, data retention, and regulatory controls.

### Weaving Rules
- **Every data access** (read/write/delete) logged to immutable audit trail
- **PII fields** encrypted at rest, tokenized in logs
- **Data retention policies** enforced via TTL/deletion jobs
- **Consent checks** before data processing
- **Right-to-deletion** supported

### Required Joinpoints
```yaml
joinpoints:
  - data_read:          [audit_log, pii_check]
  - data_write:         [audit_log, pii_encryption, consent_check]
  - data_delete:        [audit_log, hard_delete | soft_delete]
  - data_export:        [audit_log, consent_check, pii_filter]
  - log_write:          [pii_redaction]
  - api_response:       [pii_filter, consent_filter]
```

### Configuration Schema
```yaml
compliance:
  audit:
    store: database | s3 | elasticsearch
    retention_days: 2555   # 7 years
    immutable: true
    fields: [who, what, when, where, result]
  pii:
    classification: [email, phone, ssn, address, dob, biometric]
    encryption: aes256_gcm
    tokenization: true
    masking: partial          # ***-***-1234
  retention:
    active_data: 2555         # days
    archived_data: 3650       # days
    deleted_data: 90          # grace period
  gdpr:
    consent_required: true
    right_to_deletion: true
    data_portability: true
```

---

## Aspect: Performance

**Id:** `performance`
**Description:** Caching, connection pooling, async processing, and resource optimization.

### Weaving Rules
- **Repeated expensive computations** use memoization/caching
- **Database connections** pooled (min 5, max 20)
- **External API calls** use connection pooling
- **Independent operations** executed concurrently
- **Large datasets** processed in batches

### Required Joinpoints
```yaml
joinpoints:
  - expensive_function:   [cache, memoize]
  - database_access:      [connection_pool]
  - external_api_call:    [connection_pool, cache]
  - bulk_operation:       [batching, concurrency]
  - file_upload:          [streaming, chunking]
  - response_building:    [compression, etag]
```

### Configuration Schema
```yaml
performance:
  cache:
    type: redis | memcached | in_memory
    ttl: 300
    max_size: 10000
    key_pattern: "{service}:{resource}:{id}"
  connection_pool:
    database:
      min: 5
      max: 20
      max_idle_time: 300s
    http_client:
      max_connections: 100
      max_per_host: 20
  concurrency:
    max_workers: 10
    queue_size: 100
  batch:
    size: 100
    timeout: 10ms
```

---

## Aspect: Internationalization (i18n)

**Id:** `i18n`
**Description:** Localization, timezone handling, encoding, and locale-aware formatting.

### Weaving Rules
- **All user-facing strings** externalized to resource bundles
- **All dates/times** stored in UTC, displayed in user timezone
- **All numbers/currencies** formatted per locale
- **All text** encoded as UTF-8
- **Locale** resolved from request context (header, cookie, or user preference)

### Required Joinpoints
```yaml
joinpoints:
  - http_request:         [locale_resolution]
  - error_response:       [localized_message]
  - date_display:         [timezone_conversion]
  - number_display:       [locale_formatting]
  - email_template:       [localized_template]
  - report_generation:    [locale_aware_formatting]
```

### Configuration Schema
```yaml
i18n:
  default_locale: en_US
  supported_locales: [en_US, es_ES, fr_FR, de_DE, ja_JP, zh_CN]
  fallback: en_US
  timezone:
    storage: UTC
    display: user_preference
  encoding: UTF-8
  resources:
    format: json | properties | yaml | po
    path: /locales
    hot_reload: false
  dates:
    short_format: "YYYY-MM-DD"
    long_format: "MMMM D, YYYY"
    datetime_format: "YYYY-MM-DD HH:mm:ss"
  numbers:
    decimal_places: 2
    currency: USD
```
