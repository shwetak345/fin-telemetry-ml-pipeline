"""
Mock SEC EDGAR filing records for local pipeline development and testing.
All PII fields contain synthetic data only.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

_SEED = 42  # Fixed seed keeps output deterministic across runs

_COMPANY_SUFFIXES = ["Inc.", "LLC", "Corp.", "Group", "Partners", "Capital", "Fund", "Advisors"]
_COMPANY_PREFIXES = [
    "Apex", "Meridian", "Quantum", "Vantage", "Orion", "Stratos", "Pinnacle",
    "Atlas", "Nexus", "Harbor", "Crestview", "Ironbridge", "Summit", "Solaris",
    "Evergreen", "Bluerock", "Cardinal", "Delphi", "Fairfield", "Granite",
    "Halcyon", "Indigo", "Jasper", "Keystone", "Lynwood", "Mosaic", "Northgate",
    "Obsidian", "Pacific", "Quorum", "Redwood", "Sterling", "Titan", "Unified",
]

_EXECUTIVE_FIRST = [
    "Jane", "John", "Alice", "Robert", "Sandra", "Michael", "Patricia", "David",
    "Laura", "James", "Emily", "William", "Sarah", "Richard", "Karen", "Thomas",
    "Megan", "Charles", "Jessica", "Daniel",
]
_EXECUTIVE_LAST = [
    "Doe", "Smith", "Chen", "Miles", "Park", "Johnson", "Williams", "Brown",
    "Taylor", "Anderson", "Harris", "Martin", "Thompson", "Garcia", "Martinez",
    "Robinson", "Clark", "Rodriguez", "Lewis", "Lee",
]

_TITLES     = ["CEO", "CFO", "COO", "CRO", "President", "Managing Director", "General Counsel"]
_FORM_TYPES = ["10-K", "10-Q", "8-K", "DEF14A", "S-1", "20-F"]

_REVENUE_BUCKETS = [
    Decimal("50000000.00"),
    Decimal("120000000.00"),
    Decimal("340000000.00"),
    Decimal("670000000.00"),
    Decimal("920000000.00"),
    Decimal("1200000000.00"),
    Decimal("2500000000.00"),
    Decimal("4800000000.00"),
    Decimal("9100000000.00"),
    Decimal("25000000000.00"),
]

_FILING_START = date(2023, 1, 1)
_FILING_END   = date(2026, 6, 7)

# ---------------------------------------------------------------------------
# Root cause message templates
# ---------------------------------------------------------------------------

_VIOLATION_REASONS = [
    "Missing CIK identifier in the filing header — submission rejected by EDGAR validation.",
    "Filing submitted past the 48-hour grace period; late filing triggers automatic SEC review.",
    "Balance sheet reconciliation error in Schedule A: total assets do not match reported liabilities.",
    "Undisclosed related-party transaction in footnote 12 violates Regulation S-K Item 404.",
    "Revenue recognition policy change applied retroactively without required restatement disclosure.",
    "Executive compensation table omits non-cash equity awards in violation of Item 402 of Reg S-K.",
]

_ANOMALY_REASON_TEMPLATES = [
    "Revenue growth of {growth_pct}% is {sigma:.1f} standard deviations above the sector mean — possible premature recognition.",
    "Operating cash flow ratio of {ocf_ratio:.2f} is inconsistent with {quarters} consecutive historical quarters.",
    "Filing frequency increased by {freq_delta}x in the past 12 months without a corresponding M&A event.",
    "Revenue-to-cash-flow divergence of {divergence:.1f}% exceeds the 2σ threshold for this sector peer group.",
    "Accrual ratio of {accrual_ratio:.2f} signals earnings quality concern: cash flow materially lags net income.",
    "Gross margin compression of {margin_drop:.1f}pp detected within a single quarter — atypical for peer cohort.",
]

# ---------------------------------------------------------------------------
# Flag distribution across 50 records
#   ~5%  →  3 records  : known_rule_violation = True
#   ~15% →  7 records  : ml_anomaly_flag = True
#   ~80% → 40 records  : both False  (Healthy)
# Uses a separate RNG so record-level generation remains unchanged.
# ---------------------------------------------------------------------------
_cat_rng    = random.Random(_SEED + 1)
_all_idx    = list(range(1, 51))
_cat_rng.shuffle(_all_idx)
_VIOLATION_IDS = set(_all_idx[:3])   # 3 / 50 = 6 % ≈ 5 %
_ANOMALY_IDS   = set(_all_idx[3:10]) # 7 / 50 = 14 % ≈ 15 %
# indices 10-49 → healthy (80 %)


def _category(i: int) -> str:
    if i in _VIOLATION_IDS:
        return "violation"
    if i in _ANOMALY_IDS:
        return "anomaly"
    return "healthy"


def _anomaly_score(category: str, rng: random.Random) -> float:
    if category == "violation":
        return round(rng.uniform(0.75, 0.95), 4)
    if category == "anomaly":
        return round(rng.uniform(0.50, 0.84), 4)
    return round(rng.uniform(0.00, 0.30), 4)


def _random_date(rng: random.Random) -> date:
    delta = (_FILING_END - _FILING_START).days
    return _FILING_START + timedelta(days=rng.randint(0, delta))


def _filing_id(index: int) -> str:
    return f"0001193125-24-{index:06d}"


def _cik(index: int) -> str:
    return f"{(index * 1234567) % 10_000_000:010d}"


def _root_cause_message(
    cat: str,
    score: float,
    revenue: "Decimal | None",
    rng: random.Random,
) -> "str | None":
    if cat == "violation":
        return rng.choice(_VIOLATION_REASONS)
    if cat == "anomaly":
        template = rng.choice(_ANOMALY_REASON_TEMPLATES)
        ocf_val  = float(revenue) if revenue is not None else 1e9
        return template.format(
            growth_pct  = round(rng.uniform(28, 95), 1),
            sigma       = round(rng.uniform(2.8, 4.5), 1),
            ocf_ratio   = round(ocf_val / 1e10, 3),
            quarters    = rng.randint(4, 12),
            freq_delta  = round(rng.uniform(1.8, 4.2), 1),
            divergence  = round(rng.uniform(18, 47), 1),
            accrual_ratio = round(score * rng.uniform(1.1, 1.6), 3),
            margin_drop = round(rng.uniform(4.5, 18.0), 1),
        )
    return None


def get_mock_sec_filings() -> list[dict]:
    """
    Returns 50 synthetic SEC EDGAR filing records generated with a fixed random seed.

    Flag distribution (deterministic):
        ~5%  (3 records)  — known_rule_violation=True,  ml_anomaly_flag=False  → status='Pending'
        ~15% (7 records)  — ml_anomaly_flag=True,       known_rule_violation=False → status='Pending'
        ~80% (40 records) — both False                                          → status='Resolved'

    Guaranteed keys on every record:
        filing_id, revenue_usd, executive_name, cik, company_name, filing_date, form_type,
        known_rule_violation, ml_anomaly_flag, ml_anomaly_score, status, root_cause_message.

    Spark-schema keys (RAW_SCHEMA):
        executive_title, internal_notes, raw_submission_xml, submitter_email.
    """
    rng = random.Random(_SEED)
    # Independent RNGs so each concern doesn't perturb the others
    score_rng = random.Random(_SEED + 2)
    msg_rng   = random.Random(_SEED + 3)
    records = []

    for i in range(1, 51):
        prefix  = rng.choice(_COMPANY_PREFIXES)
        suffix  = rng.choice(_COMPANY_SUFFIXES)
        company = f"{prefix} {suffix}"

        has_exec   = rng.random() > 0.20
        exec_name  = f"{rng.choice(_EXECUTIVE_FIRST)} {rng.choice(_EXECUTIVE_LAST)}" if has_exec else None
        exec_title = rng.choice(_TITLES) if has_exec else None

        form_type   = rng.choice(_FORM_TYPES)
        has_revenue = form_type in ("10-K", "10-Q", "20-F", "S-1") or rng.random() > 0.6
        revenue     = rng.choice(_REVENUE_BUCKETS) if has_revenue else None

        cat                   = _category(i)
        known_rule_violation  = cat == "violation"
        ml_anomaly_flag       = cat == "anomaly"
        ml_anomaly_score      = _anomaly_score(cat, score_rng)
        status                = "Resolved" if cat == "healthy" else "Pending"
        root_cause_message    = _root_cause_message(cat, ml_anomaly_score, revenue, msg_rng)

        records.append({
            # Spark RAW_SCHEMA fields
            "filing_id":          _filing_id(i),
            "form_type":          form_type,
            "filing_date":        _random_date(rng),
            "company_name":       company,
            "cik":                _cik(i),
            "executive_name":     exec_name,
            "executive_title":    exec_title,
            "revenue_usd":        revenue,
            "internal_notes":     None,
            "raw_submission_xml": None,
            "submitter_email":    None,
            # Compliance flag fields (passed through to DuckDB via pandas)
            "known_rule_violation": known_rule_violation,
            "ml_anomaly_flag":      ml_anomaly_flag,
            "ml_anomaly_score":     ml_anomaly_score,
            "status":               status,
            "root_cause_message":   root_cause_message,
        })

    return records
