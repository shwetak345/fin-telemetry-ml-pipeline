# Prompt: Python DuckDB Connector for Financial Audit Log Storage

## Role
Act as a senior Database Engineer with expertise in analytical databases, DuckDB, and financial data governance.

## Task
Generate a production-ready Python script that initializes a local DuckDB analytical database and creates a schema-enforced table for financial audit logs.

## Prompt

```
You are a senior Database Engineer. Write a Python script that:

1. **Initializes a DuckDB database** at a configurable local file path (e.g., `data/audit.duckdb`).
   - Use a context manager for safe connection lifecycle management
   - Support both persistent (file) and in-memory (`:memory:`) modes via config
   - Log connection events without exposing file paths in production logs

2. **Creates a financial audit log table** named `financial_audit_logs` if it does not exist:
   - `log_id`           VARCHAR PRIMARY KEY  — UUID v4
   - `filing_id`        VARCHAR NOT NULL     — SEC EDGAR filing reference
   - `event_type`       VARCHAR NOT NULL     — e.g. INGEST, MASK, VALIDATE, EXPORT
   - `event_ts`         TIMESTAMPTZ NOT NULL — UTC timestamp of the event
   - `executive_name_hash` VARCHAR           — SHA-256 masked value (nullable)
   - `form_type`        VARCHAR              — 10-K, 10-Q, 8-K
   - `revenue_usd`      DECIMAL(20,2)        — nullable
   - `masking_version`  VARCHAR              — e.g. sha256-v1
   - `pipeline_run_id`  VARCHAR              — groups events from one pipeline run
   - `created_at`       TIMESTAMPTZ DEFAULT now()

3. **Provides helper functions**:
   - `insert_log_entry(conn, entry: AuditLogEntry) -> None`
   - `query_logs(conn, filters: LogQueryFilters) -> list[AuditLogEntry]`
   - `get_connection(config: DBConfig) -> duckdb.DuckDBPyConnection`

4. **Uses dataclasses** for `DBConfig`, `AuditLogEntry`, and `LogQueryFilters` with full type hints.

5. **Includes a `__main__` block** that:
   - Initializes the DB
   - Creates the table
   - Inserts two sample audit log entries
   - Queries and prints all rows

Use Python 3.11+, DuckDB 0.10+. No ORM. Raw SQL only. Include docstrings and type hints throughout.
```

## Expected Output Structure

```
duckdb_connector.py
├── DBConfig              # Dataclass: db_path, read_only, log_level
├── AuditLogEntry         # Dataclass: all audit log fields
├── LogQueryFilters       # Dataclass: event_type, form_type, date_range
├── get_connection()      # Returns a managed DuckDB connection
├── initialize_schema()   # CREATE TABLE IF NOT EXISTS
├── insert_log_entry()    # Parameterized INSERT
├── query_logs()          # SELECT with dynamic WHERE clause
└── main()                # Demo: init → insert → query → print
```

## Key Constraints

| Constraint | Requirement |
|---|---|
| SQL injection prevention | Parameterized queries only — no f-string SQL |
| Idempotency | `CREATE TABLE IF NOT EXISTS` on every startup |
| UUID generation | `uuid.uuid4()` in Python, not DB-side |
| Timestamp precision | Store all timestamps as UTC (`TIMESTAMPTZ`) |
| Connection safety | Always close via context manager or `finally` block |

## Follow-up Refinements

- Add a migration versioning system (schema_versions table)
- Export query results to Parquet via DuckDB's `COPY TO` for Delta Lake handoff
- Integrate with the PySpark ingestion pipeline to auto-log masking events
