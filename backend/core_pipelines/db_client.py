"""
DuckDB client for the financial audit warehouse.
Manages connection lifecycle, schema initialization, and DataFrame ingestion
for the audit_triage analytical table.
"""

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class DBConfig:
    db_path: Path = field(default_factory=lambda: Path("backend/data_store/audit_warehouse.db"))
    read_only: bool = False

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_AUDIT_TRIAGE = """
CREATE TABLE IF NOT EXISTS audit_triage (
    id                  VARCHAR      PRIMARY KEY,
    company_name        VARCHAR      NOT NULL,
    filing_date         DATE         NOT NULL,
    cik                 VARCHAR,
    form_type           VARCHAR,
    revenue_growth      DOUBLE,
    operating_cash_flow DECIMAL(20, 2),
    known_rule_violation BOOLEAN     NOT NULL DEFAULT FALSE,
    ml_anomaly_flag     BOOLEAN      NOT NULL DEFAULT FALSE,
    ml_anomaly_score    DOUBLE,
    root_cause_message  VARCHAR,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);
"""

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

@contextmanager
def get_connection(config: DBConfig) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Yields a managed DuckDB connection; always closes on exit."""
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(database=str(config.db_path), read_only=config.read_only)
    logger.info("DuckDB connection opened (read_only=%s)", config.read_only)
    try:
        yield conn
    finally:
        conn.close()
        logger.info("DuckDB connection closed")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def initialize_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Creates audit_triage table if it does not already exist."""
    conn.execute(_CREATE_AUDIT_TRIAGE)
    logger.info("Schema initialized: table 'audit_triage' is ready")


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

_REQUIRED_COLUMNS: set[str] = {
    "id",
    "company_name",
    "filing_date",
}

_EXPECTED_COLUMNS: list[str] = [
    "id",
    "company_name",
    "filing_date",
    "cik",
    "form_type",
    "revenue_growth",
    "operating_cash_flow",
    "known_rule_violation",
    "ml_anomaly_flag",
    "ml_anomaly_score",
    "root_cause_message",
]


def _validate_dataframe(df: pd.DataFrame) -> None:
    missing = _REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame is missing required columns: {missing}")


def append_audit_records(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """
    Appends rows from *df* into audit_triage.

    Only columns declared in _EXPECTED_COLUMNS are written; extras are ignored.
    Returns the number of rows inserted.
    """
    _validate_dataframe(df)

    present = [c for c in _EXPECTED_COLUMNS if c in df.columns]
    subset = df[present].copy()

    col_list = ", ".join(present)
    placeholders = ", ".join(["?" for _ in present])

    rows = [tuple(row) for row in subset.itertuples(index=False, name=None)]

    conn.executemany(
        f"INSERT INTO audit_triage ({col_list}) VALUES ({placeholders})",  # noqa: S608
        rows,
    )

    logger.info("Inserted %d rows into audit_triage", len(rows))
    return len(rows)


# ---------------------------------------------------------------------------
# Query helper
# ---------------------------------------------------------------------------

def fetch_audit_records(
    conn: duckdb.DuckDBPyConnection,
    limit: int = 100,
) -> pd.DataFrame:
    """Returns up to *limit* rows from audit_triage as a pandas DataFrame."""
    result: pd.DataFrame = conn.execute(
        "SELECT * FROM audit_triage ORDER BY created_at DESC LIMIT ?", [limit]
    ).df()
    logger.info("Fetched %d rows from audit_triage", len(result))
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _build_sample_df() -> pd.DataFrame:
    import uuid
    from datetime import date

    return pd.DataFrame(
        [
            {
                "id": str(uuid.uuid4()),
                "company_name": "Apex Financial Corp",
                "filing_date": date(2024, 1, 15),
                "revenue_growth": 0.12,
                "operating_cash_flow": 4_200_000_000.00,
                "known_rule_violation": False,
                "ml_anomaly_flag": True,
                "ml_anomaly_score": 0.87,
            },
            {
                "id": str(uuid.uuid4()),
                "company_name": "Meridian Capital LLC",
                "filing_date": date(2024, 3, 31),
                "revenue_growth": -0.03,
                "operating_cash_flow": 780_000_000.00,
                "known_rule_violation": True,
                "ml_anomaly_flag": True,
                "ml_anomaly_score": 0.94,
            },
            {
                "id": str(uuid.uuid4()),
                "company_name": "Quantum Asset Management",
                "filing_date": date(2024, 4, 2),
                "revenue_growth": None,
                "operating_cash_flow": None,
                "known_rule_violation": False,
                "ml_anomaly_flag": False,
                "ml_anomaly_score": 0.11,
            },
        ]
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    cfg = DBConfig()
    sample_df = _build_sample_df()

    with get_connection(cfg) as conn:
        initialize_schema(conn)
        inserted = append_audit_records(conn, sample_df)
        print(f"\nInserted {inserted} records.\n")
        print(fetch_audit_records(conn).to_string(index=False))
