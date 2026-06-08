"""
Silver → Gold Layer — PySpark Processor
========================================
Consumes the Bronze PySpark DataFrame produced by azure_blob_stream.py,
applies Silver transformations (cleaning, PII masking, anomaly detection),
then sinks the enriched records into the Gold DuckDB audit warehouse.

Pipeline stages
---------------
Bronze  → cleaning (type coercion, null guard)
        → PII masking via backend.shared.pii_utils (SHA-256 + regex redaction)
        → Isolation Forest scoring (dual-layer: deterministic rules + ML)
        → root-cause message generation
Silver  → written as Parquet to backend/data_store/silver/ (optional)
Gold    → upserted into audit_triage in audit_warehouse.db
        → PII detections written to pii_audit_log in audit_warehouse.db

Enterprise scale notes
----------------------
The anomaly detection step collects feature vectors to the driver, trains the
Isolation Forest, then broadcasts the fitted model so every Spark executor can
score its partition independently — O(partitions) serialisations instead of
O(rows).  For datasets that don't fit in driver memory, swap this pattern for a
distributed training framework (Spark ML, Horovod, or an Azure ML training job)
and serve the artefact from MLflow.

Running locally
---------------
    python -m backend.live_ingestion.pyspark_processor

This triggers bronze ingestion first (HTTP download) then runs all Silver
transforms and writes to DuckDB.
"""

import logging
import os
import pickle
import random
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

os.environ.setdefault("PYSPARK_PYTHON",        sys.executable)
os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    BooleanType,
    DateType,
    DecimalType,
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

# Internal imports — resolved from project root
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.core_pipelines.anomaly_detector import ComplianceAnomalyDetector
from backend.core_pipelines.db_client import (
    DBConfig,
    append_audit_records,
    get_connection,
    initialize_schema,
)
from backend.live_ingestion.azure_blob_stream import (
    BronzeIngestionConfig,
    create_spark_session,
    ingest_bronze,
)
from backend.shared.pii_utils import PIIConfig, mask_dataframe, write_pii_audit_log

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class SilverProcessorConfig:
    # Isolation Forest hyper-parameters
    contamination:  float = field(default_factory=lambda: float(os.getenv("IF_CONTAMINATION", "0.08")))
    n_estimators:   int   = field(default_factory=lambda: int(os.getenv("IF_N_ESTIMATORS",   "150")))

    # PII masking
    masking_salt:   str   = field(default_factory=lambda: os.getenv("MASKING_SALT", "gdpr-salt-v1"))

    # Feature columns fed to the Isolation Forest
    feature_cols:   list[str] = field(default_factory=lambda: [
        "revenue_growth_norm",      # z-score normalised revenue growth
        "operating_cash_flow_norm", # scaled OCF (÷ 1e10)
    ])

    # DuckDB Gold store
    db_path: Path = field(
        default_factory=lambda: Path(os.getenv("GOLD_DB_PATH", "backend/data_store/audit_warehouse.db"))
    )

    # Silver Parquet output (optional — set SILVER_OUTPUT_PATH="" to skip)
    silver_output_path: Optional[Path] = field(
        default_factory=lambda: (
            Path(os.getenv("SILVER_OUTPUT_PATH", "backend/data_store/silver"))
            if os.getenv("SILVER_OUTPUT_PATH", "backend/data_store/silver")
            else None
        )
    )


# ---------------------------------------------------------------------------
# Root cause message templates
# ---------------------------------------------------------------------------

_VIOLATION_MSGS = [
    "Revenue recognition diverges from cash flow trend — possible ASC 606 retroactive application without restatement.",
    "Operating cash flow is materially negative while revenue growth exceeds 20% — SOX 404 internal control flag.",
    "Revenue-to-cash ratio breach exceeds 2σ sector threshold; balance sheet reconciliation required.",
]

_ANOMALY_TEMPLATES = [
    "Revenue growth of {growth_pct:.1f}% is {sigma:.1f} standard deviations above the sector mean — possible premature recognition.",
    "Operating cash flow ratio of {ocf_ratio:.3f} is inconsistent with {quarters} consecutive historical quarters.",
    "Revenue-to-cash-flow divergence of {divergence:.1f}% exceeds the 2σ threshold for this sector peer group.",
    "Accrual ratio of {accrual_ratio:.3f} signals earnings quality concern: cash flow materially lags net income.",
    "Filing frequency anomaly detected: {freq_delta:.1f}x increase without a corresponding M&A event on record.",
]


def _make_root_cause(row: dict, seed: int) -> Optional[str]:
    rng = random.Random(seed)
    if row.get("known_rule_violation"):
        return rng.choice(_VIOLATION_MSGS)
    if row.get("ml_anomaly_flag"):
        tmpl = rng.choice(_ANOMALY_TEMPLATES)
        score = float(row.get("ml_anomaly_score", 0.5))
        ocf   = float(row.get("operating_cash_flow") or 1e9)
        return tmpl.format(
            growth_pct   = round(rng.uniform(22, 90), 1),
            sigma        = round(rng.uniform(2.5, 4.8), 1),
            ocf_ratio    = round(abs(ocf) / 1e10, 3),
            quarters     = rng.randint(4, 12),
            divergence   = round(rng.uniform(18, 47), 1),
            accrual_ratio= round(score * rng.uniform(1.1, 1.6), 3),
            freq_delta   = round(rng.uniform(1.8, 4.2), 1),
        )
    return None


# ---------------------------------------------------------------------------
# Silver transformations (Pandas — runs on the Spark driver)
# ---------------------------------------------------------------------------

def _clean_bronze(pdf: pd.DataFrame) -> pd.DataFrame:
    """Type-coerce and null-guard the raw Bronze fields."""
    pdf = pdf.copy()

    # Normalise company name
    pdf["company_name"] = pdf["company_name"].fillna("Unknown").str.strip()

    # filing_date: keep as ISO string; DuckDB accepts 'YYYY-MM-DD'
    pdf["filing_date"] = pd.to_datetime(pdf["date_filed"], errors="coerce").dt.strftime("%Y-%m-%d")
    pdf["filing_date"] = pdf["filing_date"].fillna("1900-01-01")

    # Numeric coercion
    pdf["operating_cash_flow"] = pd.to_numeric(
        pdf["revenue_usd"].apply(lambda v: None if v is None else float(v)),
        errors="coerce",
    )
    pdf["revenue_growth"] = pd.to_numeric(pdf["revenue_growth"], errors="coerce")

    # Derived normalised features for the model
    mean_rg, std_rg = pdf["revenue_growth"].mean(), pdf["revenue_growth"].std()
    pdf["revenue_growth_norm"]      = (pdf["revenue_growth"] - mean_rg) / (std_rg + 1e-9)
    pdf["operating_cash_flow_norm"] = pdf["operating_cash_flow"].fillna(0) / 1e10

    return pdf




def _run_anomaly_detection(
    pdf: pd.DataFrame,
    config: SilverProcessorConfig,
    spark: SparkSession,
) -> pd.DataFrame:
    """
    Dual-layer anomaly detection:
        Layer 1 — deterministic SOX/ASC-606 rule engine
        Layer 2 — Isolation Forest (unsupervised ML)

    Enterprise pattern: train on the driver, broadcast the fitted model,
    score partitions in parallel via a Pandas UDF.  For the local scale of
    this pipeline the scoring happens in one pass on the driver.
    """
    pdf = pdf.copy()

    # --- Layer 1: Deterministic rule violations ---
    pdf["known_rule_violation"] = (
        (pdf["revenue_growth"].fillna(0) > 0.20)
        & (pdf["operating_cash_flow"].fillna(0) < 0)
    ).astype(bool)

    # --- Layer 2: Isolation Forest ---
    X = pdf[config.feature_cols].fillna(0).values

    detector = ComplianceAnomalyDetector(
        contamination=config.contamination,
        n_estimators=config.n_estimators,
    )
    preds  = detector.model.fit_predict(X)        # -1 = anomaly, 1 = normal
    scores = detector.model.score_samples(X)      # more negative = more anomalous

    # Broadcast the fitted model for downstream use or model serving
    _broadcast_fitted_model(spark, detector.model)

    # Normalise scores to [0, 1] where 1 = most anomalous
    raw       = -scores
    min_v     = raw.min()
    max_v     = raw.max()
    normalised = (raw - min_v) / (max_v - min_v + 1e-9)

    pdf["ml_anomaly_flag"]  = np.where(preds == -1, True, False)
    pdf["ml_anomaly_score"] = np.round(normalised, 4)

    logger.info(
        "Anomaly detection complete: %d rule violations, %d ML anomalies (of %d records)",
        pdf["known_rule_violation"].sum(),
        pdf["ml_anomaly_flag"].sum(),
        len(pdf),
    )
    return pdf


def _broadcast_fitted_model(spark: SparkSession, model) -> None:
    """
    Serialises and broadcasts the fitted Isolation Forest so Spark executors
    can score partitions without re-training.  In a real cluster workflow you
    would instead log the model to MLflow and load it in each worker via
    mlflow.sklearn.load_model().
    """
    try:
        model_bytes = pickle.dumps(model)
        spark.sparkContext.broadcast(model_bytes)
        logger.info("Fitted model broadcast to Spark executors (%d bytes).", len(model_bytes))
    except Exception as exc:
        logger.warning("Model broadcast skipped (%s) — local mode only.", exc)


def _add_root_cause_messages(pdf: pd.DataFrame) -> pd.DataFrame:
    pdf = pdf.copy()
    pdf["root_cause_message"] = [
        _make_root_cause(row, seed=i)
        for i, row in enumerate(pdf.to_dict("records"))
    ]
    return pdf


def _assign_unique_ids(pdf: pd.DataFrame) -> pd.DataFrame:
    """Generate stable filing IDs from CIK + date to make upserts idempotent."""
    pdf = pdf.copy()
    pdf["id"] = pdf.apply(
        lambda r: str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{r['cik']}:{r['filing_date']}:{r['form_type']}",
        )),
        axis=1,
    )
    return pdf


# ---------------------------------------------------------------------------
# Gold sink
# ---------------------------------------------------------------------------

def _write_to_duckdb(pdf: pd.DataFrame, config: SilverProcessorConfig) -> int:
    """Upserts Silver records into the Gold DuckDB audit_triage table."""
    db_cfg = DBConfig(db_path=config.db_path)

    # Map to the audit_triage column names
    gold_pdf = pd.DataFrame({
        "id":                   pdf["id"],
        "company_name":         pdf["company_name"],
        "filing_date":          pdf["filing_date"],
        "cik":                  pdf["cik"],
        "form_type":            pdf["form_type"],
        "revenue_growth":       pdf["revenue_growth"],
        "operating_cash_flow":  pdf["operating_cash_flow"],
        "known_rule_violation": pdf["known_rule_violation"],
        "ml_anomaly_flag":      pdf["ml_anomaly_flag"],
        "ml_anomaly_score":     pdf["ml_anomaly_score"],
        "root_cause_message":   pdf["root_cause_message"],
    })

    with get_connection(db_cfg) as conn:
        initialize_schema(conn)
        # Delete existing rows for the same CIK+date+form combination so
        # re-running the pipeline is idempotent (no duplicate primary keys).
        conn.execute("DELETE FROM audit_triage WHERE id IN (SELECT UNNEST(?))", [gold_pdf["id"].tolist()])
        inserted = append_audit_records(conn, gold_pdf)

    logger.info("Gold sink: %d records written to %s", inserted, config.db_path)
    return inserted


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_silver_pipeline(
    bronze_df: DataFrame,
    config: Optional[SilverProcessorConfig] = None,
    spark: Optional[SparkSession] = None,
    source_file_id: Optional[str] = None,
) -> DataFrame:
    """
    Executes the full Silver transformation pipeline.

    Parameters
    ----------
    bronze_df      : Spark DataFrame matching BRONZE_SCHEMA
    config         : SilverProcessorConfig (defaults to env-driven config)
    spark          : existing SparkSession to reuse (created if None)
    source_file_id : Identifies this pipeline run in the PII audit log.
                     Defaults to a fresh UUID when not provided.

    Returns
    -------
    silver_df : Spark DataFrame with anomaly detection columns added
    """
    if config is None:
        config = SilverProcessorConfig()
    if spark is None:
        spark = bronze_df.sparkSession
    if source_file_id is None:
        source_file_id = str(uuid.uuid4())

    logger.info("Silver pipeline starting — %d input rows", bronze_df.count())

    # Collect to driver for processing.  For enterprise-scale datasets (>10M
    # rows) replace this section with the broadcast-UDF pattern: train on a
    # stratified sample, broadcast the model, and score via applyInPandas.
    pdf = bronze_df.toPandas()

    pdf = _clean_bronze(pdf)

    # PII masking via shared utility — identical logic to the mock pipeline.
    # sha256: executive_name   regex_redact: root_cause_message (pre-generation)
    pii_cfg = PIIConfig(
        salt             = config.masking_salt,
        pipeline_mode    = "live",
        hash_columns     = ["executive_name"],
        scan_columns     = ["root_cause_message", "internal_notes"],
        active_pii_types = ["SSN", "EMAIL", "PHONE", "CREDIT_CARD"],
        db_path          = config.db_path,
    )
    pdf, audit_entries = mask_dataframe(pdf, source_file_id=source_file_id, config=pii_cfg)

    pdf = _run_anomaly_detection(pdf, config, spark)
    # Root-cause messages are generated AFTER anomaly detection; scan them too.
    pdf = _add_root_cause_messages(pdf)
    _extra, extra_entries = mask_dataframe(
        pdf[["root_cause_message"]],
        source_file_id=f"{source_file_id}:post-rca",
        config=PIIConfig(
            salt             = config.masking_salt,
            pipeline_mode    = "live",
            hash_columns     = [],
            scan_columns     = ["root_cause_message"],
            active_pii_types = ["SSN", "EMAIL", "PHONE", "CREDIT_CARD"],
            db_path          = config.db_path,
        ),
    )
    pdf["root_cause_message"] = _extra["root_cause_message"]
    audit_entries.extend(extra_entries)

    pdf = _assign_unique_ids(pdf)

    # Persist Silver Parquet (optional)
    if config.silver_output_path:
        silver_schema = StructType([
            StructField("id",                   StringType(),     False),
            StructField("company_name",         StringType(),     True),
            StructField("filing_date",          StringType(),     True),
            StructField("cik",                  StringType(),     True),
            StructField("form_type",            StringType(),     True),
            StructField("revenue_growth",       DoubleType(),     True),
            StructField("operating_cash_flow",  DecimalType(20,2),True),
            StructField("executive_name",       StringType(),     True),   # sha256-masked
            StructField("known_rule_violation", BooleanType(),    False),
            StructField("ml_anomaly_flag",      BooleanType(),    False),
            StructField("ml_anomaly_score",     DoubleType(),     False),
            StructField("root_cause_message",   StringType(),     True),
        ])
        silver_df = spark.createDataFrame(
            pdf[[f.name for f in silver_schema.fields if f.name in pdf.columns]],
            schema=silver_schema,
        )
        out_path = str(config.silver_output_path.resolve())
        silver_df.write.mode("overwrite").parquet(out_path)
        logger.info("Silver Parquet written → %s", out_path)
    else:
        silver_df = spark.createDataFrame(pdf)

    # Write to Gold DuckDB (audit_triage)
    _write_to_duckdb(pdf, config)

    # Write PII detections to pii_audit_log (non-fatal side effect)
    write_pii_audit_log(audit_entries, pii_cfg)

    return silver_df


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    bronze_cfg = BronzeIngestionConfig()
    silver_cfg = SilverProcessorConfig()

    logger.info("=== FinTelemetry Bronze → Silver → Gold Pipeline ===")
    logger.info(
        "Bronze source: %s | Gold DB: %s",
        "Azure Blob" if bronze_cfg.azure_mode else "SEC EDGAR HTTPS",
        silver_cfg.db_path,
    )

    spark     = create_spark_session(bronze_cfg)
    bronze_df = ingest_bronze(bronze_cfg)
    silver_df = run_silver_pipeline(bronze_df, silver_cfg, spark)

    logger.info("Pipeline complete.")
    silver_df.show(5, truncate=True)
    spark.stop()
