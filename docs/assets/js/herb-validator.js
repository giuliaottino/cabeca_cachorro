(function () {
const LOCAL_API = 'http://127.0.0.1:8000/api/validator';
const PROD_API = 'https://api.tsiinohiiwiida.net/api/validator';

const host = window.location.hostname;
const isLocal = !host || host === '127.0.0.1' || host === 'localhost';

const API_BASE = isLocal ? LOCAL_API : PROD_API;

  const COLUMN_ALIASES = {
    numtombo: 'accession', tombo: 'accession', coletor: 'collector', coletores: 'collector', numero: 'number',
    numcoleta: 'number', numero_coleta: 'number', sufixo: 'suffix', dia: 'colldd', dia_coleta: 'colldd', mes: 'collmm',
    mes_coleta: 'collmm', ano: 'collyy', ano_coleta: 'collyy', familia: 'family', genero: 'genus', especie: 'sp1',
    epiteto: 'sp1', autor: 'author1', pais: 'country', estado: 'majorarea', uf: 'majorarea', municipio: 'minorarea',
    localidade: 'gazetteer', notas_localidade: 'locnotes', habitat: 'habitattxt', latitude: 'lat', longitude: 'long',
    altitude: 'alt', descricao: 'plantdesc', descricao_planta: 'plantdesc', nome_popular: 'vernacular', duplicatas: 'dups',
    herbario: 'dups', herbarios: 'dups', projeto: 'project'
  };

  const CANONICAL = new Set([
    'accession','collector','prefix','number','suffix','addcoll','colldd','collmm','collyy','initial',
    'family','genus','detstatus','sp1','rank1','sp2','detby','detdd','detmm','detyy','country','majorarea',
    'minorarea','gazetteer','locnotes','habitattxt','lat','NS','long','EW','llunit','alt','alt1','plantdesc',
    'vernacular','dups','project','genbank','author1','cf'
  ]);

  let records = [];
  let issues = [];
  let currentFilter = 'all';
  let headers = [];
  let canonicalToRaw = new Map();
  let currentJobId = null;
  let currentGeojson = null;

  function $(id) { return document.getElementById(id); }

  function fixMojibake(value) {
    let text = String(value ?? '');
    for (let i = 0; i < 3 && /(?:Ã|Â|â|�)/.test(text); i += 1) {
      try {
        const bytes = new Uint8Array(Array.from(text, (ch) => ch.charCodeAt(0) & 255));
        const decoded = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
        if (!decoded || decoded === text) break;
        text = decoded;
      } catch (_) {
        break;
      }
    }
    return text
      .replaceAll('Ã‡', 'Ç')
      .replaceAll('Ã§', 'ç')
      .replaceAll('Ã£', 'ã')
      .replaceAll('Ã¡', 'á')
      .replaceAll('Ã©', 'é')
      .replaceAll('Ã­', 'í')
      .replaceAll('Ã³', 'ó')
      .replaceAll('Ãº', 'ú')
      .replaceAll('Ãª', 'ê')
      .replaceAll('Ã‰', 'É')
      .replaceAll('Ã�', 'Í')
      .replaceAll('Âº', 'º')
      .replaceAll('Âª', 'ª')
      .replaceAll('Â·', '·')
      .replaceAll('â€“', '–')
      .replaceAll('â€”', '—')
      .replaceAll('â€œ', '“')
      .replaceAll('â€', '”')
      .replaceAll('â€˜', '‘')
      .replaceAll('â€™', '’')
      .replaceAll('â€¢', '•')
      .replaceAll('âš ï¸', 'Aviso:')
      .replaceAll('⚠️', 'Aviso:');
  }


  function escapeHtml(value) {
    return String(fixMojibake(value) ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function normalizeKey(value) {
    return String(fixMojibake(value) ?? '')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '');
  }

  function canonicalizeHeader(rawHeader) {
    const raw = String(rawHeader ?? '').trim();
    if (CANONICAL.has(raw)) return raw;
    const key = normalizeKey(raw);
    if (CANONICAL.has(key)) return key;
    return COLUMN_ALIASES[key] || key;
  }

  function setStatus(message, type = '') {
    const node = $('validator-status');
    if (!node) return;
    node.innerHTML = fixMojibake(message);
    node.className = 'hv-status' + (type ? ' is-' + type : '');
  }

  function setBusy(isBusy) {
    const btn = $('validate-button');
    if (!btn) return;
    btn.disabled = isBusy;
    btn.textContent = isBusy ? 'Validando...' : 'Validar planilha';
  }

  function configureDownload(jobId) {
    const link = $('download-annotated');
    if (!link) return;
    if (!jobId) {
      link.href = '#';
      link.classList.add('is-disabled');
      link.setAttribute('aria-disabled', 'true');
      return;
    }
    link.href = `${API_BASE}/jobs/${jobId}/download.xlsx`;
    link.download = `tsiino_planilha_anotada_${jobId}.xlsx`;
    link.classList.remove('is-disabled');
    link.setAttribute('aria-disabled', 'false');
  }

  function configureMap(jobId) {
    const btn = $('map-button');
    if (!btn) return;
    if (!jobId) {
      btn.classList.add('is-disabled');
      btn.setAttribute('aria-disabled', 'true');
      btn.disabled = true;
      currentGeojson = null;
      const panel = $('validator-map-panel');
      if (panel) panel.hidden = true;
      return;
    }
    btn.classList.remove('is-disabled');
    btn.setAttribute('aria-disabled', 'false');
    btn.disabled = false;
  }

  function getRaw(record) {
    return record && typeof record._raw === 'object' && record._raw !== null ? record._raw : record;
  }

  function buildHeaders() {
    const seen = new Set();
    headers = [];
    canonicalToRaw = new Map();

    records.forEach((record) => {
      const raw = getRaw(record);
      Object.keys(raw || {}).forEach((h) => {
        if (!h || h.startsWith('_')) return;
        if (!seen.has(h)) {
          seen.add(h);
          headers.push(h);
        }
        const canonical = canonicalizeHeader(h);
        if (!canonicalToRaw.has(canonical)) canonicalToRaw.set(canonical, h);
      });
    });

    if (!headers.length) {
      const fallback = new Set();
      records.forEach((record) => {
        Object.keys(record || {}).forEach((h) => {
          if (!h.startsWith('_') && !fallback.has(h)) {
            fallback.add(h);
            headers.push(h);
            if (!canonicalToRaw.has(h)) canonicalToRaw.set(h, h);
          }
        });
      });
    }
  }

  function issueRawColumn(item) {
    const col = item.column_name || '';
    if (!col) return '_row';
    return canonicalToRaw.get(col) || col;
  }

  function groupIssuesByCell() {
    const grouped = new Map();
    issues.forEach((item) => {
      const row = item.row_number == null ? '_global' : String(item.row_number);
      const col = issueRawColumn(item);
      const key = row + '||' + col;
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(item);
    });
    return grouped;
  }

  function rowIssueSeverity(rowNumber, grouped) {
    let hasWarning = false;
    let hasInfo = false;
    for (const h of headers) {
      const cellIssues = grouped.get(String(rowNumber) + '||' + h) || [];
      if (cellIssues.some((i) => i.severity === 'error')) return 'error';
      if (cellIssues.some((i) => i.severity === 'warning')) hasWarning = true;
      if (cellIssues.some((i) => i.severity === 'info')) hasInfo = true;
    }
    const rowIssues = grouped.get(String(rowNumber) + '||_row') || [];
    if (rowIssues.some((i) => i.severity === 'error')) return 'error';
    if (hasWarning || rowIssues.some((i) => i.severity === 'warning')) return 'warning';
    if (hasInfo || rowIssues.some((i) => i.severity === 'info')) return 'info';
    return 'clear';
  }

  function cellClass(cellIssues) {
    if (!cellIssues || !cellIssues.length) return '';
    if (cellIssues.some((i) => i.severity === 'error')) return 'hv-cell-error';
    if (cellIssues.some((i) => i.severity === 'warning')) return 'hv-cell-warning';
    return 'hv-cell-info';
  }

  function renderSummary(summary) {
    const node = $('validator-summary');
    if (!node) return;
    node.innerHTML = `
      <div class="hv-card-number"><span>Linhas</span><strong>${summary.total_rows ?? records.length}</strong><small>Registros detectados apÃƒÂ³s o cabeÃƒÂ§alho</small></div>
      <div class="hv-card-number"><span>Erros</span><strong>${summary.error_count ?? 0}</strong><small>Problemas que devem ser corrigidos</small></div>
      <div class="hv-card-number"><span>Alertas</span><strong>${summary.warning_count ?? 0}</strong><small>Casos que exigem revisÃƒÂ£o curatorial</small></div>
    `;
  }

  function renderGlobalIssues(grouped) {
    const global = grouped.get('_global||_row') || [];
    const extra = issues.filter((item) => item.row_number == null && issueRawColumn(item) !== '_row');
    const all = [...global, ...extra];
    if (!all.length) return '';
    return `<tbody>${all.map((item) => `
      <tr class="hv-global-issue"><td class="hv-rownum">Ã¢â‚¬â€</td><td colspan="${Math.max(headers.length, 1)}">
        <span class="hv-cell-msg ${escapeHtml(item.severity)}">${item.severity === 'error' ? 'Ã¢Å“â€“' : item.severity === 'warning' ? 'Ã¢Å¡Â ' : 'Ã¢â€œËœ'} ${escapeHtml(item.message)}</span>
      </td></tr>`).join('')}</tbody>`;
  }

  function renderSheet() {
    const table = $('validator-sheet');
    if (!table) return;
    buildHeaders();
    const grouped = groupIssuesByCell();

    const thead = `<thead><tr><th class="hv-rownum">Linha</th>${headers.map((h) => `<th>${escapeHtml(h)}</th>`).join('')}</tr></thead>`;
    const globals = renderGlobalIssues(grouped);

    const rowsHtml = records.map((record, idx) => {
      const rowNumber = record._row_number ?? idx + 1;
      const severity = rowIssueSeverity(rowNumber, grouped);
      const hidden = currentFilter !== 'all' && currentFilter !== severity;
      const raw = getRaw(record);
      const cells = headers.map((h) => {
        const value = raw[h] ?? record[canonicalizeHeader(h)] ?? '';
        const cellIssues = grouped.get(String(rowNumber) + '||' + h) || [];
        const messages = cellIssues.map((item) => `
          <span class="hv-cell-msg ${escapeHtml(item.severity)}">
            ${item.severity === 'error' ? 'Ã¢Å“â€“' : item.severity === 'warning' ? 'Ã¢Å¡Â ' : 'Ã¢â€œËœ'} ${escapeHtml(item.message)}${item.suggestion ? `<br><em>SugestÃƒÂ£o: ${escapeHtml(item.suggestion)}</em>` : ''}
          </span>`).join('');
        return `<td class="${cellClass(cellIssues)}"><div class="hv-cell-value">${escapeHtml(value)}</div>${messages ? `<div class="hv-cell-issues">${messages}</div>` : ''}</td>`;
      }).join('');
      return `<tr class="${hidden ? 'hv-row-muted' : ''}" ${hidden ? 'style="display:none"' : ''}><td class="hv-rownum">${escapeHtml(rowNumber)}</td>${cells}</tr>`;
    }).join('');

    table.innerHTML = thead + globals + `<tbody>${rowsHtml}</tbody>`;
  }

  function renderIssues() {
    const table = $('validator-issues');
    if (!table) return;
    const filtered = issues.filter((item) => item.severity !== 'info' || currentFilter === 'all');
    if (!filtered.length) {
      table.innerHTML = '<tbody><tr><td>Nenhum erro ou alerta encontrado.</td></tr></tbody>';
      return;
    }
    table.innerHTML = `
      <thead><tr><th>Linha</th><th>Campo</th><th>Tipo</th><th>CÃƒÂ³digo</th><th>Mensagem</th><th>Valor</th><th>SugestÃƒÂ£o</th></tr></thead>
      <tbody>
        ${filtered.map((item) => `
          <tr>
            <td>${escapeHtml(item.row_number ?? '')}</td>
            <td>${escapeHtml(item.column_name ?? '')}</td>
            <td><span class="hv-pill ${escapeHtml(item.severity)}">${escapeHtml(item.severity)}</span></td>
            <td>${escapeHtml(item.code)}</td>
            <td>${escapeHtml(item.message)}</td>
            <td>${escapeHtml(item.value ?? '')}</td>
            <td>${escapeHtml(item.suggestion ?? '')}</td>
          </tr>`).join('')}
      </tbody>`;
  }

  function renderResults(summary) {
    const result = $('validator-results');
    if (result) result.hidden = false;
    renderSummary(summary || {});
    renderSheet();
    renderIssues();
    if (result) result.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function safeFetch(url, options) {
    const response = await fetch(url, options);
    if (!response.ok) {
      let message = response.status + ' ' + response.statusText;
      try {
        const data = await response.json();
        message = data.detail || data.message || message;
      } catch (_) {}
      throw new Error(message);
    }
    return response;
  }

  function renderMap(geojson) {
    const container = $('validator-map');
    if (!container) return;
    const features = (geojson && geojson.features) || [];
    if (!features.length) {
      container.innerHTML = '<div class="hv-map-empty">Nenhum ponto com latitude e longitude foi encontrado na planilha validada.</div>';
      return;
    }

    const coords = features.map((f) => f.geometry && f.geometry.coordinates).filter((c) => Array.isArray(c) && c.length >= 2);
    const lons = coords.map((c) => Number(c[0])).filter(Number.isFinite);
    const lats = coords.map((c) => Number(c[1])).filter(Number.isFinite);
    let minLon = Math.min(...lons), maxLon = Math.max(...lons), minLat = Math.min(...lats), maxLat = Math.max(...lats);
    if (minLon === maxLon) { minLon -= 0.01; maxLon += 0.01; }
    if (minLat === maxLat) { minLat -= 0.01; maxLat += 0.01; }
    const padLon = (maxLon - minLon) * 0.12;
    const padLat = (maxLat - minLat) * 0.12;
    minLon -= padLon; maxLon += padLon; minLat -= padLat; maxLat += padLat;
    const x = (lon) => 60 + ((lon - minLon) / (maxLon - minLon)) * 880;
    const y = (lat) => 500 - ((lat - minLat) / (maxLat - minLat)) * 440;

    const points = features.map((f, idx) => {
      const c = f.geometry.coordinates;
      const props = f.properties || {};
      const cls = props.has_error ? 'hv-map-point-error' : 'hv-map-point-ok';
      const label = props.row_number ?? idx + 1;
      return `<g><circle class="${cls}" cx="${x(Number(c[0]))}" cy="${y(Number(c[1]))}" r="8"><title>Linha ${escapeHtml(label)} Ã‚Â· ${escapeHtml(props.genus || '')} ${escapeHtml(props.sp1 || '')}</title></circle><text x="${x(Number(c[0])) + 11}" y="${y(Number(c[1])) + 4}" font-size="12" font-weight="800" fill="#2E3B24">${escapeHtml(label)}</text></g>`;
    }).join('');

    const list = features.map((f) => {
      const c = f.geometry.coordinates;
      const p = f.properties || {};
      return `<li><b>Linha ${escapeHtml(p.row_number ?? '')}</b> Ã¢â‚¬â€ ${escapeHtml(p.genus ?? '')} ${escapeHtml(p.sp1 ?? '')}<small>${escapeHtml(c[1])}, ${escapeHtml(c[0])}${p.has_error ? ' Ã‚Â· com erro na linha' : ''}</small></li>`;
    }).join('');

    container.innerHTML = `
      <div class="hv-map-layout">
        <svg class="hv-map-svg" viewBox="0 0 1000 560" role="img" aria-label="Mapa simples dos pontos de coleta">
          <rect x="0" y="0" width="1000" height="560" fill="rgba(255,253,247,.82)"></rect>
          <g opacity=".34" stroke="#626A38" stroke-width="1">
            <line x1="60" y1="60" x2="60" y2="500"></line><line x1="60" y1="500" x2="940" y2="500"></line>
            <line x1="60" y1="280" x2="940" y2="280" stroke-dasharray="6 8"></line><line x1="500" y1="60" x2="500" y2="500" stroke-dasharray="6 8"></line>
          </g>
          <text x="60" y="36" fill="#6E1F1D" font-size="17" font-weight="900">Pontos de coleta</text>
          <text x="60" y="535" fill="#675F55" font-size="12">Longitude ${minLon.toFixed(3)} a ${maxLon.toFixed(3)}</text>
          <text x="770" y="535" fill="#675F55" font-size="12">Latitude ${minLat.toFixed(3)} a ${maxLat.toFixed(3)}</text>
          ${points}
        </svg>
        <div class="hv-map-list"><h4>Registros mapeados</h4><ol>${list}</ol></div>
      </div>`;
  }

  async function openMap() {
    if (!currentJobId) return;
    const panel = $('validator-map-panel');
    if (panel) panel.hidden = false;
    try {
      if (!currentGeojson) {
        const response = await safeFetch(`${API_BASE}/jobs/${currentJobId}/map.geojson`);
        currentGeojson = await response.json();
      }
      renderMap(currentGeojson);
      if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
      const container = $('validator-map');
      if (container) container.innerHTML = `<div class="hv-map-empty">NÃƒÂ£o foi possÃƒÂ­vel carregar o mapa: ${escapeHtml(error.message)}</div>`;
    }
  }

  // TSIINO_COLUMN_PREFLIGHT
  function normalizeColumnForPreflight(value) {
    return String(fixMojibake(value) ?? '')
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  }

  function arrayFromPreviewValue(value) {
    if (Array.isArray(value)) return value;
    if (value && typeof value === 'object') {
      return Object.entries(value).map(([key, val]) => {
        if (val && typeof val === 'object') return { key, name: key, ...val };
        return { key, name: key, label: String(val ?? key) };
      });
    }
    return [];
  }

  function targetNameForPreflight(col) {
    return String(col?.field ?? col?.name ?? col?.key ?? col?.header ?? col?.label ?? '').trim();
  }

  function sourceHeaderForPreflight(col) {
    return String(col?.header ?? col?.name ?? col?.field ?? col?.key ?? col?.label ?? '').trim();
  }

  function mappingHasTargetForPreflight(mapping, targetName) {
    if (!mapping || typeof mapping !== 'object') return false;
    const direct = mapping[targetName];
    if (direct !== undefined && direct !== null && direct !== '') return true;
    const wanted = normalizeColumnForPreflight(targetName);
    for (const [key, value] of Object.entries(mapping)) {
      if (normalizeColumnForPreflight(key) !== wanted) continue;
      if (value === undefined || value === null || value === '') return false;
      if (typeof value === 'object') {
        return Boolean(value.source_index || value.index || value.source || value.header || value.name || value.key);
      }
      return String(value).trim() !== '';
    }
    return false;
  }

  function previewNeedsColumnMapper(data) {
    const sourceColumns = arrayFromPreviewValue(data?.source_columns || data?.columns || data?.input_columns || data?.headers);
    const targetColumns = arrayFromPreviewValue(data?.target_columns || data?.standard_columns || data?.inpa_columns || data?.template_columns);
    if (!sourceColumns.length || !targetColumns.length) return false;

    const sourceNames = new Set(sourceColumns.map((col) => normalizeColumnForPreflight(sourceHeaderForPreflight(col))).filter(Boolean));
    const targetNames = targetColumns.map(targetNameForPreflight).filter(Boolean);
    const requiredNames = targetColumns.filter((col) => Boolean(col.required)).map(targetNameForPreflight).filter(Boolean);
    const mapping = data?.suggested_mapping || data?.mapping || data?.auto_mapping || {};

    const exactTargetCount = targetNames.filter((name) => sourceNames.has(normalizeColumnForPreflight(name))).length;
    const exactRequiredCount = requiredNames.filter((name) => sourceNames.has(normalizeColumnForPreflight(name))).length;
    const mappedRequiredCount = requiredNames.filter((name) => mappingHasTargetForPreflight(mapping, name)).length;

    const enoughRequired = requiredNames.length ? exactRequiredCount >= Math.max(1, requiredNames.length - 1) : false;
    const enoughTemplateShape = exactTargetCount >= Math.min(targetNames.length, 10);
    const looksAlreadyInpa = enoughRequired && enoughTemplateShape;

    // If it is not already a BRAHMS/INPA header, open the mapper even when aliases were recognized.
    // That gives the user a converted file and then an annotated converted file after validation.
    return !looksAlreadyInpa && (mappedRequiredCount > 0 || exactTargetCount > 0 || sourceColumns.length > 0);
  }

  async function maybeOpenColumnMapperBeforeValidation(file) {
    const mapper = window.TsiinoConverterIntegration;
    if (!mapper || typeof mapper.openMapper !== 'function' || !file) return false;
    try {
      const formData = new FormData();
      formData.append('file', file);
      const sheetName = $('sheet-name')?.value?.trim();
      if (sheetName) formData.append('sheet_name', sheetName);
      const response = await fetch(`${API_BASE}/converter/preview`, { method: 'POST', body: formData });
      if (!response.ok) return false;
      const data = await response.json();
      if (!previewNeedsColumnMapper(data)) return false;
      setStatus('Detectei colunas fora do padrao INPA/BRAHMS. Confira o mapeamento sugerido; depois baixe a convertida ou valide a convertida para gerar a anotada.', 'warning');
      await mapper.openMapper(file, 'Colunas fora do padrao INPA/BRAHMS detectadas automaticamente. Confira as sugestoes e escolha: baixar convertida sem anotacao ou aplicar mapeamento e validar.');
      return true;
    } catch (error) {
      console.warn('[Tsiino] Preflight do mapeador falhou; seguindo para validacao direta.', error);
      return false;
    }
  }

  function issuesIndicateSchemaProblem(items) {
    return Array.isArray(items) && items.some((item) => {
      const code = String(item?.code || item?.type || '').toUpperCase();
      const text = String(item?.message || item?.detail || item?.field || '');
      return /SCHEMA|HEADER|COLUMN|COLUNA|REQUIRED|OBRIGAT|PADRAO|PADRÃO/.test(code) || /coluna obrigat|coluna ausente|required column|missing column|cabec|cabeç|padrao|padrão/i.test(text);
    });
  }

  async function maybeOpenMapperFromIssues(items) {
    const mapper = window.TsiinoConverterIntegration;
    const file = $('spreadsheet-file')?.files?.[0];
    if (!mapper || typeof mapper.openMapper !== 'function' || !file || !issuesIndicateSchemaProblem(items)) return false;
    setStatus('A planilha tem colunas obrigatorias ausentes no padrao INPA/BRAHMS. Abrindo o mapeador para converter antes de validar.', 'warning');
    await mapper.openMapper(file, 'A validacao encontrou colunas obrigatorias ausentes. Mapeie as colunas da sua planilha para o padrao INPA e valide a versao convertida.');
    return true;
  }


  async function validateSpreadsheet(event) {
    event.preventDefault();
    const fileInput = $('spreadsheet-file');
    const file = fileInput && fileInput.files ? fileInput.files[0] : null;
    if (!file) {
      setStatus('Selecione uma planilha .xlsx ou .xlsm.', 'error');
      return;
    }

    
    if (await maybeOpenColumnMapperBeforeValidation(file)) return;

    setBusy(true);
    configureDownload(null);
    configureMap(null);
    setStatus('Enviando e validando a planilha...', '');

    try {
      const form = new FormData();
      form.append('file', file);
      form.append('validate_taxonomy', $('validate-taxonomy')?.checked ? 'true' : 'false');
      form.append('validate_geography', $('validate-geography')?.checked ? 'true' : 'false');
      const sheetName = ($('sheet-name')?.value || '').trim();
      if (sheetName) form.append('sheet_name', sheetName);

      const upload = await safeFetch(`${API_BASE}/upload`, { method: 'POST', body: form });
      const uploadData = await upload.json();
      currentJobId = uploadData.job_id;
      if (!currentJobId) throw new Error('A API nÃƒÂ£o retornou job_id.');

      const [summaryResponse, issuesResponse, tableResponse] = await Promise.all([
        safeFetch(`${API_BASE}/jobs/${currentJobId}`),
        safeFetch(`${API_BASE}/jobs/${currentJobId}/issues`),
        safeFetch(`${API_BASE}/jobs/${currentJobId}/table`)
      ]);

      const summary = await summaryResponse.json();
      issues = (await issuesResponse.json()).filter((item) => !["TAXONOMY_LOCAL_FIXTURE", "GEOGRAPHY_LOCAL_FIXTURE"].includes(item.code));
      records = await tableResponse.json();
      if (await maybeOpenMapperFromIssues(issues)) return;
      currentGeojson = null;
      currentFilter = 'all';
      document.querySelectorAll('.hv-filter').forEach((b) => b.classList.toggle('is-active', b.dataset.filter === 'all'));
      renderResults(summary);
      configureDownload(currentJobId);
      const annotatedLink = $('download-annotated');
      if (annotatedLink) annotatedLink.textContent = options.converted ? 'Baixar planilha convertida e anotada' : 'Baixar planilha anotada';
      configureMap(currentJobId);
      setStatus('ValidaÃƒÂ§ÃƒÂ£o concluÃƒÂ­da. Corrija as cÃƒÂ©lulas destacadas ou baixe a cÃƒÂ³pia .xlsx anotada.', 'ok');
    } catch (error) {
      const mappingFile = document.getElementById('spreadsheet-file')?.files?.[0];
      const message = String(error?.message || error || 'Erro desconhecido');
      const hasInternalMapper = Boolean(window.TsiinoConverterIntegration?.openAfterValidationFailure);

      // Se a API rejeitar a planilha por cabeÃ§alho/estrutura, nÃ£o recarregue a pÃ¡gina:
      // abra o mapeador interno e deixe a usuÃ¡ria converter + validar no mesmo fluxo.
      if (mappingFile && hasInternalMapper) {
        try {
          setStatus('A planilha nÃ£o foi reconhecida no padrÃ£o INPA/BRAHMS. Abrindo o mapeador de colunas.', 'warning');
          await window.TsiinoConverterIntegration.openAfterValidationFailure(error);
          return;
        } catch (mapperError) {
          console.warn('[Tsiino] O mapeador interno nÃ£o conseguiu abrir.', mapperError);
        }
      }

      setStatus(`NÃ£o foi possÃ­vel validar: ${escapeHtml(message)}. Em teste local, confirme se a API estÃ¡ rodando em http://127.0.0.1:8000. No site publicado, a API deve responder em https://api.tsiinohiiwiida.net/health.`, 'error');
    } finally {
      setBusy(false);
    }
  }

  function setupFilters() {
    document.querySelectorAll('.hv-filter').forEach((button) => {
      button.addEventListener('click', () => {
        currentFilter = button.dataset.filter || 'all';
        document.querySelectorAll('.hv-filter').forEach((b) => b.classList.remove('is-active'));
        button.classList.add('is-active');
        renderSheet();
      });
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    const form = $('herb-validator-form');
    if (form) form.addEventListener('submit', validateSpreadsheet);
    setupFilters();
    const mapButton = $('map-button');
    if (mapButton) mapButton.addEventListener('click', openMap);
    const mapClose = $('map-close');
    if (mapClose) mapClose.addEventListener('click', () => { const panel = $('validator-map-panel'); if (panel) panel.hidden = true; });
  });

  window.TsiinoValidatorBridge = {
    apiBase: API_BASE,
    setStatus,
    setBusy,
    async applyJob(jobId, options = {}) {
      currentJobId = jobId;
      const [summaryResponse, issuesResponse, tableResponse] = await Promise.all([
        safeFetch(`${API_BASE}/jobs/${currentJobId}`),
        safeFetch(`${API_BASE}/jobs/${currentJobId}/issues`),
        safeFetch(`${API_BASE}/jobs/${currentJobId}/table`)
      ]);
      const summary = await summaryResponse.json();
      issues = (await issuesResponse.json()).filter((item) => !["TAXONOMY_LOCAL_FIXTURE", "GEOGRAPHY_LOCAL_FIXTURE"].includes(item.code));
      records = await tableResponse.json();
      currentGeojson = null;
      
      const download = $('download-annotated');
      if (download) {
        download.href = `${API_BASE}/jobs/${currentJobId}/download.xlsx`;
        download.classList.remove('is-disabled');
        download.setAttribute('aria-disabled', 'false');
        download.textContent = options.converted ? 'Baixar planilha convertida e anotada' : 'Baixar planilha anotada';
      }
      const mapButton = $('map-button');
      if (mapButton) {
        mapButton.classList.remove('is-disabled');
        mapButton.setAttribute('aria-disabled', 'false');
      }
      setStatus(options.statusMessage || 'ValidaÃ§Ã£o concluÃ­da. Corrija as cÃ©lulas destacadas ou baixe a cÃ³pia .xlsx anotada.', 'ok');
      return summary;
    },
    async validateFile(file, options = {}) {
      if (!file) throw new Error('Nenhum arquivo informado para validaÃ§Ã£o.');
      setBusy(true);
      setStatus(options.loadingMessage || 'Validando planilha convertida...', 'loading');
      try {
        const formData = new FormData();
        formData.append('file', file);
        const collection = $('collection')?.value || 'INPA';
        const sheetName = options.sheetName ?? ($('sheet-name')?.value || '');
        formData.append('collection', collection);
        if (sheetName) formData.append('sheet_name', sheetName);
        formData.append('validate_taxonomy', $('validate-taxonomy')?.checked ? 'true' : 'false');
        formData.append('validate_geography', $('validate-geography')?.checked ? 'true' : 'false');
        const uploadResponse = await safeFetch(`${API_BASE}/jobs`, { method: 'POST', body: formData });
        const upload = await uploadResponse.json();
        const jobId = upload.job_id || upload.id || upload.jobId;
        if (!jobId) throw new Error('A API nÃ£o retornou job_id.');
        return await this.applyJob(jobId, options);
      } finally {
        setBusy(false);
      }
    }
  };

})();





