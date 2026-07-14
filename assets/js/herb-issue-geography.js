// TSIINO_ISSUE_GEO_V39B
(function () {
  'use strict';
  if (window.TsiinoIssueGeoV39B) return;
  function normalizeItem(item) {
    if (!item || typeof item !== 'object') return item;
    const out = Object.assign({}, item);
    const col = out.column_name || out.field || out.column || out.campo || null;
    const row = out.row_number ?? out.row ?? out.linha ?? out.line_number ?? null;
    out.column_name = col;
    out.field = col;
    out.column = col;
    out.row_number = row;
    return out;
  }
  function normalizePayload(data) {
    if (Array.isArray(data)) return data.map(normalizeItem);
    if (data && Array.isArray(data.issues)) return Object.assign({}, data, { issues: data.issues.map(normalizeItem) });
    if (data && Array.isArray(data.data)) return Object.assign({}, data, { data: data.data.map(normalizeItem) });
    return data;
  }
  const originalFetch = window.fetch;
  window.fetch = async function tsiinoIssueGeoFetch(input, init) {
    const response = await originalFetch.apply(this, arguments);
    try {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      if (!/\/api\/validator\/jobs\/[^/]+\/issues/.test(url)) return response;
      const cloned = response.clone();
      const data = await cloned.json();
      const normalized = normalizePayload(data);
      const headers = new Headers(response.headers);
      headers.set('content-type', 'application/json; charset=utf-8');
      return new Response(JSON.stringify(normalized), { status: response.status, statusText: response.statusText, headers });
    } catch (err) { return response; }
  };
  window.TsiinoIssueGeoV39B = { ready: true, normalizeItem };
})();
