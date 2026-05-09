# SQL Patterns and Introspection Reference

Reference guide for database introspection queries, ORM loading strategies, migration patterns, and query optimization techniques used by the Schema Explorer skill.

---

## PostgreSQL Introspection

### information_schema (Portable, SQL-Standard)

```sql
-- List all user-accessible tables
SELECT table_schema, table_name, table_type
FROM information_schema.tables
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
  AND table_type = 'BASE TABLE'
ORDER BY table_schema, table_name;

-- List columns for a specific table
SELECT column_name, data_type, is_nullable, column_default, character_maximum_length, numeric_precision
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'customers'
ORDER BY ordinal_position;

-- List foreign keys
SELECT tc.constraint_name, tc.table_name, kcu.column_name,
       ccu.table_name AS foreign_table_name, ccu.column_name AS foreign_column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public';

-- List all constraints
SELECT tc.constraint_name, tc.table_name, tc.constraint_type
FROM information_schema.table_constraints tc
WHERE tc.table_schema = 'public'
ORDER BY tc.table_name, tc.constraint_type;

-- List indexes (via pg_catalog; information_schema has limited index visibility)
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public';
```

### pg_catalog (PostgreSQL-Specific, Detailed)

```sql
-- Tables, indexes, sequences with storage params
SELECT c.relname, c.relkind, pg_size_pretty(pg_total_relation_size(c.oid)) AS size
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'i', 'S')
ORDER BY pg_total_relation_size(c.oid) DESC;

-- Column definitions with PostgreSQL-specific types
SELECT a.attname AS column_name,
       pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
       NOT a.attnotnull AS is_nullable,
       pg_get_expr(d.adbin, d.adrelid) AS default_value
FROM pg_attribute a
LEFT JOIN pg_attrdef d ON a.attrelid = d.adrelid AND a.attnum = d.adnum
WHERE a.attrelid = 'public.users'::regclass
  AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY a.attnum;

-- Index details including partial predicates
SELECT indexrelid::regclass AS index_name,
       indisunique AS is_unique,
       indisprimary AS is_primary,
       pg_get_expr(indpred, indrelid) AS partial_predicate
FROM pg_index
WHERE indrelid = 'public.users'::regclass;

-- Constraint details
SELECT conname, contype, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'public.users'::regclass;
```

---

## SQLite Introspection

### PRAGMA Commands

```sql
-- Columns in a table
PRAGMA table_info('users');

-- Indexes on a table
PRAGMA index_list('orders');

-- Columns in an index
PRAGMA index_info('idx_orders_user_id');

-- Foreign keys
PRAGMA foreign_key_list('orders');

-- All tables (SQLite 3.37+)
PRAGMA table_list;

-- Schema for all objects
SELECT type, name, tbl_name, sql FROM sqlite_schema WHERE type IN ('table', 'index', 'trigger');
```

### Table-Valued PRAGMA Functions (SQLite 3.16+)

```sql
-- All indexed columns across all tables
SELECT DISTINCT m.name AS table_name, ii.name AS indexed_column
FROM sqlite_schema AS m
JOIN pragma_index_list(m.name) AS il
JOIN pragma_index_info(il.name) AS ii
WHERE m.type = 'table';

-- Tables with their foreign key relationships
SELECT m.name AS table_name, fk.id, fk.seq, fk.table AS references_table, fk.from, fk.to
FROM sqlite_schema AS m
JOIN pragma_foreign_key_list(m.name) AS fk
WHERE m.type = 'table';
```

---

## Migration Patterns by Safety Level

### Non-Destructive (Safe)

```sql
-- Add nullable column
ALTER TABLE users ADD COLUMN middle_name VARCHAR(100) NULL;

-- Add index concurrently (PostgreSQL, no table lock)
CREATE INDEX CONCURRENTLY idx_orders_created_at ON orders(created_at);

-- Add foreign key with existing clean data
ALTER TABLE orders ADD CONSTRAINT fk_orders_user_id
  FOREIGN KEY (user_id) REFERENCES users(id);

-- Add CHECK constraint (not validated first, then validated to avoid locking)
ALTER TABLE products ADD CONSTRAINT chk_price_positive
  CHECK (price > 0) NOT VALID;
ALTER TABLE products VALIDATE CONSTRAINT chk_price_positive;
```

### Destructive (Requires Backup + Human Approval)

```sql
-- DROP COLUMN: data loss. Requires backup plan.
-- Pattern: create backup, drop, verify
CREATE TABLE users_backup_20260101 AS SELECT id, email, name FROM users;
ALTER TABLE users DROP COLUMN old_field;

-- DROP TABLE: total data loss. Blocking without exception.
-- Pattern: rename first, verify nothing breaks, drop later
ALTER TABLE old_metrics RENAME TO old_metrics_deprecated;
-- After 30-day grace period, with confirmation:
DROP TABLE old_metrics_deprecated;

-- ALTER COLUMN TYPE: may truncate or cast data destructively
-- Pattern: add new column, dual-write, backfill, switch reads, drop old
ALTER TABLE events ADD COLUMN created_at_tz TIMESTAMPTZ;
UPDATE events SET created_at_tz = created_at AT TIME ZONE 'UTC';
-- Switch application reads/writes to new column
ALTER TABLE events DROP COLUMN created_at;
ALTER TABLE events RENAME COLUMN created_at_tz TO created_at;
```

---

## ORM Loading Strategy Patterns

### SQLAlchemy

```python
from sqlalchemy.orm import joinedload, selectinload, raiseload

# Many-to-one / one-to-one: single query
users = session.query(User).options(joinedload(User.profile)).all()

# One-to-many / many-to-many: no Cartesian product
users = session.query(User).options(selectinload(User.orders)).all()

# Deep nesting: mix strategies
users = session.query(User).options(
    selectinload(User.orders).joinedload(Order.address)
).all()

# Development guard: prevent accidental lazy loading
users = session.query(User).options(raiseload("*")).all()

# Column pruning
users = session.query(User).options(
    load_only(User.id, User.email),
    selectinload(User.orders).load_only(Order.id, Order.total)
).all()
```

### Query Count Budget (Testing)

```python
def test_user_list_endpoint():
    with assert_num_queries(2):  # 1 for users, 1 for orders
        response = client.get('/api/users')
    assert response.status_code == 200
```

---

## Query Optimization Checklist

Before approving any query for production:

1. **Syntax validation**: Parse with dialect-specific parser (pglast, sqlparse, sqlite3).
2. **Schema validation**: All tables, columns, and types exist in current schema.
3. **Index check**: Run `EXPLAIN` or `EXPLAIN ANALYZE`. Reject if sequential scan on >100K rows.
4. **Join safety**: Explicit `JOIN` conditions. No implicit cartesian products.
5. **Aggregation safety**: All non-aggregated `SELECT` columns in `GROUP BY` (strict SQL).
6. **Pagination appropriateness**: Keyset for large tables, OFFSET only for small result sets.
7. **Type safety**: No implicit casts that could truncate or change semantics.
8. **Null handling**: `COALESCE` or explicit null checks where nulls could cause bugs.
9. **Injection safety**: Parameterized queries only. Never string-interpolate user input.
10. **Result size**: `LIMIT` on unbounded queries. Streaming for large exports.

---

## Zero-Downtime Migration Patterns

### PostgreSQL

```sql
-- Create index without locking table
CREATE INDEX CONCURRENTLY idx_name ON table(column);

-- Add column without default (no table rewrite)
ALTER TABLE users ADD COLUMN preferences JSONB NULL;

-- Add column with default (requires rewrite; do in chunks for large tables)
-- Pattern: add nullable, backfill in batches, add NOT NULL
ALTER TABLE users ADD COLUMN is_active BOOLEAN NULL;
UPDATE users SET is_active = TRUE WHERE is_active IS NULL;  -- batched
ALTER TABLE users ALTER COLUMN is_active SET NOT NULL;
```

### MySQL (Large Tables >50M Rows)

Use **gh-ost** (triggerless, binlog-based) or **pt-online-schema-change** (trigger-based shadow table).

```bash
# gh-ost example: add column to 500M-row table
gh-ost \
  --host=mysql-primary \
  --database=production \
  --table=events \
  --alter="ADD COLUMN region VARCHAR(10) NULL" \
  --execute

# pt-osc example: add index
pt-online-schema-change \
  --alter "ADD INDEX idx_created_at (created_at)" \
  D=production,t=events \
  --execute
```

| Feature | gh-ost | pt-osc |
|---------|--------|--------|
| Triggers | No (binlog-based) | Yes (3 triggers) |
| Throttling | Built-in, replica-aware | Manual config |
| Rollback | Pause/abort anytime | Drop shadow table |
| FK Support | Limited | Better support |

---

## Schema Drift Detection Queries

### Flyway-Style Checksum Validation

```sql
-- Verify migration script checksums match recorded values
SELECT installed_rank, version, description, checksum, installed_on
FROM flyway_schema_history
WHERE checksum IS NOT NULL;
```

### Liquibase-Style Diff Query (PostgreSQL)

```sql
-- Portable column-level drift check
SELECT table_name, column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position;
```

### PostgreSQL-Specific Drift Detection

```sql
-- Compare current schema against expected index set
SELECT schemaname, tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;
```

---

**Sources:** [^389^] SQLAlchemy 2.1 Docs; [^390^] Dev.to SQLite PRAGMA; [^391^] Medium PostgreSQL information_schema; [^392^] SQLite.org PRAGMA; [^383^] SQLAlchemy Loading Techniques; [^382^] MyDBops GH-OST Guide; [^381^] OneUptime pt-osc Guide; [^385^] Mafiree Fintech Case Study; [^388^] Medium Schema Drift Detection; [^358^] Atlasgo.io Safe Migrations.
