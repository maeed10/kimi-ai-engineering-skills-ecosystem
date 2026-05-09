# Database Migration Patterns

Reference for per-database migration syntax, ORM integration, constraint handling, and common anti-patterns.

## Table of Contents
1. [PostgreSQL](#postgresql)
2. [MySQL](#mysql)
3. [SQLite](#sqlite)
4. [MongoDB](#mongodb)
5. [DynamoDB](#dynamodb)
6. [Redis](#redis)
7. [ORM Integration](#orm-integration)
8. [Constraint Handling](#constraint-handling)
9. [Anti-Patterns](#anti-patterns)

---

## PostgreSQL

### Transactional DDL

PostgreSQL supports fully transactional DDL. Wrap migrations in `BEGIN...COMMIT` so a failure rolls everything back.

```sql
BEGIN;
  CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
  );

  CREATE INDEX idx_users_created_at ON users(created_at);
COMMIT;
```

### Adding Columns

```sql
-- Safe: nullable with default (instant in PG 11+)
ALTER TABLE users ADD COLUMN display_name VARCHAR(255);

-- Requires rewrite: NOT NULL without default
ALTER TABLE users ADD COLUMN age INTEGER NOT NULL DEFAULT 0;

-- Safer phased approach for large tables
ALTER TABLE users ADD COLUMN age INTEGER;          -- instant
UPDATE users SET age = 0 WHERE age IS NULL;       -- backfill in batches
ALTER TABLE users ALTER COLUMN age SET NOT NULL;  -- validate
```

### Adding Indexes

```sql
-- Blocks writes (bad for production)
CREATE INDEX idx_users_email ON users(email);

-- Zero-downtime (recommended)
CREATE INDEX CONCURRENTLY idx_users_email ON users(email);
```

> `CONCURRENTLY` cannot run inside a transaction. Run as a standalone statement, or use pgroll for fully transactional online migrations.

### Adding Constraints

```sql
-- Add as NOT VALID first (no table scan), then validate
ALTER TABLE orders ADD CONSTRAINT fk_orders_user_id
  FOREIGN KEY (user_id) REFERENCES users(id) NOT VALID;

ALTER TABLE orders VALIDATE CONSTRAINT fk_orders_user_id; -- scans orders, not users
```

### Column Renames

```sql
-- Simple rename (metadata-only, fast)
ALTER TABLE users RENAME COLUMN display_name TO name;

-- Rename with views for backward compatibility (expand/contract)
CREATE VIEW users_compat AS
  SELECT id, email, name AS display_name, created_at FROM users;
```

### Dropping Columns

```sql
-- PostgreSQL does NOT reclaim space until VACUUM FULL
ALTER TABLE users DROP COLUMN old_field;

-- For large tables, consider marking unused first
ALTER TABLE users ALTER COLUMN old_field SET DEFAULT 'deprecated';
-- Update application to stop reading, then drop in later migration
```

### Lock Levels Reference

| Operation                  | Lock Level         | Blocks                  |
|---------------------------|--------------------|-------------------------|
| CREATE INDEX              | ShareLock          | Writes                  |
| CREATE INDEX CONCURRENTLY | ShareUpdateExclusive | Minimal (brief)        |
| ALTER TABLE ADD COLUMN    | AccessExclusive    | All (brief)             |
| ALTER TABLE DROP COLUMN   | AccessExclusive    | All (brief)             |
| VALIDATE CONSTRAINT       | ShareUpdateExclusive | Reads/Writes briefly |
| REINDEX                   | AccessExclusive    | All                     |

---

## MySQL

### Transactional DDL

MySQL 8.0+ supports atomic DDL for InnoDB. MyISAM does not support transactional DDL—avoid MyISAM for migrations.

```sql
START TRANSACTION;
  ALTER TABLE users ADD COLUMN age INT;
  CREATE INDEX idx_age ON users(age);
COMMIT;
```

### Online DDL

MySQL 8.0+ supports online DDL for many operations with `ALGORITHM=INPLACE, LOCK=NONE`.

```sql
-- Online index creation
ALTER TABLE users ADD INDEX idx_email(email), ALGORITHM=INPLACE, LOCK=NONE;

-- Online column add
ALTER TABLE users ADD COLUMN display_name VARCHAR(255), ALGORITHM=INPLACE, LOCK=NONE;
```

### pt-online-schema-change

For operations that still require a table copy or lock:

```bash
pt-online-schema-change \
  --alter "ADD COLUMN age INT NOT NULL DEFAULT 0" \
  --execute \
  D=production,t=users
```

How it works:
1. Creates shadow table with new schema
2. Installs triggers to sync changes to shadow table
3. Copies data in chunks
4. Renames shadow to original atomically
5. Drops old table and triggers

### Adding Foreign Keys

```sql
-- Online in 8.0+ if both tables are InnoDB
ALTER TABLE orders
  ADD CONSTRAINT fk_user_id FOREIGN KEY (user_id) REFERENCES users(id),
  ALGORITHM=INPLACE, LOCK=NONE;
```

### Renaming Tables / Columns

```sql
-- Rename table (metadata-only in 8.0)
RENAME TABLE users TO app_users;

-- Rename column (requires ALGORITHM=COPY in older versions)
ALTER TABLE users RENAME COLUMN display_name TO name;
```

### Backfills

```sql
-- MySQL does not support UPDATE in batches natively; use application-level loops
-- or stored procedures with LIMIT to avoid long transactions

UPDATE users SET age = 0 WHERE age IS NULL LIMIT 10000;
-- Repeat until 0 rows affected
```

---

## SQLite

### Limitations

SQLite has limited ALTER TABLE support:
- `RENAME TABLE`
- `ADD COLUMN` (with restrictions: no PRIMARY KEY, no UNIQUE, limited types)
- No `DROP COLUMN` natively (until 3.35.0+, and even then with limits)

### Table Recreation Pattern

Most schema changes require recreating the table:

```sql
-- 1. Begin transaction
BEGIN TRANSACTION;

-- 2. Rename old table
ALTER TABLE users RENAME TO users_old;

-- 3. Create new table with desired schema
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  name TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 4. Migrate data
INSERT INTO users (id, email, name, created_at)
SELECT id, email, display_name, created_at FROM users_old;

-- 5. Recreate indexes
CREATE INDEX idx_users_email ON users(email);

-- 6. Drop old table
DROP TABLE users_old;

COMMIT;
```

### Foreign Keys

```sql
-- Disable foreign keys during recreation
PRAGMA foreign_keys = OFF;
-- ... perform recreation ...
PRAGMA foreign_keys = ON;
```

> Always validate foreign key integrity after recreation with `PRAGMA foreign_key_check;`.

---

## MongoDB

### Schema Migrations with Mongosh

MongoDB is schemaless, but applications enforce schemas. Migrations update documents and indexes.

```javascript
// Migration: add normalized email field
const migrate = async () => {
  const users = db.getCollection('users');
  const cursor = users.find({ normalized_email: { $exists: false } });

  while (cursor.hasNext()) {
    const user = cursor.next();
    users.updateOne(
      { _id: user._id },
      { $set: { normalized_email: user.email.toLowerCase().trim() } }
    );
  }
};

migrate();
```

### Index Management

```javascript
// Create index (background by default in modern versions)
db.users.createIndex({ email: 1 }, { unique: true, background: true });

// Drop index
db.users.dropIndex('email_1');
```

> Always use `background: true` for production index builds to avoid blocking.

### Rollback

```javascript
// Rollback: remove normalized_email and restore from backup if needed
db.users.updateMany(
  {},
  { $unset: { normalized_email: "" } }
);
```

### Collection Renames

```javascript
db.users.renameCollection('app_users');
```

### Sharded Clusters

- Migrations must run through `mongos`
- Index builds propagate to all shards
- Chunk migrations may be delayed during heavy updates; plan for off-peak

---

## DynamoDB

### Schema Evolution

DynamoDB has no formal schema. Migrations focus on:
1. Global Secondary Index (GSI) creation/deletion
2. Data backfills for new access patterns
3. TTL attribute additions

### GSI Management

```javascript
// AWS SDK v3 example: add GSI
const params = {
  TableName: 'Orders',
  AttributeDefinitions: [
    { AttributeName: 'userId', AttributeType: 'S' },
    { AttributeName: 'status', AttributeType: 'S' }
  ],
  GlobalSecondaryIndexUpdates: [
    {
      Create: {
        IndexName: 'UserStatusIndex',
        KeySchema: [
          { AttributeName: 'userId', KeyType: 'HASH' },
          { AttributeName: 'status', KeyType: 'RANGE' }
        ],
        Projection: { ProjectionType: 'ALL' },
        ProvisionedThroughput: { ReadCapacityUnits: 5, WriteCapacityUnits: 5 }
      }
    }
  ]
};
await dynamodb.updateTable(params).promise();
```

> GSI creation is asynchronous. Poll `describeTable` until `IndexStatus` is `ACTIVE`.

### Data Backfills

Use parallel scan with rate limiting (respect WCU):

```javascript
const backfill = async () => {
  const segments = 4;
  const workers = Array.from({ length: segments }, (_, i) =>
    docClient.scan({ TableName: 'Orders', Segment: i, TotalSegments: segments }).promise()
      .then(async (data) => {
        for (const item of data.Items) {
          await docClient.update({
            TableName: 'Orders',
            Key: { orderId: item.orderId },
            UpdateExpression: 'SET newField = :val',
            ExpressionAttributeValues: { ':val': computeValue(item) }
          }).promise();
        }
      })
  );
  await Promise.all(workers);
};
```

### Rollback

```javascript
// Remove GSI
await dynamodb.updateTable({
  TableName: 'Orders',
  GlobalSecondaryIndexUpdates: [
    { Delete: { IndexName: 'UserStatusIndex' } }
  ]
}).promise();
```

---

## Redis

### Schema Migrations

Redis is key-value; "schema" changes are application-level. Common migration patterns:

1. **Key Namespace Migration**: Rename keys with new prefix
2. **Data Structure Migration**: Hash -> JSON string, List -> Stream
3. **TTL Adjustments**: Batch update expiration

### Lua-Based Migration

```lua
-- Migrate keys from v1: prefix to v2: prefix
local cursor = "0"
repeat
  local result = redis.call("SCAN", cursor, "MATCH", "v1:*")
  cursor = result[1]
  for _, key in ipairs(result[2]) do
    local new_key = key:gsub("^v1:", "v2:")
    local value = redis.call("DUMP", key)
    redis.call("RESTORE", new_key, 0, value)
  end
until cursor == "0"
return "OK"
```

### Rollback

```bash
# Rename back or delete new keys
redis-cli --eval rollback.lua
```

> Always run Redis migrations during low-traffic periods and disable AOF rewrite if possible to avoid I/O spikes.

---

## ORM Integration

### SQLAlchemy (Python)

**Migration Generation**

```bash
alembic revision --autogenerate -m "add user table"
```

**Manual Migration Template**

```python
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now())
    )
    # Use op.execute for advanced SQL
    op.execute("CREATE INDEX CONCURRENTLY idx_users_email ON users(email)")

def downgrade():
    op.drop_table('users')
```

**Important**: `op.execute` with `CONCURRENTLY` must be in a migration with `op.execute("COMMIT")` first because Alembic wraps in a transaction.

```python
def upgrade():
    op.execute("COMMIT")  # end Alembic transaction
    op.execute("CREATE INDEX CONCURRENTLY idx_users_email ON users(email)")
```

### Prisma (TypeScript/Node)

**Migration Generation**

```bash
prisma migrate dev --name add_user_table
```

**Zero-Downtime Consideration**

Prisma Migrate does not natively support `CREATE INDEX CONCURRENTLY`. For production PostgreSQL, generate a raw SQL migration:

```bash
prisma migrate dev --create-only --name add_index_email
# Edit generated SQL to add CONCURRENTLY
```

**Rollback**

```bash
# Mark failed migration as rolled back
prisma migrate resolve --rolled-back "20231001_add_index_email"

# Downgrade database (not always supported for all engines)
```

### TypeORM (TypeScript/Node)

**Migration Generation**

```bash
typeorm migration:generate -n AddUserTable
```

**Migration Class**

```typescript
import { MigrationInterface, QueryRunner } from "typeorm";

export class AddUserTable1698000000000 implements MigrationInterface {
  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`
      CREATE TABLE users (
        id SERIAL PRIMARY KEY,
        email VARCHAR(255) NOT NULL UNIQUE
      )
    `);
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`DROP TABLE users`);
  }
}
```

**Revert**

```bash
typeorm migration:revert
```

### Sequelize (Node)

**Migration Generation**

```bash
sequelize-cli migration:generate --name add-user-table
```

**Migration File**

```javascript
module.exports = {
  up: async (queryInterface, Sequelize) => {
    await queryInterface.createTable('users', {
      id: { type: Sequelize.INTEGER, primaryKey: true, autoIncrement: true },
      email: { type: Sequelize.STRING(255), allowNull: false, unique: true },
      createdAt: { type: Sequelize.DATE, defaultValue: Sequelize.fn('NOW') }
    });
  },

  down: async (queryInterface, Sequelize) => {
    await queryInterface.dropTable('users');
  }
};
```

**Undo**

```bash
sequelize-cli db:migrate:undo        # last
sequelize-cli db:migrate:undo:all    # all
```

### Django ORM (Python)

**Migration Generation**

```bash
python manage.py makemigrations app_name
```

**Squash and Optimize**

```bash
python manage.py squashmigrations app_name 0001 0005
```

**Reversal**

Django automatically generates reverse operations for most migrations.

```bash
python manage.py migrate app_name 0003  # migrate back to 0003
```

**Raw SQL for Advanced Patterns**

```python
from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [...]
    operations = [
        migrations.RunSQL(
            sql="CREATE INDEX CONCURRENTLY idx_email ON users(email)",
            reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS idx_email"
        )
    ]
```

### GORM (Go)

**Auto Migration**

```go
db.AutoMigrate(&User{}, &Order{})
```

> `AutoMigrate` is additive-only and does not drop columns or indexes. For destructive changes, use raw migrations.

**Raw Migration with gormigrate**

```go
m := gormigrate.New(db, gormigrate.DefaultOptions, []*gormigrate.Migration{
  {
    ID: "20231001_add_users",
    Migrate: func(tx *gorm.DB) error {
      return tx.Exec("CREATE TABLE users (...)").Error
    },
    Rollback: func(tx *gorm.DB) error {
      return tx.Exec("DROP TABLE users").Error
    },
  },
})
m.Migrate()
```

---

## Constraint Handling

### Foreign Key Constraints

| Database   | Adding FK Strategy                                      |
|------------|--------------------------------------------------------|
| PostgreSQL | `NOT VALID` -> `VALIDATE CONSTRAINT` (two-step)       |
| MySQL      | Online DDL with `ALGORITHM=INPLACE` (8.0+)              |
| SQLite     | Recreate table with FK, or use `PRAGMA foreign_keys`   |
| MongoDB    | Application-level; no native FKs                      |
| DynamoDB   | Application-level; no native FKs                      |

### Unique Constraints

```sql
-- PostgreSQL / MySQL
ALTER TABLE users ADD CONSTRAINT uq_users_email UNIQUE (email);

-- For large tables, consider partial uniqueness or expression indexes
CREATE UNIQUE INDEX uq_active_email ON users(email) WHERE deleted_at IS NULL;
```

### Check Constraints

```sql
-- PostgreSQL 12+ / MySQL 8.0.16+ / SQLite 3.3.0+
ALTER TABLE users ADD CONSTRAINT chk_age_positive CHECK (age >= 0);

-- MySQL prior to 8.0.16 ignores CHECK constraints (syntax accepted but not enforced)
```

### Not Null with Default

```sql
-- Safe: add column, backfill, then set NOT NULL
ALTER TABLE users ADD COLUMN age INT;
UPDATE users SET age = 0 WHERE age IS NULL;
ALTER TABLE users ALTER COLUMN age SET NOT NULL;
```

---

## Anti-Patterns

### 1. Big Bang Backfills

```sql
-- BAD: locks table for minutes/hours on large datasets
UPDATE users SET new_field = old_field * 2;

-- GOOD: batch with LIMIT and sleep
UPDATE users SET new_field = old_field * 2 WHERE new_field IS NULL LIMIT 10000;
-- Repeat in application loop with 100ms sleep
```

### 2. Renaming Without Compatibility Layer

```sql
-- BAD: breaks running application instances mid-deploy
ALTER TABLE users RENAME COLUMN name TO display_name;

-- GOOD: expand/contract
ALTER TABLE users ADD COLUMN display_name VARCHAR(255);
UPDATE users SET display_name = name;  -- batched
-- Deploy code that reads display_name, falls back to name
-- Later migration drops name
```

### 3. Dropping Before Confirming Unused

```sql
-- BAD: irreversible data loss if code still references column
ALTER TABLE users DROP COLUMN legacy_id;

-- GOOD: soft deprecate first
ALTER TABLE users ALTER COLUMN legacy_id SET DEFAULT 'deprecated';
-- Verify no queries reference legacy_id for 1+ deploy cycles
-- Then drop with backup in rollback script
```

### 4. Missing Rollback for Data Migration

```javascript
// BAD: no way to reverse if application logic is flawed
db.users.updateMany({}, { $set: { status: 'active' } });

// GOOD: store previous state or use staged migration
const backup = db.users.find({}, { status: 1 }).toArray();
// write backup to _migration_data_backup collection
// apply change
// rollback reads backup collection and restores
```

### 5. Lock-Heavy Operations in Peak Hours

| Operation                  | Risk Level |
|----------------------------|------------|
| `CREATE INDEX` (no CONCURRENTLY) | Critical   |
| `ALTER TABLE` on multi-GB table  | Critical   |
| `VACUUM FULL`                    | Critical   |
| `REINDEX`                        | High       |
| `ALTER TABLE ADD COLUMN NULLABLE`| Low        |

Schedule high-risk operations during maintenance windows or use zero-downtime patterns.
