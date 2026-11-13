/* Validador de planilha de herbário — Tsiino Hiiwiida
 *
 * Módulo único (substitui herb-converter, herb-mapper-loader, herb-results-table, herb-standard-first-flow,
 * herb-upload-formdata, herb-issue-geography, herb-mapper-result-flow e herb-validator-flow).
 *
 * Fluxo: acorda a API -> /converter/preview -> (padrão INPA? /upload : mapeador -> /validate_mapped)
 *        -> renderiza o resultado direto da resposta (sem requisições extras).
 *
 * API: produção em https://api.tsiinohiiwiida.net (Cloudflare Worker -> Hugging Face Space);
 *      em localhost usa http://127.0.0.1:8000. Para forçar outra base: ?api=https://... na URL.
 */
(function () {
  'use strict';

  // ---------------------------------------------------------------- configuração
  const PROD_API = 'https://api.tsiinohiiwiida.net';
  const LOCAL_API = 'http://127.0.0.1:8000';
  const host = window.location.hostname;
  const isLocal = !host || host === 'localhost' || host === '127.0.0.1';
  const apiOverride = new URLSearchParams(window.location.search).get('api') || window.TSIINO_VALIDATOR_API;
  const API_ROOT = String(apiOverride || (isLocal ? LOCAL_API : PROD_API)).replace(/\/+$/, '');
  const API = API_ROOT + '/api/validator';
  const PAGE_SIZE = 200;
  const WAKE_TIMEOUT_MS = 150000;

  const SEV_LABEL = { error: 'Erro', warning: 'Alerta', info: 'Nota' };
  const SEV_RANK = { error: 0, warning: 1, info: 2 };

  const state = {
    busy: false,
    file: null,
    result: null,        // resposta de /upload ou /validate_mapped
    filter: 'all',
    code: '',
    showInfo: true,
    page: 1,
    mapper: null,        // { preview, mapping, undo: [] }
    map: null
  };

  // ---------------------------------------------------------------- utilidades
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  function setStatus(html, kind) {
    const el = $('validator-status');
    if (!el) return;
    el.innerHTML = html;
    el.className = 'hv-status' + (kind ? ' is-' + kind : '');
  }

  function setBusy(flag, label) {
    state.busy = flag;
    const btn = $('validate-button');
    if (btn) {
      btn.disabled = flag;
      btn.textContent = flag ? (label || 'Processando...') : 'Validar planilha';
    }
    document.querySelectorAll('[data-mapper-action]').forEach((b) => { b.disabled = flag; });
  }

  function selectedFile() {
    const input = $('spreadsheet-file');
    return input && input.files && input.files[0] ? input.files[0] : null;
  }

  function options() {
    return {
      sheet: ($('sheet-name')?.value || '').trim(),
      taxonomy: $('validate-taxonomy') ? $('validate-taxonomy').checked : true,
      geography: $('validate-geography') ? $('validate-geography').checked : true,
      collection: $('collection')?.value || 'INPA'
    };
  }

  function formFor(file, extra = {}) {
    const fd = new FormData();
    fd.append('file', file, file.name || 'planilha.xlsx');
    const o = options();
    if (o.sheet) fd.append('sheet_name', o.sheet);
    fd.append('validate_taxonomy', o.taxonomy ? 'true' : 'false');
    fd.append('validate_geography', o.geography ? 'true' : 'false');
    Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
    return fd;
  }

  class ApiError extends Error {
    constructor(message, status, data) { super(message); this.status = status; this.data = data; }
  }

  async function request(path, init = {}, { asBlob = false } = {}) {
    let res;
    try {
      res = await fetch(API + path, init);
    } catch (err) {
      throw new ApiError('Sem conexão com o servidor de validação. Verifique a internet e tente de novo.', 0);
    }
    if (!res.ok) {
      let data = null;
      try { data = await res.json(); } catch (_) { /* resposta não JSON */ }
      const detail = data && (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data));
      throw new ApiError(detail || `Erro ${res.status} no servidor.`, res.status, data);
    }
    return asBlob ? res.blob() : res.json();
  }

  // Free Spaces hibernam: espera o /health responder antes de enviar a planilha.
  async function ensureAwake() {
    const started = Date.now();
    let attempt = 0;
    while (Date.now() - started < WAKE_TIMEOUT_MS) {
      attempt += 1;
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 10000);
      try {
        const res = await fetch(API_ROOT + '/health', { signal: ctrl.signal, cache: 'no-store' });
        clearTimeout(timer);
        if (res.ok) return true;
      } catch (_) {
        clearTimeout(timer);
      }
      const secs = Math.round((Date.now() - started) / 1000);
      setStatus(`Acordando o servidor de validação (${secs}s)… Após um período sem uso, ele leva até 1–2 minutos para iniciar.`, 'warning');
      await sleep(Math.min(3000 + attempt * 1000, 8000));
    }
    throw new ApiError('O servidor de validação não respondeu. Tente novamente em alguns minutos.', 503);
  }

  function downloadBlob(blob, filename) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  // ---------------------------------------------------------------- fluxo principal
  async function onSubmit(event) {
    event.preventDefault();
    if (state.busy) return;
    const file = selectedFile();
    if (!file) { setStatus('Selecione uma planilha .xlsx ou .xlsm.', 'error'); return; }
    if (!/\.(xlsx|xlsm)$/i.test(file.name)) {
      setStatus('Formato não suportado. Salve a planilha como .xlsx (Excel) e envie de novo.', 'error');
      return;
    }
    state.file = file;
    resetResults();
    setBusy(true, 'Processando...');
    try {
      await ensureAwake();
      setStatus('Lendo a estrutura da planilha...', '');
      const preview = await request('/converter/preview', { method: 'POST', body: formFor(file) });
      if (options().collection === 'CUSTOM' || !preview.detected_standard) {
        openMapper(preview);
        setStatus(
          options().collection === 'CUSTOM'
            ? 'Confira o mapeamento das colunas para o padrão INPA/BRAHMS.'
            : 'A planilha não está no padrão técnico INPA/BRAHMS. Confira as correspondências sugeridas abaixo e clique em <strong>Aplicar mapeamento e validar</strong>.',
          'warning'
        );
        return;
      }
      closeMapper();
      setStatus(`Planilha no padrão INPA/BRAHMS (aba <strong>${esc(preview.sheet_name)}</strong>). Validando ${esc(file.name)}...`, '');
      const result = await request('/upload', { method: 'POST', body: formFor(file) });
      showResult(await hydrate(result));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  function fail(err) {
    console.error('[Tsiino validador]', err);
    const msg = err instanceof ApiError ? err.message : String(err && err.message || err);
    setStatus(`Não foi possível concluir: ${esc(msg)}`, 'error');
  }

  // ---------------------------------------------------------------- mapeador
  function fieldDefs() {
    return (state.mapper && state.mapper.preview.fields) || [];
  }

  function colLetter(n) { let s = ''; while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); } return s; }

  function openMapper(preview) {
    state.mapper = { preview, mapping: { ...(preview.suggested_mapping || {}) }, undo: [] };
    let panel = $('tsiino-mapper');
    if (!panel) {
      panel = document.createElement('section');
      panel.id = 'tsiino-mapper';
      panel.className = 'hv-panel hv-mapper-v20';
      panel.setAttribute('aria-label', 'Mapeamento de colunas');
      const anchor = $('enviar-planilha');
      anchor.parentNode.insertBefore(panel, anchor.nextSibling);
    }
    panel.hidden = false;
    renderMapper();
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function closeMapper() {
    const panel = $('tsiino-mapper');
    if (panel) panel.hidden = true;
    state.mapper = null;
  }

  function pushUndo() {
    state.mapper.undo.push(JSON.stringify(state.mapper.mapping));
    if (state.mapper.undo.length > 50) state.mapper.undo.shift();
  }

  function setMapping(field, column) {
    const m = state.mapper.mapping;
    pushUndo();
    if (!column) { delete m[field]; renderMapper(); return; }
    Object.keys(m).forEach((f) => { if (m[f] === column) delete m[f]; });  // uma coluna -> um campo
    m[field] = column;
    renderMapper();
  }

  function renderMapper() {
    const panel = $('tsiino-mapper');
    const mp = state.mapper;
    if (!panel || !mp) return;
    const { preview, mapping } = mp;
    const columns = preview.source_columns || [];
    const used = new Set(Object.values(mapping));
    const missing = fieldDefs().filter((f) => f.required && !mapping[f.key]).map((f) => f.key);
    const rows = (preview.rows || []).slice(0, 12);
    const letterOf = Object.fromEntries(columns.map((c) => [c.name, c.letter]));

    const optionsHtml = (current) => ['<option value="">— sem coluna —</option>']
      .concat(columns.map((c) => `<option value="${esc(c.name)}"${c.name === current ? ' selected' : ''}>${esc(c.letter)} · ${esc(c.name)}</option>`))
      .join('');

    let head = '<tr><th scope="col">Padrão<br>INPA</th>';
    let slots = '<tr class="hv-mapper-v20-source-row"><th scope="row">Sua<br>planilha</th>';
    fieldDefs().forEach((f) => {
      const req = f.required ? ' <abbr title="obrigatório" class="tsiino-req">*</abbr>' : '';
      head += `<th scope="col" class="${missing.includes(f.key) ? 'tsiino-missing' : ''}"><span class="hv-mapper-v20-code">${esc(f.code)}</span>${req}` +
        `<button type="button" class="hv-mapper-v20-help" data-help="${esc(f.key)}" aria-label="Ajuda: ${esc(f.label)}">?</button>` +
        `<small class="tsiino-field-label">${esc(f.label)}</small></th>`;
      slots += `<td><div class="hv-mapper-v20-slot" data-field="${esc(f.key)}">` +
        `<select class="tsiino-map-select" data-field="${esc(f.key)}" aria-label="Coluna para ${esc(f.label)}">${optionsHtml(mapping[f.key])}</select></div></td>`;
    });
    head += '</tr>';
    slots += '</tr>';
    const body = rows.map((r) => '<tr><th scope="row">Linha ' + esc(r._row_number) + '</th>' +
      fieldDefs().map((f) => `<td><div class="hv-mapper-v20-data">${esc(mapping[f.key] ? r[mapping[f.key]] : '')}</div></td>`).join('') + '</tr>').join('');

    const unmapped = columns.filter((c) => !used.has(c.name));
    panel.innerHTML = `
      <div class="hv-mapper-v20-head">
        <div>
          <h3>Mapear colunas para o padrão INPA/BRAHMS</h3>
          <p>Escolha, para cada campo INPA, a coluna correspondente da sua planilha (ou arraste uma coluna sem destino até o campo).
             As linhas abaixo mostram os dados reais (aba <strong>${esc(preview.sheet_name)}</strong>, cabeçalho na linha ${esc(preview.header_row)}).</p>
        </div>
        <button type="button" class="hv-secondary" data-mapper-action="close">Fechar</button>
      </div>
      <div class="hv-mapper-v20-status" role="status">
        ${missing.length ? `Campos obrigatórios sem coluna: <strong>${missing.map(esc).join(', ')}</strong>. Eles serão apontados como erro na validação.` : 'Todos os campos obrigatórios têm coluna correspondente.'}
      </div>
      <div class="hv-mapper-v20-tools">
        <button type="button" class="hv-secondary" data-mapper-action="undo" ${mp.undo.length ? '' : 'disabled'}>Desfazer</button>
        <button type="button" class="hv-secondary" data-mapper-action="reset">Restaurar sugestões</button>
        <button type="button" class="hv-secondary" data-mapper-action="clear">Limpar tudo</button>
      </div>
      <div class="hv-mapper-v20-tablewrap"><table class="hv-mapper-v20-grid"><thead>${head}</thead><tbody>${slots}${body}</tbody></table></div>
      ${unmapped.length ? `<div class="tsiino-unmapped"><strong>Colunas sem destino (${unmapped.length}):</strong> ${unmapped.map((c) =>
        `<span class="hv-mapper-v20-chip" draggable="true" data-column="${esc(c.name)}" title="${esc((c.samples || []).join(' · '))}"><span class="hv-mapper-v20-letter">${esc(c.letter || letterOf[c.name] || '')}</span><span class="hv-mapper-v20-chip-text">${esc(c.name)}</span></span>`).join(' ')}</div>` : ''}
      <div class="hv-mapper-v20-actions">
        <button type="button" class="hv-primary" data-mapper-action="validate">Aplicar mapeamento e validar</button>
        <button type="button" class="hv-secondary" data-mapper-action="download">Baixar convertida (sem anotação)</button>
      </div>`;
  }

  function onMapperEvent(event) {
    const panel = $('tsiino-mapper');
    if (!panel || !panel.contains(event.target) || !state.mapper) return;
    if (event.type === 'change' && event.target.matches('select.tsiino-map-select')) {
      setMapping(event.target.dataset.field, event.target.value);
      return;
    }
    if (event.type !== 'click') return;
    const help = event.target.closest('[data-help]');
    if (help) { showHelp(help); return; }
    const btn = event.target.closest('[data-mapper-action]');
    if (!btn || state.busy) return;
    const action = btn.dataset.mapperAction;
    const mp = state.mapper;
    if (action === 'close') closeMapper();
    else if (action === 'undo' && mp.undo.length) { mp.mapping = JSON.parse(mp.undo.pop()); renderMapper(); }
    else if (action === 'reset') { pushUndo(); mp.mapping = { ...(mp.preview.suggested_mapping || {}) }; renderMapper(); }
    else if (action === 'clear') { pushUndo(); mp.mapping = {}; renderMapper(); }
    else if (action === 'validate') validateMapped();
    else if (action === 'download') downloadConverted();
  }

  function showHelp(button) {
    document.querySelectorAll('.hv-mapper-v20-popup').forEach((p) => p.remove());
    const f = fieldDefs().find((x) => x.key === button.dataset.help);
    if (!f) return;
    const box = document.createElement('div');
    box.className = 'hv-mapper-v20-popup';
    box.setAttribute('role', 'tooltip');
    box.innerHTML = `<div class="hv-mapper-v20-popup-code">${esc(f.code)}${f.required ? ' · obrigatório' : ''}</div><strong>${esc(f.label)}</strong><p>${esc(f.help)}</p>`;
    document.body.appendChild(box);
    const r = button.getBoundingClientRect();
    box.style.position = 'fixed';
    box.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 380)) + 'px';
    box.style.top = Math.min(r.bottom + 8, window.innerHeight - 200) + 'px';
  }

  function onDrag(event) {
    if (!state.mapper) return;
    const chip = event.target.closest && event.target.closest('.hv-mapper-v20-chip[data-column]');
    const slot = event.target.closest && event.target.closest('.hv-mapper-v20-slot[data-field]');
    if (event.type === 'dragstart' && chip) event.dataTransfer.setData('text/plain', chip.dataset.column);
    else if (event.type === 'dragover' && slot) { event.preventDefault(); slot.classList.add('is-drop'); }
    else if (event.type === 'dragleave' && slot) slot.classList.remove('is-drop');
    else if (event.type === 'drop' && slot) {
      event.preventDefault();
      const col = event.dataTransfer.getData('text/plain');
      if (col) setMapping(slot.dataset.field, col);
    }
  }

  async function validateMapped() {
    const file = state.file || selectedFile();
    if (!file || !state.mapper) return;
    setBusy(true, 'Validando...');
    setStatus('Convertendo para o padrão INPA/BRAHMS e validando...', '');
    try {
      await ensureAwake();
      const fd = formFor(file, { mapping: JSON.stringify(state.mapper.mapping) });
      const result = await request('/validate_mapped', { method: 'POST', body: fd });
      closeMapper();
      showResult(await hydrate(result));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function downloadConverted() {
    const file = state.file || selectedFile();
    if (!file || !state.mapper) return;
    setBusy(true, 'Convertendo...');
    try {
      await ensureAwake();
      const blob = await request('/converter/convert', { method: 'POST', body: formFor(file, { mapping: JSON.stringify(state.mapper.mapping) }) }, { asBlob: true });
      downloadBlob(blob, file.name.replace(/\.[^.]+$/, '') + '_convertida_INPA.xlsx');
      setStatus('Planilha convertida baixada. Você ainda pode validar com o botão <strong>Aplicar mapeamento e validar</strong>.', 'ok');
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  // ---------------------------------------------------------------- resultados
  function resetResults() {
    state.result = null;
    state.map = null;
    const results = $('validator-results');
    if (results) results.hidden = true;
    const panel = $('validator-map-panel');
    if (panel) panel.hidden = true;
    configureDownloads(null);
  }

  function configureDownloads(result) {
    const link = $('download-annotated');
    if (link) {
      if (result) {
        link.href = `${API}/jobs/${encodeURIComponent(result.job_id)}/download.xlsx`;
        link.removeAttribute('download');
        link.textContent = result.summary.converted_from ? 'Baixar planilha convertida e anotada' : 'Baixar planilha anotada';
        link.classList.remove('is-disabled');
        link.setAttribute('aria-disabled', 'false');
      } else {
        link.href = '#';
        link.classList.add('is-disabled');
        link.setAttribute('aria-disabled', 'true');
      }
    }
    const map = $('map-button');
    if (map) {
      map.disabled = !result;
      map.classList.toggle('is-disabled', !result);
      map.setAttribute('aria-disabled', result ? 'false' : 'true');
    }
    const csv = $('download-issues-csv');
    if (csv) csv.disabled = !result;
  }

  // Compatibilidade com a API anterior (que devolvia só job_id em /upload).
  async function hydrate(result) {
    if (result.summary && result.issues && result.table) return result;
    const id = encodeURIComponent(result.job_id);
    const [summary, issues, table] = await Promise.all([
      request(`/jobs/${id}`), request(`/jobs/${id}/issues`), request(`/jobs/${id}/table`)
    ]);
    const columns = [];
    table.forEach((r) => Object.keys(r._raw || {}).forEach((k) => { if (!columns.includes(k)) columns.push(k); }));
    const fieldToHeader = {};
    columns.forEach((c) => { const k = c.trim(); if (!fieldToHeader[k]) fieldToHeader[k] = c; });
    summary.info_count = summary.info_count ?? issues.filter((i) => i.severity === 'info').length;
    summary.rows_with_errors = summary.rows_with_errors ?? new Set(issues.filter((i) => i.severity === 'error').map((i) => i.row_number)).size;
    return { ...result, summary, issues, table, header: { columns, field_to_header: fieldToHeader } };
  }

  function prepareResult(result) {
    const fieldToHeader = (result.header && result.header.field_to_header) || {};
    const columns = (result.header && result.header.columns) || [];
    const headerToField = {};
    Object.entries(fieldToHeader).forEach(([f, h]) => { headerToField[h] = f; });
    const byCell = new Map();
    const byRow = new Map();
    const global = [];
    result.issues.forEach((it) => {
      if (it.row_number == null) { global.push(it); return; }
      const header = fieldToHeader[it.column_name] || it.column_name || '';
      const key = it.row_number + '|' + header;
      if (!byCell.has(key)) byCell.set(key, []);
      byCell.get(key).push(it);
      if (!byRow.has(it.row_number)) byRow.set(it.row_number, []);
      byRow.get(it.row_number).push(it);
    });
    // Ocorrências em campos sem coluna na planilha aparecem numa coluna extra.
    const known = new Set(columns);
    const orphanRows = new Set();
    byCell.forEach((items, key) => { if (!known.has(key.slice(key.indexOf('|') + 1))) orphanRows.add(Number(key.split('|')[0])); });
    result._view = { columns, headerToField, fieldToHeader, byCell, byRow, global, hasOrphans: orphanRows.size > 0 };
    return result;
  }

  function rowSeverity(row) {
    const items = state.result._view.byRow.get(row) || [];
    let best = 'clear';
    items.forEach((i) => { if (SEV_RANK[i.severity] < (SEV_RANK[best] ?? 9)) best = i.severity; });
    return best;
  }

  function showResult(result) {
    state.result = prepareResult(result);
    state.filter = 'all';
    state.code = '';
    state.page = 1;
    state.map = null;
    const results = $('validator-results');
    if (results) results.hidden = false;
    renderSummary();
    renderCodeFilter();
    renderSheet();
    renderIssueList();
    configureDownloads(result);
    const s = result.summary;
    const verdict = s.error_count
      ? `${plural(s.error_count, 'erro', 'erros')} em ${plural(s.rows_with_errors, 'linha', 'linhas')} precisam de correção antes do depósito.`
      : 'Nenhum erro encontrado. Revise os alertas antes do depósito.';
    setStatus(`Validação concluída em ${esc(s.elapsed_seconds)}s: ${esc(verdict)}`, s.error_count ? 'warning' : 'ok');
    results && results.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function renderSummary() {
    const s = state.result.summary;
    const node = $('validator-summary');
    if (!node) return;
    const card = (label, value, hint) => `<div class="hv-card-number"><span>${label}</span><strong>${value ?? 0}</strong><small>${hint}</small></div>`;
    node.innerHTML =
      card('Linhas', s.total_rows, `Aba “${esc(s.sheet_name)}”${s.converted_from ? ' (convertida)' : ''}`) +
      card('Linhas com erro', s.rows_with_errors, 'Precisam de correção') +
      card('Erros', s.error_count, 'Impedem o depósito') +
      card('Alertas', s.warning_count, 'Exigem revisão curatorial') +
      card('Notas', s.info_count, 'Sugestões de padronização');
    const counts = { all: s.total_rows, error: 0, warning: 0, clear: 0 };
    state.result.table.forEach((r) => {
      const sev = rowSeverity(r._row_number);
      if (sev === 'error') counts.error += 1;
      else if (sev === 'warning') counts.warning += 1;
      else counts.clear += 1;
    });
    document.querySelectorAll('.hv-filter[data-filter]').forEach((b) => {
      const base = b.dataset.label || (b.dataset.label = b.textContent.trim());
      b.textContent = `${base} (${counts[b.dataset.filter] ?? 0})`;
      b.classList.toggle('is-active', b.dataset.filter === state.filter);
    });
  }

  function renderCodeFilter() {
    const sel = $('validator-code-filter');
    if (!sel) return;
    const counts = new Map();
    state.result.issues.forEach((i) => {
      const k = i.code;
      if (!counts.has(k)) counts.set(k, { n: 0, severity: i.severity, message: i.message });
      counts.get(k).n += 1;
    });
    const items = [...counts.entries()].sort((a, b) => (SEV_RANK[a[1].severity] - SEV_RANK[b[1].severity]) || b[1].n - a[1].n);
    sel.innerHTML = '<option value="">Todas as ocorrências</option>' + items.map(([code, v]) =>
      `<option value="${esc(code)}">${esc(SEV_LABEL[v.severity] || v.severity)} · ${esc(code)} (${v.n})</option>`).join('');
    sel.value = '';
  }

  function visibleRows() {
    const view = state.result._view;
    return state.result.table.filter((r) => {
      const row = r._row_number;
      if (state.filter !== 'all') {
        const sev = rowSeverity(row);
        if (state.filter === 'clear' ? (sev === 'error' || sev === 'warning') : sev !== state.filter) return false;
      }
      if (state.code) return (view.byRow.get(row) || []).some((i) => i.code === state.code);
      return true;
    });
  }

  function cellIssues(row, header) {
    const items = state.result._view.byCell.get(row + '|' + header) || [];
    return state.showInfo ? items : items.filter((i) => i.severity !== 'info');
  }

  function messageHtml(it) {
    return `<span class="hv-cell-msg ${esc(it.severity)}" title="${esc(it.code)}${it.source ? ' · ' + esc(it.source) : ''}">` +
      `${esc(SEV_LABEL[it.severity] || '')}: ${esc(it.message)}${it.suggestion ? `<br><em>Sugestão: ${esc(it.suggestion)}</em>` : ''}</span>`;
  }

  function renderSheet() {
    const table = $('validator-sheet');
    if (!table) return;
    const view = state.result._view;
    const cols = view.columns;
    const rows = visibleRows();
    const shown = rows.slice(0, state.page * PAGE_SIZE);
    const head = '<thead><tr><th class="hv-rownum" scope="col">Linha</th>' + cols.map((h) => {
      const field = view.headerToField[h];
      return `<th scope="col">${esc(h)}${field && field !== h ? `<br><small class="tsiino-field-tag">${esc(field)}</small>` : ''}</th>`;
    }).join('') + (view.hasOrphans ? '<th scope="col">Campos ausentes</th>' : '') + '</tr></thead>';

    const known = new Set(cols);
    const body = shown.map((r) => {
      const row = r._row_number;
      const raw = r._raw || {};
      const cells = cols.map((h) => {
        const items = cellIssues(row, h);
        const sev = items.length ? (items.some((i) => i.severity === 'error') ? 'error' : items.some((i) => i.severity === 'warning') ? 'warning' : 'info') : '';
        return `<td class="${sev ? 'hv-cell-' + sev : ''}"><div class="hv-cell-value">${esc(raw[h])}</div>` +
          (items.length ? `<div class="hv-cell-issues">${items.map(messageHtml).join('')}</div>` : '') + '</td>';
      }).join('');
      let orphan = '';
      if (view.hasOrphans) {
        const items = (view.byRow.get(row) || []).filter((i) => !known.has(view.fieldToHeader[i.column_name] || i.column_name) && (state.showInfo || i.severity !== 'info'));
        orphan = `<td class="${items.some((i) => i.severity === 'error') ? 'hv-cell-error' : items.length ? 'hv-cell-warning' : ''}">` +
          (items.length ? `<div class="hv-cell-issues">${items.map((i) => messageHtml({ ...i, message: `[${i.column_name}] ${i.message}` })).join('')}</div>` : '') + '</td>';
      }
      return `<tr id="hv-row-${esc(row)}" data-severity="${rowSeverity(row)}"><td class="hv-rownum">${esc(row)}</td>${cells}${orphan}</tr>`;
    }).join('');

    const empty = rows.length ? '' : `<tbody><tr><td colspan="${cols.length + 1}">Nenhuma linha para este filtro.</td></tr></tbody>`;
    table.innerHTML = head + `<tbody>${body}</tbody>` + empty;

    const pager = $('validator-pager');
    if (pager) {
      const more = rows.length - shown.length;
      pager.innerHTML = `<span>Exibindo ${shown.length} de ${plural(rows.length, 'linha', 'linhas')}.</span>` +
        (more > 0 ? ` <button type="button" class="hv-secondary" data-more>Mostrar mais ${Math.min(more, PAGE_SIZE)}</button>` : '');
    }
    const globalBox = $('validator-global-issues');
    if (globalBox) {
      const g = view.global.filter((i) => state.showInfo || i.severity !== 'info');
      globalBox.hidden = !g.length;
      globalBox.innerHTML = g.length ? `<strong>Ocorrências na planilha como um todo</strong><div class="hv-cell-issues">${g.map(messageHtml).join('')}</div>` : '';
    }
  }

  function renderIssueList() {
    const table = $('validator-issues');
    if (!table) return;
    const items = state.result.issues.filter((i) => (!state.code || i.code === state.code) && (state.showInfo || i.severity !== 'info'));
    if (!items.length) { table.innerHTML = '<tbody><tr><td>Nenhuma ocorrência.</td></tr></tbody>'; return; }
    table.innerHTML = '<thead><tr><th>Linha</th><th>Campo</th><th>Tipo</th><th>Código</th><th>Mensagem</th><th>Valor</th><th>Sugestão</th><th>Fonte</th></tr></thead><tbody>' +
      items.map((i) => `<tr><td>${i.row_number != null ? `<a href="#hv-row-${esc(i.row_number)}" data-goto="${esc(i.row_number)}">${esc(i.row_number)}</a>` : '—'}</td>` +
        `<td>${esc(i.column_name)}</td><td><span class="hv-pill ${esc(i.severity)}">${esc(SEV_LABEL[i.severity] || i.severity)}</span></td>` +
        `<td>${esc(i.code)}</td><td>${esc(i.message)}</td><td>${esc(i.value)}</td><td>${esc(i.suggestion)}</td><td>${esc(i.source)}</td></tr>`).join('') + '</tbody>';
  }

  function gotoRow(row) {
    // Garante que a linha esteja renderizada antes de rolar.
    state.filter = 'all'; state.code = '';
    const sel = $('validator-code-filter'); if (sel) sel.value = '';
    const idx = state.result.table.findIndex((r) => String(r._row_number) === String(row));
    state.page = Math.max(state.page, Math.ceil((idx + 1) / PAGE_SIZE));
    renderSummary();
    renderSheet();
    const tr = $('hv-row-' + row);
    if (tr) {
      tr.scrollIntoView({ behavior: 'smooth', block: 'center' });
      tr.classList.add('tsiino-row-flash');
      setTimeout(() => tr.classList.remove('tsiino-row-flash'), 1800);
    }
  }

  function downloadIssuesCsv() {
    if (!state.result) return;
    const cols = ['row_number', 'column_name', 'severity', 'code', 'message', 'value', 'suggestion', 'source'];
    const q = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const lines = [cols.join(';')].concat(state.result.issues.map((i) => cols.map((c) => q(i[c])).join(';')));
    const name = (state.result.summary.filename || 'planilha').replace(/\.[^.]+$/, '');
    downloadBlob(new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' }), `${name}_ocorrencias_tsiino.csv`);
  }

  // ---------------------------------------------------------------- mapa
  function loadLeaflet() {
    if (window.L) return Promise.resolve(window.L);
    if (loadLeaflet.p) return loadLeaflet.p;
    loadLeaflet.p = new Promise((resolve, reject) => {
      const css = document.createElement('link');
      css.rel = 'stylesheet';
      css.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
      document.head.appendChild(css);
      const js = document.createElement('script');
      js.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
      js.onload = () => resolve(window.L);
      js.onerror = reject;
      document.head.appendChild(js);
    });
    return loadLeaflet.p;
  }

  function mapFeatures() {
    return state.result.table
      .filter((r) => typeof r.lat === 'number' && typeof r.long === 'number')
      .map((r) => ({ row: r._row_number, lat: r.lat, lon: r.long, sev: rowSeverity(r._row_number), r }));
  }

  async function openMap() {
    if (!state.result) return;
    const panel = $('validator-map-panel');
    const box = $('validator-map');
    if (!panel || !box) return;
    panel.hidden = false;
    const pts = mapFeatures();
    if (!pts.length) { box.innerHTML = '<div class="hv-map-empty">Nenhuma linha com latitude e longitude válidas.</div>'; return; }
    try {
      const L = await loadLeaflet();
      if (state.map) state.map.remove();
      box.innerHTML = '';
      box.classList.add('tsiino-leaflet');
      const map = L.map(box, { scrollWheelZoom: false });
      state.map = map;
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18, attribution: '&copy; OpenStreetMap' }).addTo(map);
      const colors = { error: '#B94262', warning: '#D47A00', info: '#626A38', clear: '#2E3B24' };
      const markers = pts.map((p) => L.circleMarker([p.lat, p.lon], {
        radius: 7, weight: 2, color: '#fff', fillColor: colors[p.sev] || colors.clear, fillOpacity: 0.9
      }).bindPopup(`<strong>Linha ${esc(p.row)}</strong><br>${esc(p.r.collector)} ${esc(p.r.number)}<br><em>${esc(p.r.genus)} ${esc(p.r.sp1)}</em><br>${esc(p.r.minorarea)} – ${esc(p.r.majorarea)}<br>${esc(p.lat)}, ${esc(p.lon)}<br><a href="#hv-row-${esc(p.row)}" data-goto="${esc(p.row)}">Ver na planilha</a>`).addTo(map));
      map.fitBounds(L.featureGroup(markers).getBounds().pad(0.2), { maxZoom: 12 });
      setTimeout(() => map.invalidateSize(), 150);
    } catch (err) {
      box.innerHTML = '<div class="hv-map-empty">Não foi possível carregar o mapa base. Pontos: ' +
        pts.map((p) => `linha ${esc(p.row)} (${esc(p.lat)}, ${esc(p.lon)})`).join('; ') + '</div>';
    }
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // ---------------------------------------------------------------- eventos
  function install() {
    const form = $('herb-validator-form');
    if (!form) return;
    form.addEventListener('submit', onSubmit);
    $('spreadsheet-file')?.addEventListener('change', () => {
      const f = selectedFile();
      closeMapper();
      resetResults();
      if (f) setStatus(`Arquivo selecionado: <strong>${esc(f.name)}</strong> (${(f.size / 1024 / 1024).toFixed(2)} MB). Clique em <strong>Validar planilha</strong>.`, '');
    });
    $('map-button')?.addEventListener('click', openMap);
    $('map-close')?.addEventListener('click', () => { const p = $('validator-map-panel'); if (p) p.hidden = true; });
    $('download-issues-csv')?.addEventListener('click', downloadIssuesCsv);
    $('validator-code-filter')?.addEventListener('change', (e) => { state.code = e.target.value; state.page = 1; renderSheet(); renderIssueList(); });
    $('validator-show-info')?.addEventListener('change', (e) => { state.showInfo = e.target.checked; renderSheet(); renderIssueList(); });
    document.querySelectorAll('.hv-filter[data-filter]').forEach((b) => b.addEventListener('click', () => {
      if (!state.result) return;
      state.filter = b.dataset.filter; state.page = 1;
      document.querySelectorAll('.hv-filter[data-filter]').forEach((x) => x.classList.toggle('is-active', x === b));
      renderSheet();
    }));
    document.addEventListener('click', (e) => {
      const more = e.target.closest('[data-more]');
      if (more && state.result) { state.page += 1; renderSheet(); return; }
      const go = e.target.closest('[data-goto]');
      if (go && state.result) { e.preventDefault(); gotoRow(go.dataset.goto); return; }
      if (!e.target.closest('.hv-mapper-v20-help') && !e.target.closest('.hv-mapper-v20-popup')) {
        document.querySelectorAll('.hv-mapper-v20-popup').forEach((p) => p.remove());
      }
      onMapperEvent(e);
    });
    document.addEventListener('change', onMapperEvent);
    ['dragstart', 'dragover', 'dragleave', 'drop'].forEach((t) => document.addEventListener(t, onDrag));
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') document.querySelectorAll('.hv-mapper-v20-popup').forEach((p) => p.remove());
      if (state.mapper && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.target.matches('input, textarea')) {
        e.preventDefault();
        if (state.mapper.undo.length) { state.mapper.mapping = JSON.parse(state.mapper.undo.pop()); renderMapper(); }
      }
    });
    const tpl = $('download-template');
    if (tpl) tpl.href = API + '/converter/template';
    // Acorda o Space em segundo plano assim que a página abre (sem bloquear a interface).
    fetch(API_ROOT + '/health', { cache: 'no-store' }).catch(() => null);
  }

  window.TsiinoValidator = { api: API, state, showResult, openMapper };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
  else install();
})();
