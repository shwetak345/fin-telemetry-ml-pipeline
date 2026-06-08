# Prompt: PySpark SEC EDGAR Ingestion Script with PII Masking (GDPR)

## Role
Act as a senior Data Engineer with expertise in PySpark, financial data pipelines, and GDPR compliance.

## Task
Generate a production-ready PySpark script that ingests SEC EDGAR filings and applies PII masking to ensure GDPR compliance.

## Prompt

```
You are a senior Data Engineer. Write a PySpark script that:

1. **Ingests SEC EDGAR data** from the bulk data endpoint (https://www.sec.gov/Archives/edgar/full-index/).
   - Download quarterly index files (company.idx, form.idx)
   - Parse 10-K, 10-Q, and 8-K filings
   - Store raw data in a Bronze Delta Lake table

2. **Detects and masks PII** before writing to Silver layer:
   - Mask: full names, email addresses, phone numbers, SSNs, addresses
   - Use SHA-256 hashing for deterministic masking of identifiers
   - Apply regex-based redaction for free-text fields
   - Log all masking operations with field name and record ID (never log raw PII)

3. **Applies GDPR controls**:
   - Tag masked columns with metadata: `{"pii": true, "masking": "sha256"}`
   - Partition output by `filing_date` and `form_type`
   - Include a `data_lineage` struct column: `{source, ingestion_ts, masking_version}`

4. **Schema**:
   - Bronze: raw fields as ingested (string types)
   - Silver: typed fields + masked PII columns suffixed `_masked`

5. **Output**: Delta Lake tables at `s3://your-bucket/sec-edgar/{bronze,silver}/`

Use PySpark 3.x, Delta Lake 2.x. Include type hints, docstrings, and a `if __name__ == "__main__"` entry point.
```

## Expected Output Structure

```
sec_edgar_ingestion.py
├── ingest_edgar_index()      # Downloads and parses EDGAR index files
├── detect_pii_columns()      # Identifies PII fields via regex + schema hints
├── mask_pii()                # Applies SHA-256 / redaction transformations
├── write_bronze()            # Writes raw data to Bronze Delta table
├── write_silver()            # Writes masked, typed data to Silver Delta table
└── main()                    # Orchestrates the pipeline
```

## Key Constraints

| Constraint | Requirement |
|---|---|
| PII masking method | SHA-256 (deterministic) or regex redaction |
| GDPR right to erasure | Masking key stored separately; supports re-masking |
| Logging | Mask field names only — never raw PII values |
| Partitioning | `filing_date` (YYYY-MM) + `form_type` |
| Format | Delta Lake (ACID, schema enforcement) |

## Follow-up Refinements

- Add Spark Structured Streaming support for near-real-time ingestion
- Integrate with AWS Glue Data Catalog for schema registration
- Parameterize masking salt via AWS Secrets Manager
