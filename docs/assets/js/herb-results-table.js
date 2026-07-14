/* TSIINO_RESULTS_STABLE_V37
   Renderizador robusto para resultados do validador.
   Objetivo: quando a API retorna issues/contadores, mas a tabela aparece vazia
   ou apenas com LINHA, reconstruir a planilha anotada a partir de /jobs/{id}/table
   e /jobs/{id}/issues, incluindo dados que venham dentro de _RAW.
*/
(function () {
  'use strict';

  const MARK = 'TSIINO_RESULTS_STABLE_V37';
  const LOCAL_API = 'http://127.0.0.1:8000/api/validator';
  const PROD_API = 'https://api.tsiinohiiwiida.net/api/validator';
  const host = window.location.hostname;
  const API_BASE = (window.TsiinoValidatorBridge && window.TsiinoValidatorBridge.apiBase) ||
    ((!host || host === '127.0.0.1' || host === 'localhost') ? LOCAL_API : PROD_API);

  const originalFetch = window.fetch ? window.fetch.bind(window) : null;
  const state = {
    jobId: null,
    summary: null,
    rows: [],
    issues: [],
    filter: 'all',
    loading: false,
    renderedAt: 0
  };

  const canonicalOrder = [
    'accession', 'collector', 'prefix', 'number', 'suffix', 'addcoll',
    'colldd', 'collmm', 'collyy', 'initial', 'family', 'genus', 'detstatus',
    'sp1', 'rank1', 'sp2', 'detby', 'detdd', 'detmm', 'detyy', 'country',
    'majorarea', 'minorarea', 'gazetteer', 'locnotes', 'habitattxt', 'lat',
    'NS', 'long', 'EW', 'llunit', 'alt', 'alt1', 'plantdesc', 'vernacular',
    'dups', 'project', 'genbank'
  ];

  const fieldLabels = {
    accession: 'ACCESSION', collector: 'COLLECTOR', prefix: 'PREFIX', number: 'NUMBER', suffix: 'SUFFIX', addcoll: 'ADDCOLL',
    colldd: 'COLLDD', collmm: 'COLLMM', collyy: 'COLLYY', initial: 'INITIAL', family: 'FAMILY', genus: 'GENUS', detstatus: 'DETSTATUS',
    sp1: 'SP1', rank1: 'RANK1', sp2: 'SP2', detby: 'DETBY', detdd: 'DETDD', detmm: 'DETMM', detyy: 'DETYY', country: 'COUNTRY',
    majorarea: 'MAJORAREA', minorarea: 'MINORAREA', gazetteer: 'GAZETTEER', locnotes: 'LOCNOTES', habitattxt: 'HABITATTXT',
    lat: 'LAT', NS: 'NS', long: 'LONG', EW: 'EW', llunit: 'LLUNIT', alt: 'ALT', alt1: 'ALT1', plantdesc: 'PLANTDESC', vernacular: 'VERNACULAR',
    dups: 'DUPS', project: 'PROJECT', genbank: 'GENBANK'
  };

  const aliases = new Map([
    ['row_number', '_ROW_NUMBER'], ['linha', '_ROW_NUMBER'], ['_row_number', '_ROW_NUMBER'],
    ['familia', 'family'], ['família', 'family'], ['family', 'family'],
    ['genero', 'genus'], ['gênero', 'genus'], ['genus', 'genus'],
    ['especie', 'sp1'], ['espécie', 'sp1'], ['epiteto', 'sp1'], ['epíteto', 'sp1'], ['sp1', 'sp1'],
    ['latitude', 'lat'], ['lat', 'lat'], ['longitude', 'long'], ['long', 'long'],
    ['municipio', 'minorarea'], ['município', 'minorarea'], ['estado', 'majorarea'], ['uf', 'majorarea'], ['pais', 'country'], ['país', 'country'],
    ['numero', 'number'], ['número', 'number'], ['numero de coleta', 'number'], ['número de coleta', 'number'],
    ['coletor', 'collector'], ['collector', 'collector'], ['descricao', 'plantdesc'], ['descrição', 'plantdesc'],
    ['plantdesc', 'plantdesc']
  ]);

  function normText(value) {
    return String(value == null ? '' : value)
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .replace(/[^a-zA-Z0-9]+/g, ' ')
      .trim().toLowerCase();
  }

  function canonicalField(value) {
    const raw = String(value == null ? '' : value).trim();
    if (!raw) return '';
    if (canonicalOrder.includes(raw)) return raw;
    if (canonicalOrder.includes(raw.toLowerCase())) return raw.toLowerCase();
    const n = normText(raw);
    return aliases.get(n) || raw;
  }

  function cleanMojibake(text) {
    let s = String(text == null ? '' : text);
    const pairs = [
      ['Ã§', 'ç'], ['Ã£', 'ã'], ['Ã¡', 'á'], ['Ã©', 'é'], ['Ã­', 'í'], ['Ã³', 'ó'], ['Ãº', 'ú'],
      ['Ãª', 'ê'], ['Ã´', 'ô'], ['Ãµ', 'õ'], ['Ã¢', 'â'], ['Ã ', 'à'], ['Ã‡', 'Ç'], ['Ã‰', 'É'],
      ['Âº', 'º'], ['Âª', 'ª'], ['â€“', '–'], ['â€”', '—'], ['â€œ', '“'], ['â€�', '”'], ['â€˜', '‘'], ['â€™', '’']
    ];
    for (const [a, b] of pairs) s = s.split(a).join(b);
    s = s.replace(/^ÃçÃ[^"]*?\s+/g, '').replace(/^AçA[^"]*?\s+/g, '');
    return s;
  }

  function parseRaw(raw) {
    if (!raw) return {};
    if (typeof raw === 'object' && !Array.isArray(raw)) return raw;
    if (typeof raw === 'string') {
      try {
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' ? parsed : {};
      } catch (_) {
        return {};
      }
    }
    return {};
  }

  function getValue(row, field) {
    if (!row) return '';
    const fieldRaw = String(field);
    const candidates = [fieldRaw, canonicalField(fieldRaw), fieldRaw.toLowerCase(), fieldRaw.toUpperCase()];
    for (const key of candidates) {
      if (Object.prototype.hasOwnProperty.call(row, key) && row[key] != null && String(row[key]).trim() !== '') return row[key];
    }
    const nf = normText(fieldRaw);
    for (const [key, value] of Object.entries(row)) {
      if (normText(key) === nf && value != null && String(value).trim() !== '') return value;
    }
    return '';
  }

  function normalizeRows(rows) {
    if (!Array.isArray(rows)) return [];
    return rows.map((row, idx) => {
      const raw = parseRaw(row && (row._RAW || row.raw || row.__raw || row.original || row.values));
      const out = Object.assign({}, raw, row || {});
      // Também copie chaves normalizadas/canônicas para facilitar a renderização.
      for (const [key, value] of Object.entries(out)) {
        const canon = canonicalField(key);
        if (canon && canonicalOrder.includes(canon) && (out[canon] == null || String(out[canon]).trim() === '')) {
          out[canon] = value;
        }
      }
      const rn = out._ROW_NUMBER || out.row_number || out.linha || out.LINHA || out.row || out.Row || (idx + 1);
      out._ROW_NUMBER = rn;
      return out;
    });
  }

  function rowNumber(row, idx) {
    const rn = row && (row._ROW_NUMBER || row.row_number || row.linha || row.LINHA || row.row || row.Row);
    const n = Number(rn);
    return Number.isFinite(n) && n > 0 ? n : idx + 1;
  }

  function inferField(issue, row) {
    const explicit = canonicalField(issue.field || issue.column || issue.col || issue.header || '');
    if (explicit && canonicalOrder.includes(explicit)) return explicit;
    const msg = normText(issue.message || issue.msg || issue.detail || issue.description || '');
    if (msg.includes('latitude')) return 'lat';
    if (msg.includes('longitude')) return 'long';
    if (msg.includes('numero de coleta') || msg.includes('number')) return 'number';
    if (msg.includes('familia informada') || msg.includes('familia esperada') || msg.includes('familia')) return 'family';
    if (msg.includes('genero')) return 'genus';
    if (msg.includes('especie') || msg.includes('epiteto')) return getValue(row, 'sp1') ? 'sp1' : 'genus';
    if (msg.includes('municipio')) return 'minorarea';
    if (msg.includes('estado') || msg.includes('uf')) return 'majorarea';
    if (msg.includes('pais')) return 'country';
    if (msg.includes('descricao')) return 'plantdesc';
    return explicit || '';
  }

  function suggestionName(msg) {
    const m = String(msg || '').match(/Sugest(?:ão|ao):\s*([^.;\n]+)/i);
    return m ? m[1].trim() : '';
  }

  function editDistance(a, b) {
    a = normText(a); b = normText(b);
    const dp = Array.from({ length: a.length + 1 }, () => Array(b.length + 1).fill(0));
    for (let i = 0; i <= a.length; i++) dp[i][0] = i;
    for (let j = 0; j <= b.length; j++) dp[0][j] = j;
    for (let i = 1; i <= a.length; i++) {
      for (let j = 1; j <= b.length; j++) {
        const cost = a[i - 1] === b[j - 1] ? 0 : 1;
        dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost);
      }
    }
    return dp[a.length][b.length];
  }

  function likelyWrongTaxonomicIssue(issue, row) {
    const msg = cleanMojibake(issue.message || issue.msg || issue.detail || issue.description || '');
    const nmsg = normText(msg);
    const family = String(getValue(row, 'family') || '').trim();
    const genus = String(getValue(row, 'genus') || '').trim();
    const sp1 = String(getValue(row, 'sp1') || '').trim();

    if ((nmsg.includes('flora e funga') || nmsg.includes('genero') || nmsg.includes('especie') || nmsg.includes('familia')) && !genus) return true;
    if (nmsg.includes('especie') && !sp1) return true;

    const suggestion = suggestionName(msg);
    if (suggestion) {
      const sg = suggestion.split(/\s+/)[0];
      if (nmsg.includes('especie') && genus && sg && normText(sg) !== normText(genus)) return true;
      if (nmsg.includes('genero nao encontrado') && genus && sg) {
        const d = editDistance(genus, sg);
        const maxLen = Math.max(normText(genus).length, normText(sg).length, 1);
        // Mantenha só sugestões realmente próximas, como Passflora -> Passiflora.
        if (d / maxLen > 0.34) return true;
      }
    }

    // Algumas mensagens de família vazavam para linhas seguintes; quando vier sem campo explícito
    // e com família/gênero já preenchidos, deixe o backend futuro decidir. Aqui só removemos as
    // mensagens sabidamente genéricas e vagas.
    if (nmsg.includes('familia e genero estao vazios') && (family || genus)) return true;
    return false;
  }

  function normalizeIssues(issues, rows) {
    if (!Array.isArray(issues)) return [];
    const byRow = new Map(rows.map((r, i) => [rowNumber(r, i), r]));
    const out = [];
    const seen = new Set();

    for (const rawIssue of issues) {
      const issue = Object.assign({}, rawIssue || {});
      issue.message = cleanMojibake(issue.message || issue.msg || issue.detail || issue.description || '');
      issue.severity = String(issue.severity || issue.level || issue.type || '').toLowerCase().includes('warn') ? 'warning' : 'error';
      const rn = Number(issue.row_number || issue.row || issue.linha || issue.line || issue.record_index || issue.record || 0);
      if (!rn) continue;
      const row = byRow.get(rn);
      if (!row) continue;
      issue.field = inferField(issue, row);
      if (likelyWrongTaxonomicIssue(issue, row)) continue;
      const key = [rn, issue.field, issue.severity, normText(issue.message)].join('|');
      if (seen.has(key)) continue;
      seen.add(key);
      issue.row_number = rn;
      out.push(issue);
    }
    return out;
  }

  function chooseColumns(rows, issues) {
    const cols = [];
    for (const col of canonicalOrder) {
      const hasValue = rows.some((row) => String(getValue(row, col) || '').trim() !== '');
      const hasIssue = issues.some((issue) => canonicalField(issue.field) === col);
      if (hasValue || hasIssue) cols.push(col);
    }
    if (cols.length) return cols;
    const skip = new Set(['_RAW', 'raw', '__raw', 'original', 'values', '_ROW_NUMBER', 'row_number', 'linha', 'row', 'id']);
    const keys = [];
    for (const row of rows.slice(0, 20)) {
      for (const key of Object.keys(row || {})) {
        if (skip.has(key) || key.startsWith('_')) continue;
        if (!keys.includes(key)) keys.push(key);
      }
    }
    return keys;
  }

  function issuesFor(row, field, issues, idx) {
    const rn = rowNumber(row, idx);
    const cf = canonicalField(field);
    return issues.filter((issue) => issue.row_number === rn && canonicalField(issue.field) === cf);
  }

  function rowIssues(row, issues, idx) {
    const rn = rowNumber(row, idx);
    return issues.filter((issue) => issue.row_number === rn);
  }

  function ensureResultsContainer() {
    const results = document.getElementById('validator-results') || document.querySelector('[id*="result"], .hv-results, .validator-results');
    if (!results) return null;
    results.classList.add('tsiino-v37-active');
    let box = document.getElementById('tsiino-results-stable-v37');
    if (!box) {
      box = document.createElement('div');
      box.id = 'tsiino-results-stable-v37';
      box.className = 'tsiino-results-stable-v37';
      const anchor = Array.from(results.querySelectorAll('p, div, h2, h3')).find((el) => /Planilha anotada/i.test(el.textContent || ''));
      if (anchor && anchor.parentElement) {
        anchor.parentElement.insertBefore(box, anchor.nextSibling);
      } else {
        results.appendChild(box);
      }
    }
    return box;
  }

  function setStatus(text, mode) {
    const status = document.getElementById('validator-status') || document.querySelector('.hv-status');
    if (!status) return;
    status.textContent = text;
    status.className = 'hv-status ' + (mode || 'ok');
  }

  function render() {
    if (!state.jobId) return;
    const box = ensureResultsContainer();
    if (!box) return;

    let rows = normalizeRows(state.rows);
    let issues = normalizeIssues(state.issues, rows);
    const columns = chooseColumns(rows, issues);

    if (state.filter === 'errors') {
      rows = rows.filter((row, idx) => rowIssues(row, issues, idx).some((issue) => issue.severity === 'error'));
    } else if (state.filter === 'warnings') {
      rows = rows.filter((row, idx) => rowIssues(row, issues, idx).some((issue) => issue.severity === 'warning'));
    } else if (state.filter === 'ok') {
      rows = rows.filter((row, idx) => rowIssues(row, issues, idx).length === 0);
    }

    const header = ['<th class="tsiino-v37-rowhead">LINHA</th>']
      .concat(columns.map((col) => `<th>${fieldLabels[col] || String(col).toUpperCase()}</th>`)).join('');

    const body = rows.map((row, idx) => {
      const rn = rowNumber(row, idx);
      const cells = columns.map((col) => {
        const value = cleanMojibake(getValue(row, col));
        const cellIssues = issuesFor(row, col, issues, idx);
        const sev = cellIssues.some((i) => i.severity === 'error') ? 'error' : (cellIssues.length ? 'warning' : '');
        const notes = cellIssues.map((issue) => `<div class="tsiino-v37-note ${issue.severity}">${escapeHtml(issue.message)}</div>`).join('');
        return `<td class="${sev ? 'tsiino-v37-cell-' + sev : ''}"><div class="tsiino-v37-value">${escapeHtml(value)}</div>${notes}</td>`;
      }).join('');
      return `<tr><th class="tsiino-v37-rowhead">${escapeHtml(rn)}</th>${cells}</tr>`;
    }).join('');

    const msg = rows.length
      ? ''
      : '<div class="tsiino-v37-empty">Nenhuma linha para o filtro atual. Clique em <strong>Todos</strong> para voltar à planilha completa.</div>';

    box.innerHTML = `
      <div class="tsiino-v37-toolbar" aria-label="Resultado renderizado pelo estabilizador v37">
        <span>${rows.length} linhas exibidas</span>
        <span>${issues.length} ocorrências vinculadas a células</span>
      </div>
      <div class="tsiino-v37-scroll">
        <table class="tsiino-v37-table">
          <thead><tr>${header}</tr></thead>
          <tbody>${body}</tbody>
        </table>
        ${msg}
      </div>
    `;

    setStatus('Validação concluída. Corrija as células destacadas ou baixe a cópia .xlsx anotada.', 'ok');
    state.renderedAt = Date.now();
    moveDownloadButton();
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
  }

  async function renderJob(jobId) {
    if (!jobId || state.loading) return;
    state.loading = true;
    try {
      const [summaryRes, issuesRes, tableRes] = await Promise.all([
        originalFetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}`),
        originalFetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/issues`),
        originalFetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/table`)
      ]);
      if (!summaryRes.ok || !issuesRes.ok || !tableRes.ok) return;
      state.jobId = jobId;
      state.summary = await summaryRes.json();
      state.issues = await issuesRes.json();
      state.rows = await tableRes.json();
      // Sempre volte para Todos quando chega um novo job.
      state.filter = 'all';
      syncFilterButtons('all');
      render();
    } catch (err) {
      console.warn('[Tsiino v37] Falha ao renderizar job', jobId, err);
    } finally {
      state.loading = false;
    }
  }

  function syncFilterButtons(filter) {
    document.querySelectorAll('.hv-filter, [data-filter]').forEach((button) => {
      const f = normalizeFilter(button.dataset && button.dataset.filter ? button.dataset.filter : button.textContent);
      button.classList.toggle('is-active', f === filter);
    });
  }

  function normalizeFilter(value) {
    const n = normText(value);
    if (n.includes('erro')) return 'errors';
    if (n.includes('alert')) return 'warnings';
    if (n.includes('sem problema') || n === 'ok') return 'ok';
    return 'all';
  }

  function installFilterHandlers() {
    document.addEventListener('click', (event) => {
      const button = event.target.closest('.hv-filter, [data-filter]');
      if (!button) return;
      const filter = normalizeFilter(button.dataset && button.dataset.filter ? button.dataset.filter : button.textContent);
      state.filter = filter;
      syncFilterButtons(filter);
      if (state.jobId) {
        event.preventDefault();
        render();
      }
    }, true);
  }

  function moveDownloadButton() {
    const results = document.getElementById('validator-results');
    if (!results) return;
    const download = document.getElementById('download-button') || document.getElementById('validator-download') ||
      Array.from(document.querySelectorAll('button, a')).find((el) => /Baixar planilha anotada/i.test(el.textContent || ''));
    const filters = Array.from(results.querySelectorAll('.hv-filter, [data-filter]')).pop();
    if (download && filters && download.parentElement !== filters.parentElement) {
      filters.insertAdjacentElement('afterend', download);
      download.classList.add('tsiino-v37-download-button');
    }
  }

  function extractJobId(url) {
    const m = String(url || '').match(/\/api\/validator\/jobs\/([^/?#]+)/) || String(url || '').match(/\/jobs\/([^/?#]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function installFetchWatcher() {
    if (!originalFetch) return;
    const priorFetch = window.fetch.bind(window);
    // Evite encapsular várias vezes.
    if (window.__tsiinoResultsStableV37FetchInstalled) return;
    window.__tsiinoResultsStableV37FetchInstalled = true;
    window.fetch = async function (...args) {
      const res = await priorFetch(...args);
      try {
        const url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url);
        const jobId = extractJobId(url);
        if (jobId && !/\/download/i.test(String(url))) {
          setTimeout(() => renderJob(jobId), 250);
        }
      } catch (_) {}
      return res;
    };
  }

  function scanPerformanceForJob() {
    try {
      const ids = Array.from(new Set(performance.getEntriesByType('resource')
        .map((e) => extractJobId(e.name))
        .filter(Boolean)));
      const last = ids[ids.length - 1];
      if (last && last !== state.jobId) renderJob(last);
    } catch (_) {}
  }

  function install() {
    installFilterHandlers();
    installFetchWatcher();
    setInterval(scanPerformanceForJob, 1500);
    setTimeout(scanPerformanceForJob, 500);
    window.TsiinoResultsStableV37 = { renderJob, render, state, mark: MARK };
    console.info('[Tsiino] Results stable v37 carregado.');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install);
  } else {
    install();
  }
})();
