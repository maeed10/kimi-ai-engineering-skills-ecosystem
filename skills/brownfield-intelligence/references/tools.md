## Tool Usage & Integration Protocols

### SQLite Schema Definition

**Canonical six-table schema**:

```sql
-- Core entities
CREATE TABLE files (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    language TEXT,
    lines_of_code INTEGER,
    bytes INTEGER,
    last_modified TEXT,
    sha256 TEXT
);

CREATE TABLE symbols (
    id INTEGER PRIMARY KEY,
    file_id INTEGER REFERENCES files(id),
    name TEXT NOT NULL,
    type TEXT NOT NULL,  -- 'function', 'class', 'variable', 'import', 'interface', etc.
    line_start INTEGER,
    line_end INTEGER,
    signature TEXT,
    docstring TEXT,
    parent_symbol_id INTEGER REFERENCES symbols(id)
);

-- Relationships
CREATE TABLE dependencies (
    id INTEGER PRIMARY KEY,
    source_file_id INTEGER REFERENCES files(id),
    target_file_id INTEGER REFERENCES files(id),
    source_symbol_id INTEGER REFERENCES symbols(id),
    target_symbol_id INTEGER REFERENCES symbols(id),
    dep_type TEXT NOT NULL,  -- 'import', 'call', 'inherit', 'type_use', 'contain'
    line_number INTEGER
);

-- API endpoints
CREATE TABLE api_endpoints (
    id INTEGER PRIMARY KEY,
    file_id INTEGER REFERENCES files(id),
    method TEXT,
    path TEXT,
    handler_symbol_id INTEGER REFERENCES symbols(id),
    framework TEXT,  -- 'fastapi', 'flask', 'django', 'spring', 'express', etc.
    auth_required INTEGER DEFAULT 0,  -- 0=unknown, 1=yes, -1=no
    openapi_spec TEXT
);

-- Metrics
CREATE TABLE file_metrics (
    file_id INTEGER PRIMARY KEY REFERENCES files(id),
    cyclomatic_complexity INTEGER,
    function_count INTEGER,
    class_count INTEGER,
    import_count INTEGER,
    comment_ratio REAL,
    duplicate_flag INTEGER DEFAULT 0
);

-- Full-text search on code content
CREATE VIRTUAL TABLE code_fts USING fts5(
    path, content, tokenize='porter'
);
```

**Recommended indexes**:
```sql
CREATE INDEX idx_symbols_file ON symbols(file_id);
CREATE INDEX idx_symbols_name ON symbols(name);
CREATE INDEX idx_symbols_type ON symbols(type);
CREATE INDEX idx_deps_source_file ON dependencies(source_file_id);
CREATE INDEX idx_deps_target_file ON dependencies(target_file_id);
CREATE INDEX idx_deps_type ON dependencies(dep_type);
CREATE INDEX idx_api_file ON api_endpoints(file_id);
CREATE INDEX idx_api_path ON api_endpoints(path);
CREATE INDEX idx_files_lang ON files(language);
CREATE INDEX idx_files_sha ON files(sha256);
```

### Tree-Sitter Extraction Pipeline

**Pass 1: AST Symbol Extraction** (deterministic, all languages)
1. Parse file with tree-sitter grammar
2. Extract function definitions: name, parameter signature, docstring, line range
3. Extract class definitions: name, base classes, methods, line range
4. Extract variable declarations: name, type annotation (if available), scope
5. Extract import statements: module path, imported names, alias mapping

**Pass 2: Dependency Resolution** (deterministic, cross-file)
1. Map import statements to resolved file paths
2. Map function calls to defined symbols (intra-file and inter-file)
3. Map inheritance chains to parent class definitions
4. Map type usages to type definitions
5. Record `dep_type` and `line_number` for every edge

**Pass 3: Framework-Specific API Extraction** (deterministic where possible)
- **FastAPI**: Extract `@app.get/post/put/delete` decorators, path parameters, handler functions
- **Flask**: Extract `@app.route` decorators, methods, view functions
- **Django REST**: Extract `path()` or `url()` patterns, `@api_view` decorators
- **Spring Boot**: Extract `@GetMapping`, `@PostMapping`, `@RequestMapping` annotations
- **Express.js**: Extract `app.get/post/put/delete` and `router` patterns
- **Rails**: Extract `resources`, `get/post` in `routes.rb` and controller actions

For frameworks requiring runtime discovery, flag endpoints as `extracted_from: "static"` and note that dynamic route registration may be missed.

**Pass 4: Metrics Computation** (deterministic)
- SLOC: count non-empty, non-comment lines
- Cyclomatic complexity: count branching statements (if, for, while, case, and, or) + 1 [^15^]
- Function count: count from symbols table where type='function'
- Class count: count from symbols table where type='class'
- Import count: count from dependencies where dep_type='import'
- Comment ratio: comment lines / total lines

### Query Interface

**Direct lookups** (parameterized SQL):
```sql
-- What symbols are defined in file X?
SELECT * FROM symbols WHERE file_id = ?;

-- What files depend on file X?
SELECT DISTINCT f.path FROM files f
JOIN dependencies d ON f.id = d.source_file_id
WHERE d.target_file_id = ?;

-- What is the cyclomatic complexity of file X?
SELECT cyclomatic_complexity FROM file_metrics WHERE file_id = ?;
```

**Transitive queries** (recursive CTEs):
```sql
-- Full dependency chain for file X
WITH RECURSIVE chain AS (
    SELECT target_file_id, 0 as depth FROM dependencies
    WHERE source_file_id = ?
    UNION ALL
    SELECT d.target_file_id, c.depth + 1
    FROM dependencies d
    JOIN chain c ON d.source_file_id = c.target_file_id
    WHERE c.depth < 10
)
SELECT DISTINCT f.path, c.depth FROM files f
JOIN chain c ON f.id = c.target_file_id;
```

**FTS5 full-text search**:
```sql
-- Search code content for pattern
SELECT * FROM code_fts WHERE content MATCH ?;
```

**Predefined templates** (whitelist of safe query patterns):
| Template | Description | Parameters |
|----------|-------------|------------|
| `file_dependencies` | Files depending on target | `file_id` |
| `symbol_callers` | Functions calling target symbol | `symbol_id` |
| `complexity_hotspots` | Files with complexity > threshold | `threshold` |
| `dead_code_candidates` | Symbols with zero incoming deps | `exclude_tests` |
| `api_surface` | All API endpoints | `framework` (optional) |
| `circular_dependencies` | Circular import pairs | none |
| `unauth_endpoints` | API endpoints with auth_unknown | none |

### Validation Protocols

- **Pre-indexing**: Verify tree-sitter grammar packages installed, SQLite writable, target path exists and is a directory
- **Post-indexing**: Run integrity checks:
  - `SELECT COUNT(*) FROM symbols` should be > 0 for non-empty codebases
  - `SELECT COUNT(*) FROM dependencies` should be > 0 for multi-file projects
  - `PRAGMA integrity_check` on SQLite database
  - Spot-check: query known file, verify symbol count matches manual inspection
- **Query-time**: Validate all parameters against expected types and ranges. Reject queries that would return >10,000 rows (suggest pagination or narrowing).
