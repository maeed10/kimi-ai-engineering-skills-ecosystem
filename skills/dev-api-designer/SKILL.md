---
name: dev-api-designer
description: Developer-facing API design skill for REST and GraphQL. Generates OpenAPI specs, mock servers, client SDKs, and contract tests. Use when designing endpoints, documenting APIs, generating SDKs, validating backward compatibility, or setting up API mocking. Supports pagination, rate limiting, versioning, and GraphQL schema design.
---

# dev-api-designer

Design, document, and validate REST and GraphQL APIs. Generate OpenAPI specs, mock servers, client SDKs, and contract tests from code or requirements.

## Overview

This skill provides end-to-end API design capabilities for software engineers working in Kimi CLI. It covers REST and GraphQL API design, OpenAPI 3.1 specification generation, mock server setup, client SDK generation, contract testing, and operational concerns like rate limiting and versioning.

Use this skill when:
- Designing a new API endpoint, resource, or service
- Documenting existing APIs with OpenAPI/Swagger
- Generating TypeScript, Python, or Go client SDKs from specs
- Setting up mock servers for frontend development
- Validating API backward compatibility during changes
- Implementing pagination, filtering, or rate limiting
- Designing GraphQL schemas, resolvers, or federation boundaries

## Workflow Decision Tree

```
Start: API Task
│
├─ Designing a new API?
│   ├─ REST ──> OpenAPI 3.1 spec → Review checklist → Mock server → SDK
│   └─ GraphQL ──> Schema design → Resolver plan → N+1 audit → Federation review
│
├─ Documenting an existing API?
│   ├─ Has code annotations (FastAPI, SpringDoc, tsoa)?
│   │   └─ Yes ──> Extract / generate OpenAPI from code
│   └─ No annotations? ──> Hand-write OpenAPI YAML/JSON → Validate
│
├─ Need mocking for frontend/dev?
│   └─ Use OpenAPI/GraphQL schema → Prism, Mockoon, or graphql-yoga
│
├─ Need client SDK?
│   └─ OpenAPI generator → TypeScript, Python, Go, Java, etc.
│
├─ Changing an existing API?
│   └─ Backward compatibility check → Contract tests → Versioning strategy
│
└─ Operational design?
    ├─ Rate limiting ──> Token bucket / Leaky bucket / Sliding window
    └─ Versioning ──> URL / Header / GraphQL schema evolution
```

## Core Capabilities

### 1. OpenAPI 3.1 Generation

Auto-generate OpenAPI specs from code annotations or hand-write them from requirements.

**From code annotations:**
- **FastAPI**: Native `openapi.json` at `/openapi.json`. Use `response_model`, `Query()`, `Path()` for accurate schemas.
- **SpringDoc**: Spring Boot with `@Operation`, `@ApiResponse`, `@Schema`. Generates `/v3/api-docs`.
- **tsoa**: TypeScript decorators `@Route`, `@Get`, `@Post` with controller classes.

**Hand-written OpenAPI (YAML preferred):**
```yaml
openapi: 3.1.0
info:
  title: Task Service API
  version: 1.0.0
  description: REST API for task management
paths:
  /tasks:
    get:
      operationId: listTasks
      parameters:
        - $ref: '#/components/parameters/PageCursor'
        - $ref: '#/components/parameters/PageLimit'
      responses:
        '200':
          description: Paginated list of tasks
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/PaginatedTasks'
    post:
      operationId: createTask
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/TaskCreate'
      responses:
        '201':
          description: Task created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Task'
        '409':
          description: Conflict - idempotent key replayed with different payload
```

**Validation tools:**
- `swagger-editor` (web) or `@apidevtools/swagger-cli validate openapi.yaml`
- `schemathesis run openapi.yaml --base-url=http://localhost:8080`

### 2. GraphQL Schema Design

Design type schemas with clear boundaries, pagination, and mutation patterns.

**Schema-first approach:**
```graphql
type Query {
  tasks(first: Int, after: String, filter: TaskFilter): TaskConnection!
  task(id: ID!): Task
}

type Mutation {
  createTask(input: CreateTaskInput!): CreateTaskPayload!
}

type Task {
  id: ID!
  title: String!
  status: TaskStatus!
  createdAt: DateTime!
}

type TaskConnection {
  edges: [TaskEdge!]!
  pageInfo: PageInfo!
}

type TaskEdge {
  node: Task!
  cursor: String!
}

type PageInfo {
  hasNextPage: Boolean!
  endCursor: String
  totalCount: Int
}

input TaskFilter {
  status: TaskStatus
  search: String
}

input CreateTaskInput {
  title: String!
  status: TaskStatus = BACKLOG
  clientMutationId: String
}

type CreateTaskPayload {
  task: Task!
  clientMutationId: String
}

enum TaskStatus { BACKLOG TODO IN_PROGRESS DONE CANCELLED }
```

**Pagination pattern**: Relay Cursor Connections for collections. Offset/limit only acceptable for small, non-realtime datasets.

**Mutation pattern**: Input object + Payload object + `clientMutationId` for idempotency tracking.

### 3. API Review Checklist

Before finalizing any API design, verify against the checklist in `references/rest_patterns.md` and `references/graphql_patterns.md`.

**Quick REST checklist:**
- [ ] Resource-oriented URLs (`/tasks`, not `/getTasks`)
- [ ] Correct HTTP methods (GET, POST, PUT, PATCH, DELETE)
- [ ] Proper status codes (201 Created, 204 No Content, 409 Conflict, 422 Unprocessable Entity)
- [ ] Idempotency keys for POST/PUT/PATCH when needed (`Idempotency-Key: <uuid>`)
- [ ] Consistent pagination strategy (cursor vs offset)
- [ ] Filtering and sorting as query params, not body
- [ ] Rate limit headers (`RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`)
- [ ] Content negotiation (`Accept`, `Content-Type: application/json`)
- [ ] Error response schema consistency (`{ error: { code, message, details[] } }`)
- [ ] Versioning strategy defined (URL `/v1/`, header `API-Version`, or content-type)

### 4. Mock Server Generation

Generate mock servers from OpenAPI or GraphQL schemas for frontend development.

**OpenAPI mock servers:**
- **Prism**: `prism mock openapi.yaml` — dynamic mocking from examples.
- **Mockoon**: GUI/CLI with rules, latency simulation, and proxy mode.

**GraphQL mock servers:**
- **graphql-yoga + @graphql-tools/mock**: Mock resolvers from schema.
- **Apollo Server mocks**: `new ApolloServer({ typeDefs, mocks: true })`

**Best practice**: Include `x-examples` in OpenAPI or `@example` directives in GraphQL for realistic mock data.

### 5. Client SDK Generation

Generate client libraries from OpenAPI specs using `openapi-generator`.

```bash
# TypeScript-fetch
docker run --rm -v $(pwd):/local openapitools/openapi-generator-cli generate \
  -i /local/openapi.yaml \
  -g typescript-fetch \
  -o /local/sdk-ts

# Python
docker run --rm -v $(pwd):/local openapitools/openapi-generator-cli generate \
  -i /local/openapi.yaml \
  -g python \
  -o /local/sdk-py

# Go
docker run --rm -v $(pwd):/local openapitools/openapi-generator-cli generate \
  -i /local/openapi.yaml \
  -g go \
  -o /local/sdk-go
```

**Alternatives:**
- `openapi-typescript` (TypeScript types from spec)
- `swagger-codegen` (legacy, use `openapi-generator` instead)
- Custom generator with `openapi-generator-cli meta`

### 6. Contract Testing

Validate that the API implementation conforms to the OpenAPI/GraphQL schema.

**Tools:**
- **Schemathesis**: Property-based testing from OpenAPI. `st run openapi.yaml --base-url=http://localhost:8080`
- **Dredd**: API Blueprint / OpenAPI integration testing. `dredd openapi.yaml http://localhost:8080`
- **Prism**: Validate proxy mode `prism proxy openapi.yaml http://localhost:8080`

**GraphQL contract tests:**
- Use `@graphql-inspector` for schema diff and coverage.
- Use `jest` + `graphql-tools` to validate resolver return types against schema.

### 7. Rate Limiting Design

Choose a rate limiting algorithm based on traffic patterns:

| Algorithm | Use Case | Tradeoff |
|-----------|----------|----------|
| Token Bucket | Bursty traffic, overall rate cap | Allows bursts |
| Leaky Bucket | Smooth, consistent rate | Queues or drops excess; no burst |
| Sliding Window Log | Accurate strict limit | Memory intensive |
| Sliding Window Counter | Approximate, memory efficient | May allow slight burst |

**Headers (RFC 6585 + draft-ietf-httpapi-ratelimit-headers):**
```
RateLimit-Limit: 100
RateLimit-Remaining: 42
RateLimit-Reset: 1699999999
Retry-After: 3600
```

**GraphQL rate limiting:**
- Complexity-based scoring (field cost × depth)
- Query depth limiting
- Persisted queries for production

### 8. Versioning Strategy

| Strategy | Mechanism | Pros | Cons |
|----------|-----------|------|------|
| URL Versioning | `/v1/tasks`, `/v2/tasks` | Simple, cacheable, explicit | Pollutes URL; resource identity changes |
| Header Versioning | `API-Version: 2024-01-15` | Clean URLs; resource stable | Less visible; requires header discipline |
| Content Negotiation | `Accept: application/vnd.api+json;version=2` | REST purist approach | Complex; poor tooling support |
| GraphQL Evolution | Add fields, deprecate with `@deprecated` | No versioning needed | Schema bloat; requires deprecation policy |

**Recommended:** URL versioning for REST in multi-year contracts. Header versioning (Stripe-style) for SaaS APIs. GraphQL should avoid versioning and use schema evolution with `@deprecated(reason: "Use newField")`.

## Decision Reference

### Cursor vs Offset Pagination

| Factor | Offset | Cursor |
|--------|--------|--------|
| Jump to page | Yes | No |
| Real-time data stability | No (drift) | Yes (stable) |
| Large datasets | Slow (deep OFFSET) | Fast |
| Implementation complexity | Low | Medium |

**Rule of thumb:** Use cursor pagination for user-facing infinite scroll or large datasets. Use offset only for admin/backoffice with small tables.

### PUT vs PATCH

- **PUT**: Full resource replacement. Idempotent. Use when client sends complete resource.
- **PATCH**: Partial update. Not necessarily idempotent. Use JSON Merge Patch (RFC 7386) or JSON Patch (RFC 6902) for structured partial updates.

### When to Use GraphQL vs REST

- **REST**: Simple CRUD, caching at edge (CDN), file uploads, public APIs with many unknown consumers.
- **GraphQL**: Complex nested data requirements, mobile apps with varying bandwidth, BFF pattern, internal APIs with known consumers.

## Resources

### scripts/
- `generate_openapi.py` — Generate OpenAPI 3.1 specs from requirements or code annotations (FastAPI/SpringDoc/tsoa stubs). Validates output and writes YAML/JSON.

### references/
- `rest_patterns.md` — REST best practices, pagination/filtering patterns, idempotency, status codes, error schemas, content negotiation.
- `graphql_patterns.md` — GraphQL schema design, Relay pagination, N+1 prevention, DataLoader patterns, federation, mutation design.
