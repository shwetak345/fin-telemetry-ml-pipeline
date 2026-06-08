"""
Shared PII Detection, Masking, and Audit Logging
=================================================
Framework-agnostic utilities that operate on **Pandas DataFrames**.  Both the
mock pipeline (core_pipelines) and the live pipeline (live_ingestion) import
this module to guarantee identical PII handling across environments.

Public API
----------
    from backend.shared.pii_utils import PIIConfig, mask_dataframe, write_pii_audit_log

    config = PIIConfig(pipeline_mode="mock", salt="gdpr-salt-v1")
    masked_df, audit_entries = mask_dataframe(df, source_file_id="run-abc", config=config)
    write_pii_audit_log(audit_entries, config)   # side-effect: sinks to DuckDB

Two-pass masking strategy
--------------------------
Pass 1 — Structured PII (hash_columns)
    Columns whose entire value is PII (e.g. executive_name) are replaced with
    their SHA-256 hex digest.  Deterministic: the same name always produces the
    same hash, enabling cross-pipeline joins on the masked value.

Pass 2 — Free-text PII (scan_columns)
    Arbitrary text fields are scanned with regex patterns.  Any match is
    replaced with [REDACTED_<TYPE>] in place.  The log records how many rows
    were affected — never the raw PII value itself.

Audit log
---------
    One PIIAuditEntry is produced per (pipeline_run × column × pii_type).
    Entries are written to the ``pii_audit_log`` table in audit_warehouse.db
    via write_pii_audit_log().  The table is created automatically on first use.
"""

import hashlib
import logging
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Resolve project root so absolute imports work regardless of CWD
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# PII regex patterns
# ---------------------------------------------------------------------------

#: Compiled regex patterns keyed by the PII type label they detect.
#: Add new patterns here to extend detection without changing any other code.
PII_PATTERNS: dict[str, re.Pattern] = {
    "SSN": re.compile(
        r"\b\d{3}-\d{2}-\d{4}\b"
    ),
    "EMAIL": re.compile(
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
    ),
    "PHONE": re.compile(
        r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"
    ),
    "CREDIT_CARD": re.compile(
        r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6(?:011|5\d{2}))"
        r"[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"
    ),
    "IP_ADDRESS": re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
    ),
}

_REDACT_PLACEHOLDER = "[REDACTED_{pii_type}]"

# ---------------------------------------------------------------------------
# DuckDB audit table DDL (authoritative — used by initialize_pii_audit_schema)
# ---------------------------------------------------------------------------

PII_AUDIT_LOG_DDL = """
CREATE TABLE IF NOT EXISTS pii_audit_log (
    id               VARCHAR      PRIMARY KEY,
    source_file_id   VARCHAR      NOT NULL,
    field_name       VARCHAR      NOT NULL,
    pii_type         VARCHAR      NOT NULL,
    masking_method   VARCHAR      NOT NULL,
    detection_ts     TIMESTAMPTZ  NOT NULL,
    pipeline_mode    VARCHAR,
    record_count     INTEGER      NOT NULL DEFAULT 0
);
"""

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PIIAuditEntry:
    """
    One audit record per (pipeline_run × column × pii_type).

    Attributes
    ----------
    id             : UUID for the audit row — primary key in pii_audit_log.
    source_file_id : Identifies the pipeline run or data batch (e.g. a UUID
                     or "2024-QTR1").  Never contains raw PII.
    field_name     : DataFrame column where PII was detected.
    pii_type       : Category label: EXECUTIVE_NAME | SSN | EMAIL | PHONE | …
    masking_method : ``sha256`` for structured fields, ``regex_redact`` for text.
    detection_ts   : UTC ISO-8601 timestamp of detection.
    pipeline_mode  : ``mock`` or ``live`` — which pipeline produced this entry.
    record_count   : Number of rows that contained this PII type in this field.
    """
    id:             str = field(default_factory=lambda: str(uuid.uuid4()))
    source_file_id: str = ""
    field_name:     str = ""
    pii_type:       str = ""
    masking_method: str = "sha256"
    detection_ts:   str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    pipeline_mode:  str = "mock"
    record_count:   int = 0


@dataclass
class PIIConfig:
    """
    Runtime configuration for a masking pass.

    Attributes
    ----------
    salt              : Deterministic salt prepended to values before SHA-256
                        hashing.  Keep consistent across runs so the same name
                        always produces the same hash (enables right-to-erasure
                        re-masking by rotating the salt).
    pipeline_mode     : Recorded in audit entries ("mock" or "live").
    hash_columns      : Columns whose entire value is PII and should be hashed.
    scan_columns      : Free-text columns to scan with regex patterns.
    active_pii_types  : Subset of PII_PATTERNS keys to enable.  Omit types you
                        know can't appear in the data to reduce false positives.
    db_path           : DuckDB file path for writing the audit log.
    """
    salt:             str       = "gdpr-salt-v1"
    pipeline_mode:    str       = "mock"
    hash_columns:     list[str] = field(
        default_factory=lambda: ["executive_name"]
    )
    scan_columns:     list[str] = field(
        default_factory=lambda: ["root_cause_message", "internal_notes"]
    )
    active_pii_types: list[str] = field(
        default_factory=lambda: ["SSN", "EMAIL", "PHONE", "CREDIT_CARD"]
    )
    db_path:          Path      = field(
        default_factory=lambda: Path("backend/data_store/audit_warehouse.db")
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sha256_hash(value: Optional[str], salt: str) -> Optional[str]:
    """SHA-256 hash *value* with *salt*.  Returns None if input is None/NaN."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()


def _count_regex_matches(series: pd.Series, pattern: re.Pattern) -> int:
    """Count non-null values in *series* that contain at least one regex match."""
    non_null = series.dropna()
    if non_null.empty:
        return 0
    # Cast to bool explicitly before sum so the result is always numeric,
    # even on pandas 3.x where sum() on an empty object Series returns ''.
    matches: pd.Series = non_null.astype(str).apply(lambda v: bool(pattern.search(v)))
    return int(matches.sum())


def _redact_series(series: pd.Series, pattern: re.Pattern, pii_type: str) -> pd.Series:
    """Replace every regex match in *series* with a typed redaction placeholder."""
    placeholder = _REDACT_PLACEHOLDER.format(pii_type=pii_type)
    return series.apply(
        lambda v: pattern.sub(placeholder, str(v)) if pd.notna(v) else v
    )


# ---------------------------------------------------------------------------
# Public API — masking
# ---------------------------------------------------------------------------

def mask_dataframe(
    df: pd.DataFrame,
    source_file_id: str,
    config: Optional[PIIConfig] = None,
) -> tuple[pd.DataFrame, list[PIIAuditEntry]]:
    """
    Apply the two-pass PII masking strategy to *df* and return a masked copy
    together with a list of audit entries to persist.

    This function does **not** write to the database — call
    ``write_pii_audit_log(audit_entries, config)`` after this to persist the
    audit trail.

    Parameters
    ----------
    df             : Input Pandas DataFrame.  Not modified in place.
    source_file_id : Identifier for the pipeline run (UUID, quarter string, etc.)
    config         : PIIConfig controlling which columns/patterns to apply.
                     Defaults to PIIConfig() if omitted.

    Returns
    -------
    (masked_df, audit_entries)
        masked_df     — new DataFrame with PII replaced.
        audit_entries — list of PIIAuditEntry, one per detected (col × pii_type).
    """
    if config is None:
        config = PIIConfig()

    masked: pd.DataFrame      = df.copy()
    entries: list[PIIAuditEntry] = []
    now_ts = datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Pass 1: SHA-256 hash on structured PII columns
    # ------------------------------------------------------------------
    for col in config.hash_columns:
        if col not in masked.columns:
            logger.debug("hash_columns: '%s' absent from DataFrame — skipping.", col)
            continue

        non_null_count = int(masked[col].notna().sum())
        if non_null_count == 0:
            logger.debug("hash_columns: '%s' is entirely null — skipping.", col)
            continue

        masked[col] = masked[col].apply(lambda v: _sha256_hash(v, config.salt))

        entries.append(PIIAuditEntry(
            source_file_id = source_file_id,
            field_name     = col,
            pii_type       = "EXECUTIVE_NAME",
            masking_method = "sha256",
            detection_ts   = now_ts,
            pipeline_mode  = config.pipeline_mode,
            record_count   = non_null_count,
        ))
        logger.info(
            "[PII] sha256-masked '%s' | %d records | source=%s",
            col, non_null_count, source_file_id,
        )

    # ------------------------------------------------------------------
    # Pass 2: Regex scan + redact on free-text columns
    # ------------------------------------------------------------------
    active_patterns = {
        k: v for k, v in PII_PATTERNS.items() if k in config.active_pii_types
    }

    for col in config.scan_columns:
        if col not in masked.columns:
            logger.debug("scan_columns: '%s' absent from DataFrame — skipping.", col)
            continue

        for pii_type, pattern in active_patterns.items():
            hit_count = _count_regex_matches(masked[col], pattern)
            if hit_count == 0:
                continue

            masked[col] = _redact_series(masked[col], pattern, pii_type)

            entries.append(PIIAuditEntry(
                source_file_id = source_file_id,
                field_name     = col,
                pii_type       = pii_type,
                masking_method = "regex_redact",
                detection_ts   = now_ts,
                pipeline_mode  = config.pipeline_mode,
                record_count   = hit_count,
            ))
            # Log the field name and count — never the raw PII value
            logger.warning(
                "[PII] %s detected in '%s' | %d records redacted | source=%s. "
                "Field name logged; raw value never stored.",
                pii_type, col, hit_count, source_file_id,
            )

    logger.info(
        "[PII] Pass complete — %d audit entries | source=%s",
        len(entries), source_file_id,
    )
    return masked, entries


# ---------------------------------------------------------------------------
# Public API — audit schema
# ---------------------------------------------------------------------------

def initialize_pii_audit_schema(conn) -> None:
    """
    Creates the pii_audit_log table in *conn* if it does not already exist.
    Safe to call on every startup (idempotent).
    """
    conn.execute(PII_AUDIT_LOG_DDL)
    logger.debug("pii_audit_log schema ready.")


# ---------------------------------------------------------------------------
# Public API — audit log persistence
# ---------------------------------------------------------------------------

def write_pii_audit_log(
    entries: list[PIIAuditEntry],
    config: Optional[PIIConfig] = None,
) -> int:
    """
    Persists *entries* to the ``pii_audit_log`` table in the Gold DuckDB.

    The table is created automatically if it does not yet exist.  If the
    database file is locked (e.g. the dev server holds it open), a warning
    is logged and the function returns 0 without raising — audit logging
    should never interrupt the main ingestion path.

    Parameters
    ----------
    entries : Output of mask_dataframe().
    config  : PIIConfig carrying the db_path; defaults to PIIConfig().

    Returns
    -------
    Number of rows written (0 if nothing to write or DB unavailable).
    """
    if not entries:
        logger.debug("write_pii_audit_log: no entries to write.")
        return 0

    if config is None:
        config = PIIConfig()

    from backend.core_pipelines.db_client import DBConfig, get_connection  # lazy import

    rows = [
        (
            e.id, e.source_file_id, e.field_name, e.pii_type,
            e.masking_method, e.detection_ts, e.pipeline_mode, e.record_count,
        )
        for e in entries
    ]

    try:
        db_cfg = DBConfig(db_path=config.db_path)
        with get_connection(db_cfg) as conn:
            initialize_pii_audit_schema(conn)
            conn.executemany(
                """
                INSERT INTO pii_audit_log
                    (id, source_file_id, field_name, pii_type,
                     masking_method, detection_ts, pipeline_mode, record_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        logger.info(
            "[PII Audit] %d entries written to %s", len(rows), config.db_path
        )
        return len(rows)

    except Exception as exc:
        logger.warning(
            "[PII Audit] Could not write audit log to %s: %s — "
            "entries not persisted, pipeline continues.",
            config.db_path, exc,
        )
        return 0


# ---------------------------------------------------------------------------
# Standalone smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uuid as _uuid
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )

    # Build a tiny DataFrame with synthetic PII across all detection types
    test_df = pd.DataFrame({
        "executive_name": ["Alice Smith", "Bob Jones", None],
        "root_cause_message": [
            "Contact investor at alice@example.com for SOX review.",
            "Executive SSN 123-45-6789 flagged in Schedule A.",
            "No anomaly detected.",
        ],
        "ml_anomaly_score": [0.87, 0.91, 0.11],
    })

    cfg = PIIConfig(
        pipeline_mode  = "test",
        hash_columns   = ["executive_name"],
        scan_columns   = ["root_cause_message"],
        active_pii_types = ["SSN", "EMAIL", "PHONE", "CREDIT_CARD"],
    )

    run_id = str(_uuid.uuid4())
    masked, audit = mask_dataframe(test_df, source_file_id=run_id, config=cfg)

    print("\n=== Masked DataFrame ===")
    print(masked.to_string(index=False))

    print(f"\n=== Audit Entries ({len(audit)}) ===")
    for e in audit:
        print(f"  field={e.field_name!r:30s} pii_type={e.pii_type!r:20s} method={e.masking_method!r:14s} count={e.record_count}")

    print("\n(Skipping DB write in smoke test — no DuckDB file targeted.)")
