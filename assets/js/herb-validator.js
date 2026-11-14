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
    query: '',
    onlyIssueCols: false,
    tab: 'sheet',
    mapper: null,        // { preview, mapping, undo: [] }
    map: null,
    mapFilter: { error: true, warning: true, clear: true },
    base: 'map'
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
    return (state.mapper && state.mapper.view.fields) || [];
  }

  function colLetter(n) { let s = ''; while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); } return s; }
  function letterIndex(s) { return String(s).toUpperCase().split('').reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0); }

  /* Normaliza a resposta de /converter/preview. Há duas versões da API em circulação:
   *  - atual:   source_columns[{index, letter, name}], suggested_mapping {campo: "cabeçalho"}, rows [{_row_number, <cabeçalho>: valor}]
   *  - antiga:  source_columns[{index, letter, header}], suggested_mapping {campo: "M"},        rows [{row_number, values: [...]}]
   * Internamente cada coluna é identificada pelo índice 1-based, que as duas versões aceitam em /convert e /validate_mapped.
   */
  function normalizePreview(p) {
    const rawCols = p.source_columns_meta || p.source_columns || p.columns || [];
    const byName = rawCols.some((c) => c && typeof c === 'object' && 'name' in c);
    const columns = rawCols.map((c, i) => {
      const o = typeof c === 'string' ? { name: c } : (c || {});
      const index = Number(o.index) || (o.column_index != null ? Number(o.column_index) + 1 : 0) || (o.letter ? letterIndex(o.letter) : i + 1);
      const name = String(o.name ?? o.header ?? o.key ?? '').trim();
      return { index, letter: o.letter || colLetter(index), name: name || '(sem título)', rawName: name, samples: o.samples || [] };
    });
    const nameIdx = new Map(columns.filter((c) => c.rawName).map((c) => [c.rawName, c.index]));
    const letterIdx = new Map(columns.map((c) => [c.letter.toUpperCase(), c.index]));
    const valid = new Set(columns.map((c) => c.index));
    const toIndex = (v) => {
      if (v == null || v === '') return null;
      if (typeof v === 'number') return valid.has(v) ? v : null;
      const s = String(v).trim();
      const asLetter = /^[A-Za-z]{1,3}$/.test(s) ? letterIdx.get(s.toUpperCase()) : undefined;
      const hit = byName ? (nameIdx.get(s) ?? asLetter) : (asLetter ?? nameIdx.get(s));
      if (hit != null) return hit;
      return /^\d+$/.test(s) && valid.has(Number(s)) ? Number(s) : null;
    };
    const suggested = {};
    Object.entries(p.suggested_mapping || p.mapping || p.field_to_column || {}).forEach(([f, v]) => {
      const idx = toIndex(v);
      if (idx != null) suggested[f] = idx;
    });
    const rows = (p.rows || p.preview_rows || p.data_rows || []).map((r) => {
      const cells = {};
      columns.forEach((c) => {
        cells[c.index] = Array.isArray(r.values) ? r.values[c.index - 1] : r[c.rawName];
      });
      return { row: r._row_number ?? r.row_number, cells };
    });
    const fields = (p.fields || p.standard_fields || []).map((f) => {
      const key = f.key || f.name;
      return { ...f, key, code: f.code || String(key).toUpperCase(), label: f.label || key, help: f.help || f.label || '' };
    });
    return { columns, suggested, rows, fields, sheet_name: p.sheet_name, header_row: p.header_row };
  }

  function openMapper(preview) {
    const view = normalizePreview(preview);
    state.mapper = { preview, view, mapping: { ...view.suggested }, undo: [] };
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
    column = Number(column) || null;
    if (!column) { delete m[field]; renderMapper(); return; }
    Object.keys(m).forEach((f) => { if (m[f] === column) delete m[f]; });  // uma coluna -> um campo
    m[field] = column;
    renderMapper();
  }

  function renderMapper() {
    const panel = $('tsiino-mapper');
    const mp = state.mapper;
    if (!panel || !mp) return;
    const { view: preview, mapping } = mp;
    const columns = preview.columns;
    const used = new Set(Object.values(mapping));
    const missing = fieldDefs().filter((f) => f.required && !mapping[f.key]).map((f) => f.key);
    const rows = preview.rows.slice(0, 12);

    const optionsHtml = (current) => ['<option value="">— sem coluna —</option>']
      .concat(columns.map((c) => `<option value="${c.index}"${c.index === current ? ' selected' : ''}>${esc(c.letter)} · ${esc(c.name)}</option>`))
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
    const body = rows.map((r) => '<tr><th scope="row">Linha ' + esc(r.row) + '</th>' +
      fieldDefs().map((f) => `<td><div class="hv-mapper-v20-data">${esc(mapping[f.key] ? r.cells[mapping[f.key]] : '')}</div></td>`).join('') + '</tr>').join('');

    const unmapped = columns.filter((c) => !used.has(c.index));
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
        `<span class="hv-mapper-v20-chip" draggable="true" data-column="${c.index}" title="${esc((c.samples || []).join(' · '))}"><span class="hv-mapper-v20-letter">${esc(c.letter)}</span><span class="hv-mapper-v20-chip-text">${esc(c.name)}</span></span>`).join(' ')}</div>` : ''}
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
    else if (action === 'reset') { pushUndo(); mp.mapping = { ...mp.view.suggested }; renderMapper(); }
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
  /* Rótulos dos campos canônicos INPA/BRAHMS (usados no painel e nos gráficos). */
  const FIELD_LABELS = {
    accession: 'Nº de tombo', collector: 'Coletor', prefix: 'Prefixo', number: 'Nº de coleta', suffix: 'Sufixo',
    addcoll: 'Coletores adicionais', colldd: 'Dia da coleta', collmm: 'Mês da coleta', collyy: 'Ano da coleta',
    initial: 'Nº de amostras', family: 'Família', genus: 'Gênero', detstatus: 'cf./aff.', sp1: 'Epíteto',
    rank1: 'Categoria infraesp.', sp2: 'Epíteto infraesp.', detby: 'Determinador', detdd: 'Dia da determinação',
    detmm: 'Mês da determinação', detyy: 'Ano da determinação', country: 'País', majorarea: 'Estado (UF)',
    minorarea: 'Município', gazetteer: 'Localidade', locnotes: 'Notas da localidade', habitattxt: 'Habitat',
    lat: 'Latitude', NS: 'N/S', long: 'Longitude', EW: 'E/W', llunit: 'Unidade lat/long', alt: 'Altitude',
    alt1: 'Altitude máxima', plantdesc: 'Descrição da planta', vernacular: 'Nome popular', dups: 'Duplicatas',
    project: 'Projeto', genbank: 'GenBank'
  };
  const REQUIRED_HINT = new Set(['collector', 'number', 'colldd', 'collmm', 'collyy', 'family', 'genus', 'country',
    'majorarea', 'minorarea', 'lat', 'long', 'plantdesc']);
  const CATEGORIES = [
    { key: 'struct', label: 'Estrutura da planilha', test: /^(MISSING_COLUMN|UNKNOWN_COLUMN|NO_DATA_ROWS|ROW_LIMIT)/ },
    { key: 'req', label: 'Campos obrigatórios vazios', test: /_REQUIRED$/ },
    { key: 'tax', label: 'Nomes botânicos', test: /TAXON|SPECIES|GENUS|FAMILY|EPITHET|^SP[12]_|RANK1|INFRASPECIFIC|DETSTATUS|SYNONYM/ },
    { key: 'geo', label: 'Coordenadas e localidade', test: /POINT_|^LAT_|^LONG_|^NS_|^EW_|STATE|MUNICIPALITY|COUNTRY|LLUNIT|^ALT/ },
    { key: 'date', label: 'Datas', test: /DATE|^DET_/ },
    { key: 'fill', label: 'Preenchimento e padronização', test: /./ }
  ];
  const categoryOf = (code) => (CATEGORIES.find((c) => c.test.test(String(code || ''))) || CATEGORIES[CATEGORIES.length - 1]).key;
  const fieldLabel = (f) => FIELD_LABELS[f] || f || '—';
  const fmt = (n) => Number(n || 0).toLocaleString('pt-BR');
  const pct = (a, b) => (b ? Math.round((a / b) * 1000) / 10 : 0);
  const pctTxt = (a, b) => `${pct(a, b).toLocaleString('pt-BR')}%`;
  const isFilled = (v) => v != null && String(v).trim() !== '';

  function resetResults() {
    state.result = null;
    if (state.map) { state.map.remove(); state.map = null; }
    const results = $('validator-results');
    if (results) results.hidden = true;
    configureDownloads(null);
  }

  function configureDownloads(result) {
    const href = result ? `${API}/jobs/${encodeURIComponent(result.job_id)}/download.xlsx` : '#';
    const label = result && result.summary.converted_from ? 'Baixar planilha convertida e anotada' : 'Baixar planilha anotada';
    ['download-annotated', 'tsr-download-annotated'].forEach((id) => {
      const link = $(id);
      if (!link) return;
      link.href = href;
      link.textContent = label;
      link.classList.toggle('is-disabled', !result);
      link.setAttribute('aria-disabled', result ? 'false' : 'true');
    });
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

  /* Índices calculados uma vez por resultado: ocorrências por célula/linha, severidade por linha,
   * colunas com ocorrência e o texto pesquisável de cada linha. */
  function prepareResult(result) {
    const fieldToHeader = (result.header && result.header.field_to_header) || {};
    const columns = (result.header && result.header.columns) || [];
    const headerToField = {};
    Object.entries(fieldToHeader).forEach(([f, h]) => { headerToField[h] = f; });
    const byCell = new Map();
    const byRow = new Map();
    const global = [];
    const issueCols = new Set();
    result.issues.forEach((it) => {
      if (it.row_number == null) { global.push(it); return; }
      const header = fieldToHeader[it.column_name] || it.column_name || '';
      const key = it.row_number + '|' + header;
      if (!byCell.has(key)) byCell.set(key, []);
      byCell.get(key).push(it);
      if (!byRow.has(it.row_number)) byRow.set(it.row_number, []);
      byRow.get(it.row_number).push(it);
      issueCols.add(header);
    });
    const known = new Set(columns);
    let hasOrphans = false;
    byCell.forEach((items, key) => { if (!known.has(key.slice(key.indexOf('|') + 1))) hasOrphans = true; });
    const rowSev = new Map();
    byRow.forEach((items, row) => {
      let best = 'clear';
      items.forEach((i) => { if (SEV_RANK[i.severity] < (SEV_RANK[best] ?? 9)) best = i.severity; });
      rowSev.set(row, best);
    });
    result._view = { columns, headerToField, fieldToHeader, byCell, byRow, global, hasOrphans, rowSev, issueCols, text: new Map() };
    result._stats = computeStats(result);
    return result;
  }

  function rowSeverity(row) {
    return state.result._view.rowSev.get(row) || 'clear';
  }
  // "info" não impede nada: para filtros e mapa, a linha só com notas conta como "sem problemas".
  function rowStatus(row) {
    const s = rowSeverity(row);
    return s === 'error' || s === 'warning' ? s : 'clear';
  }

  // ---------------------------------------------------------------- estatísticas da planilha
  function countBy(values) {
    const m = new Map();
    values.forEach((v) => { if (v) m.set(v, (m.get(v) || 0) + 1); });
    return [...m.entries()].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0]), 'pt-BR'));
  }
  const clean = (v) => (isFilled(v) ? String(v).trim().replace(/\s+/g, ' ') : '');
  const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : '');

  function computeStats(result) {
    const rows = result.table;
    const total = rows.length;
    const fields = Object.keys((result.header && result.header.field_to_header) || {}).filter((f) => FIELD_LABELS[f]);
    const present = fields.length ? fields : Object.keys(FIELD_LABELS);

    const completeness = present.map((f) => {
      const filled = rows.reduce((n, r) => n + (isFilled(r[f]) ? 1 : 0), 0);
      return { field: f, filled, total, required: REQUIRED_HINT.has(f) };
    });

    const families = countBy(rows.map((r) => cap(clean(r.family))));
    const genera = countBy(rows.map((r) => cap(clean(r.genus))));
    const species = countBy(rows.map((r) => {
      const g = cap(clean(r.genus)); const e = clean(r.sp1).toLowerCase();
      return g && e && !/^sp\.?$/.test(e) ? `${g} ${e}` : '';
    }));
    const collectors = countBy(rows.map((r) => clean(String(r.collector || '').split(/[;&|]/)[0])));
    const states = countBy(rows.map((r) => clean(r.majorarea)));
    const municipalities = countBy(rows.map((r) => {
      const m = clean(r.minorarea); const uf = clean(r.majorarea);
      return m ? (uf ? `${m} (${uf})` : m) : '';
    }));
    const years = countBy(rows.map((r) => {
      const y = parseInt(r.collyy, 10);
      return y > 1700 && y < 2200 ? y : 0;
    })).sort((a, b) => a[0] - b[0]);
    const alts = rows.map((r) => parseFloat(String(r.alt ?? '').replace(',', '.'))).filter((n) => Number.isFinite(n));
    const georef = rows.filter((r) => typeof r.lat === 'number' && typeof r.long === 'number').length;
    const identifiedToSpecies = rows.filter((r) => isFilled(r.genus) && isFilled(r.sp1) && !/^sp\.?$/i.test(clean(r.sp1))).length;

    // Ocorrências agrupadas por código, por campo e por categoria.
    const codes = new Map();
    const fieldIssues = new Map();
    const cats = new Map(CATEGORIES.map((c) => [c.key, { error: 0, warning: 0, info: 0 }]));
    result.issues.forEach((i) => {
      let c = codes.get(i.code);
      if (!c) {
        c = { code: i.code, severity: i.severity, n: 0, rows: new Set(), messages: new Map(), field: i.column_name, cat: categoryOf(i.code), suggestions: 0 };
        codes.set(i.code, c);
      }
      c.n += 1;
      if (i.row_number != null) c.rows.add(i.row_number);
      c.messages.set(i.message, (c.messages.get(i.message) || 0) + 1);
      if (i.suggestion) c.suggestions += 1;
      if (SEV_RANK[i.severity] < SEV_RANK[c.severity]) c.severity = i.severity;
      cats.get(categoryOf(i.code))[i.severity] = (cats.get(categoryOf(i.code))[i.severity] || 0) + 1;
      if (i.row_number != null && i.column_name) {
        let f = fieldIssues.get(i.column_name);
        if (!f) { f = { field: i.column_name, error: new Set(), warning: new Set(), info: new Set() }; fieldIssues.set(i.column_name, f); }
        (f[i.severity] || f.info).add(i.row_number);
      }
    });
    const codeList = [...codes.values()].sort((a, b) => (SEV_RANK[a.severity] - SEV_RANK[b.severity]) || b.n - a.n);
    const fieldList = [...fieldIssues.values()].map((f) => {
      const err = f.error; const warn = [...f.warning].filter((r) => !err.has(r));
      return { field: f.field, error: err.size, warning: warn.length, info: f.info.size };
    }).filter((f) => f.error + f.warning > 0).sort((a, b) => (b.error + b.warning) - (a.error + a.warning));

    const status = { error: 0, warning: 0, clear: 0 };
    rows.forEach((r) => { status[rowStatusFor(result, r._row_number)] += 1; });

    return {
      total, completeness, families, genera, species, collectors, states, municipalities, years, alts, georef,
      identifiedToSpecies, codeList, fieldList, cats, status
    };
  }
  function rowStatusFor(result, row) {
    const s = result._view.rowSev.get(row) || 'clear';
    return s === 'error' || s === 'warning' ? s : 'clear';
  }

  // ---------------------------------------------------------------- renderização do resultado
  function showResult(result) {
    state.result = prepareResult(result);
    state.filter = 'all';
    state.code = '';
    state.query = '';
    state.page = 1;
    state.mapFilter = { error: true, warning: true, clear: true };
    if (state.map) { state.map.remove(); state.map = null; }
    const results = $('validator-results');
    if (results) results.hidden = false;
    const search = $('validator-search'); if (search) search.value = '';
    renderHeader();
    renderSummary();
    renderHealth();
    renderInsights();
    renderDashboard();
    renderCodeFilter();
    renderSheet();
    renderIssueList();
    configureDownloads(result);
    switchTab('sheet');
    const s = result.summary;
    const verdict = s.error_count
      ? `${plural(s.error_count, 'erro', 'erros')} em ${plural(s.rows_with_errors, 'linha', 'linhas')} precisam de correção antes do depósito.`
      : 'Nenhum erro encontrado. Revise os alertas antes do depósito.';
    setStatus(`Validação concluída em ${esc(s.elapsed_seconds)}s: ${esc(verdict)}`, s.error_count ? 'warning' : 'ok');
    results && results.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function renderHeader() {
    const s = state.result.summary;
    const st = state.result._stats;
    const head = $('validator-results');
    const title = $('tsr-verdict');
    const meta = $('tsr-meta');
    let tone; let text;
    if (s.error_count) {
      tone = 'error';
      text = `${fmt(st.status.error)} de ${fmt(st.total)} ${st.total === 1 ? 'linha precisa' : 'linhas precisam'} de correção`;
    } else if (s.warning_count) {
      tone = 'warning';
      text = 'Sem erros — revise os alertas antes do depósito';
    } else {
      tone = 'ok';
      text = 'Planilha pronta para depósito';
    }
    if (head) head.dataset.tone = tone;
    if (title) title.textContent = text;
    if (meta) {
      const bits = [
        `<span class="tsr-meta-file">${esc(s.converted_from || s.filename || 'planilha')}</span>`,
        `aba “${esc(s.sheet_name)}”`,
        s.converted_from ? '<span class="tsr-tag">convertida para INPA/BRAHMS</span>' : '<span class="tsr-tag">padrão INPA/BRAHMS</span>',
        `validada em ${esc(String(s.elapsed_seconds).replace('.', ','))} s`
      ];
      const off = [];
      if (s.validate_taxonomy === false) off.push('nomes botânicos');
      if (s.validate_geography === false) off.push('geografia');
      if (off.length) bits.push(`<span class="tsr-tag is-muted">sem checagem de ${off.join(' e ')}</span>`);
      meta.innerHTML = bits.join('<span class="tsr-dot" aria-hidden="true">·</span>');
    }
  }

  function renderSummary() {
    const s = state.result.summary;
    const st = state.result._stats;
    const node = $('validator-summary');
    if (node) {
      const kpi = (label, value, hint, tone) => `<div class="tsr-kpi"${tone ? ` data-tone="${tone}"` : ''}>` +
        `<span class="tsr-kpi-label">${tone ? `<i class="tsr-swatch" data-sev="${tone}" aria-hidden="true"></i>` : ''}${label}</span>` +
        `<strong class="tsr-kpi-value">${value}</strong><span class="tsr-kpi-hint">${hint}</span></div>`;
      const ready = st.total - st.status.error;
      node.innerHTML =
        kpi('Linhas', fmt(s.total_rows), ready ? `${fmt(ready)} sem erro (${pctTxt(ready, st.total)})` : 'nenhuma sem erro ainda') +
        kpi('Erros', fmt(s.error_count), `em ${plural(fmt(s.rows_with_errors), 'linha', 'linhas')} · impedem o depósito`, 'error') +
        kpi('Alertas', fmt(s.warning_count), 'revisão curatorial', 'warning') +
        kpi('Notas', fmt(s.info_count), 'sugestões de padronização', 'info') +
        kpi('Georreferenciadas', pctTxt(st.georef, st.total), `${fmt(st.georef)} com lat/long válidas`);
    }
    const counts = { all: st.total, error: st.status.error, warning: st.status.warning, clear: st.status.clear };
    document.querySelectorAll('.hv-filter[data-filter]').forEach((b) => {
      const base = b.dataset.label || (b.dataset.label = b.textContent.trim());
      b.innerHTML = `${esc(base)} <span class="tsr-count">${fmt(counts[b.dataset.filter] ?? 0)}</span>`;
      b.classList.toggle('is-active', b.dataset.filter === state.filter);
    });
    const cm = $('tsr-count-map'); if (cm) cm.textContent = fmt(st.georef);
    const ci = $('tsr-count-issues'); if (ci) ci.textContent = fmt(state.result.issues.length);
  }

  // Barra empilhada da situação das linhas: com erro | só alertas | sem problemas.
  function renderHealth() {
    const node = $('tsr-health');
    if (!node) return;
    const st = state.result._stats;
    const segs = [
      { key: 'error', label: 'Com erro', n: st.status.error },
      { key: 'warning', label: 'Só alertas', n: st.status.warning },
      { key: 'clear', label: 'Sem problemas', n: st.status.clear }
    ];
    node.innerHTML = `<div class="tsr-health-label">Situação das ${fmt(st.total)} linhas</div>` +
      `<div class="tsr-stack" role="img" aria-label="${segs.map((s) => `${s.label}: ${s.n}`).join(', ')}">` +
      segs.filter((s) => s.n).map((s) => `<button type="button" class="tsr-stack-seg" data-sev="${s.key}" style="flex-grow:${s.n}" ` +
        `data-row-filter="${s.key}" data-tip="${esc(`${s.label}: ${fmt(s.n)} linhas (${pctTxt(s.n, st.total)}) — clique para filtrar`)}"></button>`).join('') +
      '</div><div class="tsr-legend">' +
      segs.map((s) => `<button type="button" class="tsr-legend-item" data-row-filter="${s.key}"><i class="tsr-swatch" data-sev="${s.key}"></i>${s.label} <strong>${fmt(s.n)}</strong> <span>${pctTxt(s.n, st.total)}</span></button>`).join('') +
      '</div>';
  }

  // Leituras automáticas: o que mais pesa e o que dá para resolver rápido.
  function renderInsights() {
    const node = $('tsr-insights');
    if (!node) return;
    const r = state.result;
    const st = r._stats;
    const out = [];
    const errCodes = st.codeList.filter((c) => c.severity === 'error');
    const totalErr = errCodes.reduce((n, c) => n + c.n, 0);

    const emptyEverywhere = st.codeList.filter((c) => /_REQUIRED$/.test(c.code) && c.rows.size === st.total && st.total > 1);
    if (emptyEverywhere.length) {
      out.push({ tone: 'error', title: `${plural(emptyEverywhere.length, 'campo obrigatório está vazio', 'campos obrigatórios estão vazios')} em todas as linhas`,
        body: `${emptyEverywhere.map((c) => `<strong>${esc(fieldLabel(c.field))}</strong>`).join(', ')}. Provavelmente a coluna não existe na planilha ou não foi mapeada — vale conferir antes de corrigir linha a linha.` });
    }
    if (totalErr && errCodes.length > 1) {
      const top = errCodes.slice().sort((a, b) => b.n - a.n).slice(0, 3);
      const share = top.reduce((n, c) => n + c.n, 0);
      out.push({ tone: 'neutral', title: `${plural(top.length, 'tipo de erro concentra', 'tipos de erro concentram')} ${pctTxt(share, totalErr)} dos erros`,
        body: top.map((c) => `<button type="button" class="tsr-link" data-code="${esc(c.code)}">${esc(c.code)}</button> (${fmt(c.n)})`).join(', ') + '. Corrigir esses primeiro reduz a maior parte do trabalho.' });
    }
    const fromCoord = st.codeList.filter((c) => /_FROM_COORDINATE$/.test(c.code));
    if (fromCoord.length) {
      const rows = new Set(); fromCoord.forEach((c) => c.rows.forEach((x) => rows.add(x)));
      out.push({ tone: 'info', title: `UF/município de ${plural(fmt(rows.size), 'linha pode', 'linhas podem')} ser preenchidos pelas coordenadas`,
        body: 'O validador cruzou os pontos com a base do IBGE e deixou a sugestão em cada célula da planilha anotada.' });
    }
    const outside = st.codeList.filter((c) => /^POINT_OUTSIDE/.test(c.code));
    if (outside.length) {
      const rows = new Set(); outside.forEach((c) => c.rows.forEach((x) => rows.add(x)));
      out.push({ tone: 'warning', title: `${plural(fmt(rows.size), 'ponto cai', 'pontos caem')} fora do município, UF ou do Brasil`,
        body: 'Pode ser sinal trocado, latitude e longitude invertidas ou localidade errada. <button type="button" class="tsr-link" data-open-tab="map">Ver no mapa</button>' });
    }
    const dup = st.codeList.find((c) => c.code === 'DUPLICATE_COLLECTION_NUMBER');
    if (dup) out.push({ tone: 'warning', title: `${plural(fmt(dup.rows.size), 'linha com número de coleta repetido', 'linhas com número de coleta repetido')}`, body: 'Confira se são duplicatas do mesmo espécime ou erro de digitação.' });
    const noCoord = st.total - st.georef;
    if (noCoord > 0 && noCoord < st.total) out.push({ tone: 'neutral', title: `${plural(fmt(noCoord), 'linha sem coordenada válida', 'linhas sem coordenada válida')}`, body: `Essas linhas não aparecem no mapa (${pctTxt(noCoord, st.total)} da planilha).` });
    if (!r.summary.error_count && !r.summary.warning_count) out.unshift({ tone: 'ok', title: 'Nenhum erro ou alerta', body: 'A planilha está consistente com o padrão INPA/BRAHMS e com as bases consultadas.' });

    node.innerHTML = out.slice(0, 4).map((i) => `<article class="tsr-insight" data-tone="${i.tone}"><h3>${i.title}</h3><p>${i.body}</p></article>`).join('');
    node.hidden = !out.length;
  }

  // ---------------------------------------------------------------- painel (visão geral)
  function barRow({ label, sub, value, max, segs, tip, attrs = '', valueText }) {
    const width = max && value ? Math.max(1.5, (value / max) * 100) : 0;
    const inner = segs
      ? segs.filter((s) => s.n).map((s) => `<i class="tsr-bar-seg" data-sev="${s.sev}" style="flex-grow:${s.n}"></i>`).join('')
      : '<i class="tsr-bar-seg" data-sev="accent" style="flex-grow:1"></i>';
    return `<li class="tsr-bar-row"${attrs}${tip ? ` data-tip="${esc(tip)}"` : ''}>` +
      `<span class="tsr-bar-label">${label}${sub ? `<small>${sub}</small>` : ''}</span>` +
      `<span class="tsr-bar-track"><span class="tsr-bar" style="width:${width}%">${inner}</span></span>` +
      `<span class="tsr-bar-value">${valueText ?? fmt(value)}</span></li>`;
  }

  function card(title, body, { wide = false, sub = '', action = '' } = {}) {
    return `<section class="tsr-card${wide ? ' is-wide' : ''}"><header class="tsr-card-head"><div><h3>${title}</h3>${sub ? `<p>${sub}</p>` : ''}</div>${action}</header>${body}</section>`;
  }

  function renderDashboard() {
    const node = $('tsr-dashboard');
    if (!node) return;
    const st = state.result._stats;
    const parts = [];

    // 1. Prioridades: tipos de ocorrência (erros e alertas) por nº de linhas afetadas.
    const prio = st.codeList.filter((c) => c.severity !== 'info').slice(0, 8);
    if (prio.length) {
      const max = Math.max(...prio.map((c) => c.rows.size || c.n));
      parts.push(card('O que corrigir primeiro', `<ul class="tsr-bars is-prio">${prio.map((c) => {
        const msg = [...c.messages.entries()].sort((a, b) => b[1] - a[1])[0][0];
        const n = c.rows.size || c.n;
        return barRow({
          label: `<span class="tsr-sev" data-sev="${c.severity}">${SEV_LABEL[c.severity]}</span> ${esc(msg)}`,
          sub: `${esc(c.code)} · ${esc(fieldLabel(c.field))}`,
          value: n, max, segs: [{ sev: c.severity, n: 1 }],
          valueText: `${fmt(n)} <small>${pctTxt(n, st.total)}</small>`,
          tip: `${fmt(n)} linhas afetadas — clique para ver na planilha`,
          attrs: ` data-code="${esc(c.code)}" role="button" tabindex="0"`
        });
      }).join('')}</ul>`, { wide: true, sub: 'Tipos de ocorrência por número de linhas afetadas. Clique para filtrar a planilha.',
        action: '<button type="button" class="hv-secondary tsr-btn is-small" data-open-tab="issues">Ver todas</button>' }));
    }

    // 2. Campos com mais problemas.
    if (st.fieldList.length) {
      const list = st.fieldList.slice(0, 10);
      const max = Math.max(...list.map((f) => f.error + f.warning));
      parts.push(card('Campos com mais problemas', `<ul class="tsr-bars">${list.map((f) => barRow({
        label: esc(fieldLabel(f.field)), sub: esc(f.field), value: f.error + f.warning, max,
        segs: [{ sev: 'error', n: f.error }, { sev: 'warning', n: f.warning }],
        tip: `${fieldLabel(f.field)}: ${fmt(f.error)} linhas com erro, ${fmt(f.warning)} só com alerta`
      })).join('')}</ul>${legend(['error', 'warning'])}`, { sub: 'Linhas afetadas por campo.' }));
    }

    // 3. Ocorrências por grupo.
    const cats = CATEGORIES.map((c) => ({ ...c, ...st.cats.get(c.key) })).filter((c) => c.error + c.warning + c.info);
    if (cats.length) {
      const max = Math.max(...cats.map((c) => c.error + c.warning + c.info));
      parts.push(card('Ocorrências por grupo', `<ul class="tsr-bars">${cats.map((c) => barRow({
        label: esc(c.label), value: c.error + c.warning + c.info, max,
        segs: [{ sev: 'error', n: c.error }, { sev: 'warning', n: c.warning }, { sev: 'info', n: c.info }],
        tip: `${c.label}: ${fmt(c.error)} erros, ${fmt(c.warning)} alertas, ${fmt(c.info)} notas`
      })).join('')}</ul>${legend(['error', 'warning', 'info'])}`, { sub: 'Total de ocorrências por tipo de verificação.' }));
    }

    // 4. Conteúdo da coleção.
    const yr = st.years;
    const tiles = [
      ['Famílias', fmt(st.families.length)],
      ['Gêneros', fmt(st.genera.length)],
      ['Espécies', fmt(st.species.length), `${pctTxt(st.identifiedToSpecies, st.total)} identificadas até espécie`],
      ['Coletores', fmt(st.collectors.length), 'coletor principal'],
      ['Municípios', fmt(st.municipalities.length), st.states.length ? `em ${plural(st.states.length, 'UF', 'UFs')}` : ''],
      ['Período', yr.length ? (yr[0][0] === yr[yr.length - 1][0] ? String(yr[0][0]) : `${yr[0][0]}–${yr[yr.length - 1][0]}`) : '—', 'ano de coleta'],
      ['Altitude', st.alts.length ? `${fmt(Math.min(...st.alts))}–${fmt(Math.max(...st.alts))} m` : '—', st.alts.length ? `${fmt(st.alts.length)} com altitude` : 'não informada']
    ];
    parts.push(card('Conteúdo da planilha', `<div class="tsr-tiles">${tiles.map(([l, v, h]) =>
      `<div class="tsr-tile"><span>${l}</span><strong>${v}</strong>${h ? `<small>${h}</small>` : ''}</div>`).join('')}</div>`,
    { wide: true, sub: 'Resumo do que foi coletado, calculado a partir das linhas enviadas.' }));

    // 5. Famílias.
    if (st.families.length) parts.push(card('Famílias mais representadas', topList(st.families, 10, 'espécimes'),
      { sub: `${fmt(st.families.length)} famílias no total.` }));
    // 6. Coletas por ano.
    if (yr.length) parts.push(card('Coletas por ano', yearChart(yr), { sub: `${fmt(yr.reduce((n, y) => n + y[1], 0))} linhas com ano válido.` }));
    // 7. Gêneros e espécies.
    if (st.species.length) parts.push(card('Espécies mais coletadas', topList(st.species, 10, 'espécimes', true), { sub: `${fmt(st.species.length)} espécies distintas.` }));
    else if (st.genera.length) parts.push(card('Gêneros mais coletados', topList(st.genera, 10, 'espécimes', true), { sub: `${fmt(st.genera.length)} gêneros distintos.` }));
    // 8. Coletores.
    if (st.collectors.length) parts.push(card('Principais coletores', topList(st.collectors, 8, 'coletas'), { sub: 'Considera o primeiro nome do campo de coletor.' }));
    // 9. Localidades.
    if (st.municipalities.length) parts.push(card('Municípios', topList(st.municipalities, 8, 'espécimes'),
      { sub: `${fmt(st.georef)} de ${fmt(st.total)} linhas georreferenciadas.`, action: '<button type="button" class="hv-secondary tsr-btn is-small" data-open-tab="map">Abrir mapa</button>' }));
    else parts.push(card('Distribuição geográfica', `<p class="tsr-empty">Município não informado. ${fmt(st.georef)} de ${fmt(st.total)} linhas têm coordenadas.</p>`,
      { action: st.georef ? '<button type="button" class="hv-secondary tsr-btn is-small" data-open-tab="map">Abrir mapa</button>' : '' }));

    // 10. Completude dos campos.
    const req = st.completeness.filter((c) => c.required).sort((a, b) => a.filled - b.filled);
    const opt = st.completeness.filter((c) => !c.required && c.filled).sort((a, b) => b.filled - a.filled);
    const emptyOpt = st.completeness.filter((c) => !c.required && !c.filled);
    const comp = req.concat(opt);
    parts.push(card('Preenchimento dos campos', `<ul class="tsr-bars is-meter">${comp.map((c) => barRow({
      label: `${esc(fieldLabel(c.field))}${c.required ? ' <abbr class="tsr-req" title="obrigatório">*</abbr>' : ''}`,
      value: c.filled, max: c.total || 1, valueText: pctTxt(c.filled, c.total),
      segs: [{ sev: c.required && c.filled < c.total ? 'gap' : 'accent', n: 1 }],
      tip: `${fieldLabel(c.field)}: ${fmt(c.filled)} de ${fmt(c.total)} linhas preenchidas`
    })).join('')}</ul>${emptyOpt.length ? `<p class="tsr-card-foot">Campos opcionais sem nenhum valor: ${emptyOpt.map((c) => esc(fieldLabel(c.field))).join(', ')}.</p>` : ''}`, { wide: true, sub: 'Porcentagem de linhas com valor em cada campo. <abbr class="tsr-req" title="obrigatório">*</abbr> obrigatório no padrão INPA.' }));

    node.innerHTML = parts.join('');
  }

  function legend(sevs) {
    const names = { error: 'Erro', warning: 'Alerta', info: 'Nota', clear: 'Sem problemas' };
    return `<div class="tsr-legend is-small">${sevs.map((s) => `<span class="tsr-legend-item"><i class="tsr-swatch" data-sev="${s}"></i>${names[s]}</span>`).join('')}</div>`;
  }

  function topList(entries, limit, unit, italic) {
    const list = entries.slice(0, limit);
    const rest = entries.slice(limit).reduce((n, e) => n + e[1], 0);
    const max = list.length ? list[0][1] : 1;
    return `<ul class="tsr-bars">${list.map(([name, n]) => barRow({
      label: italic ? `<em>${esc(name)}</em>` : esc(name), value: n, max, tip: `${name}: ${fmt(n)} ${unit}`
    })).join('')}${rest ? `<li class="tsr-bar-rest">+ ${fmt(entries.length - limit)} outros (${fmt(rest)} ${unit})</li>` : ''}</ul>`;
  }

  function yearChart(years) {
    // Preenche anos sem coleta para o eixo ser contínuo (até 60 colunas; depois agrupa por década).
    const first = years[0][0]; const last = years[years.length - 1][0];
    let bins;
    if (last - first <= 60) {
      const m = new Map(years);
      bins = []; for (let y = first; y <= last; y += 1) bins.push([String(y), m.get(y) || 0]);
    } else {
      const m = new Map();
      years.forEach(([y, n]) => { const d = Math.floor(y / 10) * 10; m.set(d, (m.get(d) || 0) + n); });
      bins = [...m.entries()].sort((a, b) => a[0] - b[0]).map(([d, n]) => [`${d}s`, n]);
    }
    const max = Math.max(...bins.map((b) => b[1]));
    const step = Math.ceil(bins.length / 8);
    return `<div class="tsr-cols" role="img" aria-label="Coletas por ano">${bins.map(([label, n], i) =>
      `<div class="tsr-col" data-tip="${esc(`${label}: ${fmt(n)} coletas`)}"><span class="tsr-col-bar" style="height:${n ? Math.max(2, (n / max) * 100) : 0}%"></span>` +
      `<span class="tsr-col-label">${i % step === 0 || i === bins.length - 1 ? esc(label) : ''}</span></div>`).join('')}</div>` +
      `<div class="tsr-cols-max">máx. ${fmt(max)}</div>`;
  }

  // ---------------------------------------------------------------- abas
  function switchTab(name) {
    document.querySelectorAll('.tsr-tab[data-tab]').forEach((t) => {
      const on = t.dataset.tab === name;
      t.classList.toggle('is-active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
    });
    document.querySelectorAll('.tsr-pane[data-pane]').forEach((p) => { p.hidden = p.dataset.pane !== name; });
    state.tab = name;
    if (name === 'map') openMap();
  }

  // ---------------------------------------------------------------- planilha anotada
  function renderCodeFilter() {
    const sel = $('validator-code-filter');
    if (!sel) return;
    sel.innerHTML = '<option value="">Todas as ocorrências</option>' + state.result._stats.codeList.map((c) =>
      `<option value="${esc(c.code)}">${esc(SEV_LABEL[c.severity] || c.severity)} · ${esc(c.code)} (${fmt(c.n)})</option>`).join('');
    sel.value = state.code || '';
  }

  function rowText(r) {
    const cache = state.result._view.text;
    let t = cache.get(r._row_number);
    if (t == null) {
      t = Object.values(r._raw || {}).map((v) => (v == null ? '' : String(v))).join(' ').toLowerCase();
      cache.set(r._row_number, t);
    }
    return t;
  }

  function visibleRows() {
    const view = state.result._view;
    const q = (state.query || '').trim().toLowerCase();
    return state.result.table.filter((r) => {
      const row = r._row_number;
      if (state.filter !== 'all' && rowStatus(row) !== state.filter) return false;
      if (state.code && !(view.byRow.get(row) || []).some((i) => i.code === state.code)) return false;
      if (q && !(String(row) === q || rowText(r).includes(q))) return false;
      return true;
    });
  }

  function cellIssues(row, header) {
    const items = state.result._view.byCell.get(row + '|' + header) || [];
    return state.showInfo ? items : items.filter((i) => i.severity !== 'info');
  }

  function messageHtml(it) {
    return `<span class="tsr-msg" data-sev="${esc(it.severity)}" title="${esc(it.code)}${it.source ? ' · ' + esc(it.source) : ''}">` +
      `<b>${esc(SEV_LABEL[it.severity] || '')}</b> ${esc(it.message)}${it.suggestion ? `<em>Sugestão: ${esc(it.suggestion)}</em>` : ''}</span>`;
  }

  function sheetColumns() {
    const view = state.result._view;
    if (!state.onlyIssueCols) return view.columns;
    const cols = view.columns.filter((h) => view.issueCols.has(h));
    return cols.length ? cols : view.columns;
  }

  function renderSheet() {
    const table = $('validator-sheet');
    if (!table) return;
    const view = state.result._view;
    const cols = sheetColumns();
    const rows = visibleRows();
    const shown = rows.slice(0, state.page * PAGE_SIZE);
    const head = '<thead><tr><th class="tsr-rownum" scope="col">Linha</th>' + cols.map((h) => {
      const field = view.headerToField[h];
      const label = field && FIELD_LABELS[field] && field === h ? FIELD_LABELS[field] : '';
      return `<th scope="col"${view.issueCols.has(h) ? ' class="has-issues"' : ''}><span class="tsr-th-name">${esc(h)}</span>` +
        `${field && field !== h ? `<small>${esc(field)}</small>` : label ? `<small>${esc(label)}</small>` : ''}</th>`;
    }).join('') + (view.hasOrphans ? '<th scope="col"><span class="tsr-th-name">Campos ausentes</span></th>' : '') + '</tr></thead>';

    const known = new Set(view.columns);
    const body = shown.map((r) => {
      const row = r._row_number;
      const raw = r._raw || {};
      const cells = cols.map((h) => {
        const items = cellIssues(row, h);
        const sev = items.length ? (items.some((i) => i.severity === 'error') ? 'error' : items.some((i) => i.severity === 'warning') ? 'warning' : 'info') : '';
        const v = raw[h];
        return `<td${sev ? ` data-sev="${sev}"` : ''}>${isFilled(v) ? `<div class="tsr-cell-value">${esc(v)}</div>` : '<div class="tsr-cell-value is-empty">vazio</div>'}` +
          (items.length ? `<div class="tsr-cell-issues">${items.map(messageHtml).join('')}</div>` : '') + '</td>';
      }).join('');
      let orphan = '';
      if (view.hasOrphans) {
        const items = (view.byRow.get(row) || []).filter((i) => !known.has(view.fieldToHeader[i.column_name] || i.column_name) && (state.showInfo || i.severity !== 'info'));
        const sev = items.some((i) => i.severity === 'error') ? 'error' : items.length ? 'warning' : '';
        orphan = `<td${sev ? ` data-sev="${sev}"` : ''}>` +
          (items.length ? `<div class="tsr-cell-issues">${items.map((i) => messageHtml({ ...i, message: `[${i.column_name}] ${i.message}` })).join('')}</div>` : '') + '</td>';
      }
      return `<tr id="hv-row-${esc(row)}" data-severity="${rowStatus(row)}"><th scope="row" class="tsr-rownum">${esc(row)}</th>${cells}${orphan}</tr>`;
    }).join('');

    const span = cols.length + 1 + (view.hasOrphans ? 1 : 0);
    const empty = rows.length ? '' : `<tbody><tr><td colspan="${span}" class="tsr-empty-row">Nenhuma linha para este filtro.</td></tr></tbody>`;
    table.innerHTML = head + `<tbody>${body}</tbody>` + empty;

    const pager = $('validator-pager');
    if (pager) {
      const more = rows.length - shown.length;
      const active = [];
      if (state.code) active.push(`ocorrência <strong>${esc(state.code)}</strong>`);
      if (state.query) active.push(`busca “${esc(state.query)}”`);
      pager.innerHTML = `<span>Exibindo ${fmt(shown.length)} de ${plural(fmt(rows.length), 'linha', 'linhas')}${active.length ? ` · ${active.join(' · ')}` : ''}.</span>` +
        (active.length ? ' <button type="button" class="tsr-link" data-clear-filters>Limpar filtros</button>' : '') +
        (more > 0 ? ` <button type="button" class="hv-secondary tsr-btn is-small" data-more>Mostrar mais ${fmt(Math.min(more, PAGE_SIZE))}</button>` : '');
    }
    const globalBox = $('validator-global-issues');
    if (globalBox) {
      const g = view.global.filter((i) => state.showInfo || i.severity !== 'info');
      globalBox.hidden = !g.length;
      globalBox.innerHTML = g.length ? `<h3>Ocorrências na planilha como um todo</h3><div class="tsr-cell-issues">${g.map(messageHtml).join('')}</div>` : '';
    }
  }

  // ---------------------------------------------------------------- ocorrências agrupadas
  const ROWS_PREVIEW = 80;
  function renderIssueList() {
    const node = $('validator-issues');
    if (!node) return;
    const list = state.result._stats.codeList.filter((c) => state.showInfo || c.severity !== 'info');
    if (!list.length) { node.innerHTML = '<p class="tsr-empty">Nenhuma ocorrência.</p>'; return; }
    const total = state.result._stats.total;
    node.innerHTML = list.map((c) => {
      const msgs = [...c.messages.entries()].sort((a, b) => b[1] - a[1]);
      const rows = [...c.rows].sort((a, b) => a - b);
      const cat = CATEGORIES.find((x) => x.key === c.cat);
      return `<details class="tsr-issue" data-sev="${c.severity}">` +
        `<summary><span class="tsr-sev" data-sev="${c.severity}">${SEV_LABEL[c.severity]}</span>` +
        `<span class="tsr-issue-title"><strong>${esc(msgs[0][0])}</strong><small>${esc(c.code)} · ${esc(fieldLabel(c.field))} · ${esc(cat ? cat.label : '')}</small></span>` +
        `<span class="tsr-issue-count">${fmt(c.n)}<small>${rows.length ? `${pctTxt(rows.length, total)} das linhas` : 'planilha'}</small></span></summary>` +
        `<div class="tsr-issue-body">` +
        (msgs.length > 1 ? `<ul class="tsr-issue-msgs">${msgs.slice(0, 6).map(([m, n]) => `<li>${esc(m)} <span>${fmt(n)}×</span></li>`).join('')}${msgs.length > 6 ? `<li class="is-muted">+ ${fmt(msgs.length - 6)} variações</li>` : ''}</ul>` : '') +
        (c.suggestions ? `<p class="tsr-issue-note">${fmt(c.suggestions)} ${c.suggestions === 1 ? 'ocorrência tem' : 'ocorrências têm'} sugestão de correção na planilha anotada.</p>` : '') +
        (rows.length ? `<div class="tsr-issue-rows"><span>Linhas:</span>${rows.slice(0, ROWS_PREVIEW).map((r) => `<a href="#hv-row-${r}" data-goto="${r}">${r}</a>`).join('')}` +
          `${rows.length > ROWS_PREVIEW ? `<button type="button" class="tsr-link" data-code="${esc(c.code)}">+ ${fmt(rows.length - ROWS_PREVIEW)} — ver todas na planilha</button>` : ''}</div>` : '') +
        `<div class="tsr-issue-actions">${rows.length ? `<button type="button" class="hv-secondary tsr-btn is-small" data-code="${esc(c.code)}">Filtrar planilha por esta ocorrência</button>` : ''}</div>` +
        '</div></details>';
    }).join('');
  }

  function filterByCode(code) {
    state.code = code; state.filter = 'all'; state.page = 1;
    const sel = $('validator-code-filter'); if (sel) sel.value = code;
    renderSummary();
    switchTab('sheet');
    renderSheet();
    $('tsr-pane-sheet')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function filterByStatus(status) {
    state.filter = status; state.code = ''; state.page = 1;
    const sel = $('validator-code-filter'); if (sel) sel.value = '';
    renderSummary();
    switchTab('sheet');
    renderSheet();
  }

  function gotoRow(row) {
    // Garante que a linha esteja renderizada antes de rolar.
    state.filter = 'all'; state.code = ''; state.query = '';
    const sel = $('validator-code-filter'); if (sel) sel.value = '';
    const search = $('validator-search'); if (search) search.value = '';
    const idx = state.result.table.findIndex((r) => String(r._row_number) === String(row));
    state.page = Math.max(state.page, Math.ceil((idx + 1) / PAGE_SIZE));
    if (state.map) state.map.closePopup();
    switchTab('sheet');
    renderSummary();
    renderSheet();
    const tr = $('hv-row-' + row);
    if (tr) {
      tr.scrollIntoView({ behavior: 'smooth', block: 'center' });
      tr.classList.add('tsr-row-flash');
      setTimeout(() => tr.classList.remove('tsr-row-flash'), 1800);
    }
  }

  function downloadIssuesCsv() {
    if (!state.result) return;
    const cols = ['row_number', 'column_name', 'severity', 'code', 'message', 'value', 'suggestion', 'source'];
    const q = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const lines = [cols.join(';')].concat(state.result.issues.map((i) => cols.map((c) => q(i[c])).join(';')));
    const name = (state.result.summary.converted_from || state.result.summary.filename || 'planilha').replace(/\.[^.]+$/, '');
    downloadBlob(new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' }), `${name}_ocorrencias_tsiino.csv`);
  }

  // ---------------------------------------------------------------- mapa
  const SEV_COLOR = { error: '#A93632', warning: '#C27A12', clear: '#626A38' };
  const BASEMAPS = {
    map: ['https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap' }],
    sat: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 18, attribution: 'Imagens &copy; Esri' }],
    topo: ['https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', { maxZoom: 17, attribution: '&copy; OpenStreetMap, SRTM · OpenTopoMap' }]
  };

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
      js.onerror = (e) => { loadLeaflet.p = null; reject(e); };
      document.head.appendChild(js);
    });
    return loadLeaflet.p;
  }

  function mapFeatures() {
    return state.result.table
      .filter((r) => typeof r.lat === 'number' && typeof r.long === 'number' && Math.abs(r.lat) <= 90 && Math.abs(r.long) <= 180)
      .map((r) => ({ row: r._row_number, lat: r.lat, lon: r.long, sev: geoStatus(r._row_number), overall: rowStatus(r._row_number), r }));
  }
  // No mapa a cor indica a situação da localização (coordenadas, UF, município), não a da linha inteira.
  function geoStatus(row) {
    let best = 'clear';
    (state.result._view.byRow.get(row) || []).forEach((i) => {
      if (categoryOf(i.code) !== 'geo' || i.severity === 'info') return;
      if (SEV_RANK[i.severity] < (SEV_RANK[best] ?? 9)) best = i.severity;
    });
    return best;
  }
  const GEO_LABEL = { error: 'Erro de localização', warning: 'Alerta de localização', clear: 'Localização sem problemas' };

  /* Enquadramento: ignora pontos muito distantes do núcleo (ex.: sinal trocado no meio do oceano),
   * que continuam no mapa e acessíveis pela lista lateral. */
  function coreBounds(pts) {
    if (pts.length < 10) return pts.map((p) => [p.lat, p.lon]);
    const q = (arr, f) => { const s = arr.slice().sort((a, b) => a - b); return s[Math.min(s.length - 1, Math.max(0, Math.round(f * (s.length - 1))))]; };
    const lats = pts.map((p) => p.lat); const lons = pts.map((p) => p.lon);
    const la = [q(lats, 0.02), q(lats, 0.98)]; const lo = [q(lons, 0.02), q(lons, 0.98)];
    const padLa = Math.max(0.5, (la[1] - la[0]) * 0.5); const padLo = Math.max(0.5, (lo[1] - lo[0]) * 0.5);
    const core = pts.filter((p) => p.lat >= la[0] - padLa && p.lat <= la[1] + padLa && p.lon >= lo[0] - padLo && p.lon <= lo[1] + padLo);
    return (core.length >= pts.length * 0.9 ? core : pts).map((p) => [p.lat, p.lon]);
  }

  function popupHtml(p) {
    const r = p.r;
    const taxon = [cap(clean(r.genus)), clean(r.sp1).toLowerCase()].filter(Boolean).join(' ');
    const items = (state.result._view.byRow.get(p.row) || []).filter((i) => i.severity !== 'info');
    const geo = items.filter((i) => categoryOf(i.code) === 'geo');
    const shown = (geo.length ? geo : items).slice(0, 4);
    return `<div class="tsr-pop"><div class="tsr-pop-head"><strong>Linha ${esc(p.row)}</strong>` +
      `<span class="tsr-sev" data-sev="${p.sev}">${GEO_LABEL[p.sev]}</span></div>` +
      (taxon || r.family ? `<div class="tsr-pop-taxon">${taxon ? `<em>${esc(taxon)}</em>` : ''}${r.family ? ` <small>${esc(cap(clean(r.family)))}</small>` : ''}</div>` : '') +
      `<div class="tsr-pop-meta">${esc(clean(r.collector).split(/[;&|]/)[0])} ${esc(r.number ?? '')}${r.collyy ? ` · ${esc(r.collyy)}` : ''}</div>` +
      (r.minorarea || r.majorarea ? `<div class="tsr-pop-meta">${esc([clean(r.minorarea), clean(r.majorarea)].filter(Boolean).join(' – '))}</div>` : '') +
      `<div class="tsr-pop-coord">${esc(p.lat.toFixed(5))}, ${esc(p.lon.toFixed(5))}</div>` +
      (p.overall !== 'clear' && !geo.length ? `<div class="tsr-pop-meta">A linha tem ${p.overall === 'error' ? 'erros' : 'alertas'} em outros campos.</div>` : '') +
      (shown.length ? `<ul class="tsr-pop-issues">${shown.map((i) => `<li data-sev="${i.severity}">${esc(i.message)}</li>`).join('')}` +
        `${items.length > shown.length ? `<li class="is-muted">+ ${items.length - shown.length} ocorrências</li>` : ''}</ul>` : '') +
      `<a href="#hv-row-${esc(p.row)}" data-goto="${esc(p.row)}">Ver na planilha →</a></div>`;
  }

  function renderMapSide(pts) {
    const side = $('tsr-map-side');
    if (!side) return;
    const st = state.result._stats;
    const by = { error: 0, warning: 0, clear: 0 };
    pts.forEach((p) => { by[p.sev] += 1; });
    const missing = st.total - pts.length;
    const outside = st.codeList.filter((c) => /^POINT_OUTSIDE/.test(c.code));
    const outsideRows = new Set(); outside.forEach((c) => c.rows.forEach((x) => outsideRows.add(x)));
    let bbox = '';
    if (pts.length) {
      const lats = pts.map((p) => p.lat); const lons = pts.map((p) => p.lon);
      bbox = `<dl class="tsr-dl"><dt>Latitude</dt><dd>${Math.min(...lats).toFixed(3)} a ${Math.max(...lats).toFixed(3)}</dd>` +
        `<dt>Longitude</dt><dd>${Math.min(...lons).toFixed(3)} a ${Math.max(...lons).toFixed(3)}</dd></dl>`;
    }
    side.innerHTML = `<h3>${fmt(pts.length)} pontos no mapa</h3>` +
      '<p class="tsr-map-note is-top">A cor indica só a situação da localização: coordenadas, UF e município.</p>' +
      `<ul class="tsr-map-counts">${['error', 'warning', 'clear'].map((k) => `<li><i class="tsr-swatch is-dot" data-sev="${k}"></i>${GEO_LABEL[k]}<strong>${fmt(by[k])}</strong></li>`).join('')}</ul>` +
      (missing ? `<p class="tsr-map-note">${plural(fmt(missing), 'linha não aparece', 'linhas não aparecem')} por falta de coordenada válida.</p>` : '') +
      bbox +
      (outsideRows.size ? `<h4>Pontos fora do limite esperado</h4><div class="tsr-issue-rows">${[...outsideRows].sort((a, b) => a - b).slice(0, 40).map((r) =>
        `<button type="button" class="tsr-chip" data-focus-row="${r}">${r}</button>`).join('')}</div>` : '') +
      '<p class="tsr-map-note">Clique em um ponto para ver o táxon, a localidade e as ocorrências da linha.</p>';
  }

  function renderMapFilters(pts) {
    const box = $('tsr-map-filters');
    if (!box) return;
    const by = { error: 0, warning: 0, clear: 0 };
    pts.forEach((p) => { by[p.sev] += 1; });
    const names = { error: 'Erro de localização', warning: 'Alerta', clear: 'Sem problemas' };
    box.innerHTML = ['error', 'warning', 'clear'].map((k) =>
      `<button type="button" class="tsr-seg-btn${state.mapFilter[k] ? ' is-active' : ''}" data-map-sev="${k}" aria-pressed="${state.mapFilter[k]}">` +
      `<i class="tsr-swatch is-dot" data-sev="${k}"></i>${names[k]} <span class="tsr-count">${fmt(by[k])}</span></button>`).join('');
  }

  async function openMap() {
    if (!state.result) return;
    const box = $('validator-map');
    if (!box) return;
    if (state.tab !== 'map') { switchTab('map'); return; }
    if (state.map) { setTimeout(() => state.map.invalidateSize(), 60); return; }
    const pts = mapFeatures();
    renderMapFilters(pts);
    renderMapSide(pts);
    if (!pts.length) { box.innerHTML = '<div class="tsr-map-empty">Nenhuma linha com latitude e longitude válidas.</div>'; return; }
    box.innerHTML = '<div class="tsr-map-empty">Carregando mapa…</div>';
    try {
      const L = await loadLeaflet();
      if (!state.result || state.map) return;
      box.innerHTML = '';
      const map = L.map(box, { scrollWheelZoom: false, preferCanvas: true, worldCopyJump: true });
      state.map = map;
      state.mapBase = L.tileLayer(...BASEMAPS[state.base || 'map']).addTo(map);
      const groups = { error: L.layerGroup(), warning: L.layerGroup(), clear: L.layerGroup() };
      state.mapMarkers = new Map();
      // Desenha os pontos sem problema primeiro, para os com erro ficarem por cima.
      ['clear', 'warning', 'error'].forEach((sev) => pts.filter((p) => p.sev === sev).forEach((p) => {
        const m = L.circleMarker([p.lat, p.lon], {
          radius: sev === 'clear' ? 5 : 6.5, weight: 2, color: '#fff', fillColor: SEV_COLOR[sev], fillOpacity: 0.92
        }).bindPopup(() => popupHtml(p), { maxWidth: 300 });
        m.addTo(groups[sev]);
        state.mapMarkers.set(p.row, { marker: m, sev });
      }));
      state.mapGroups = groups;
      ['clear', 'warning', 'error'].forEach((k) => { if (state.mapFilter[k]) groups[k].addTo(map); });
      map.on('click', () => map.scrollWheelZoom.enable());
      L.control.scale({ imperial: false }).addTo(map);
      const bounds = L.latLngBounds(coreBounds(pts));
      map.fitBounds(bounds.pad(0.15), { maxZoom: 12 });
      setTimeout(() => map.invalidateSize(), 120);
    } catch (err) {
      box.innerHTML = '<div class="tsr-map-empty">Não foi possível carregar o mapa base. Verifique a conexão e abra a aba novamente.</div>';
    }
  }

  function setMapFilter(sev) {
    state.mapFilter[sev] = !state.mapFilter[sev];
    document.querySelectorAll('[data-map-sev]').forEach((b) => {
      const on = state.mapFilter[b.dataset.mapSev];
      b.classList.toggle('is-active', on);
      b.setAttribute('aria-pressed', String(on));
    });
    if (state.map && state.mapGroups) {
      const g = state.mapGroups[sev];
      if (state.mapFilter[sev]) g.addTo(state.map); else state.map.removeLayer(g);
    }
  }

  function setBasemap(name) {
    state.base = name;
    document.querySelectorAll('[data-base]').forEach((b) => b.classList.toggle('is-active', b.dataset.base === name));
    if (state.map && window.L) {
      if (state.mapBase) state.map.removeLayer(state.mapBase);
      state.mapBase = window.L.tileLayer(...BASEMAPS[name]).addTo(state.map);
      state.mapBase.bringToBack();
    }
  }

  function focusRowOnMap(row) {
    const hit = state.mapMarkers && state.mapMarkers.get(Number(row));
    if (!hit || !state.map) return;
    if (!state.mapFilter[hit.sev]) setMapFilter(hit.sev);
    state.map.setView(hit.marker.getLatLng(), Math.max(state.map.getZoom(), 9));
    hit.marker.openPopup();
  }

  // ---------------------------------------------------------------- dica flutuante dos gráficos
  function installTooltip() {
    const tip = document.createElement('div');
    tip.className = 'tsr-tip';
    tip.setAttribute('role', 'tooltip');
    tip.hidden = true;
    document.body.appendChild(tip);
    const show = (el, x, y) => {
      tip.textContent = el.dataset.tip;
      tip.hidden = false;
      const w = tip.offsetWidth; const h = tip.offsetHeight;
      tip.style.left = Math.max(8, Math.min(x - w / 2, window.innerWidth - w - 8)) + 'px';
      tip.style.top = Math.max(8, y - h - 12) + 'px';
    };
    document.addEventListener('mousemove', (e) => {
      const el = e.target.closest && e.target.closest('#validator-results [data-tip]');
      if (!el) { tip.hidden = true; return; }
      show(el, e.clientX, e.clientY);
    });
    document.addEventListener('focusin', (e) => {
      const el = e.target.closest && e.target.closest('#validator-results [data-tip]');
      if (!el) { tip.hidden = true; return; }
      const r = el.getBoundingClientRect();
      show(el, r.left + r.width / 2, r.top);
    });
    window.addEventListener('scroll', () => { tip.hidden = true; }, { passive: true });
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
    $('map-button')?.addEventListener('click', () => {
      if (!state.result) return;
      switchTab('map');
      $('validator-results')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    $('download-issues-csv')?.addEventListener('click', downloadIssuesCsv);
    $('validator-code-filter')?.addEventListener('change', (e) => { state.code = e.target.value; state.page = 1; renderSheet(); });
    $('validator-show-info')?.addEventListener('change', (e) => { state.showInfo = e.target.checked; renderSheet(); renderIssueList(); });
    $('validator-only-issue-cols')?.addEventListener('change', (e) => { state.onlyIssueCols = e.target.checked; renderSheet(); });
    let searchTimer = null;
    $('validator-search')?.addEventListener('input', (e) => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { if (!state.result) return; state.query = e.target.value; state.page = 1; renderSheet(); }, 180);
    });
    document.querySelectorAll('.hv-filter[data-filter]').forEach((b) => b.addEventListener('click', () => {
      if (!state.result) return;
      state.filter = b.dataset.filter; state.page = 1;
      document.querySelectorAll('.hv-filter[data-filter]').forEach((x) => x.classList.toggle('is-active', x === b));
      renderSheet();
    }));
    const tabs = document.querySelector('.tsr-tabs');
    tabs?.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      const all = [...tabs.querySelectorAll('.tsr-tab')];
      const i = all.findIndex((t) => t.classList.contains('is-active'));
      const next = all[(i + (e.key === 'ArrowRight' ? 1 : all.length - 1)) % all.length];
      switchTab(next.dataset.tab); next.focus();
    });
    document.addEventListener('click', (e) => {
      const t = e.target;
      const tab = t.closest('.tsr-tab[data-tab]');
      if (tab && state.result) { switchTab(tab.dataset.tab); return; }
      const open = t.closest('[data-open-tab]');
      if (open && state.result) { switchTab(open.dataset.openTab); $('validator-results')?.querySelector('.tsr-tabs')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); return; }
      const code = t.closest('[data-code]');
      if (code && state.result && !t.closest('summary')) { filterByCode(code.dataset.code); return; }
      const rf = t.closest('[data-row-filter]');
      if (rf && state.result) { filterByStatus(rf.dataset.rowFilter); return; }
      const ms = t.closest('[data-map-sev]');
      if (ms) { setMapFilter(ms.dataset.mapSev); return; }
      const base = t.closest('[data-base]');
      if (base) { setBasemap(base.dataset.base); return; }
      const focus = t.closest('[data-focus-row]');
      if (focus) { focusRowOnMap(focus.dataset.focusRow); return; }
      if (t.closest('[data-clear-filters]') && state.result) {
        state.code = ''; state.query = ''; state.page = 1;
        const sel = $('validator-code-filter'); if (sel) sel.value = '';
        const s = $('validator-search'); if (s) s.value = '';
        renderSheet(); return;
      }
      const more = t.closest('[data-more]');
      if (more && state.result) { state.page += 1; renderSheet(); return; }
      const go = t.closest('[data-goto]');
      if (go && state.result) { e.preventDefault(); gotoRow(go.dataset.goto); return; }
      if (!t.closest('.hv-mapper-v20-help') && !t.closest('.hv-mapper-v20-popup')) {
        document.querySelectorAll('.hv-mapper-v20-popup').forEach((p) => p.remove());
      }
      onMapperEvent(e);
    });
    document.addEventListener('keydown', (e) => {
      if ((e.key === 'Enter' || e.key === ' ') && e.target.matches && e.target.matches('.tsr-bar-row[data-code]')) {
        e.preventDefault(); filterByCode(e.target.dataset.code);
      }
    });
    ['download-annotated', 'tsr-download-annotated'].forEach((id) => $(id)?.addEventListener('click', (e) => {
      if (e.currentTarget.getAttribute('aria-disabled') === 'true') e.preventDefault();
    }));
    document.addEventListener('change', onMapperEvent);
    ['dragstart', 'dragover', 'dragleave', 'drop'].forEach((t) => document.addEventListener(t, onDrag));
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') document.querySelectorAll('.hv-mapper-v20-popup').forEach((p) => p.remove());
      if (state.mapper && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.target.matches('input, textarea')) {
        e.preventDefault();
        if (state.mapper.undo.length) { state.mapper.mapping = JSON.parse(state.mapper.undo.pop()); renderMapper(); }
      }
    });
    installTooltip();
    const tpl = $('download-template');
    if (tpl) tpl.href = API + '/converter/template';
    // Acorda o Space em segundo plano assim que a página abre (sem bloquear a interface).
    fetch(API_ROOT + '/health', { cache: 'no-store' }).catch(() => null);
  }

  window.TsiinoValidator = { api: API, state, showResult, openMapper, switchTab };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
  else install();
})();
