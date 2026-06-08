import { useState, useEffect } from "react";

// ---------------------------------------------------------------------------
// URL helpers
// ---------------------------------------------------------------------------

function getUrlParams() {
  const p = new URLSearchParams(window.location.search);
  return { tab: p.get("tab") ?? "Dashboard", filingId: p.get("filingId") };
}

function setUrlParams(tab, filingId) {
  const p = new URLSearchParams();
  p.set("tab", tab);
  if (filingId) p.set("filingId", String(filingId));
  window.history.replaceState({}, "", `?${p}`);
}

// ---------------------------------------------------------------------------
// Static reference data
// ---------------------------------------------------------------------------

const REPORTS = [
  { id: "r1", title: "Q1 2024 SOX Compliance Report",      date: "2024-04-15", size: "1.2 MB" },
  { id: "r2", title: "Q2 2024 ML Anomaly Summary",         date: "2024-07-10", size: "840 KB" },
  { id: "r3", title: "Annual EDGAR Audit Trail 2023",      date: "2024-01-20", size: "3.8 MB" },
  { id: "r4", title: "ASC 606 Revenue Recognition Review", date: "2024-06-01", size: "560 KB" },
];

const NAV_ITEMS = ["Dashboard", "Filings", "Reports", "Settings"];

// ---------------------------------------------------------------------------
// Shared UI primitives
// ---------------------------------------------------------------------------

function SectionHeader({ title, subtitle }) {
  return (
    <div className="mb-8">
      <h1 className="text-2xl font-bold tracking-tight text-slate-800">{title}</h1>
      {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
    </div>
  );
}

function Card({ children, className = "" }) {
  return (
    <div className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>
      {children}
    </div>
  );
}

function Spinner() {
  return (
    <div className="flex items-center justify-center py-20">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-200 border-t-indigo-600" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared sort infrastructure
// ---------------------------------------------------------------------------

const SEVERITY_SORT = { violation: 0, anomaly: 1, healthy: 2 };
const STATUS_SORT   = { "Needs Review": 0, "In Progress": 1, "Resolved": 2 };

function parseAgeToHours(age) {
  if (!age || age === "—") return 0;
  if (age.endsWith("h")) return parseInt(age, 10);
  if (age.endsWith("d")) return parseInt(age, 10) * 24;
  return 0;
}

function compareRows(a, b, col) {
  switch (col) {
    case "company":      return a.company.localeCompare(b.company);
    case "formType":     return a.formType.localeCompare(b.formType);
    case "filingDate":   return a.filingDate.localeCompare(b.filingDate);
    case "issueType":    return (SEVERITY_SORT[a.severity] ?? 9) - (SEVERITY_SORT[b.severity] ?? 9);
    case "status":       return (STATUS_SORT[a.status] ?? 9) - (STATUS_SORT[b.status] ?? 9);
    case "anomalyScore": return (a.mlTelemetry?.anomalyScore ?? 0) - (b.mlTelemetry?.anomalyScore ?? 0);
    case "rootCause":    return (a.violationDetails ?? "").localeCompare(b.violationDetails ?? "");
    case "assignee":     return (a.assignee ?? "").localeCompare(b.assignee ?? "");
    case "alertAge":     return parseAgeToHours(a.alertAge) - parseAgeToHours(b.alertAge);
    default:             return 0;
  }
}

function useSortableData(data) {
  const [sort, setSort] = useState({ col: null, dir: "asc" });

  const sorted = sort.col
    ? [...data].sort((a, b) => {
        const cmp = compareRows(a, b, sort.col);
        return sort.dir === "asc" ? cmp : -cmp;
      })
    : data;

  function requestSort(col) {
    setSort((prev) =>
      prev.col === col
        ? { col, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { col, dir: "asc" }
    );
  }

  return { sorted, sort, requestSort };
}

function SortIcon({ active, dir }) {
  if (!active) {
    return (
      <span
        className="ml-1.5 inline-flex flex-col gap-[1px] text-[7px] leading-none text-slate-300 select-none"
        aria-hidden="true"
      >
        <span>▲</span><span>▼</span>
      </span>
    );
  }
  return (
    <span
      className="ml-1.5 text-[10px] leading-none text-indigo-500 select-none"
      aria-hidden="true"
    >
      {dir === "asc" ? "▲" : "▼"}
    </span>
  );
}

function SortableHeader({ label, col, sort, onSort }) {
  const active = sort.col === col;
  return (
    <th
      scope="col"
      onClick={() => onSort(col)}
      aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
      className={`cursor-pointer select-none px-4 py-3 text-left font-semibold transition-colors hover:bg-slate-100 hover:text-indigo-600 ${
        active ? "text-indigo-600" : ""
      }`}
    >
      <span className="inline-flex items-center">
        {label}
        <SortIcon active={active} dir={sort.dir} />
      </span>
    </th>
  );
}

const ROWS_PER_PAGE = 10;

function Pagination({ currentPage, totalPages, onPrev, onNext }) {
  return (
    <div className="mt-4 flex items-center justify-between">
      <button
        onClick={onPrev}
        disabled={currentPage === 1}
        className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40 focus:outline-none focus:ring-2 focus:ring-indigo-400"
      >
        ← Previous
      </button>
      <span className="text-xs text-slate-500">
        Page <span className="font-semibold text-slate-700">{currentPage}</span> of{" "}
        <span className="font-semibold text-slate-700">{totalPages}</span>
      </span>
      <button
        onClick={onNext}
        disabled={currentPage === totalPages}
        className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40 focus:outline-none focus:ring-2 focus:ring-indigo-400"
      >
        Next →
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Investigate drawer
// ---------------------------------------------------------------------------

function ScoreBar({ score }) {
  const pct   = Math.round(score * 100);
  const color = score >= 0.8 ? "bg-red-500" : score >= 0.5 ? "bg-yellow-400" : "bg-emerald-500";
  return (
    <div className="mt-1 flex items-center gap-3">
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-right text-xs font-semibold tabular-nums text-slate-600">
        {score.toFixed(2)}
      </span>
    </div>
  );
}

function DrawerMetaRow({ label, value }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs font-medium uppercase tracking-widest text-slate-400">{label}</span>
      <span className="text-sm font-medium text-slate-700">{value}</span>
    </div>
  );
}

function InvestigateDrawer({ record, onClose, onResolve }) {
  const isOpen = record !== null;
  const ml     = record?.mlTelemetry;

  return (
    <>
      <div
        onClick={onClose}
        aria-hidden="true"
        className={`fixed inset-0 z-40 bg-slate-900/30 backdrop-blur-sm transition-opacity duration-300 ${
          isOpen ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Investigation details"
        className={`fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col bg-white shadow-2xl transition-transform duration-300 ease-in-out ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {!record ? null : (
          <>
            <div className="flex items-start justify-between border-b border-slate-200 px-6 py-5">
              <div>
                <p className="text-xs font-semibold uppercase tracking-widest text-indigo-600">Investigation</p>
                <h2 className="mt-0.5 text-lg font-bold text-slate-800">{record.company}</h2>
                <div className="mt-2 flex items-center gap-2">
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-0.5 text-xs font-semibold text-amber-700 ring-1 ring-amber-300">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
                    In Progress
                  </span>
                  <span className={`inline-block rounded-full px-3 py-0.5 text-xs font-semibold ${
                    record.severity === "violation"
                      ? "bg-red-50 text-red-700 ring-1 ring-red-300"
                      : "bg-yellow-50 text-yellow-700 ring-1 ring-yellow-300"
                  }`}>
                    {record.issueType}
                  </span>
                </div>
              </div>
              <button
                onClick={onClose}
                aria-label="Close panel"
                className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
              >
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
              <section>
                <h3 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400">Filing Metadata</h3>
                <div className="grid grid-cols-2 gap-4 rounded-xl border border-slate-100 bg-slate-50 p-4">
                  <DrawerMetaRow label="CIK"         value={record.cik}        />
                  <DrawerMetaRow label="Form Type"   value={record.formType}   />
                  <DrawerMetaRow label="Filing Date" value={record.filingDate} />
                  <div className="flex flex-col gap-0.5">
                    <span className="text-xs font-medium uppercase tracking-widest text-slate-400">Revenue</span>
                    {record.revenue
                      ? <span className="text-sm font-medium text-slate-700">{record.revenue}</span>
                      : <span className="text-sm italic text-slate-400">Data Unavailable</span>}
                  </div>
                </div>
              </section>

              <section>
                <h3 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400">ML Telemetry</h3>
                <div className="space-y-4 rounded-xl border border-slate-100 bg-slate-50 p-4">
                  <div>
                    <DrawerMetaRow label="Anomaly Score" value="" />
                    <ScoreBar score={ml.anomalyScore} />
                    <p className="mt-1 text-xs text-slate-400">95% CI: {ml.confidenceInterval}</p>
                  </div>
                  <DrawerMetaRow label="Isolation Forest Cluster" value={ml.isolationCluster} />
                  <DrawerMetaRow label="Model Version"            value={ml.modelVersion}      />
                  <DrawerMetaRow label="Data Ingestion Timestamp" value={ml.ingestionTs}       />
                </div>
              </section>

              <section>
                <h3 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400">Root Cause Analysis</h3>
                <div className="rounded-xl border border-slate-100 bg-slate-50 p-4">
                  {record.knownRuleViolation && record.violationDetails ? (
                    <div className="flex gap-3">
                      <div className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-100 text-red-600">
                        <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
                        </svg>
                      </div>
                      <div>
                        <p className="text-xs font-bold text-red-700">Compliance Alert</p>
                        <p className="mt-1 text-xs leading-relaxed text-slate-600">{record.violationDetails}</p>
                      </div>
                    </div>
                  ) : record.mlAnomalyFlag ? (() => {
                    const entries     = Object.entries(ml.featureContrib);
                    const topFeature  = entries.sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0];
                    const featureName = topFeature[0].replace(/([A-Z])/g, " $1").trim();
                    const featureVal  = topFeature[1];
                    return (
                      <div className="flex gap-3">
                        <div className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-yellow-100 text-yellow-600">
                          <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-11.25a.75.75 0 00-1.5 0v4.5a.75.75 0 001.5 0v-4.5zm-.75 7a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
                          </svg>
                        </div>
                        <div>
                          <p className="text-xs font-bold text-yellow-700">ML Signal Detected</p>
                          {record.violationDetails && (
                            <p className="mt-1 text-xs leading-relaxed text-slate-600">{record.violationDetails}</p>
                          )}
                          <p className="mt-2 text-xs text-slate-500">
                            Top driver: <span className="font-semibold capitalize">{featureName}</span>
                            {" "}(contribution:{" "}
                            <span className={`font-semibold tabular-nums ${featureVal >= 0 ? "text-red-600" : "text-emerald-600"}`}>
                              {featureVal >= 0 ? "+" : ""}{featureVal.toFixed(3)}
                            </span>)
                          </p>
                        </div>
                      </div>
                    );
                  })() : (
                    <div className="flex gap-3">
                      <div className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                        <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clipRule="evenodd" />
                        </svg>
                      </div>
                      <div>
                        <p className="text-xs font-bold text-emerald-700">No Issues Detected</p>
                        <p className="mt-1 text-xs leading-relaxed text-slate-600">
                          This filing shows no rule violations or ML-flagged anomalies. No further action required.
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              </section>

              <section>
                <h3 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400">Top Feature Contributions</h3>
                <div className="space-y-3 rounded-xl border border-slate-100 bg-slate-50 p-4">
                  {Object.entries(ml.featureContrib).map(([feat, val]) => {
                    const pct   = Math.min(Math.abs(val) * 100, 100);
                    const isPos = val >= 0;
                    return (
                      <div key={feat}>
                        <div className="flex items-center justify-between text-xs text-slate-600">
                          <span className="font-medium capitalize">{feat.replace(/([A-Z])/g, " $1")}</span>
                          <span className={`font-semibold tabular-nums ${isPos ? "text-red-600" : "text-emerald-600"}`}>
                            {isPos ? "+" : ""}{val.toFixed(3)}
                          </span>
                        </div>
                        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
                          <div className={`h-full rounded-full ${isPos ? "bg-red-400" : "bg-emerald-400"}`} style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            </div>

            <div className="flex items-center gap-3 border-t border-slate-200 px-6 py-4">
              <button
                onClick={() => onResolve(record.id)}
                className="flex-1 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-700 focus:outline-none focus:ring-2 focus:ring-emerald-400 focus:ring-offset-2"
              >
                Mark as Resolved
              </button>
              <button
                onClick={onClose}
                className="flex-1 rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-semibold text-slate-600 transition hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-slate-300"
              >
                Close
              </button>
            </div>
          </>
        )}
      </aside>
    </>
  );
}

// ---------------------------------------------------------------------------
// Shared badge primitives
// ---------------------------------------------------------------------------

function IssueBadge({ issueType, severity }) {
  const styles =
    severity === "violation" ? "bg-red-50 text-red-700 ring-1 ring-red-300"
    : severity === "anomaly" ? "bg-yellow-50 text-yellow-700 ring-1 ring-yellow-300"
    : "bg-slate-100 text-slate-500 ring-1 ring-slate-200";
  return (
    <span className={`inline-block rounded-full px-3 py-0.5 text-xs font-semibold ${styles}`}>
      {issueType}
    </span>
  );
}

// Three-tier status: Needs Review (yellow) · In Progress (blue) · Resolved (green)
function StatusBadge({ status }) {
  const styles = {
    "Needs Review": "bg-yellow-50 text-yellow-700 ring-1 ring-yellow-300",
    "In Progress":  "bg-blue-50 text-blue-700 ring-1 ring-blue-300",
    "Resolved":     "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
  }[status] ?? "bg-slate-100 text-slate-500 ring-1 ring-slate-200";
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${styles}`}>
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Dashboard view
// ---------------------------------------------------------------------------

function StatCard({ label, value, accent }) {
  const accentMap = {
    neutral: "border-slate-400 text-slate-700",
    red:     "border-red-500 text-red-600",
    yellow:  "border-yellow-400 text-yellow-600",
  };
  return (
    <div className={`flex flex-col gap-1 rounded-xl border border-slate-200 border-l-4 bg-white px-6 py-4 shadow-sm ${accentMap[accent]}`}>
      <span className="text-2xl font-bold tracking-tight">{value.toLocaleString()}</span>
      <span className="text-xs font-medium uppercase tracking-widest text-slate-400">{label}</span>
    </div>
  );
}

// Coloured dot + numeric score
function SeverityScore({ score }) {
  const dot  = score >= 0.8 ? "bg-red-500" : score >= 0.5 ? "bg-yellow-400" : "bg-emerald-400";
  const text = score >= 0.8 ? "text-red-700" : score >= 0.5 ? "text-yellow-700" : "text-emerald-700";
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2 w-2 shrink-0 rounded-full ${dot}`} aria-hidden="true" />
      <span className={`tabular-nums font-semibold ${text}`}>{score.toFixed(2)}</span>
    </span>
  );
}

// Avatar initials + name
function AssigneeCell({ assignee }) {
  if (!assignee) return <span className="text-slate-300 text-xs">—</span>;
  const initials = assignee.split(" ").map((w) => w[0]).join("").toUpperCase();
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[9px] font-bold text-indigo-700">
        {initials}
      </span>
      <span className="truncate text-xs text-slate-700">{assignee}</span>
    </span>
  );
}

// Age of alert — turns red at ≥ 2 days
function AlertAgeCell({ alertAge }) {
  if (!alertAge) return <span className="text-slate-300 text-xs">—</span>;
  const urgent = alertAge.endsWith("d") && parseInt(alertAge, 10) >= 2;
  return (
    <span className={`tabular-nums text-xs font-semibold ${urgent ? "text-red-600" : "text-slate-500"}`}>
      {alertAge}
    </span>
  );
}

// High-utility triage table — table-fixed with defined column widths
function TriageTable({ rows, sort, onSort, onInvestigate }) {
  return (
    <Card>
      <div className="overflow-x-auto">
        <table className="min-w-full table-fixed text-sm text-slate-700">
          <colgroup>
            <col style={{ width: "21%" }} />
            <col style={{ width: "11%" }} />
            <col style={{ width: "10%" }} />
            <col style={{ width: "27%" }} />
            <col style={{ width: "13%" }} />
            <col style={{ width: "9%"  }} />
            <col style={{ width: "9%"  }} />
          </colgroup>
          <thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500">
            <tr>
              <SortableHeader label="Company"    col="company"      sort={sort} onSort={onSort} />
              <SortableHeader label="Status"     col="status"       sort={sort} onSort={onSort} />
              <SortableHeader label="Severity"   col="anomalyScore" sort={sort} onSort={onSort} />
              <SortableHeader label="Root Cause" col="rootCause"    sort={sort} onSort={onSort} />
              <SortableHeader label="Assignee"   col="assignee"     sort={sort} onSort={onSort} />
              <SortableHeader label="Age"        col="alertAge"     sort={sort} onSort={onSort} />
              <th scope="col" className="px-4 py-3 text-left font-semibold">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {rows.map((row) => (
              <tr key={row.id} className="transition hover:bg-slate-50">
                {/* Company + sub-line */}
                <td className="px-4 py-3">
                  <div className="truncate font-medium text-slate-800">{row.company}</div>
                  <div className="truncate text-xs text-slate-400">
                    {row.formType} · {row.filingDate}
                  </div>
                </td>

                {/* Status badge */}
                <td className="px-4 py-3">
                  <StatusBadge status={row.status} />
                </td>

                {/* Severity score with coloured dot */}
                <td className="px-4 py-3">
                  <SeverityScore score={row.mlTelemetry.anomalyScore} />
                </td>

                {/* Root cause — truncated, full text in tooltip */}
                <td className="max-w-0 px-4 py-3">
                  <p
                    className="truncate text-xs text-slate-600"
                    title={row.violationDetails ?? ""}
                  >
                    {row.violationDetails ?? <span className="text-slate-300">—</span>}
                  </p>
                </td>

                {/* Assignee avatar */}
                <td className="px-4 py-3">
                  <AssigneeCell assignee={row.assignee} />
                </td>

                {/* Age of alert */}
                <td className="px-4 py-3">
                  <AlertAgeCell alertAge={row.alertAge} />
                </td>

                {/* Action */}
                <td className="px-4 py-3">
                  <button
                    onClick={() => onInvestigate(row)}
                    className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:ring-offset-1"
                  >
                    View
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function FilterBar({ filter, onFilterChange }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <input
        type="text"
        placeholder="Search company…"
        value={filter.search}
        onChange={(e) => onFilterChange({ ...filter, search: e.target.value })}
        className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 placeholder-slate-400 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
      />
      <select
        value={filter.severity}
        onChange={(e) => onFilterChange({ ...filter, severity: e.target.value })}
        className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
      >
        <option value="all">All Issues</option>
        <option value="violation">Violations Only</option>
        <option value="anomaly">Anomalies Only</option>
      </select>
    </div>
  );
}

function PriorityFilterBar({ value, onChange }) {
  const options = [
    { key: "needs-review", label: "Needs Review" },
    { key: "all",          label: "All Records"  },
  ];
  return (
    <div className="inline-flex rounded-lg border border-slate-200 bg-white shadow-sm" role="group" aria-label="Priority filter">
      {options.map(({ key, label }) => (
        <button
          key={key}
          onClick={() => onChange(key)}
          aria-pressed={value === key}
          className={`px-4 py-2 text-xs font-semibold transition first:rounded-l-lg last:rounded-r-lg focus:outline-none focus:ring-2 focus:ring-inset focus:ring-indigo-400 ${
            value === key
              ? "bg-indigo-600 text-white"
              : "text-slate-500 hover:bg-slate-50 hover:text-slate-700"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function DashboardView({ queue, loading, fetchError, onInvestigate }) {
  const [filter, setFilter]           = useState({ search: "", severity: "all" });
  const [priorityFilter, setPriority] = useState("needs-review");
  const [currentPage, setPage]        = useState(1);

  const priorityRows = priorityFilter === "needs-review"
    ? queue.filter((r) => r.needsTriage)
    : queue;

  const filteredRows = priorityRows.filter((row) => {
    const matchesSearch   = row.company.toLowerCase().includes(filter.search.toLowerCase());
    const matchesSeverity = filter.severity === "all" || row.severity === filter.severity;
    return matchesSearch && matchesSeverity;
  });

  const { sorted: sortedRows, sort, requestSort } = useSortableData(filteredRows);

  const totalPages  = Math.max(1, Math.ceil(sortedRows.length / ROWS_PER_PAGE));
  const safePage    = Math.min(currentPage, totalPages);
  const pageStart   = (safePage - 1) * ROWS_PER_PAGE;
  const visibleRows = sortedRows.slice(pageStart, pageStart + ROWS_PER_PAGE);

  useEffect(() => { setPage(1); }, [filter, priorityFilter, sort.col, sort.dir, queue.length]);

  function handleFilterChange(next) { setFilter(next); setPage(1); }
  function handlePriorityChange(next) { setPriority(next); setPage(1); }

  return (
    <>
      <SectionHeader
        title="Compliance Dashboard"
        subtitle="Real-time triage of SEC EDGAR filings fetched from the audit warehouse."
      />

      <section>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-slate-700">
              Triage Queue
              <span className="ml-2 rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-500">
                {sortedRows.length}
              </span>
            </h2>
            <PriorityFilterBar value={priorityFilter} onChange={handlePriorityChange} />
          </div>
          <FilterBar filter={filter} onFilterChange={handleFilterChange} />
        </div>

        {loading ? (
          <Spinner />
        ) : fetchError ? (
          <Card className="py-16 text-center">
            <p className="text-sm font-semibold text-red-600">Failed to load filings</p>
            <p className="mt-1 text-xs text-slate-400">{fetchError}</p>
          </Card>
        ) : visibleRows.length > 0 ? (
          <TriageTable rows={visibleRows} sort={sort} onSort={requestSort} onInvestigate={onInvestigate} />
        ) : (
          <Card className="py-16 text-center text-slate-400">
            {queue.length === 0
              ? "No filings found in the audit warehouse."
              : priorityFilter === "needs-review"
              ? "No flagged records found. Switch to 'All Records' to see healthy filings."
              : "No records match your filters."}
          </Card>
        )}

        {!loading && !fetchError && sortedRows.length > 0 && (
          <>
            <Pagination
              currentPage={safePage}
              totalPages={totalPages}
              onPrev={() => setPage((p) => Math.max(1, p - 1))}
              onNext={() => setPage((p) => Math.min(totalPages, p + 1))}
            />
            <p className="mt-3 text-right text-xs text-slate-400">
              Showing {pageStart + 1}–{Math.min(pageStart + ROWS_PER_PAGE, sortedRows.length)} of{" "}
              {sortedRows.length} records
            </p>
          </>
        )}
      </section>
    </>
  );
}

// ---------------------------------------------------------------------------
// Filings view — fully sortable, paginated
// ---------------------------------------------------------------------------

function FilingsView({ queue, loading, fetchError, onInvestigate }) {
  const [search, setSearch]    = useState("");
  const [currentPage, setPage] = useState(1);

  const totalViolations = queue.filter((r) => r.knownRuleViolation).length;
  const totalAnomalies  = queue.filter((r) => r.mlAnomalyFlag).length;

  const searched = search
    ? queue.filter((r) => r.company.toLowerCase().includes(search.toLowerCase()))
    : queue;

  const { sorted, sort, requestSort } = useSortableData(searched);

  const totalPages  = Math.max(1, Math.ceil(sorted.length / ROWS_PER_PAGE));
  const safePage    = Math.min(currentPage, totalPages);
  const pageStart   = (safePage - 1) * ROWS_PER_PAGE;
  const visibleRows = sorted.slice(pageStart, pageStart + ROWS_PER_PAGE);

  useEffect(() => { setPage(1); }, [search, sort.col, sort.dir]);

  return (
    <>
      <SectionHeader
        title="SEC Filings"
        subtitle="All ingested filings. Click any column header to sort. Click View to open the analysis drawer."
      />

      <section aria-label="Summary statistics" className="mb-8 grid gap-4 sm:grid-cols-3">
        <StatCard label="Total Filings"     value={queue.length}    accent="neutral" />
        <StatCard label="Active Violations" value={totalViolations} accent="red"     />
        <StatCard label="ML Anomalies"      value={totalAnomalies}  accent="yellow"  />
      </section>

      <div className="mb-4 flex items-center justify-between gap-4">
        <p className="text-xs text-slate-500">{sorted.length} filings</p>
        <input
          type="text"
          placeholder="Search company…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 placeholder-slate-400 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
      </div>

      {loading ? (
        <Spinner />
      ) : fetchError ? (
        <Card className="py-16 text-center">
          <p className="text-sm font-semibold text-red-600">Failed to load filings</p>
          <p className="mt-1 text-xs text-slate-400">{fetchError}</p>
        </Card>
      ) : (
        <>
          <Card>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm text-slate-700">
                <thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500">
                  <tr>
                    <SortableHeader label="Company"       col="company"    sort={sort} onSort={requestSort} />
                    <SortableHeader label="Form Type"     col="formType"   sort={sort} onSort={requestSort} />
                    <SortableHeader label="Filing Date"   col="filingDate" sort={sort} onSort={requestSort} />
                    <SortableHeader label="Triage Status" col="status"     sort={sort} onSort={requestSort} />
                    <SortableHeader label="Issue Type"    col="issueType"  sort={sort} onSort={requestSort} />
                    <th scope="col" className="px-6 py-3 text-left font-semibold">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {visibleRows.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-6 py-16 text-center text-slate-400">
                        No filings match your search.
                      </td>
                    </tr>
                  ) : visibleRows.map((r) => (
                    <tr
                      key={r.id}
                      className={`transition hover:bg-indigo-50 ${r.needsTriage ? "border-l-4 border-l-red-300" : ""}`}
                    >
                      <td className="px-6 py-4 font-medium text-slate-800">{r.company}</td>
                      <td className="px-6 py-4 font-mono text-slate-500">{r.formType}</td>
                      <td className="px-6 py-4 tabular-nums text-slate-500">{r.filingDate}</td>
                      <td className="px-6 py-4"><StatusBadge status={r.status} /></td>
                      <td className="px-6 py-4"><IssueBadge issueType={r.issueType} severity={r.severity} /></td>
                      <td className="px-6 py-4">
                        <button
                          onClick={() => onInvestigate(r)}
                          className="rounded-lg bg-indigo-600 px-4 py-1.5 text-xs font-semibold text-white transition hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:ring-offset-2 focus:ring-offset-white"
                        >
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {sorted.length > 0 && (
            <>
              <Pagination
                currentPage={safePage}
                totalPages={totalPages}
                onPrev={() => setPage((p) => Math.max(1, p - 1))}
                onNext={() => setPage((p) => Math.min(totalPages, p + 1))}
              />
              <p className="mt-3 text-right text-xs text-slate-400">
                Showing {pageStart + 1}–{Math.min(pageStart + ROWS_PER_PAGE, sorted.length)} of{" "}
                {sorted.length} records
              </p>
            </>
          )}
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Reports view
// ---------------------------------------------------------------------------

function ReportCard({ report }) {
  return (
    <Card className="flex items-center justify-between px-6 py-4">
      <div className="flex items-center gap-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-red-50 text-red-500">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 1.5L18.5 9H13V3.5zM6 20V4h5v7h7v9H6z"/>
          </svg>
        </div>
        <div>
          <p className="text-sm font-semibold text-slate-800">{report.title}</p>
          <p className="text-xs text-slate-400">{report.date} · {report.size}</p>
        </div>
      </div>
      <button className="rounded-lg bg-indigo-600 px-4 py-1.5 text-xs font-semibold text-white transition hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:ring-offset-2 focus:ring-offset-white">
        Download PDF
      </button>
    </Card>
  );
}

function ReportsView() {
  return (
    <>
      <SectionHeader title="Compliance Reports" subtitle="Download generated PDF reports for audit and regulatory review." />
      <div className="flex flex-col gap-3">
        {REPORTS.map((r) => <ReportCard key={r.id} report={r} />)}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Settings view
// ---------------------------------------------------------------------------

function ToggleSwitch({ enabled, onChange }) {
  return (
    <button
      role="switch"
      aria-checked={enabled}
      onClick={() => onChange(!enabled)}
      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:ring-offset-2 ${
        enabled ? "bg-indigo-600" : "bg-slate-200"
      }`}
    >
      <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition-transform duration-200 ${enabled ? "translate-x-5" : "translate-x-0"}`} />
    </button>
  );
}

function SettingRow({ label, description, enabled, onChange }) {
  return (
    <div className="flex items-center justify-between gap-6 px-6 py-4">
      <div>
        <p className="text-sm font-semibold text-slate-800">{label}</p>
        <p className="text-xs text-slate-500">{description}</p>
      </div>
      <ToggleSwitch enabled={enabled} onChange={onChange} />
    </div>
  );
}

function SettingsView() {
  const [settings, setSettings] = useState({
    emailAlerts: true, mlAlerts: true, weeklyDigest: false, slackNotify: false, auditReminders: true,
  });
  const toggle = (key) => setSettings((prev) => ({ ...prev, [key]: !prev[key] }));
  const rows = [
    { key: "emailAlerts",    label: "Email Violation Alerts",    description: "Receive an email when a new rule violation is detected." },
    { key: "mlAlerts",       label: "ML Anomaly Notifications",  description: "Get notified when the ML model flags a filing." },
    { key: "weeklyDigest",   label: "Weekly Compliance Digest",  description: "A summary email of all activity sent every Monday." },
    { key: "slackNotify",    label: "Slack Notifications",       description: "Push alerts to your connected Slack workspace." },
    { key: "auditReminders", label: "Filing Deadline Reminders", description: "Reminders 7 days before SEC submission deadlines." },
  ];
  return (
    <>
      <SectionHeader title="Settings" subtitle="Manage notification preferences and compliance alert controls." />
      <Card>
        <div className="divide-y divide-slate-100">
          {rows.map((r) => (
            <SettingRow key={r.key} label={r.label} description={r.description} enabled={settings[r.key]} onChange={() => toggle(r.key)} />
          ))}
        </div>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------------------
// Root — shared drawer + URL state
// ---------------------------------------------------------------------------

export default function Dashboard() {
  const [initParams]                    = useState(() => getUrlParams());
  const [activeView, setActiveView]     = useState(initParams.tab);
  const [queue, setQueue]               = useState([]);
  const [loading, setLoading]           = useState(true);
  const [fetchError, setFetchError]     = useState(null);
  const [activeRecord, setActiveRecord] = useState(null);
  const [toast, setToast]               = useState("");

  useEffect(() => {
    fetch("/api/filings")
      .then((res) => {
        if (!res.ok) throw new Error(`Server returned ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setQueue(data);
        if (initParams.filingId) {
          const found = data.find((r) => r.id === initParams.filingId);
          if (found) setActiveRecord(found);
        }
      })
      .catch((err) => setFetchError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    setUrlParams(activeView, activeRecord?.id ?? null);
  }, [activeView, activeRecord]);

  function handleResolve(id) {
    const company = queue.find((r) => r.id === id)?.company ?? "";
    setQueue((prev) => prev.filter((r) => r.id !== id));
    setActiveRecord(null);
    setToast(`${company} marked as resolved and removed from queue.`);
    setTimeout(() => setToast(""), 4000);
  }

  function renderView() {
    switch (activeView) {
      case "Filings":
        return <FilingsView queue={queue} loading={loading} fetchError={fetchError} onInvestigate={setActiveRecord} />;
      case "Reports":
        return <ReportsView />;
      case "Settings":
        return <SettingsView />;
      default:
        return <DashboardView queue={queue} loading={loading} fetchError={fetchError} onInvestigate={setActiveRecord} />;
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      <div className="flex">
        <aside className="hidden w-56 shrink-0 flex-col gap-1 border-r border-slate-200 bg-white px-4 py-8 shadow-sm md:flex">
          <span className="mb-6 text-lg font-bold tracking-tight text-indigo-600">FinTelemetry</span>
          {NAV_ITEMS.map((item) => (
            <button
              key={item}
              onClick={() => setActiveView(item)}
              className={`rounded-lg px-3 py-2 text-left text-sm font-medium transition ${
                activeView === item
                  ? "bg-indigo-50 font-semibold text-indigo-700"
                  : "text-slate-500 hover:bg-slate-100 hover:text-slate-800"
              }`}
            >
              {item}
            </button>
          ))}
        </aside>

        <main className="flex-1 px-6 py-8 md:px-10">
          {renderView()}
        </main>
      </div>

      <InvestigateDrawer
        record={activeRecord}
        onClose={() => setActiveRecord(null)}
        onResolve={handleResolve}
      />

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-3 rounded-xl bg-emerald-600 px-5 py-3 text-sm font-medium text-white shadow-lg">
          <span>{toast}</span>
          <button onClick={() => setToast("")} aria-label="Dismiss" className="text-emerald-200 hover:text-white">✕</button>
        </div>
      )}
    </div>
  );
}
