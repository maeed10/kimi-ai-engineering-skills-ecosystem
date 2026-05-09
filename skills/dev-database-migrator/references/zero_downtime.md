# Zero-Downtime Migration Patterns

Detailed guide for performing schema changes without application downtime. Includes expand/contract, shadow tables, online index creation, trigger-based approaches, and pgroll.

## Table of Contents
1. [Pattern Selection Matrix](#pattern-selection-matrix)
2. [Expand/Contract Pattern](#expandcontract-pattern)
3. [Shadow Table Pattern](#shadow-table-pattern)
4. [Online Index Creation](#online-index-creation)
5. [Trigger-Based Migration (pt-osc)](#trigger-based-migration)
6. [pgroll (PostgreSQL)](#pgroll-postgresql)
7. [Phased Rollout Strategy](#phased-rollout-strategy)

---

## Pattern Selection Matrix

| Change Type                  | Recommended Pattern          | Database       | Complexity |
|-----------------------------|------------------------------|----------------|------------|
| Add nullable column         | Direct DDL                   | All            | Low        |
| Add NOT NULL column         | Expand/Contract              | PostgreSQL/MySQL | Low      |
| Rename column               | Expand/Contract + View       | PostgreSQL     | Low        |
| Add index on large table    | Online Index / CONCURRENTLY  | PostgreSQL/MySQL | Low      |
| Drop column                 | Expand/Contract (deprecate first) | All      | Medium     |
| Change column type          | Expand/Contract or Shadow Table | All       | Medium     |
| Add FK to large table       | NOT VALID + VALIDATE (PG)    | PostgreSQL     | Low        |
| Rebuild large table         | Shadow Table / pt-osc        | MySQL          | High       |
| Multi-step schema refactor  | pgroll                       | PostgreSQL     | Low        |

---

## Expand/Contract Pattern

The safest general-purpose pattern for additive and destructive changes. Schema changes are deployed in multiple phases so old and new code versions can run simultaneously.

### Use For
- Column renames
- Column type changes
- Adding constraints that require validation
- Removing columns or tables

### Phase 1: Expand

Add the new schema element alongside the old one. Application code still uses the old element.

```sql
-- Example: Rename 'name' to 'display_name'
-- Step 1.1: Add new column
ALTER TABLE users ADD COLUMN display_name VARCHAR(255);

-- Step 1.2: Backfill from old column (batched for large tables)
UPDATE users SET display_name = name WHERE display_name IS NULL LIMIT 10000;
-- Repeat until fully backfilled

-- Step 1.3: (Optional) Create compatibility view for reads
CREATE VIEW users_v1 AS
SELECT id, email, name, display_name, created_at FROM users;
```

Application code at this stage:
- **Reads**: `SELECT name FROM users` (still works)
- **Writes**: `INSERT INTO users (name) VALUES ('Ada')` (still works)

### Phase 2: Migrate Reads/Writes

Deploy application code that reads from the new element but falls back to the old.

```python
# Pseudocode for application read
def get_display_name(user):
    return user.display_name or user.name  # fallback

def set_display_name(user, value):
    user.display_name = value
    user.name = value  # write both for now
```

### Phase 3: Contract

Once all application instances write only to the new element, remove the old one.

```sql
-- Step 3.1: Drop old column
ALTER TABLE users DROP COLUMN name;

-- Step 3.2: (Optional) Rename if needed
-- ALTER TABLE users RENAME COLUMN display_name TO name;
-- Only do this if external systems depend on the name; otherwise keep display_name

-- Step 3.3: Drop compatibility view
DROP VIEW IF EXISTS users_v1;
```

### Rollback in Expand/Contract

At any phase before Contract, rollback is trivial:
- **Before Phase 2**: Drop the new column, no data loss.
- **During Phase 2**: Revert application code to old reads/writes; optionally backfill old column if writes stopped.
- **After Phase 3**: To rollback, add the old column back, backfill from backups or logs, and revert application code.

### Complete Example: Adding a Required Column

```sql
-- Phase 1: Expand
ALTER TABLE orders ADD COLUMN status VARCHAR(20);

-- Phase 1.5: Backfill in batches (application accepts NULL during transition)
UPDATE orders SET status = 'pending' WHERE status IS NULL LIMIT 5000;

-- Phase 2: Deploy code that writes 'pending' for new orders
-- Phase 2.5: Once all rows have status, add constraint
ALTER TABLE orders ALTER COLUMN status SET NOT NULL;

-- Phase 3: Contract (nothing to drop in this case; migration complete)
```

---

## Shadow Table Pattern

Create a new table with the desired schema, migrate data incrementally, then swap names atomically. Best for changes that cannot be done in-place on very large tables.

### Use For
- Rebuilding a table with a different primary key
- Complex column reorders or type changes
- Removing significant dead space (SQLite, MySQL)
- MySQL 5.7 large migrations where online DDL is insufficient

### Step-by-Step

```sql
-- 1. Create shadow table with new schema
CREATE TABLE users_new (
  id BIGINT PRIMARY KEY,          -- changed from INT to BIGINT
  email VARCHAR(255) NOT NULL UNIQUE,
  name VARCHAR(255) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 2. (MySQL) Create triggers to keep shadow table in sync
DELIMITER //
CREATE TRIGGER users_insert_trigger AFTER INSERT ON users
FOR EACH ROW
BEGIN
  INSERT INTO users_new (id, email, name, created_at)
  VALUES (NEW.id, NEW.email, NEW.name, NEW.created_at);
END//

CREATE TRIGGER users_update_trigger AFTER UPDATE ON users
FOR EACH ROW
BEGIN
  UPDATE users_new SET
    email = NEW.email,
    name = NEW.name,
    created_at = NEW.created_at
  WHERE id = NEW.id;
END//

CREATE TRIGGER users_delete_trigger AFTER DELETE ON users
FOR EACH ROW
BEGIN
  DELETE FROM users_new WHERE id = OLD.id;
END//
DELIMITER ;

-- 3. Copy existing data in chunks
INSERT INTO users_new (id, email, name, created_at)
SELECT id, email, name, created_at FROM users
WHERE id BETWEEN 1 AND 100000;
-- Repeat for subsequent chunks

-- 4. Verify row counts match
SELECT count(*) FROM users;
SELECT count(*) FROM users_new;

-- 5. Atomic rename (brief metadata lock)
RENAME TABLE users TO users_old, users_new TO users;

-- 6. Drop old table and triggers
DROP TABLE users_old;
DROP TRIGGER users_insert_trigger;
DROP TRIGGER users_update_trigger;
DROP TRIGGER users_delete_trigger;
```

### PostgreSQL Variant: Using Views for Atomic Swap

PostgreSQL supports transactional DDL, but `RENAME` on heavily locked objects can still cause contention. Use a view or synonym layer:

```sql
-- Create new table
CREATE TABLE users_new (...);

-- Migrate data
INSERT INTO users_new SELECT * FROM users;

-- In a single transaction:
BEGIN;
  ALTER TABLE users RENAME TO users_old;
  ALTER TABLE users_new RENAME TO users;
  -- Recreate permissions, constraints, indexes
COMMIT;
```

### SQLite Shadow Table

SQLite essentially requires shadow tables for most schema changes (see `database_patterns.md`). The pattern is identical but must include index and trigger recreation.

---

## Online Index Creation

### PostgreSQL: `CREATE INDEX CONCURRENTLY`

```sql
-- Cannot run inside a transaction
CREATE INDEX CONCURRENTLY idx_users_email ON users(email);

-- If interrupted, a broken ("invalid") index may remain. Drop and retry:
DROP INDEX CONCURRENTLY IF EXISTS idx_users_email;
CREATE INDEX CONCURRENTLY idx_users_email ON users(email);

-- For unique constraints, use CONCURRENTLY with a manual conflict check first
SELECT email, count(*) FROM users GROUP BY email HAVING count(*) > 1;
```

### MySQL: Online DDL

```sql
-- MySQL 8.0+ native online DDL
ALTER TABLE users ADD INDEX idx_email(email), ALGORITHM=INPLACE, LOCK=NONE;

-- Monitor progress
SELECT EVENT_NAME, WORK_COMPLETED, WORK_ESTIMATED
FROM performance_schema.events_stages_current;
```

### MongoDB: Background Index Build

```javascript
// Background is default in modern MongoDB for foreground shell operations
// but explicit declaration is safer

db.users.createIndex(
  { email: 1 },
  { unique: true, background: true }
);

-- Monitor

db.currentOp({ "originatingCommand.createIndexes": "users" });
```

### DynamoDB: GSI Backfill

DynamoDB GSIs are built automatically in the background when created. There is no native index creation lock, but applications must handle the `ResourceInUseException` while the index is `CREATING`.

---

## Trigger-Based Migration

Percona Toolkit's `pt-online-schema-change` is the canonical implementation for MySQL. It uses triggers to synchronize a shadow table during migration.

### When to Use
- MySQL 5.7 or older where online DDL is limited
- Table size > 100GB and migration time exceeds maintenance window
- Complex changes not supported by `ALGORITHM=INPLACE`

### How It Works

1. **Create shadow table**: `CREATE TABLE _users_new LIKE users;`
2. **Alter shadow table**: Apply desired schema changes to `_users_new`
3. **Create triggers**: `INSERT`, `UPDATE`, `DELETE` triggers on original table propagate to shadow
4. **Chunked copy**: `INSERT INTO _users_new (...) SELECT ... FROM users WHERE ... LIMIT 1000`
5. **Rename**: `RENAME TABLE users TO _users_old, _users_new TO users;`
6. **Cleanup**: Drop old table and triggers

### Bash Example

```bash
pt-online-schema-change \
  --alter "ADD COLUMN age INT NOT NULL DEFAULT 0, ADD INDEX idx_age(age)" \
  --execute \
  --max-load Threads_running=25 \
  --critical-load Threads_running=50 \
  --chunk-size 1000 \
  --pause-file /tmp/pause_migration \
  D=production,t=users
```

### Safety Options

| Option              | Purpose                                           |
|--------------------|---------------------------------------------------|
| `--max-load`       | Pause if server load exceeds threshold              |
| `--critical-load`  | Abort if load spikes dangerously                  |
| `--chunk-size`     | Rows copied per `SELECT/INSERT` chunk               |
| `--pause-file`     | Pause migration if this file exists                 |
| `--nodrop-triggers`| Keep triggers for manual inspection post-migration  |
| `--dry-run`        | Verify commands without executing                   |

### Rollback with pt-osc

If something goes wrong before the rename:
- Kill `pt-online-schema-change` process
- Drop shadow table `_users_new`
- Drop triggers on original table
- Original table is untouched

If rename already happened, use the generated `_users_old` table to reverse the rename manually.

---

## pgroll (PostgreSQL)

[pgroll](https://github.com/xataio/pgroll) is an open-source PostgreSQL migration tool that provides instant, reversible, and online schema changes using versioned schemas.

### Concepts

- **Schemas as versions**: Each migration creates a new PostgreSQL schema with views pointing to underlying tables
- **Instant changes**: `CREATE SCHEMA`, view creation, and function updates are metadata-only and instantaneous
- **Reversible**: Every migration is kept as a schema version; rollback is a metadata change

### Example Migration JSON

```json
{
  "name": "add_status_to_orders",
  "operations": [
    {
      "add_column": {
        "table": "orders",
        "column": {
          "name": "status",
          "type": "varchar(20)",
          "nullable": true,
          "default": "'pending'"
        }
      }
    }
  ]
}
```

### Running pgroll

```bash
# Start migration
pgroll start add_status_to_orders.json

-- pgroll creates:
--   - New schema version
--   - Views exposing the new column
--   - Backfill trigger to populate default for existing rows
--   - Original schema still accessible

# Complete migration (after backfill and code deploy)
pgroll complete

# Or rollback instantly if issues arise
pgroll rollback
```

### Advantages
- True zero-downtime: views switch atomically
- Multiple versions can coexist (blue/green deploy friendly)
- No long locks on large tables for additive changes
- Built-in backfill for new columns with defaults

### Limitations
- PostgreSQL only
- Requires application to use pgroll-managed views instead of raw tables
- Not suitable for all destructive changes without manual intervention

---

## Phased Rollout Strategy

For teams running blue/green or canary deployments, combine patterns:

```
Phase 1: Schema Expand
  - Deploy migration that adds new elements only
  - Old and new code paths both work

Phase 2: Application Canary
  - Deploy new application code to 5% of fleet
  - Monitors error rates and query performance

Phase 3: Application Full Deploy
  - Roll out to 100% once canary is healthy

Phase 4: Schema Contract
  - Deploy migration that removes deprecated elements
  - Only new code path remains
```

### Communication Checklist

```
- [ ] Schema change PR reviewed by DB-aware engineer
- [ ] Migration dry-run completed in staging (same data volume if possible)
- [ ] Application code PR includes feature flags for new schema usage
- [ ] On-call engineer notified of migration window
- [ ] Monitoring dashboards prepared for lock wait time, replication lag, slow queries
- [ ] Rollback command tested and documented in runbook
```

---

## Monitoring During Migrations

| Metric                  | Tool / Query                                          | Alert Threshold |
|------------------------|-------------------------------------------------------|-----------------|
| Lock waits             | `pg_stat_activity.wait_event_type = 'Lock'` (PG)      | > 5 queries     |
| Replication lag        | `pg_stat_replication.replay_lag` (PG)                 | > 10 seconds    |
| Online DDL progress    | `events_stages_current` (MySQL 8.0)                    | Stalled > 5 min |
| Query latency p99      | APM / slow query log                                    | > 2x baseline   |
| CPU / I/O              | CloudWatch, Datadog, Prometheus                       | > 80% for 5 min |

If thresholds are breached, pause the migration (for pt-osc, create the pause file) or rollback if the migration is still in an early phase.
