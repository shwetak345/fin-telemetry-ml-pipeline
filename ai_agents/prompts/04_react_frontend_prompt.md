# Prompt: React Compliance Dashboard for Financial Anomaly Display

## Role
Act as a senior Frontend Engineer with expertise in React, Tailwind CSS, and financial compliance UIs.

## Task
Generate a production-ready React dashboard that displays financial anomalies surfaced by the ML pipeline, enabling compliance officers to triage flagged filings.

## Prompt

```
You are a senior Frontend Engineer. Build a React compliance dashboard that:

1. **Displays a financial anomaly table** with the following columns:
   - Company Name
   - Filing Date
   - Revenue Growth (formatted as %)
   - Operating Cash Flow (formatted as $)
   - Known Rule Violation (badge: red "YES" / green "NO")
   - ML Anomaly Flag (badge: amber "FLAGGED" / grey "CLEAN")
   - ML Anomaly Score (progress bar, 0–1 scale, color-coded by severity)
   - Actions (View Details button)

2. **Implements filtering controls** above the table:
   - Search by company name (debounced input, 300ms)
   - Filter by ML Anomaly Flag (All / Flagged / Clean)
   - Filter by Known Rule Violation (All / Yes / No)
   - Date range picker (Filing Date from/to)

3. **Includes a summary stats bar** at the top:
   - Total filings reviewed
   - Flagged anomalies count (amber)
   - Known violations count (red)
   - Average anomaly score

4. **Uses mock data** matching the audit_triage schema:
   `{ id, company_name, filing_date, revenue_growth, operating_cash_flow,
      known_rule_violation, ml_anomaly_flag, ml_anomaly_score }`

5. **Styling requirements**:
   - Tailwind CSS only — no external UI libraries
   - Dark sidebar with light main content area
   - Responsive: mobile-first, collapses table to card view on <768px
   - Severity color scale: score ≥ 0.8 → red, 0.5–0.79 → amber, <0.5 → green

Use React 18, TypeScript, Tailwind CSS 3.x. Functional components and hooks only.
No Redux — local state with useState/useReducer. Include prop types for all components.
```

## Expected Component Structure

```
Dashboard.tsx
├── SummaryStatsBar.tsx       # Aggregate KPI cards
├── FilterControls.tsx        # Search + dropdowns + date range
├── AnomalyTable.tsx          # Sortable, filterable data table
│   └── AnomalyRow.tsx        # Single row with badges and score bar
├── AnomalyScoreBar.tsx       # Colour-coded 0–1 progress bar
├── StatusBadge.tsx           # Reusable YES/NO/FLAGGED/CLEAN pill
└── mockData.ts               # Typed mock records (10 rows minimum)
```

## Key Constraints

| Constraint | Requirement |
|---|---|
| State management | `useState` / `useReducer` only — no external state lib |
| Filtering logic | Client-side only; all filters compose with AND logic |
| Score bar colours | Red ≥ 0.8 · Amber 0.5–0.79 · Green < 0.5 |
| Accessibility | `aria-label` on badges, table `scope` attributes, keyboard-navigable filters |
| Data shape | Mirrors `audit_triage` DuckDB schema exactly |

## Follow-up Refinements

- Replace mock data with a `useFetch` hook hitting a FastAPI `/audit-records` endpoint
- Add column sorting (click header to toggle asc/desc)
- Export filtered results to CSV via `Blob` + `URL.createObjectURL`
- Add a detail drawer/modal showing full filing metadata on row click
