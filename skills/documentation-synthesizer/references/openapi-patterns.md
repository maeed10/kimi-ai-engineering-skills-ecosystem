# OpenAPI Generation Patterns

Language-specific recipes for extracting OpenAPI 3.0 specifications from code, with validation pipelines and CI integration examples.

## Python — FastAPI + Pydantic

**Pattern**: Type hints + Pydantic models + route decorators → automatic OpenAPI schema [^264^].

```python
from fastapi import FastAPI, Query
from pydantic import BaseModel, Field

class Item(BaseModel):
    name: str = Field(description="The item's display name")
    price: float = Field(gt=0, description="Price in USD")
    tags: list[str] = []

app = FastAPI(title="Items API", version="1.0.0")

@app.get("/items/{item_id}", response_model=Item, tags=["items"])
async def get_item(
    item_id: int = Path(..., ge=1),
    include_deleted: bool = Query(False)
):
    """Retrieve a single item by ID."""
    ...
```

**Extraction points**:
- `app = FastAPI(...)` → `info.title`, `info.version`, `info.description`
- `@app.get/post/put/delete` → paths, methods, operationIds
- `response_model=` → response schema reference
- Path/Query/Body parameter defaults → parameter schema with required, type, constraints
- Pydantic `Field(...)` → `description`, `minimum`, `maximum`, `pattern`, `enum`
- `tags=` → operation tags for grouping

**Validation pipeline**:
```bash
# 1. Generate spec at build time
python -c "import json; from main import app; print(json.dumps(app.openapi()))" > openapi.json

# 2. Spectral lint
npx @stoplight/spectral-cli lint openapi.json

# 3. Diff against committed version
oasdiff diff base/openapi.json openapi.json

# 4. Contract testing (optional but recommended)
schemathesis run openapi.json --base-url=http://localhost:8000
```

---

## TypeScript / Node.js — tsoa + Express

**Pattern**: Controller decorators + TypeScript interfaces → OpenAPI spec [^321^].

```typescript
import { Route, Get, Controller, Query } from "tsoa";

interface User {
  id: number;
  name: string;
  email: string;
}

@Route("users")
export class UsersController extends Controller {
  @Get("{userId}")
  async getUser(
    @Path() userId: number,
    @Query() includeProfile?: boolean
  ): Promise<User> {
    ...
  }
}
```

**Extraction points**:
- `@Route("path")` on class → base path
- `@Get/Post/Put/Delete("subpath")` → operation path + method
- Method return type `Promise<User>` → response schema
- `@Path()`, `@Query()`, `@Body()` parameter decorators → parameter location + type
- TypeScript interfaces → `#/components/schemas/`

**Build-time generation**:
```bash
# tsoa generates routes.ts and swagger.json from decorators
tsoa spec-and-routes

# Validate generated spec
npx @stoplight/spectral-cli lint build/swagger.json

# Capture traffic from E2E tests and compare against spec
optic capture openapi.yaml --command "npm run test:e2e"
optic verify openapi.yaml
```

---

## Java — Springdoc + Spring Boot

**Pattern**: Spring annotations + Java types → OpenAPI spec.

```java
@RestController
@RequestMapping("/api/v1/items")
@Tag(name = "items", description = "Item management endpoints")
public class ItemController {

    @GetMapping("/{id}")
    @Operation(summary = "Get item by ID")
    @ApiResponses({
        @ApiResponse(responseCode = "200", description = "Item found"),
        @ApiResponse(responseCode = "404", description = "Item not found")
    })
    public ResponseEntity<Item> getItem(
        @PathVariable @Parameter(description = "Item ID") Long id
    ) { ... }
}
```

**Extraction points**:
- `@RestController` + `@RequestMapping` → base path
- `@GetMapping/PostMapping` → operation path + method
- `@Operation` → `summary`, `description`, `operationId`
- `@ApiResponse` → responses section
- Method return type `ResponseEntity<Item>` → response schema
- `@PathVariable/@RequestParam/@RequestBody` → parameters with location

**Maven/Gradle integration**:
```xml
<plugin>
  <groupId>org.springdoc</groupId>
  <artifactId>springdoc-openapi-maven-plugin</artifactId>
  <executions>
    <execution>
      <id>generate-openapi</id>
      <goals><goal>generate</goal></goals>
    </execution>
  </executions>
</plugin>
```

---

## Rust — utoipa + Axum/Actix

**Pattern**: Macros + Rust types → OpenAPI spec [^322^].

```rust
use utoipa::{OpenApi, ToSchema, path};
use serde::Serialize;

#[derive(Serialize, ToSchema)]
struct Item {
    #[schema(example = "Widget")]
    name: String,
    #[schema(minimum = 0.0)]
    price: f64,
}

#[utoipa::path(
    get,
    path = "/items/{id}",
    params(("id" = i64, Path, description = "Item ID")),
    responses((status = 200, body = Item))
)]
async fn get_item(id: i64) -> Json<Item> { ... }
```

**Extraction points**:
- `#[utoipa::path(...)]` macro → path, method, params, responses
- `#[derive(ToSchema)]` → component schema registration
- `#[schema(...)]` attributes → field descriptions, constraints, examples
- Function parameters → operation parameters with type inference

**Validation pipeline**:
```bash
# Generate spec in test; fail CI if spec changes
cargo test --test openapi_snapshot
# Test reads generated spec, compares against committed version

# Schemathesis property-based validation
schemathesis run openapi.json --base-url=http://localhost:8080
```

---

## CI/CD Integration Matrix

| Stage | Tool | Command | Gate |
|-------|------|---------|------|
| Build | Language-specific generator | `tsoa spec`, `springdoc`, `app.openapi()` | Generate spec |
| Lint | Spectral | `npx @stoplight/spectral-cli lint openapi.json` | Block on errors |
| Diff | oasdiff | `oasdiff diff base/head openapi.json` | Block on breaking changes |
| Test | Schemathesis | `schemathesis run openapi.json` | Block on contract failures |
| Deploy | Git-based | Mintlify/Fern/Redocly | Auto-deploy on merge |

**Breaking change detection**:
```bash
# Fail CI if breaking changes introduced
oasdiff breaking base/openapi.json head/openapi.json \
  --fail-on BREAKING_REQUEST_CHANGED \
  --fail-on BREAKING_RESPONSE_CHANGED
```

**Snapshot testing** (recommended for all languages):
Store a committed `openapi.json` in version control. CI generates fresh spec and fails if `diff` is non-empty. This guarantees docs and code ship as an atomic unit.

---

## Symbolication & Drift Prevention

**Spec-as-source-of-truth** [^254^]: In OpenAPI-first workflows, the spec is the contract. Both server code and documentation derive from it. This eliminates human coordination for core reference content.

**Code-as-source-of-truth** (default for this skill): The code generates the spec. CI enforces that committed spec matches generated spec. This ensures the spec never diverges from implementation.

**Hybrid approach** [^254^][^363^]: Use spec for public API contracts, code-generated docs for internal modules. Contract testing (Pactflow, Karate, Hypertest) verifies both directions.

---

**Sources**: FastAPI docs [^264^], tsoa [^321^], Optic [^321^], Springdoc, utoipa [^322^], Schemathesis [^322^], Spectral [^315^], oasdiff [^315^], Fern spec-driven docs [^254^], Nordic APIs drift analysis [^363^]
