# FinTelemetry: Bug Tracking & Improvements

## 1. UI Theme Consistency
- **Issue**: Current layout is dark-themed, needs to match a cleaner "token-aware-dashboard" light style.
- **Prompt**: "Act as a Frontend Engineer. Refactor the Tailwind CSS styling inside `frontend/src/Dashboard.jsx` to use a clean light-mode theme. Change the main layout background to a crisp white/light gray (#FAFAFA or bg-slate-50), update typography to deep slate for contrast, and ensure sidebar/cards have soft shadows."

## 2. Broken Sidebar Navigation
- **Issue**: Filings, Reports, and Settings links in the sidebar are non-functional.
- **Prompt**: "Act as a Frontend Engineer. Update `frontend/src/Dashboard.jsx` so sidebar links (Dashboard, Filings, Reports, Settings) are functional using `useState` to track the active view. Add placeholder layouts: 'Filings' (pending submissions), 'Reports' (PDF download cards), and 'Settings' (notification toggles)."

## 3. Incomplete Triage Workflow
- **Issue**: "Investigate" button triggers a basic alert instead of a functional workflow.
- **Prompt**: "Act as a Frontend Engineer. Upgrade `frontend/src/Dashboard.jsx` to make the 'Investigate' button open a side drawer. Display detailed metadata (Anomaly Score, Ingestion Timestamp), change Status to 'In Progress', and add a 'Mark as Resolved' button that removes the violation from the queue."

## 4. Realistic Data Distribution
- **Issue**: All records are currently flagged as ML anomalies, lacking a realistic distribution.
- **Prompt**: "Update `backend/core_pipelines/mock_data.py` for realistic distribution: 5% `known_rule_violation=True`, 15% `ml_anomaly_flag=True`, and 80% healthy. Add a `status` field: 'Pending' by default, 'Resolved' for healthy."

## 5. Metric Calculation Logic
- **Issue**: Metric counters change incorrectly when switching filters between "Needs Review" and "All".
- **Prompt**: "Fix bug in `src/Dashboard.jsx` where metric counters change based on filter. Calculate `totalViolations` and `totalAnomalies` by filtering the **full** data array, not the displayData array, so counters remain consistent across views."

## 6. Investigation Data Clarity
- **Issue**: Root cause analysis is repetitive and generic across records.
- **Prompt**: "Update `backend/core_pipelines/mock_data.py` to generate dynamic Root Cause Analysis messages. For rule violations, cite specific reasons (e.g., 'Missing CIK'). For ML anomalies, cite top-contributing features (e.g., 'Revenue Growth'). Ensure unique, context-specific reasons for every alert."

## 7. Filings Tab Functionality
- **Issue**: Filings tab lacks sort, pagination, and cross-tab linking.
- **Prompt**: "Improve 'Filings' tab: 1) Add click-to-sort for 'Triage Status' and 'Issue Type'. 2) Implement 10-row pagination. 3) Enable cross-tab linking (clicking a record in 'Filings' should open the Investigation modal or scroll to the record in 'Dashboard' using URL parameters like ?filingId=123)."

## 8. Metric Aggregation & Table Sorting
- **Issue**: 'Needs Review' counter incorrectly displays 47 ML anomalies instead of 7. 'Issue Type' column is not sortable.
- **Prompt**: "Fix metric logic to strictly filter by flag status (ml_anomaly_flag / known_rule_violation) and implement click-to-sort functionality for the 'Issue Type' header in both the Triage and Filings tables."

## 9. Universal Table Sorting
- **Issue**: Columns in both Dashboard and Filings tabs lack sorting, and 'Company Name' is missing from the Dashboard view.
- **Prompt**: "Implement universal column sorting (▲/▼) for all headers in both the Triage Queue and Filings Registry. Add 'Company Name' to the Dashboard view, ensuring it is sortable alongside Filing Date, Issue Type, and Status."

## 10. Dashboard Triage Schema Refactor
- **Issue**: Dashboard requires specific triage columns (Company, Status, Severity, Root Cause, Assignee, Timer).
- **Prompt**: "Implement new dashboard schema: [Company Name, Status, Severity Score, Root Cause, Assignee, Timer]. Enable sorting for all columns and apply 'table-fixed' layout with truncated text for Root Cause and colored badges for Status."

## 11: PII Audit Traceability Gap
- **Issue**: System processes PII data but does not maintain a lineage or audit log of where PII was detected or the source file identity.
- **Status**: Open
- **Priority**: High
- **Description**: Current masking is 'blind'. We need to log PII detection events with `source_file_id` to ensure compliance and auditability.
- **Fix Path**: Implement `pii_utils.py` with logging and integrate into both Mock and Live ingestion pipelines.

## 12: Dashboard Data Synchronization Mismatch
- **Issue**: High-level metrics on the Dashboard view were static and did not match the granular filing data.
- **Status**: Updated
- **Description**: Migrated metric calculation logic to be derived directly from the filings dataset.
- **Resolution**: Consolidating metrics into the Filings tab to declutter the main dashboard view, using a dynamic MetricsSummary component to ensure a single source of truth and improve UI hierarchy.