"""
Bronze Layer — SEC EDGAR Filing Index Ingestion
================================================
Reads the quarterly EDGAR full-index from Azure Blob Storage and writes a
partitioned Parquet dataset (the Bronze table) to the local data store.

Enterprise mode
---------------
Set the following environment variables to point Spark at a real ADLS Gen2 or
Blob Storage container:

    AZURE_STORAGE_ACCOUNT   Storage account name
    AZURE_CONTAINER_NAME    Container name (default: "edgar-full-index")

Authentication — choose one:
    AZURE_STORAGE_KEY                          Shared-key auth
    AZURE_CLIENT_ID + AZURE_CLIENT_SECRET      Service-principal (recommended)
      + AZURE_TENANT_ID
    AZURE_MANAGED_IDENTITY=true                Managed Identity (Azure VMs / AKS)

Expected blob layout (mirrors the public EDGAR full-index structure):
    {container}/full-index/{YYYY}/{QTRN}/company.gz

Local dev mode
--------------
Leave AZURE_STORAGE_ACCOUNT unset.  The script downloads the quarterly index
directly from https://www.sec.gov/Archives/edgar/full-index/ over HTTPS and
processes it without any Azure credentials.

Tuning knobs (env vars)
-----------------------
    EDGAR_YEAR          Quarterly index year    (default: 2024)
    EDGAR_QUARTER       Quarterly index quarter (default: QTR1)
    EDGAR_MAX_RECORDS   Cap on records ingested (default: 500)
    BRONZE_OUTPUT_PATH  Parquet output root     (default: backend/data_store/bronze)
"""

import gzip
import hashlib
import io
import logging
import os
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import requests

# Must be set before PySpark is imported so the worker and driver share the
# same interpreter — avoids "Python worker exited unexpectedly" on Windows.
os.environ.setdefault("PYSPARK_PYTHON",        sys.executable)
os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.types import (
    DecimalType,
    DoubleType,
    StringType,
    StructField,
    StructType,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bronze schema
# ---------------------------------------------------------------------------

BRONZE_SCHEMA = StructType([
    StructField("cik",            StringType(),      True),
    StructField("company_name",   StringType(),      True),
    StructField("form_type",      StringType(),      True),
    StructField("date_filed",     StringType(),      True),   # raw string — cast in Silver
    StructField("filename",       StringType(),      True),
    StructField("edgar_year",     StringType(),      True),
    StructField("edgar_quarter",  StringType(),      True),
    # Simulated financial metrics.  In production these come from an XBRL
    # parsing step that reads the filing documents referenced by `filename`.
    StructField("revenue_usd",    DecimalType(20,2), True),
    StructField("revenue_growth", DoubleType(),      True),
    StructField("executive_name", StringType(),      True),   # raw PII — masked in Silver
])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class BronzeIngestionConfig:
    # Azure connection
    storage_account:      str  = field(default_factory=lambda: os.getenv("AZURE_STORAGE_ACCOUNT",  ""))
    container_name:       str  = field(default_factory=lambda: os.getenv("AZURE_CONTAINER_NAME",   "edgar-full-index"))
    storage_key:          str  = field(default_factory=lambda: os.getenv("AZURE_STORAGE_KEY",      ""))
    client_id:            str  = field(default_factory=lambda: os.getenv("AZURE_CLIENT_ID",        ""))
    client_secret:        str  = field(default_factory=lambda: os.getenv("AZURE_CLIENT_SECRET",    ""))
    tenant_id:            str  = field(default_factory=lambda: os.getenv("AZURE_TENANT_ID",        ""))
    use_managed_identity: bool = field(default_factory=lambda: os.getenv("AZURE_MANAGED_IDENTITY","").lower() == "true")

    # EDGAR target
    edgar_base_url:   str       = "https://www.sec.gov/Archives/edgar/full-index"
    target_year:      str       = field(default_factory=lambda: os.getenv("EDGAR_YEAR",    "2024"))
    target_quarter:   str       = field(default_factory=lambda: os.getenv("EDGAR_QUARTER", "QTR1"))
    form_type_filter: list[str] = field(default_factory=lambda: ["10-K", "10-Q", "8-K"])
    max_records:      int       = field(default_factory=lambda: int(os.getenv("EDGAR_MAX_RECORDS", "500")))

    # Output
    bronze_output_path: Path = field(
        default_factory=lambda: Path(os.getenv("BRONZE_OUTPUT_PATH", "backend/data_store/bronze"))
    )
    app_name: str = "sec-edgar-bronze-ingestion"

    @property
    def azure_mode(self) -> bool:
        return bool(self.storage_account)

    @property
    def adls_uri(self) -> str:
        """ADLS Gen2 (abfss) URI prefix — recommended for new Azure deployments."""
        return f"abfss://{self.container_name}@{self.storage_account}.dfs.core.windows.net"

    @property
    def wasbs_uri(self) -> str:
        """Legacy Blob Storage (wasbs) URI prefix — for classic Blob accounts."""
        return f"wasbs://{self.container_name}@{self.storage_account}.blob.core.windows.net"


# ---------------------------------------------------------------------------
# Spark session
# ---------------------------------------------------------------------------

def create_spark_session(config: BronzeIngestionConfig) -> SparkSession:
    """
    Builds a SparkSession configured for both local CPUs and Azure clusters.

    Enterprise cluster notes
    ------------------------
    • On Azure HDInsight / Databricks, set master to the cluster URI and omit
      spark.jars.packages (Hadoop-Azure JARs are pre-installed).
    • The hadoop-azure Maven co-ordinate enables wasbs:// and abfss:// support.
    • ADLS Gen2 OAuth is wired via the per-account spark.conf.set() calls below.
    • For production, replace shared-key auth with service-principal or Managed
      Identity so credentials are never stored in Spark config.
    """
    builder = (
        SparkSession.builder
        .appName(config.app_name)
        .master("local[*]")                                          # use all laptop CPU cores
        .config("spark.driver.host",          "127.0.0.1")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.execution.arrow.pyspark.enabled", "false")
        # Hadoop-Azure connector — resolved from Maven Central at startup.
        # On an enterprise cluster, remove this line and add the JARs to the
        # cluster's init script instead.
        .config(
            "spark.jars.packages",
            "org.apache.hadoop:hadoop-azure:3.3.6,"
            "com.azure:azure-storage-blob:12.25.1",
        )
    )

    if config.azure_mode:
        acct = config.storage_account
        dfs_host = f"{acct}.dfs.core.windows.net"

        if config.storage_key:
            builder = builder.config(f"fs.azure.account.key.{dfs_host}", config.storage_key)

        elif config.client_id:
            # Service-principal via AAD OAuth2 — recommended for production
            builder = (
                builder
                .config(f"fs.azure.account.auth.type.{dfs_host}", "OAuth")
                .config(
                    f"fs.azure.account.oauth.provider.type.{dfs_host}",
                    "org.apache.hadoop.fs.azurebfs.oauth2.ClientCredsTokenProvider",
                )
                .config(f"fs.azure.account.oauth2.client.id.{dfs_host}",     config.client_id)
                .config(f"fs.azure.account.oauth2.client.secret.{dfs_host}", config.client_secret)
                .config(
                    f"fs.azure.account.oauth2.client.endpoint.{dfs_host}",
                    f"https://login.microsoftonline.com/{config.tenant_id}/oauth2/token",
                )
            )

        elif config.use_managed_identity:
            builder = builder.config(
                f"fs.azure.account.auth.type.{dfs_host}", "ManagedIdentity"
            )

    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    logger.info("SparkSession ready (master=%s, azure_mode=%s)", spark.master, config.azure_mode)
    return spark


# ---------------------------------------------------------------------------
# EDGAR index parsing — HTTP fallback (local dev)
# ---------------------------------------------------------------------------

# Fixed-width column positions in the EDGAR company.gz full-index file
_FWF_COLSPECS = [(0, 62), (62, 74), (74, 86), (86, 98), (98, None)]
_FWF_NAMES    = ["company_name", "form_type", "cik", "date_filed", "filename"]


def _download_edgar_index(config: BronzeIngestionConfig) -> pd.DataFrame:
    """
    Downloads the quarterly EDGAR company filing index via HTTPS and parses
    its fixed-width text format into a pandas DataFrame.

    The EDGAR full-index files are gzip-compressed fixed-width text:
        https://www.sec.gov/Archives/edgar/full-index/{YYYY}/{QTRN}/company.gz
    """
    url = (
        f"{config.edgar_base_url}/{config.target_year}"
        f"/{config.target_quarter}/company.gz"
    )
    logger.info("Downloading EDGAR index: %s", url)

    resp = requests.get(
        url,
        headers={"User-Agent": "FinTelemetry-Pipeline contact@example.com"},
        timeout=60,
    )
    resp.raise_for_status()

    raw_text  = gzip.decompress(resp.content).decode("latin-1")
    # Skip the 2-line header (description row + dash separator)
    data_body = "\n".join(line for line in raw_text.splitlines()[2:] if line.strip())

    df = pd.read_fwf(
        io.StringIO(data_body),
        colspecs=_FWF_COLSPECS,
        names=_FWF_NAMES,
        dtype=str,
    )

    df["company_name"] = df["company_name"].str.strip()
    df["form_type"]    = df["form_type"].str.strip()
    df["cik"]          = df["cik"].str.strip().str.lstrip("0")
    df["date_filed"]   = df["date_filed"].str.strip()
    df["filename"]     = df["filename"].str.strip()
    df = df.dropna(subset=["company_name", "cik"])

    df = (
        df[df["form_type"].isin(config.form_type_filter)]
        .head(config.max_records)
        .reset_index(drop=True)
    )
    logger.info("Parsed %d filings from EDGAR index.", len(df))
    return df


# ---------------------------------------------------------------------------
# EDGAR index reading — Azure Blob (enterprise)
# ---------------------------------------------------------------------------

def _read_from_azure_blob(spark: SparkSession, config: BronzeIngestionConfig) -> pd.DataFrame:
    """
    Reads the quarterly EDGAR index from Azure Blob / ADLS Gen2 via Spark.

    The blob path mirrors the public EDGAR layout:
        {container}/full-index/{YYYY}/{QTRN}/company.gz

    Spark auto-decompresses .gz files when reading as text.  The Hadoop-Azure
    JARs (configured in create_spark_session) handle abfss:// URI resolution.
    """
    blob_path = (
        f"{config.adls_uri}/full-index/{config.target_year}"
        f"/{config.target_quarter}/company.gz"
    )
    logger.info("Reading Bronze index from Azure Blob: %s", blob_path)

    raw_rdd = spark.sparkContext.textFile(blob_path)

    # Strip the 2-line header
    lines_with_idx = raw_rdd.zipWithIndex()
    data_rdd = (
        lines_with_idx
        .filter(lambda x: x[1] >= 2 and x[0].strip())
        .map(lambda x: x[0])
    )

    rows = data_rdd.map(lambda ln: {
        "company_name": ln[0:62].strip(),
        "form_type":    ln[62:74].strip(),
        "cik":          ln[74:86].strip().lstrip("0"),
        "date_filed":   ln[86:98].strip(),
        "filename":     ln[98:].strip(),
    }).collect()

    df = pd.DataFrame(rows)
    df = df[df["form_type"].isin(config.form_type_filter)].head(config.max_records).reset_index(drop=True)
    logger.info("Fetched %d filings from Azure Blob.", len(df))
    return df


# ---------------------------------------------------------------------------
# Financial feature simulation
# ---------------------------------------------------------------------------

_EXEC_FIRST = ["Jane", "John", "Alice", "Robert", "Sandra", "Michael", "Patricia", "David"]
_EXEC_LAST  = ["Doe", "Smith", "Chen", "Miles", "Park", "Johnson", "Williams", "Brown"]
_REV_BUCKETS = [5e7, 1.2e8, 3.4e8, 6.7e8, 9.2e8, 1.2e9, 2.5e9, 4.8e9, 9.1e9, 2.5e10]


def _enrich_financial_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Attaches simulated financial metrics to each filing row, seeded by CIK so
    values are deterministic across pipeline runs.

    Production replacement: an XBRL parsing stage reads the actual filing
    document at `filename` and extracts typed financial facts (us-gaap taxonomy).
    The CIK-seeded values here exist solely to make the local pipeline runnable
    without XBRL infrastructure.
    """
    records = []
    for _, row in df.iterrows():
        cik_int = int(row["cik"]) if str(row["cik"]).isdigit() else hash(row["cik"]) & 0x7FFFFFFF
        rng     = random.Random(cik_int)

        has_rev    = row["form_type"] in ("10-K", "10-Q", "20-F", "S-1") or rng.random() > 0.6
        rev_usd    = rng.choice(_REV_BUCKETS) if has_rev else None
        rev_growth = round(rng.gauss(0.05, 0.12), 4)
        exec_name  = (
            f"{rng.choice(_EXEC_FIRST)} {rng.choice(_EXEC_LAST)}" if rng.random() > 0.2 else None
        )

        records.append({
            **row.to_dict(),
            "revenue_usd":    rev_usd,
            "revenue_growth": rev_growth,
            "executive_name": exec_name,
        })

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ingest_bronze(config: Optional[BronzeIngestionConfig] = None) -> DataFrame:
    """
    Orchestrates Bronze ingestion and returns a PySpark DataFrame.

    Steps
    -----
    1. Acquire the EDGAR filing index (Azure Blob → HTTP fallback).
    2. Enrich rows with simulated financial features.
    3. Coerce to BRONZE_SCHEMA and create a Spark DataFrame.
    4. Write partitioned Parquet to config.bronze_output_path.
    5. Return the DataFrame for downstream Silver processing.
    """
    if config is None:
        config = BronzeIngestionConfig()

    spark = create_spark_session(config)

    if config.azure_mode:
        index_pd = _read_from_azure_blob(spark, config)
    else:
        index_pd = _download_edgar_index(config)

    index_pd = _enrich_financial_features(index_pd)
    index_pd["edgar_year"]    = config.target_year
    index_pd["edgar_quarter"] = config.target_quarter

    # Coerce NaN → None for Spark nullable columns
    index_pd = index_pd.replace({float("nan"): None})
    index_pd["revenue_usd"] = index_pd["revenue_usd"].apply(
        lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 2)
    )

    bronze_df = spark.createDataFrame(index_pd, schema=BRONZE_SCHEMA)

    out_path = str(config.bronze_output_path.resolve())
    (
        bronze_df.write
        .mode("overwrite")
        .partitionBy("edgar_year", "edgar_quarter")
        .parquet(out_path)
    )
    logger.info(
        "Bronze Parquet written → %s  (%d rows)",
        out_path, bronze_df.count(),
    )
    return bronze_df


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    cfg = BronzeIngestionConfig()
    logger.info(
        "Mode: %s | Year: %s | Quarter: %s | Forms: %s",
        "Azure" if cfg.azure_mode else "HTTP (local dev)",
        cfg.target_year, cfg.target_quarter,
        ", ".join(cfg.form_type_filter),
    )
    df = ingest_bronze(cfg)
    df.printSchema()
    df.show(5, truncate=True)
