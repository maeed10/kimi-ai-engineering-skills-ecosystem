# Breaking Change Taxonomy for OpenAPI Specs

Use this catalog to classify every detected diff. When in doubt, treat as breaking.

## Breaking Changes — Require Major Version Bump

### Endpoints

| Change | Severity | Rationale |
|--------|----------|-----------|
| Remove an endpoint/path entirely | Critical | Consumers lose functionality |
| Change HTTP method for existing path | Critical | Existing calls return 405 |
| Change path parameter pattern (e.g., `/items/{id}` → `/items/{itemId}` with different regex) | High | Existing URLs may no longer match |
| Remove path parameter | High | URL structure changes |

### Request Parameters

| Change | Severity | Rationale |
|--------|----------|-----------|
| Add `required` query/header/path parameter | High | Existing requests fail validation |
| Remove a parameter that was previously accepted | Medium | Clients sending it get rejected by strict validators |
| Change parameter type (e.g., `string` → `integer`) | Critical | Existing requests may fail parsing |
| Change parameter `format` (e.g., `date-time` → `uuid`) | High | Existing values become invalid |
| Add `enum` restriction to existing free-form parameter | High | Previously valid values rejected |
| Reduce `maxLength` / increase `minLength` | High | Existing values may violate constraint |
| Add `pattern` regex constraint | High | Existing values may fail |
| Change `allowEmptyValue` from true to false | Medium | Empty values now rejected |

### Request Body

| Change | Severity | Rationale |
|--------|----------|-----------|
| Add `required` field to request body schema | Critical | Existing payloads fail validation |
| Remove field from request body | Medium | Consumers referencing it break |
| Change field type in request body | Critical | Payload parsing fails |
| Add `additionalProperties: false` where previously allowed | High | Extra fields now rejected |
| Tighten `oneOf` / `anyOf` / `allOf` constraints | High | Previously valid payloads fail |

### Responses

| Change | Severity | Rationale |
|--------|----------|-----------|
| Remove success response status code (e.g., remove `200`, keep only `201`) | Critical | Clients expecting 200 fail |
| Remove field from response schema | Critical | Consumer parsing breaks |
| Change response field type | Critical | Consumer deserialization fails |
| Change `200` response to `201` or vice versa | Medium | If consumer differentiates strictly |
| Remove `default` or error response | Low | Error handling may break |
| Change `Content-Type` | High | Consumer content negotiation fails |

### Security

| Change | Severity | Rationale |
|--------|----------|-----------|
| Add authentication requirement to previously open endpoint | Critical | Unauthenticated consumers blocked |
| Change auth scheme (e.g., basic → OAuth2) | Critical | Existing credentials/calls fail |
| Add required scope/permission | High | Existing tokens insufficient |
| Remove security scheme option (if multiple were offered) | Medium | Consumers using removed scheme break |

## Non-Breaking Changes — Safe Without Notification

### Endpoints

| Change | Notes |
|--------|-------|
| Add new endpoint/path | Net new capability |
| Add new HTTP method to existing path | e.g., add `PATCH` where only `GET` existed |

### Parameters

| Change | Notes |
|--------|-------|
| Add optional parameter | `required: false` or no `required` set |
| Remove `required` from parameter | Relaxing constraint |
| Increase `maxLength` / decrease `minLength` | Relaxing constraint |
| Remove `pattern` constraint | Relaxing validation |
| Add `default` value to optional parameter | Improves ergonomics |
| Add `deprecated: true` flag | Informational only |

### Request Body

| Change | Notes |
|--------|-------|
| Add optional field | Consumers ignoring unknown fields unaffected |
| Change `additionalProperties` to `true` | Relaxing constraint |
| Remove `required` from existing field | Relaxing constraint |

### Responses

| Change | Notes |
|--------|-------|
| Add new response status code | Consumers handle known codes; new one is extra |
| Add field to response schema | Consumers ignoring unknown fields unaffected |
| Add `description` to response | Documentation only |
| Relax response schema constraints | Wider acceptance |
| Add `examples` | Documentation only |

### Schema

| Change | Notes |
|--------|-------|
| Add schema to `components/schemas/` | Unused until referenced |
| Add `description`, `title`, `format: uuid` annotations | Documentation only |
| Add `x-*` extension fields | Ignored by standard tools |

## Gray Area — Evaluate Case by Case

| Change | Default Classification | Evaluation Criteria |
|--------|----------------------|---------------------|
| Change default value of parameter | Breaking | Do consumers rely on the implicit default? |
| Add new value to `enum` response field | Non-Breaking | Do downstream consumers validate enums strictly? |
| Split a field into two (e.g., `name` → `firstName` + `lastName`) | Breaking | Is old field preserved with `deprecated`? |
| Change error response schema | Breaking | Do consumers parse error bodies programmatically? |
| Change pagination default `limit` | Non-Breaking | Do consumers depend on specific page sizes? |
| Reorder `anyOf`/`oneOf` alternatives | Non-Breaking | Does consumer validation depend on order? |

## Checklist for Manual Review

When automated classification is ambiguous:

- [ ] Are there known consumers that strictly validate responses?
- [ ] Do mobile clients require schema stability for deserialization?
- [ ] Is the change behind a feature flag that limits blast radius?
- [ ] Can the change be rolled back within 5 minutes if issues arise?
- [ ] Is there a deprecation period with the old behavior still functional?

If 2+ answers are "yes" → classify as breaking and require HITL approval.