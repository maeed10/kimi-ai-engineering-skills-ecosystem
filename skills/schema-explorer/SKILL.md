---
name: schema-explorer
description: Inspects database schemas via postgres/sqlite MCPs, generates safe migrations, validates data models against Architecture Design plans, and builds queries from natural language. Assesses migration impact (data loss, downtime) via Blast Radius. Zero database-specific skills existed in the previous 10-skill ecosystem.
license: MIT
compatibility: Kimi Code CLI v1.0+
type: standard
---

# Schema Explorer & Query Builder

Systematic database schema introspection, safe migration generation, query construction from natural language, and schema-drift detection across PostgreSQL, SQLite, and other supported databases. Operates through read-first, validate-always, human-gate-for-write safety architecture.

## Overview

Database schemas are the foundational contract between application code and persistent state. Every schema change carries risk: data loss from destructive DDL, downtime from table locks, application breakage from type mismatches, and cascading failures from foreign key cascades. This skill provides a rigorous, five-phase framework for connecting to databases, introspecting schemas, modeling data, generating safe migrations, and validating queries — with mandatory human gates for all write operations.

Key research foundations:
- SQLAlchemy Inspector provides the most comprehensive backend-agnostic schema reflection API in Python, with multi-table reflection added in 2.0 for efficient bulk introspection [^389^].
- Prisma `db pull` auto-generates models from existing databases across PostgreSQL, MySQL, SQLite, SQL Server, CockroachDB, and MongoDB [^417^][^418^].
- Human experts achieve 92.96% execution accuracy on text-to-SQL benchmarks; top AI systems reach ~81.67%, but benchmark annotation error rates exceed 50% on some datasets, undermining leaderboard reliability [^397^][^354^][^396^].
- Atlas provides declarative schema management with policy-as-code: block destructive operations, block table locks, enforce row-level security [^358^].
- gh-ost (GitHub) and pt-online-schema-change (Percona) enable zero-downtime MySQL migrations for tables with 500M+ rows. A fintech case study with a 500M-row table used gh-ost for column modifications (4h 22min, replica lag < 2.8s) [^385^].
- ORM loading strategies have dramatic performance differences: lazy loading causes N+1 queries; `selectinload()` and `joinedload()` collapse queries to 1-2 [^383^].
- Schema drift detection uses Flyway checksums or Liquibase `diff` against system catalogs (`information_schema`, `pg_catalog`) [^388^].
- PostgreSQL offers `information_schema` for portable queries and `pg_catalog` for PostgreSQL-specific details [^391^]. SQLite uses PRAGMA commands with table-valued function support since 3.16.0 [^390^][^392^].
- AI-generated database code is prone to dangerous anti-patterns: missing indexes, N+1 queries, pathological SQL, wrong dialects, inefficient pagination, and soft-delete filter misses [^413^][^414^][^422^].

For detailed SQL patterns, introspection queries, and ORM optimization guidance, see [references/sql-patterns.md](references/sql-patterns.md).

## Operational Guidelines & Rules

### Always
- Use read-only connections and MCP (Model Context Protocol) tools for schema introspection. Never use a write-capable connection for exploration.
- Provide the full schema context — including all tables, columns, indexes, constraints, and foreign keys — when generating queries or migrations. LLMs cannot infer missing indexes [^423^].
- Generate a schema diff before and after any migration proposal. The diff is the primary validation artifact.
- Validate all AI-generated SQL and DDL with `EXPLAIN ANALYZE` on a read-only replica before production consideration.
- Include rollback scripts (`downgrade()`, `DROP` guards, reverse operations) with every migration proposal.
- Use `selectinload()` for collection relationships and `joinedload()` for many-to-one / one-to-one in ORM query generation [^383^].
- Set query count budgets in development to catch N+1 patterns: assert that endpoint X fires no more than N queries.
- Run schema drift detection in CI pipelines before every deployment. Alert on drift; never auto-remediate.
- Verify generated queries against the specific SQL dialect of the target database (PostgreSQL, SQLite, MySQL). Dialect differences cause silent failures.
- Document migration impact: estimated downtime, rows affected, lock types acquired, and rollback procedure.

### Never
- Generate destructive DDL (`DROP TABLE`, `DROP COLUMN`, `TRUNCATE`, destructive `ALTER TABLE`) without a documented backup plan and human approval.
- Run migrations on a production database without explicit human confirmation and a verified rollback strategy.
- Generate queries without validating them against the actual schema. Missing indexes, wrong types, and phantom columns produce incorrect results.
- Use offset-based pagination for large tables without warning about O(n) degradation. Prefer keyset (cursor) pagination.
- Assume default database permissions are safe. Always verify the migration runs with least-privilege credentials.
- Trust AI-generated SQL for production execution without syntax checking, execution on a read-only replica, and result verification.
- Skip index analysis when generating queries. LLMs do not know what indexes exist unless explicitly provided [^423^].
- Use `DELETE` or `UPDATE` without a `WHERE` clause in any generated example or migration script — even in "safe" examples.
- Generate migrations that modify multiple unrelated tables in a single batch. Split by domain boundary with independent rollback paths.
- Execute schema changes during peak traffic hours. All production migrations require maintenance window coordination.

## Tool Ecosystem & Integration Matrix

| Tool | Role | Databases | Key Strength | Integration Notes |
|------|------|-----------|--------------|-------------------|
| SQLAlchemy Inspector | Python introspection | PostgreSQL, MySQL, SQLite, Oracle, SQL Server, others | Backend-agnostic, multi-table reflection | Use `get_multi_*` APIs for efficiency [^389^] |
| Prisma `db pull` | Model generation | PostgreSQL, MySQL, SQLite, SQL Server, CockroachDB, MongoDB | Auto-generates Prisma models from DB | Preserves manual schema changes on re-introspection [^418^] |
| PostgreSQL `information_schema` | Standard introspection | PostgreSQL | SQL-standard, portable across databases | Use for cross-database tooling [^391^] |
| PostgreSQL `pg_catalog` | Deep introspection | PostgreSQL | PostgreSQL-specific details: partial indexes, storage params | Use when `information_schema` is insufficient [^391^] |
| SQLite PRAGMA | Lightweight introspection | SQLite | Simple commands: `table_info`, `index_list`, `foreign_key_list` | Table-valued PRAGMA enables JOINs since 3.16.0 [^390^][^392^] |
| Alembic | Python migrations | PostgreSQL, MySQL, SQLite, others | Autogenerate from SQLAlchemy models | Review all autogenerated migrations; use batch ops for SQLite [^399^] |
| Flyway | Versioned migrations | All major | Checksum-based drift detection | Integrate in CI; validate before deploy [^388^] |
| Liquibase | Cross-database migrations | All major | `diff` command compares DBs directly via system catalogs | Use for complex cross-database deployments [^388^] |
| gh-ost | Zero-downtime MySQL | MySQL | Triggerless, binlog-based replication | Standard for tables >50M rows [^382^][^385^] |
| pt-online-schema-change | Zero-downtime MySQL | MySQL | Trigger-based shadow table | Better FK support than gh-ost [^381^] |
| Atlas | Declarative schema | PostgreSQL, MySQL, SQLite, SQL Server, MariaDB | Policy-as-code: block destructive ops, table locks | Integrate for AI-assisted migration safety [^358^] |

**Tool selection strategy by database**:
- **PostgreSQL**: SQLAlchemy Inspector for Python tooling; `information_schema` for portable queries; `pg_catalog` for deep details; `CREATE INDEX CONCURRENTLY` for online index builds.
- **SQLite**: PRAGMA commands for simple introspection; table-valued PRAGMA functions for complex JOIN-based analysis. No native online migration support — use batch operations in application code.
- **MySQL at scale**: gh-ost or pt-osc mandatory for tables >50M rows. Never use native `ALTER TABLE` on large production tables.
- **Multi-database enterprise**: Liquibase for cross-database changelogs; Flyway for simple versioned migrations; Atlas for declarative policy-as-code.

**Zero-downtime migration comparison** (MySQL tables >50M rows):

| Feature | gh-ost | pt-osc |
|---------|--------|--------|
| Mechanism | Binlog-based replication | Trigger-based shadow table |
| Trigger Dependency | No triggers required | Requires 3 triggers |
| Throttling | Built-in, replica-aware | Manual configuration |
| Rollback | Pause/abort at any time | Drop shadow table |
| Foreign Key Support | Limited | Better support |
| Standard Use Case | Column modifications | Index creation |

A fintech case study with a 500M-row table used gh-ost for column modifications (4h 22min, replica lag < 2.8s) and pt-osc for index creation (3h 15min, zero impact) [^385^].

## Workflow: Five-Phase Database Analysis

### Phase 1 — Connect

**Objective**: Establish safe, least-privilege connections to the target database.

1. Identify database type and version from connection string or environment variables.
2. Verify connection credentials have read-only permissions for introspection. Write permissions require explicit escalation with documented justification.
3. Test connection with a lightweight ping query (`SELECT 1`, `PRAGMA schema_version`).
4. For MCP-based connections (Postgres MCP, SQLite MCP), verify MCP server health and available tools.
5. Document connection parameters (host, port, database name, SSL mode, search path) without exposing credentials.
6. For production databases, confirm connection is to a read replica or snapshot, not the primary.
7. Verify SSL/TLS configuration for production connections. Unencrypted connections are a blocking finding.

**Output**: Connection manifest, permission level, database version, MCP tool inventory, SSL status.

### Phase 2 — Introspect

**Objective**: Discover and catalog the full schema structure.

1. List all schemas (PostgreSQL) or databases (SQLite) accessible to the connection.
2. Enumerate all tables, views, materialized views, and sequences.
3. For each table, extract: columns (name, type, nullable, default), primary key, foreign keys, unique constraints, check constraints, indexes.
4. For each index, extract: type (B-tree, hash, GiST, GIN), columns, partial predicate, uniqueness.
5. Document relationships: one-to-one, one-to-many, many-to-many via junction tables.
6. Capture sample row counts and approximate table sizes for migration impact estimation.
7. Store introspection results in a structured format (JSON, YAML) for caching and diff generation.

**Introspection queries by database**:
- PostgreSQL: `information_schema.columns`, `information_schema.table_constraints`, `pg_catalog.pg_class`, `pg_catalog.pg_index` [^391^]
- SQLite: `PRAGMA table_info`, `PRAGMA index_list`, `PRAGMA foreign_key_list`, `PRAGMA table_list` [^390^][^392^]

**Output**: Complete schema catalog, relationship graph, size estimates, introspection query log.

### Phase 3 — Model

**Objective**: Build semantic and structural models from the raw schema.

1. Construct an entity-relationship diagram (textual or Mermaid) from foreign key constraints and naming conventions.
2. Identify domain boundaries: group tables by functional area (users, orders, inventory, audit).
3. Map data types to application-layer equivalents (PostgreSQL `timestamp with time zone` → Python `datetime.timezone-aware`, SQLite `INTEGER` → Python `int`).
4. Identify anti-patterns: missing foreign keys, missing indexes on foreign key columns, no primary key, enum-as-string instead of CHECK constraint, redundant denormalization.
5. Compare actual schema against Architecture Design data model. Flag divergence: tables missing, columns renamed, types mismatched, indexes missing.
6. Score schema health: index coverage ratio (are FK columns indexed?), constraint coverage ratio, normalization level (3NF assessment), documentation presence (column comments, table descriptions).

**Output**: ER diagram, domain boundary map, schema health score, Architecture Design divergence report.

### Phase 4 — Generate

**Objective**: Produce safe queries, migrations, and data access patterns.

**Query Generation**:
1. Accept natural language question or explicit SQL requirement.
2. Resolve to the specific SQL dialect (PostgreSQL, SQLite, MySQL).
3. Include full schema context in generation prompt: relevant tables, columns, indexes, relationships.
4. Generate SQL with explicit `JOIN` conditions (never implicit cartesian products).
5. Apply ORM optimization patterns: `selectinload()` for collections, `joinedload()` for single references, `raiseload("*")` guards [^383^].
6. Validate syntax with a lightweight parser (sqlparse, pglast, sqlite3 prepare).
7. Run `EXPLAIN` (or `EXPLAIN ANALYZE` on read replica) to verify query plan uses indexes, avoids seq scans on large tables.

**Migration Generation**:
1. Accept schema change requirement (add column, add table, add index, modify type).
2. Determine if change is destructive (data loss possible) or non-destructive.
3. For destructive changes, require backup strategy: `CREATE TABLE ... AS SELECT`, `pg_dump` segment, point-in-time recovery.
4. Generate forward migration (`upgrade()`) and backward migration (`downgrade()`).
5. For large tables, recommend zero-downtime tools: gh-ost or pt-osc for MySQL; `CREATE INDEX CONCURRENTLY` for PostgreSQL.
6. Estimate impact: rows affected, lock duration, temporary disk space, replication lag risk.
7. Generate validation queries to confirm migration success: row count match, constraint validation, index usage check.

**Output**: Validated SQL query or migration script, query plan, impact estimate, rollback script.

### Phase 5 — Validate

**Objective**: Verify correctness, performance, and safety before any execution.

1. **Syntax validation**: Parse generated SQL with dialect-specific parser. Reject on syntax error.
2. **Schema diff**: Compare proposed schema against current schema. Highlight all additions, modifications, deletions.
3. **Data loss analysis**: For destructive operations, enumerate columns/tables that would lose data. Require explicit data migration plan or backup confirmation.
4. **Performance validation**: Run `EXPLAIN ANALYZE` on read replica. Reject queries with sequential scans on tables >100K rows unless justified.
5. **Query count test**: For ORM-generated code, assert query count budget. Fail if N+1 detected.
6. **Blast Radius assessment**: Document which application endpoints, background jobs, and reports are affected by schema change.
7. **Gate decision**: Human approval required for all production DDL. Read-only validation can proceed automatically.

**Output**: Validation report, schema diff, data loss analysis, performance check, Blast Radius assessment, Gate decision.

## Schema Drift Detection & Handling

Schema drift occurs when a live database diverges from its expected schema (migration scripts, source code, or baseline) [^388^]. Drift is dangerous because it creates an inconsistent state between what the application expects and what the database actually contains.

**Detection methods**:
1. **Flyway**: Checksum-based validation — computes a hash of the local migration script and compares against the recorded checksum in the `flyway_schema_history` table. Catches silent changes like altering a default value inside an already-applied script.
2. **Liquibase**: `diff` command compares two databases directly or a database against its changelog by querying system catalogs (`INFORMATION_SCHEMA` in PostgreSQL/MySQL).
3. **Manual catalog queries**: Run portable `information_schema` queries to extract current schema state and diff against expected state.

**Handling strategy**:
- Run drift detection in CI/CD pipelines before every deployment.
- Never automatically apply drift corrections without human review.
- Alert on drift detection rather than auto-remediating.
- Set `DropObjectsNotInSource=False` in comparison tools to prevent accidental object drops.

**Typical drift detection query** (PostgreSQL):
```sql
SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position;
```

## Database Anti-Pattern Detection

AI-generated database code is prone to dangerous anti-patterns that must be caught during validation [^413^][^414^][^422^]:

| Anti-Pattern | Detection Method | Prevention |
|--------------|-----------------|------------|
| Missing indexes | Check if filtered columns are indexed | Always include full schema with indexes in query context |
| N+1 queries | Query count budget testing in development | Use `selectinload()` for collections; `raiseload("*")` guards |
| Pathological SQL | `EXPLAIN` plan review for missing filters | Validate all generated queries have appropriate WHERE clauses |
| Wrong SQL dialect | Dialect-specific parser validation | Explicitly specify target database dialect |
| Inefficient pagination | Check for `OFFSET` on large tables | Prefer keyset pagination; warn on OFFSET for tables >10K rows |
| Redundant joins | `EXPLAIN` plan analysis | Replace unnecessary joins with `EXISTS` where appropriate |
| Soft-delete misses | Review WHERE clauses for `deleted_at` filters | Include soft-delete filters in all query templates |

**Query optimization checklist** (before any query reaches production):
1. Parse with dialect-specific parser (pglast, sqlparse, sqlite3)
2. Verify all referenced tables and columns exist in current schema
3. Run `EXPLAIN` to confirm index usage; reject sequential scans on >100K rows
4. Check for cartesian products in JOIN plans
5. Verify aggregation columns are properly grouped
6. Confirm pagination strategy matches table size
7. Validate parameterized queries (no string interpolation)
8. Set result size limits on unbounded queries

Safety constraints are absolute, non-negotiable, and enforced without exception fatigue.

### Prohibited Actions
- Executing `DROP TABLE`, `DROP COLUMN`, `TRUNCATE`, or destructive `ALTER TABLE` on production without explicit documented backup and human sign-off.
- Running migrations on a production primary database during peak hours or without a maintenance window.
- Generating migrations without corresponding rollback/downgrade scripts.
- Executing AI-generated DDL on production without schema diff review and read-replica validation.
- Using production credentials for introspection or migration tools.

### Required Practices
- Validate all queries with `EXPLAIN ANALYZE` before production deployment.
- Use `RAISE`/`ASSERT` query count budgets in development to prevent N+1 regressions.
- Generate and archive schema snapshots (Liquibase changelog, Flyway baseline, or SQL dump) before any migration.
- Implement schema drift detection in CI: Flyway checksum validation or Liquibase diff before every deployment.
- Separate schema deployment from application deployment: apply schema first, then deploy code that depends on it.
- Monitor migration runtime and replication lag during execution. Abort if lag exceeds threshold.

## Text-to-SQL & Query Generation Safety

Text-to-SQL accuracy is improving but not production-autonomous. Benchmark reality:
- Human experts: 92.96% on BIRD dev set [^397^]
- Top AI systems: ~81.67% on BIRD test set [^397^]
- GPT-4: ~54.89% with curated knowledge, ~34.88% without [^398^]
- Benchmark annotation error rate: 52.8% (BIRD Mini-Dev), 62.8% (Spider 2.0-Snow) [^354^][^396^]

**Safety protocol for AI-generated queries**:
1. Treat all AI-generated SQL as a **suggestion requiring validation**, not direct execution.
2. Validate syntax with a dialect-specific parser before any execution.
3. Run on a read-only replica first, with `LIMIT` on result sets.
4. Verify result correctness against known data points or manual calculation.
5. Check execution plan for missing indexes, cartesian products, or full table scans.
6. For complex analytical queries, have a human SQL expert review before production.

**AI anti-patterns to detect and prevent** [^413^][^414^][^422^]:
- Missing indexes on filtered columns causing full table scans
- N+1 query problems from ORM lazy loading
- Pathological SQL: missing filters returning huge datasets, cartesian products from improper joins
- Wrong SQL dialect: `LIMIT` vs `ROWNUM`, non-existent functions, incorrect quoting
- Inefficient offset-based pagination degrading linearly with table size
- Redundant joins and subqueries replaceable with `EXISTS`
- Soft-delete filter misses returning logically deleted records

## Integration with Other Skills

| Skill | Direction | Data |
|-------|-----------|------|
| Blast Radius | Feed INTO | Migration impact: tables, rows, locks, downtime, affected endpoints |
| Architecture Design | Feed INTO | Schema divergence report: missing tables, type mismatches, normalization gaps |
| Architecture Design | Feed FROM | Data model requirements inform schema design and normalization decisions |
| Security Auditor | Feed INTO | Schema-level security: row-level security policies, column encryption, audit logging |
| CI/CD Engineer | Feed INTO | Migration scripts, schema drift checks, query performance gates for pipeline |

## ORM Optimization Reference

SQLAlchemy relationship loading strategies [^383^]:

| Strategy | Parent Queries | Related Queries | Total | Best For |
|----------|---------------|-----------------|-------|----------|
| lazy | 1 | N (one per parent) | 1 + N | Single object access |
| joinedload | 1 | 0 | 1 | Many-to-one / one-to-one |
| selectinload | 1 | 1 per relationship | 1 + R | One-to-many / many-to-many |
| subqueryload | 1 | 1 per relationship | 1 + R | One-to-many |
| immediateload | 1 | N | 1 + N | Never for lists |

**Guidelines for query generation**:
- Many-to-one / one-to-one: Use `joinedload()` — single query, no Cartesian product risk.
- One-to-many / many-to-many: Use `selectinload()` — no Cartesian product risk, efficient batched loading.
- Multiple collections: Use `selectinload()` for all collections to avoid Cartesian products.
- Deep nesting: Mix strategies (e.g., `selectinload(User.orders).joinedload(Order.address)`).
- Development guard: Use `raiseload("*")` to raise errors on accidental lazy loading.
- Column pruning: Use `load_only()` to restrict columns fetched in related objects.
- Conditional loading: Use `with_loader_criteria()` for relationship filtering.

**Query count budget testing**:
```python
def test_post_list_endpoint():
    with assert_num_queries(2):  # One for posts, one for authors
        response = client.get('/posts')
    assert response.status_code == 200
```

---

**Document version:** 1.0 | **Last updated:** April 2026 | **Sources:** SQLAlchemy 2.1 docs, Prisma docs, SQLite.org, Atlas documentation, arXiv text-to-SQL research, BIRD benchmark, Endor Labs, UIUC annotation error study


## Context Management & Token Budget

This skill operates within Kimi K2.6 CLI's **262,100-token context window**.
Follow these principles for efficient token usage:

- **Progressive disclosure**: Load `references/` content only when needed. SKILL.md
  stays metadata-only (~500-700 tokens); full detail loads on-demand.
- **Budget awareness**: Typical skill activation costs ~5,000-8,000 tokens. Target
  keeping active skill content under **18,000 tokens** (3-skill average, ~6.9% of
  262.1K context). Hard ceiling: **25,000 tokens** (~9.5% of context).
- **Deactivate when done**: When this skill's phase completes, the Orchestrator
  deactivates it to free budget for the next phase.
- **Frugality over completeness**: Prefer targeted queries over broad analysis.
  Use Brownfield Intelligence's SQLite index or Graphify's graph for structural
  lookups instead of loading entire codebases into context.
