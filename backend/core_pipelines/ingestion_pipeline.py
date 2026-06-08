"""
SEC EDGAR Ingestion Pipeline
Streams mock EDGAR filings, applies data minimization, and SHA-256 masks
executive names before exporting a GDPR-compliant DataFrame.
"""
import os
import sys
from pathlib import Path

# Resolve project root before any local imports so the module works both when
# run directly (python -m backend.core_pipelines.ingestion_pipeline) and when
# imported from another package.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

os.environ.setdefault("PYSPARK_PYTHON",        sys.executable)
os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

import hashlib
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

from backend.core_pipelines.db_client import DBConfig, get_connection, initialize_schema, append_audit_records
from backend.core_pipelines.mock_data import get_mock_sec_filings

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType,
    DecimalType,
    StringType,
    StructField,
    StructType,
)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

RAW_SCHEMA = StructType(
    [
        StructField("filing_id", StringType(), False),
        StructField("form_type", StringType(), False),
        StructField("filing_date", DateType(), False),
        StructField("company_name", StringType(), False),
        StructField("cik", StringType(), False),
        StructField("executive_name", StringType(), True),
        StructField("executive_title", StringType(), True),
        StructField("revenue_usd", DecimalType(20, 2), True),
        # Columns intentionally dropped during minimization:
        StructField("internal_notes", StringType(), True),
        StructField("raw_submission_xml", StringType(), True),
        StructField("submitter_email", StringType(), True),
    ]
)

# Columns retained after data minimization (GDPR Art. 5(1)(c))
MINIMIZED_COLUMNS: list[str] = [
    "filing_id",
    "form_type",
    "filing_date",
    "company_name",
    "cik",
    "executive_name",
    "executive_title",
    "revenue_usd",
]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    app_name: str = "sec-edgar-ingestion"
    masking_salt: str = "gdpr-salt-v1"
    output_partition_cols: list[str] = field(
        default_factory=lambda: ["form_type", "filing_date"]
    )


# ---------------------------------------------------------------------------
# Data source
# ---------------------------------------------------------------------------

def load_raw_stream(spark: SparkSession) -> DataFrame:
    """Creates a Spark DataFrame from mock_data.get_mock_sec_filings()."""
    rows = get_mock_sec_filings()
    return spark.createDataFrame(rows, schema=RAW_SCHEMA)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Transformations
# ---------------------------------------------------------------------------

def minimize_columns(df: DataFrame) -> DataFrame:
    """Drops columns not required for downstream analytics (GDPR minimization)."""
    return df.select(MINIMIZED_COLUMNS)


def _sha256_udf(salt: str) -> F.UserDefinedFunction:
    """Returns a UDF that SHA-256 hashes a nullable string with a fixed salt."""

    def _hash(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        salted = f"{salt}:{value}".encode("utf-8")
        return hashlib.sha256(salted).hexdigest()

    return F.udf(_hash, StringType())


def mask_executive_names(df: DataFrame, salt: str) -> DataFrame:
    """
    Replaces executive_name with its SHA-256 digest.
    Preserves NULL values so absence-of-data is not fabricated.
    """
    hash_fn = _sha256_udf(salt)
    return df.withColumn("executive_name", hash_fn(F.col("executive_name")))


def add_lineage_metadata(df: DataFrame) -> DataFrame:
    """Appends audit columns required for data lineage tracking."""
    return (
        df.withColumn("ingestion_ts", F.current_timestamp())
        .withColumn("masking_version", F.lit("sha256-v1"))
        .withColumn("pii_masked", F.lit(True))
    )


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------

def run_pipeline(config: PipelineConfig) -> DataFrame:
    """
    Executes the end-to-end ingestion pipeline and returns the
    GDPR-compliant DataFrame ready for downstream consumption.
    """

    spark = (
        SparkSession.builder
        .appName(config.app_name)
        .master("local[*]")  # Keeps execution in-process to avoid socket issues
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.driver.host", "127.0.0.1")
        # --- NEW CONFIGS ---
        .config("spark.sql.execution.pyspark.udf.faulthandler.enabled", "true")
        .config("spark.sql.execution.arrow.pyspark.enabled", "false") # Disables risky pipe communication
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    raw_df = load_raw_stream(spark)
    minimized_df = minimize_columns(raw_df)
    masked_df = mask_executive_names(minimized_df, config.masking_salt)
    final_df = add_lineage_metadata(masked_df)

    return final_df


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging
    import sys
    import uuid
    from pathlib import Path

    from backend.shared.pii_utils import PIIConfig, mask_dataframe, write_pii_audit_log

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    # 1. Load mock filings into a Pandas DataFrame (bypasses Spark entirely
    #    for the __main__ path — keeps everything single-process on Windows)
    pandas_df = pd.DataFrame(get_mock_sec_filings())

    # 2. Rename to match audit_triage column names
    pandas_df = pandas_df.rename(columns={
        "filing_id": "id",
        "revenue_usd": "operating_cash_flow",
    })

    # 3. PII masking pass — SHA-256 executive names, regex-scan free text.
    #    Produces a masked copy and an audit trail (never logged raw PII).
    run_id  = str(uuid.uuid4())
    pii_cfg = PIIConfig(
        pipeline_mode    = "mock",
        hash_columns     = ["executive_name"],
        scan_columns     = ["root_cause_message", "internal_notes"],
        active_pii_types = ["SSN", "EMAIL", "PHONE", "CREDIT_CARD"],
    )
    pandas_df, audit_entries = mask_dataframe(
        pandas_df, source_file_id=run_id, config=pii_cfg,
    )

    # 4. Sink to Gold DuckDB
    db_cfg = DBConfig()
    with get_connection(db_cfg) as conn:
        initialize_schema(conn)
        inserted = append_audit_records(conn, pandas_df)
    print(f"Ingested {inserted} records into audit_triage.")

    # 5. Write PII audit log (side effect — non-fatal if DB is locked)
    logged = write_pii_audit_log(audit_entries, pii_cfg)
    print(f"PII audit: {logged} entr{'y' if logged == 1 else 'ies'} written to pii_audit_log.")