/**
 * FinTelemetry — React Dev Server
 * ================================
 * Serves Dashboard.jsx as an inline-compiled HTML page and proxies all
 * /api/* requests to the FastAPI backend running on FASTAPI_PORT (default 8000).
 *
 * Start order:
 *   1.  python -m backend.api.main          ← FastAPI on port 8000
 *   2.  node frontend/dev_server.js         ← React dev server on port 5174
 *
 * Environment variables:
 *   PORT         React server port    (default: 5174)
 *   FASTAPI_PORT FastAPI backend port (default: 8000)
 */

const http = require("http");
const fs   = require("fs");
const path = require("path");

const PORT         = parseInt(process.env.PORT         || "5174", 10);
const FASTAPI_PORT = parseInt(process.env.FASTAPI_PORT || "8000", 10);
const FASTAPI_HOST = process.env.FASTAPI_HOST || "127.0.0.1";

const DASHBOARD_PATH = path.join(__dirname, "src", "Dashboard.jsx");

// ---------------------------------------------------------------------------
// HTML template
// ---------------------------------------------------------------------------

function buildHtml(componentSource) {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>FinTelemetry — Compliance Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      theme: { extend: { colors: { slate: { 950: '#020617' } } } }
    }
  </script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <script src="https://unpkg.com/react@18/umd/react.development.js"></script>
  <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel" data-presets="react">
    const { useState, useEffect } = React;

    ${componentSource}

    const root = ReactDOM.createRoot(document.getElementById('root'));
    root.render(<Dashboard />);
  </script>
</body>
</html>`;
}

function readDashboard() {
  try {
    let src = fs.readFileSync(DASHBOARD_PATH, "utf8");
    src = src.replace(/^import\s.+?;?\s*$/gm, "");
    src = src.replace(/^export\s+default\s+/m, "");
    return { source: src, error: null };
  } catch (err) {
    return { source: null, error: err.message };
  }
}

// ---------------------------------------------------------------------------
// FastAPI proxy
// ---------------------------------------------------------------------------

function proxyToFastApi(req, res) {
  const options = {
    hostname: FASTAPI_HOST,
    port:     FASTAPI_PORT,
    path:     req.url,
    method:   req.method,
    headers:  { ...req.headers, host: `${FASTAPI_HOST}:${FASTAPI_PORT}` },
  };

  const proxyReq = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, {
      ...proxyRes.headers,
      "Access-Control-Allow-Origin": "*",
    });
    proxyRes.pipe(res, { end: true });
  });

  proxyReq.on("error", (err) => {
    console.warn(`[proxy] FastAPI unreachable (${err.message})`);
    res.writeHead(503, { "Content-Type": "application/json" });
    res.end(JSON.stringify({
      error:   "FastAPI backend unavailable",
      detail:  `Could not reach http://${FASTAPI_HOST}:${FASTAPI_PORT}${req.url}`,
      hint:    "Run: python -m backend.api.main",
    }));
  });

  req.pipe(proxyReq, { end: true });
}

// ---------------------------------------------------------------------------
// HTTP server
// ---------------------------------------------------------------------------

const server = http.createServer((req, res) => {
  // Proxy all /api/* requests to the FastAPI backend
  if (req.url.startsWith("/api/")) {
    return proxyToFastApi(req, res);
  }

  // Serve dashboard HTML (strip query-string before route match so
  // /?tab=Filings&filingId=123 is handled correctly)
  const pathname = req.url.split("?")[0];
  if ((pathname === "/" || pathname === "/index.html") && req.method === "GET") {
    const { source, error } = readDashboard();
    if (error) {
      res.writeHead(500, { "Content-Type": "text/plain" });
      res.end(`Failed to read Dashboard.jsx:\n${error}`);
      return;
    }
    const html = buildHtml(source);
    res.writeHead(200, {
      "Content-Type":  "text/html; charset=utf-8",
      "Cache-Control": "no-store",
    });
    res.end(html);
    return;
  }

  res.writeHead(404, { "Content-Type": "text/plain" });
  res.end("Not found");
});

server.listen(PORT, () => {
  console.log(`\nFinTelemetry dev server  →  http://localhost:${PORT}/`);
  console.log(`API proxy               →  http://${FASTAPI_HOST}:${FASTAPI_PORT}/api/*`);
  console.log(`Serving                 →  ${DASHBOARD_PATH}`);
  console.log("Press Ctrl+C to stop.\n");
});
