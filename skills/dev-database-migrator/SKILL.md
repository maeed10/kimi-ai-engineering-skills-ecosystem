---
name: dev-database-migrator
description: Developer-facing database migration skill that generates forward/rollback scripts, validates schema changes, and manages data seeding. Use when modifying schemas, adding indexes, migrating data, or setting up database versioning. Supports PostgreSQL, MySQL, MongoDB, DynamoDB with ORM integration and zero-downtime patterns.
---

# dev-database-migrator

## Overview

Generates, validates, and executes database schema migrations. Supports SQL and NoSQL databases with rollback scripts, data seeding, and ORM integration.

## When to Use

- Creating a new database schema or modifying existing tables
- Adding indexes, constraints, or columns to production databases
- Migrating data between schemas or databases
- Setting up database versioning for a team
- Generating seed data for development or testing
- Reverting a failed or harmful migration
- Validating schema consistency across environments

## When Not to Use

- Database administration tasks unrelated to schema changes (use DBA tools)
- Complex data analytics or ETL pipelines (use dedicated ETL tools)
- Real-time replication or streaming (use CDC tools)

## Migration Workflow

### 1. Assess the Change

Determine the scope before generating anything:

```
- [ ] Identify target database and version
- [ ] Classify change type: additive, destructive, rename, data migration
- [ ] Estimate table size and lock duration
- [ ] Check for ORM model drift (if applicable)
- [ ] Determine zero-downtime requirement
```

### 2. Generate Migration Script

Use the provided script or manual approach:

```bash
# From schema diff
python scripts/generate_migration.py \
  --from schema_old.yaml \
  --to schema_new.yaml \
  --db postgresql \
  --orm sqlalchemy \
  --output migrations/

# From ORM models
python scripts/generate_migration.py \
  --orm-model models/user.py \
  --db mysql \
  --output migrations/
```

Every generated migration must include:
- Forward migration script (`YYYYMMDD_name.up.sql|js|py`)
- Rollback script (`YYYYMMDD_name.down.sql|js|py`)
- Checksum for integrity verification
- Estimated execution time and lock classification

### 3. Validate the Migration

Run pre-flight checks before execution:

```bash
# SQL validation
psql -f migration.up.sql --dry-run

# ORM validation
alembic upgrade head --sql  # generate without executing
prisma migrate diff           # Prisma-native diffing

# Constraint and drift checks
python scripts/generate_migration.py --validate-only migration.up.sql
```

Validation rules:
- Forward and rollback scripts must be symmetric (rollback restores original state)
- No implicit data loss in destructive operations without explicit `WARNING` marker
- Index creation on large tables must use `CONCURRENTLY` (PostgreSQL) or online DDL (MySQL)
- Foreign key additions must validate existing data

### 4. Execute with Safeguards

```bash
# 1. Backup / snapshot (mandatory for production)
# 2. Run in transaction where possible (PostgreSQL, SQLite)
# 3. For large tables, use zero-downtime patterns (see references/zero_downtime.md)
# 4. Record checksum in migration tracking table

# Example PostgreSQL
BEGIN;
  CREATE TABLE _migration_log (...);
  -- migration steps
  INSERT INTO _migration_log (name, checksum, applied_at) VALUES (...);
COMMIT;
```

### 5. Verify and Seed (if needed)

```bash
# Run seed script for new environments
python scripts/generate_migration.py --seed --environment dev

# Verify constraints and row counts
SELECT count(*) FROM new_table;
\d new_table
```

### 6. Rollback on Failure

If migration fails or causes issues:

```bash
# Immediate rollback (if within transaction)
ROLLBACK;

# Post-hoc rollback
psql -f migration.down.sql

# For partial applies with checksum tracking
python scripts/generate_migration.py --rollback-last
```

## Rollback Procedures

### Rollback Safety Rules

1. **Data Preservation**: Rollback scripts must preserve data added since migration (insert into backup table, don't truncate)
2. **Destructive Change Rollback**: For column drops, rollback must restore from backup table or soft-delete marker
3. **Rename Rollback**: Store old->new name mapping in a migration metadata table to reverse accurately
4. **Index Rollback**: Dropping an index in rollback is always safe; recreating it must use original definition
5. **Rollback Verification**: Before execution, check that rollback script references existing objects and has no forward-only dependencies

### Rollback Checklist

```
- [ ] Confirm no downstream consumers depend on new schema
- [ ] Verify backup table / column exists for data restoration
- [ ] Check migration log: was this migration fully applied?
- [ ] Test rollback in staging environment first
- [ ] Ensure rollback script checksum is valid
- [ ] Coordinate with application deploy (code may need reverting first)
```

## Database Support Summary

| Database   | Migration Format | Transactional | Online DDL | Native Tooling       |
|------------|---------------|---------------|------------|----------------------|
| PostgreSQL | SQL           | Yes           | Partial    | pgroll, pg_dump      |
| MySQL      | SQL           | Partial       | Yes (8.0+)| pt-online-schema-change |
| SQLite     | SQL           | Yes           | No         | None (recreate)      |
| MongoDB    | JavaScript    | No            | Yes        | mongosh, mongomirror |
| DynamoDB   | JS/Python/Go  | No            | N/A        | AWS CLI, custom      |
| Redis      | Lua/Redis CLI | No            | N/A        | None                 |

> See `references/database_patterns.md` for detailed per-database patterns and ORM mappings.

## Zero-Downtime Strategies

Quick reference; full details in `references/zero_downtime.md`:

| Pattern            | Best For                         | Complexity |
|--------------------|----------------------------------|------------|
| Expand/Contract    | Column/constraint changes        | Low        |
| Shadow Table       | Large table rewrites             | Medium     |
| Online Index       | Adding indexes to hot tables     | Low        |
| Trigger-Based      | MySQL large migrations           | High       |
| pgroll             | PostgreSQL full migrations       | Low        |

## ORM Integration

| ORM         | Migration Command              | Rollback Command            | Notes                         |
|-------------|-------------------------------|-----------------------------|-------------------------------|
| SQLAlchemy  | `alembic revision --autogenerate` | `alembic downgrade -1`    | Autogenerate needs manual review |
| Prisma      | `prisma migrate dev`          | `prisma migrate resolve --rolled-back` | Shadow DB for validation       |
| TypeORM     | `typeorm migration:generate` | `typeorm migration:revert`| Uses DataSource config          |
| Sequelize   | `sequelize-cli migration:generate` | `sequelize-cli db:migrate:undo` | Manual migration files       |
| Django ORM  | `python manage.py makemigrations` | `python manage.py migrate app N` | Auto rollback built-in      |
| GORM        | `gorm.AutoMigrate` + raw      | Manual down migration       | Limited native rollback         |

## Schema Validation

Automated checks to prevent drift and corruption:

1. **Syntax Validation**: Parse SQL/JS migration without executing
2. **Object Reference Check**: Ensure all `ALTER` targets exist; all `CREATE` targets do not exist (forward)
3. **Constraint Compatibility**: Validate foreign key types match; check unique constraints on nullable columns
4. **Checksum Verification**: SHA-256 of migration file recorded in `_migration_log`; re-verify on every apply
5. **Drift Detection**: Compare live schema against expected post-migration state; flag differences

## Migration Status Tracking

Maintain a `_migration_log` (SQL) or `_migrations` collection (NoSQL):

```sql
CREATE TABLE IF NOT EXISTS _migration_log (
  id SERIAL PRIMARY KEY,
  name VARCHAR(255) NOT NULL UNIQUE,
  checksum VARCHAR(64) NOT NULL,
  applied_at TIMESTAMP NOT NULL DEFAULT NOW(),
  execution_time_ms INTEGER,
  rolled_back_at TIMESTAMP,
  rolled_back BOOLEAN NOT NULL DEFAULT FALSE
);
```

Checksums prevent partial applies: if a migration file changes after application, subsequent runs must fail with a clear mismatch error.

## Data Seeding

Generate realistic seed data for development and testing:

```bash
# Generate seed script from schema
python scripts/generate_migration.py --seed --environment dev --count 100

# Seed from production snapshot (anonymized)
python scripts/generate_migration.py --seed --from-snapshot prod.dump --anonymize
```

Seed guidelines:
- Foreign keys must be satisfied (seed in dependency order)
- Use deterministic IDs for stable test assertions
- Anonymize PII (names, emails, phones) when cloning production
- Mark seed data with `is_seed = TRUE` for easy cleanup

## Quick Reference: Migration Classification

```
ADDITIVE (safest)
  - Add nullable column
  - Add index (CONCURRENTLY)
  - Add table
  - Add non-validated constraint

DESTRUCTIVE (requires caution)
  - Drop column/table
  - Add NOT NULL without default
  - Rename column/table
  - Change column type (narrowing)

DATA MIGRATION (special handling)
  - Backfill new column
  - Split/merge tables
  - Migrate between databases
  - Archive old data
```

Always pair destructive changes with expand/contract or a phased rollout plan.

## Safety Checklist

```
Before any migration to production:
- [ ] Migration generated with forward + rollback scripts
- [ ] Checksums recorded for both directions
- [ ] Validated against staging database
- [ ] Backup or snapshot completed
- [ ] Lock duration estimated; zero-downtime pattern applied if > 2s
- [ ] ORM models reviewed for drift
- [ ] Seed data generated for new tables/columns (dev/test)
- [ ] Rollback tested in staging
- [ ] Team notified for coordinated deploy
```
