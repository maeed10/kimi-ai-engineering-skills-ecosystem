# REST API Patterns

Reference guide for REST API design, covering resource naming, HTTP semantics, pagination, filtering, idempotency, error handling, caching, and rate limiting headers.

## Resource Naming

Use plural nouns for collection resources. Use nouns, not verbs, in URLs.

| Good | Bad |
|------|-----|
| `GET /tasks` | `GET /getTasks` |
| `GET /tasks/123` | `GET /getTask?id=123` |
| `POST /tasks` | `POST /createTask` |
| `PATCH /tasks/123` | `POST /updateTask/123` |
| `GET /projects/456/tasks` | `GET /tasks?projectId=456` (prefer sub-resource when scoped) |

**Sub-resources vs Query params:**
- Use sub-resources for hierarchical containment: `/projects/{id}/tasks`
- Use query params for cross-cutting filters: `/tasks?status=open&assignee=me`
- Use both for scoped filtered lists: `/projects/{id}/tasks?status=open`

## HTTP Methods and Semantics

| Method | Idempotent | Safe | Usage |
|--------|------------|------|-------|
| GET | Yes | Yes | Read resource or collection |
| POST | No | No | Create resource or execute action |
| PUT | Yes | No | Full replacement of resource |
| PATCH | No* | No | Partial update |
| DELETE | Yes | No | Remove resource |
| HEAD | Yes | Yes | Read metadata only |
| OPTIONS | Yes | Yes | Discovery / CORS preflight |

*PATCH may be idempotent depending on implementation. JSON Merge Patch with absolute field assignments is usually idempotent; JSON Patch `add/remove` ops may not be.

## Status Codes

### Success
| Code | When to use |
|------|-------------|
| 200 OK | General success for GET, PUT, PATCH |
| 201 Created | Resource created successfully. Include `Location` header. |
| 202 Accepted | Request accepted for async processing |
| 204 No Content | Success with no body (DELETE, empty PUT/PATCH) |

### Client Error
| Code | When to use |
|------|-------------|
| 400 Bad Request | Malformed request syntax or invalid query params |
| 401 Unauthorized | Missing or invalid authentication |
| 403 Forbidden | Authenticated but not authorized for this resource |
| 404 Not Found | Resource does not exist |
| 409 Conflict | Business logic conflict (duplicate idempotency key with different payload, stale version) |
| 412 Precondition Failed | ETag / If-Match version conflict |
| 422 Unprocessable Entity | Semantic validation errors (e.g., invalid enum value, missing required field in body) |
| 429 Too Many Requests | Rate limit exceeded |

### Server Error
| Code | When to use |
|------|-------------|
| 500 Internal Server Error | Unexpected server error |
| 502 Bad Gateway | Upstream service error |
| 503 Service Unavailable | Server temporarily overloaded or in maintenance |
| 504 Gateway Timeout | Upstream timeout |

## Idempotency Patterns

### Idempotency Keys

For non-idempotent operations (POST, non-idempotent PATCH), accept an `Idempotency-Key: <uuid>` header.

**Server behavior:**
1. Store `key → { request_hash, response, expiry }` in a cache or idempotency store.
2. On replay with matching request hash, return cached response with `200/201`.
3. On replay with mismatching request hash, return `409 Conflict`.
4. Return `Idempotency-Key` in response headers.

**OpenAPI example:**
```yaml
paths:
  /payments:
    post:
      operationId: createPayment
      parameters:
        - name: Idempotency-Key
          in: header
          required: true
          schema:
            type: string
            format: uuid
      responses:
        '201':
          description: Payment created or replayed
          headers:
            Idempotency-Key:
              schema:
                type: string
```

### Conditional Requests (Optimistic Locking)

Use `ETag` + `If-Match` for concurrent modification protection:

```
GET /tasks/123
ETag: "abc123"

PATCH /tasks/123
If-Match: "abc123"
```

If the resource changed since read, respond `412 Precondition Failed`.

## Pagination Patterns

### Offset Pagination

Best for small tables, admin interfaces, or when users need direct page navigation.

```
GET /tasks?offset=0&limit=20
GET /tasks?page=1&per_page=20
```

**Response body:**
```json
{
  "data": [...],
  "pagination": {
    "offset": 0,
    "limit": 20,
    "total": 145,
    "has_more": true
  }
}
```

**Tradeoffs:**
- Deep offsets are slow in SQL (`OFFSET 100000`).
- Results shift if data changes during pagination (drift).

### Cursor Pagination (Recommended)

Best for user-facing infinite scroll, real-time data, and large datasets.

```
GET /tasks?cursor=eyJpZCI6MTAwfQ&limit=20
```

**Response body:**
```json
{
  "data": [...],
  "pagination": {
    "next_cursor": "eyJpZCI6MTIwfQ",
    "prev_cursor": null,
    "has_more": true
  }
}
```

**Cursor encoding:** Base64-encode a JSON object with the sort field(s): `base64({"id": 120, "created_at": "2024-01-15T10:00:00Z"})`

**SQL implementation:**
```sql
SELECT * FROM tasks
WHERE (created_at, id) > (:cursor_created_at, :cursor_id)
ORDER BY created_at ASC, id ASC
LIMIT :limit;
```

**Headers alternative:** Some APIs use `Link` headers:
```
Link: <https://api.example.com/tasks?cursor=abc123>; rel="next"
```

### Keyset Pagination (Cursor variant)

Use when sorting by multiple columns. Always include a deterministic tie-breaker (e.g., `id`).

## Filtering and Sorting

### Filtering

Use query parameters. Allow compound filters with consistent operators.

```
GET /tasks?status=in_progress&priority=high
GET /tasks?created_at[gte]=2024-01-01&created_at[lte]=2024-01-31
GET /tasks?tags=backend,api
GET /tasks?search=invoice payment
```

**Operators (bracket style):**
| Operator | Meaning |
|----------|---------|
| `[eq]` | Equal (default if omitted) |
| `[ne]` | Not equal |
| `[gt]` | Greater than |
| `[gte]` | Greater than or equal |
| `[lt]` | Less than |
| `[lte]` | Less than or equal |
| `[in]` | In list (comma-separated) |
| `[like]` | Pattern match (use sparingly; prefer `search`) |

**OpenAPI parameter example:**
```yaml
parameters:
  - name: created_at[gte]
    in: query
    schema:
      type: string
      format: date-time
```

### Sorting

Use a single `sort` or `order_by` parameter. Support multi-column sorting with comma separation. Prefix with `-` for descending.

```
GET /tasks?sort=-priority,created_at
```

## Error Response Schema

Return a consistent error envelope for all 4xx and 5xx responses.

```json
{
  "error": {
    "code": "invalid_request",
    "message": "The request could not be processed.",
    "request_id": "req_abc123",
    "details": [
      {
        "field": "email",
        "code": "invalid_format",
        "message": "Must be a valid email address."
      }
    ]
  }
}
```

**Required fields:**
- `code`: Machine-readable error code (snake_case)
- `message`: Human-readable summary
- `request_id`: Unique request identifier for tracing

**Optional fields:**
- `details[]`: Field-level validation errors
- `doc_url`: Link to error documentation

**OpenAPI component:**
```yaml
components:
  schemas:
    Error:
      type: object
      required: [error]
      properties:
        error:
          type: object
          required: [code, message, request_id]
          properties:
            code: { type: string }
            message: { type: string }
            request_id: { type: string }
            details:
              type: array
              items:
                type: object
                properties:
                  field: { type: string }
                  code: { type: string }
                  message: { type: string }
```

## Caching Headers

### Resource-level Caching

```
Cache-Control: max-age=60, stale-while-revalidate=300
ETag: "sha256:abc123"
Last-Modified: Wed, 15 Jan 2024 10:00:00 GMT
```

### Collection-level Caching

Collections typically use shorter cache times or no caching:

```
Cache-Control: no-cache
```

For slowly changing collections, use `ETag` on the query string hash.

## Rate Limiting Headers

Use standard or draft-standard headers:

```
RateLimit-Limit: 100
RateLimit-Remaining: 42
RateLimit-Reset: 1700000000
Retry-After: 120
```

**Legacy headers (also acceptable):**
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 42
X-RateLimit-Reset: 1700000000
```

**Response on 429:**
```json
{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "Rate limit exceeded. Retry after 120 seconds.",
    "request_id": "req_xyz789"
  }
}
```

## Content Negotiation

Default to JSON. Support explicit content types.

```
Accept: application/json
Content-Type: application/json
```

For bulk operations or file uploads:
```
Content-Type: multipart/form-data
```

For PATCH formats, be explicit:
```
Content-Type: application/merge-patch+json    # RFC 7386
Content-Type: application/json-patch+json      # RFC 6902
```

## HATEOAS (Optional)

For hypermedia-driven APIs, include `_links` in responses:

```json
{
  "id": "123",
  "title": "Deploy API",
  "_links": {
    "self": { "href": "/tasks/123" },
    "complete": { "href": "/tasks/123/complete", "method": "POST" },
    "project": { "href": "/projects/456" }
  }
}
```

HATEOAS is powerful but adds payload size. Use when API consumers are generic or unknown (public APIs, SDKs).

## URL Versioning

Place version at the start of the path:

```
/v1/tasks
/v2/tasks
```

**Guidelines:**
- Bump version only for breaking changes.
- Maintain at least one previous version for a deprecation window (typically 6-12 months).
- Include deprecation headers on sunset versions:
  ```
  Sunset: Sat, 01 Jun 2024 00:00:00 GMT
  Deprecation: true
  ```

## Batch Operations

For bulk create/update/delete, use a dedicated sub-resource or a single PATCH/PUT with array semantics.

```
POST /tasks/bulk
Content-Type: application/json

{
  "operations": [
    { "action": "create", "data": { "title": "Task A" } },
    { "action": "update", "id": "123", "data": { "status": "done" } }
  ]
}
```

Return `207 Multi-Status` with per-item results:

```json
{
  "results": [
    { "status": 201, "id": "789", "data": { "title": "Task A" } },
    { "status": 200, "id": "123", "data": { "status": "done" } },
    { "status": 404, "id": "999", "error": { "code": "not_found" } }
  ]
}
```

## Webhooks

When exposing webhooks to consumers:

- Allow consumers to register multiple endpoints with filtering (event types).
- Deliver with `Webhook-Id`, `Webhook-Timestamp`, and a signature header.
- Retry with exponential backoff + jitter on non-2xx or timeout.
- Support idempotency on delivery using `Webhook-Id`.

**Webhook payload envelope:**
```json
{
  "event": "task.completed",
  "id": "evt_abc123",
  "timestamp": "2024-01-15T10:00:00Z",
  "data": {
    "id": "task_123",
    "previous_attributes": { "status": "in_progress" }
  }
}
```
