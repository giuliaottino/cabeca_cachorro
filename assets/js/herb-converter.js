/* TSIINO_MAPPER_ROWS_HELP_V20 */
(function () {
  'use strict';

  const LOCAL_API = 'http://127.0.0.1:8000/api/validator';
  const PROD_API = 'https://api.tsiinohiiwiida.net/api/validator';
  const host = window.location.hostname;
  const API_BASE = (!host || host === '127.0.0.1' || host === 'localhost') ? LOCAL_API : PROD_API;

  const FIELD_DEFS = [
    ['accession','ACCESSION','Registro INPA','Deixar este campo em branco. Aqui será incluído o número de registro no Herbário INPA.'],
    ['collector','COLLECTOR','Coletor principal','Nome do coletor principal. Formato: Silva, LIL da. Inclua o nome completo na aba Pessoas-Coletores.'],
    ['prefix','PREFIX','Prefixo','Usar este campo somente no caso de séries diferentes. Não colocar suas iniciais.'],
    ['number','NUMBER','Número de coleta','Número de coleta do coletor principal. Evite "s.n.". Use números sequenciais.'],
    ['suffix','SUFFIX','Sufixo','Usar somente se o número de coleta foi repetido por engano. Nesse caso pode preencher com A, B, C...'],
    ['addcoll','ADDCOLL','Coletores adicionais','Demais pessoas presentes na coleta. Mesmo formato do coletor, separados por ponto-vírgula.'],
    ['colldd','COLLDD','Dia da coleta','Dia da coleta.'],
    ['collmm','COLLMM','Mês da coleta','Mês da coleta.'],
    ['collyy','COLLYY','Ano da coleta','Ano da coleta.'],
    ['initial','INITIAL','Nº de amostras','Número de amostras por coleta, ou seja, em quantas amostras sua coleta foi dividida.'],
    ['family','FAMILY','Família','Família. Verifique a grafia correta do nome da família na Flora e Funga do Brasil e/ou MOBOT.'],
    ['genus','GENUS','Gênero','Gênero. Verifique a grafia correta do nome do gênero na Flora e Funga do Brasil e/ou MOBOT.'],
    ['detstatus','DETSTATUS','cf./aff.','Use “cf.” para conferir e “aff.” para material afim quando não tiver certeza do táxon.'],
    ['sp1','SP1','Epíteto específico','Epíteto específico. Se souber o gênero e não souber o epíteto, deixe em branco; não escreva “sp.”.'],
    ['rank1','RANK1','Rank infraespecífico','Use “ssp.” para subespécie ou “var.” para variedade.'],
    ['sp2','SP2','Epíteto infraespecífico','Epíteto da subespécie ou variedade.'],
    ['detby','DETBY','Determinador','Nome do determinador, no mesmo formato do coletor. Separe múltiplos nomes por ponto-vírgula.'],
    ['detdd','DETDD','Dia da determinação','Dia da determinação.'],
    ['detmm','DETMM','Mês da determinação','Mês da determinação.'],
    ['detyy','DETYY','Ano da determinação','Ano da determinação.'],
    ['country','COUNTRY','País','País.'],
    ['majorarea','MAJORAREA','Estado','Estado por extenso. Não usar sigla.'],
    ['minorarea','MINORAREA','Município','Município.'],
    ['gazetteer','GAZETTEER','Localidade','Localidade, por exemplo Campus do INPA, Reserva Florestal Adolfo Ducke, BR174 etc.'],
    ['locnotes','LOCNOTES','Notas da localidade','Detalhes de onde a coleta foi feita, por exemplo ao lado da cantina, atrás do alojamento etc.'],
    ['habitattxt','HABITATTXT','Habitat','Descrição do tipo de habitat onde a planta foi coletada.'],
    ['lat','LAT','Latitude','Latitude em graus decimais. Usar sinal negativo para Sul e sem sinal para Norte.'],
    ['NS','NS','N/S','Utilizar N para Norte e S para Sul. Usar sinal negativo para Sul na latitude.'],
    ['long','LONG','Longitude','Longitude em graus decimais. Usar sinal negativo para Oeste no Brasil.'],
    ['EW','EW','E/W','Utilizar E para Leste e W para Oeste. Usar sinal negativo quando necessário.'],
    ['llunit','LLUNIT','Unidade lat/long','Deixar este campo em branco no padrão INPA/BRAHMS.'],
    ['alt','ALT','Altitude','Altitude em metros. Não incluir “m”.'],
    ['alt1','ALT1','Altitude máxima','Usar somente quando houver duas medidas de altitude.'],
    ['plantdesc','PLANTDESC','Descrição da planta','Descrição detalhada do indivíduo coletado: hábito, tamanho, exsudatos, odores, cores etc. Não copiar descrições gerais de livros/artigos.'],
    ['vernacular','VERNACULAR','Nome vernacular','Nome popular da planta, em minúsculo; se houver mais de um, separar por ponto-vírgula.'],
    ['dups','DUPS','Duplicatas','Siglas dos herbários onde o material será depositado. Para INPA, preencher com INPA.'],
    ['project','PROJECT','Projeto','Campo opcional para nome do projeto/órgão financiador, com até 60 caracteres.'],
    ['genbank','GENBANK','GenBank','Sequências, DNA ou gene. Se houver, mencionar gene, primers ou número de acesso no GenBank.']
  ];

  const FIELDS = FIELD_DEFS.map(([key, code, label, help]) => ({ key, code, label, help }));
  const FIELD_KEYS = new Set(FIELDS.map(f => f.key));
  let state = { file:null, preview:null, columns:[], rows:[], mapping:{}, help:{}, undo:[], redo:[], popup:null };

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])); }
  function norm(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,' ').trim(); }
  function cleanHeader(h) {
    if (h == null) return '';
    if (typeof h === 'string') return h;
    if (typeof h === 'object') return String(h.header || h.name || h.key || h.label || h.title || h.original || '').trim();
    return String(h).trim();
  }
  function cleanText(s) {
    return String(s ?? '')
      .replace(/Ã§/g,'ç').replace(/Ã£/g,'ã').replace(/Ã¡/g,'á').replace(/Ã©/g,'é').replace(/Ãª/g,'ê')
      .replace(/Ã³/g,'ó').replace(/Ãµ/g,'õ').replace(/Ãº/g,'ú').replace(/Ã­/g,'í').replace(/Âº/g,'º').replace(/Âª/g,'ª');
  }
  function setStatus(msg) { const el = $('converter-status-v20'); if (el) el.textContent = msg; }

  const ALIASES = [
    [/nome do coletor principal|coletor principal|recordedby|recorded by|coletor|collector/, 'collector'],
    [/seu numero de coleta|seu número de coleta|numero de coleta|número de coleta|record ?number|num coleta|number/, 'number'],
    [/prefixo|prefix|series|série|serie/, 'prefix'],
    [/sufixo|suffix/, 'suffix'],
    [/quem estava presente|coletores adicionais|coletor adicional|addcoll|additional collectors/, 'addcoll'],
    [/^dia$|dia da coleta|data dia|colldd/, 'colldd'],
    [/^mes$|^mês$|mes da coleta|mês da coleta|collmm/, 'collmm'],
    [/^ano$|ano da coleta|collyy/, 'collyy'],
    [/numero de duplicatas|número de duplicatas|duplicatas coletadas|duplicatas|dups/, 'dups'],
    [/numero de amostras|número de amostras|n amostras|initial/, 'initial'],
    [/familia|família|family/, 'family'],
    [/genero|gênero|genus/, 'genus'],
    [/cf|aff|detstatus/, 'detstatus'],
    [/epiteto da especie|epíteto da espécie|epiteto especifico|epíteto específico|species|sp1/, 'sp1'],
    [/subespecie|subespécie|rank infra|rank1/, 'rank1'],
    [/variedade|epiteto infra|epíteto infra|sp2/, 'sp2'],
    [/determinador|identified by|detby/, 'detby'],
    [/dia de determinacao|dia de determinação|detdd/, 'detdd'],
    [/mes de determinacao|mês de determinação|detmm/, 'detmm'],
    [/ano de determinacao|ano de determinação|detyy/, 'detyy'],
    [/pais|país|country/, 'country'],
    [/estado|uf|majorarea/, 'majorarea'],
    [/municipio|município|minorarea|cidade/, 'minorarea'],
    [/localidade|gazetteer/, 'gazetteer'],
    [/detalhes de onde|notas localidade|locnotes/, 'locnotes'],
    [/habitat|vegetacao|vegetação|habitattxt/, 'habitattxt'],
    [/latitude|\blat\b/, 'lat'],
    [/longitude|\blong\b|\blon\b/, 'long'],
    [/\bns\b|n\/s|hemisferio latitude|hemisfério latitude/, 'NS'],
    [/\bew\b|e\/w|hemisferio longitude|hemisfério longitude/, 'EW'],
    [/dms|graus minutos segundos|unidade coordenada|llunit/, 'llunit'],
    [/altitude maxima|altitude máxima|alt1/, 'alt1'],
    [/altitude|\balt\b/, 'alt'],
    [/descricao detalhada|descricao da planta|descrição da planta|descrição detalhada|plantdesc/, 'plantdesc'],
    [/nome popular|nome vernacular|vernacular/, 'vernacular'],
    [/projeto|project/, 'project'],
    [/genbank|gene|dna|sequenc/, 'genbank']
  ];

  function guessField(col) {
    const n = norm(cleanHeader(col));
    if (!n || /notas para voce seguir|notas para você seguir|exemplo|seus dados/.test(n)) return null;
    if (FIELD_KEYS.has(col)) return col;
    if (FIELD_KEYS.has(n)) return n;
    for (const [rx, target] of ALIASES) if (rx.test(n)) return target;
    return null;
  }

  async function postForm(path, file, extra={}) {
    const fd = new FormData();
    const realFile = file instanceof File ? file : $('spreadsheet-file')?.files?.[0];
    if (!realFile) throw new Error('Nenhuma planilha selecionada.');
    fd.append('file', realFile, realFile.name || 'planilha.xlsx');
    for (const [k,v] of Object.entries(extra)) fd.append(k, v);
    const res = await fetch(API_BASE + path, { method:'POST', body: fd });
    if (!res.ok) throw new Error(path + ' retornou ' + res.status);
    return res;
  }

  function extractColumns(obj) {
    const candidates = [obj?.source_columns, obj?.headers, obj?.columns, obj?.raw_headers, obj?.preview?.source_columns, obj?.preview?.headers];
    for (const arr of candidates) {
      if (Array.isArray(arr) && arr.length) {
        const out = arr.map(cleanHeader).filter(Boolean);
        if (out.length) return Array.from(new Set(out));
      }
    }
    return [];
  }

  function extractRows(preview, rowsInfo, columns) {
    const candidates = [rowsInfo?.rows, rowsInfo?.preview_rows, rowsInfo?.data_rows, rowsInfo?.source_rows, preview?.rows, preview?.preview_rows, preview?.data_rows, preview?.source_rows];
    let raw = [];
    for (const x of candidates) if (Array.isArray(x) && x.length) { raw = x; break; }
    if (!raw.length) return [];
    if (Array.isArray(raw[0])) {
      return raw.map((arr, i) => {
        const row = { _row_number: i + 1, _values: arr };
        columns.forEach((c, j) => row[c] = cleanText(arr[j] ?? ''));
        return row;
      });
    }
    return raw.map((r, i) => {
      const row = { _row_number: r._row_number || r.row_number || r.linha || r.line || i + 1 };
      if (r._source && typeof r._source === 'object') {
        Object.entries(r._source).forEach(([k,v]) => row[cleanHeader(k)] = cleanText(v));
      }
      Object.entries(r).forEach(([k,v]) => {
        if (k === '_source') return;
        row[cleanHeader(k)] = typeof v === 'object' && v !== null ? v : cleanText(v);
      });
      return row;
    });
  }

  function extractHelp(preview, rowsInfo) {
    const help = {};
    for (const f of FIELDS) help[f.key] = f.help;
    const sources = [preview?.field_help, preview?.fieldHelp, rowsInfo?.field_help, rowsInfo?.fieldHelp, preview?.recommendations, rowsInfo?.recommendations];
    for (const src of sources) {
      if (!src || typeof src !== 'object') continue;
      Object.entries(src).forEach(([k,v]) => { if (FIELD_KEYS.has(k) && v) help[k] = cleanText(v); });
    }
    return help;
  }

  function extractMapping(preview, rowsInfo, columns) {
    const mapping = {};
    const used = new Set();
    function set(field, source) {
      source = cleanHeader(source);
      if (!FIELD_KEYS.has(field) || !source || mapping[field]) return;
      mapping[field] = source;
      used.add(source);
    }
    const candidates = [rowsInfo?.canonical_mapping, preview?.canonical_mapping, preview?.mapping, rowsInfo?.mapping, preview?.suggested_mapping, rowsInfo?.suggested_mapping, preview?.column_mapping, rowsInfo?.column_mapping];
    for (const raw of candidates) {
      if (!raw || typeof raw !== 'object') continue;
      Object.entries(raw).forEach(([a,b]) => {
        const aa = cleanHeader(a), bb = cleanHeader(b);
        if (FIELD_KEYS.has(aa)) set(aa, bb);
        else if (FIELD_KEYS.has(bb)) set(bb, aa);
      });
    }
    for (const col of columns) {
      if (used.has(col)) continue;
      const f = guessField(col);
      if (f) set(f, col);
    }
    return mapping;
  }

  async function getPreview(file) {
    const preview = await (await postForm('/converter/preview', file)).json();
    let rowsInfo = null;
    try {
      rowsInfo = await (await postForm('/converter/preview_rows', file, { max_rows:'80' })).json();
    } catch (err) {
      console.warn('[Tsiino] preview_rows indisponível; usando preview principal.', err);
    }
    const merged = Object.assign({}, preview || {}, rowsInfo || {});
    const columns = extractColumns(merged);
    const rows = extractRows(preview, rowsInfo, columns);
    const mapping = extractMapping(preview, rowsInfo, columns);
    const help = extractHelp(preview, rowsInfo);
    return { preview, rowsInfo, columns, rows, mapping, help };
  }

  function ensurePanel() {
    let panel = $('tsiino-mapper-v20');
    if (panel) return panel;
    panel = document.createElement('section');
    panel.id = 'tsiino-mapper-v20';
    panel.className = 'hv-mapper-v20';
    const anchor = $('validator-status') || $('herb-validator-form') || document.querySelector('form');
    if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(panel, anchor.nextSibling);
    else document.body.appendChild(panel);
    return panel;
  }

  function fieldForColumn(col) { return Object.entries(state.mapping).find(([,v]) => v === col)?.[0] || null; }
  function colLetter(i) { let n=i+1,s=''; while(n>0){const m=(n-1)%26;s=String.fromCharCode(65+m)+s;n=Math.floor((n-1)/26);} return s; }
  function pushUndo(){ state.undo.push(JSON.stringify(state.mapping)); state.redo=[]; updateUndoButtons(); }
  function undo(){ if(!state.undo.length) return; state.redo.push(JSON.stringify(state.mapping)); state.mapping=JSON.parse(state.undo.pop()); renderTable(); updateUndoButtons(); }
  function redo(){ if(!state.redo.length) return; state.undo.push(JSON.stringify(state.mapping)); state.mapping=JSON.parse(state.redo.pop()); renderTable(); updateUndoButtons(); }
  function updateUndoButtons(){ const u=$('mapper-undo-v20'), r=$('mapper-redo-v20'); if(u) u.disabled=!state.undo.length; if(r) r.disabled=!state.redo.length; }

  function chip(col) {
    if (!col) return '<span class="hv-mapper-v20-empty">solte uma coluna aqui</span>';
    const idx = state.columns.indexOf(col);
    return `<span class="hv-mapper-v20-chip" draggable="true" data-column="${esc(col)}"><span class="hv-mapper-v20-letter">${esc(idx >= 0 ? colLetter(idx) : '')}</span><span class="hv-mapper-v20-chip-text">${esc(col)}</span><button type="button" class="hv-mapper-v20-remove" data-remove="${esc(col)}">×</button></span>`;
  }

  function rowValue(row, field) {
    const source = state.mapping[field];
    const choices = [source, field];
    for (const key of choices) {
      if (!key) continue;
      if (row[key] != null && row[key] !== '') return row[key];
      const match = Object.keys(row).find(k => norm(k) === norm(key));
      if (match && row[match] != null && row[match] !== '') return row[match];
    }
    if (Array.isArray(row._values) && source) {
      const idx = state.columns.indexOf(source);
      if (idx >= 0 && row._values[idx] != null) return row._values[idx];
    }
    return '';
  }

  function closePopup(){ if(state.popup){ state.popup.remove(); state.popup=null; } }
  function showPopup(e, field) {
    closePopup();
    const def = FIELDS.find(f => f.key === field) || { code: field.toUpperCase(), label: field, help: '' };
    const help = state.help[field] || def.help || 'Campo do padrão INPA/BRAHMS.';
    const box = document.createElement('div');
    box.className = 'hv-mapper-v20-popup';
    box.innerHTML = `<div class="hv-mapper-v20-popup-code">${esc(def.code || field.toUpperCase())}</div><strong>${esc(def.label || field)}</strong><p>${esc(help)}</p>`;
    document.body.appendChild(box);
    const r = e.currentTarget.getBoundingClientRect();
    box.style.left = Math.min(r.left, window.innerWidth - 390) + 'px';
    box.style.top = Math.min(r.bottom + 8, window.innerHeight - 190) + 'px';
    state.popup = box;
    e.stopPropagation();
  }

  function renderTable() {
    const wrap = $('mapper-table-wrap-v20');
    if (!wrap) return;
    const sl = wrap.scrollLeft, st = wrap.scrollTop;
    let html = '<table class="hv-mapper-v20-grid"><thead><tr><th>PADRÃO<br>INPA</th>';
    for (const f of FIELDS) html += `<th><span class="hv-mapper-v20-code">${esc(f.code)}</span><button type="button" class="hv-mapper-v20-help" data-help="${esc(f.key)}">?</button></th>`;
    html += '</tr></thead><tbody><tr class="hv-mapper-v20-source-row"><td>SUA<br>PLANILHA</td>';
    for (const f of FIELDS) html += `<td><div class="hv-mapper-v20-slot" data-field="${esc(f.key)}">${chip(state.mapping[f.key])}</div></td>`;
    html += '</tr>';
    const rows = state.rows.slice(0, 80);
    for (const [i,row] of rows.entries()) {
      html += `<tr><td>${esc(row._row_number ? 'Linha ' + row._row_number : 'Linha ' + (i+1))}</td>`;
      for (const f of FIELDS) html += `<td><div class="hv-mapper-v20-data">${esc(rowValue(row, f.key))}</div></td>`;
      html += '</tr>';
    }
    const unmapped = state.columns.filter(c => !fieldForColumn(c));
    if (unmapped.length) html += `<tr class="hv-mapper-v20-unmapped"><td>SEM<br>DESTINO</td><td colspan="${FIELDS.length}">${unmapped.map(chip).join(' ')}</td></tr>`;
    html += '</tbody></table>';
    wrap.innerHTML = html;
    installEvents();
    requestAnimationFrame(() => { wrap.scrollLeft = sl; wrap.scrollTop = st; });
  }

  function installEvents() {
    document.querySelectorAll('.hv-mapper-v20-help').forEach(b => b.addEventListener('click', e => showPopup(e, b.dataset.help)));
    document.querySelectorAll('.hv-mapper-v20-remove').forEach(b => b.addEventListener('click', e => {
      e.stopPropagation(); pushUndo(); const col=b.dataset.remove; const f=fieldForColumn(col); if(f) delete state.mapping[f]; renderTable();
    }));
    document.querySelectorAll('.hv-mapper-v20-chip').forEach(el => el.addEventListener('dragstart', e => e.dataTransfer.setData('text/plain', el.dataset.column)));
    document.querySelectorAll('.hv-mapper-v20-slot').forEach(slot => {
      slot.addEventListener('dragover', e => { e.preventDefault(); slot.classList.add('is-drop'); });
      slot.addEventListener('dragleave', () => slot.classList.remove('is-drop'));
      slot.addEventListener('drop', e => {
        e.preventDefault(); slot.classList.remove('is-drop');
        const col = e.dataTransfer.getData('text/plain'); const target = slot.dataset.field;
        if (!col || !target) return;
        pushUndo();
        const old = fieldForColumn(col);
        const displaced = state.mapping[target];
        if (old) delete state.mapping[old];
        state.mapping[target] = col;
        if (displaced && old && displaced !== col) state.mapping[old] = displaced;
        renderTable();
      });
    });
  }

  function renderPanel() {
    const panel = ensurePanel();
    panel.hidden = false;
    panel.innerHTML = `<div class="hv-mapper-v20-head"><div><h3>Mapear colunas para o padrão INPA</h3><p>A linha “Sua planilha” mostra as colunas da planilha enviada; as linhas abaixo mostram os dados reais para conferência. Use o botão “?” para ver a recomendação de preenchimento do campo INPA.</p></div><button type="button" class="hv-secondary" id="mapper-close-v20">Fechar</button></div><div id="converter-status-v20" class="hv-mapper-v20-status">${state.rows.length ? state.rows.length + ' linhas de dados carregadas para conferência.' : 'Nenhuma linha de dado carregada.'}</div><div class="hv-mapper-v20-tools"><button type="button" class="hv-secondary" id="mapper-undo-v20">Desfazer</button><button type="button" class="hv-secondary" id="mapper-redo-v20">Refazer</button></div><div id="mapper-table-wrap-v20" class="hv-mapper-v20-tablewrap"></div><div class="hv-mapper-v20-actions"><button type="button" class="hv-primary" id="mapper-apply-v20">Aplicar mapeamento e validar</button><button type="button" class="hv-secondary" id="mapper-download-v20">Baixar convertida sem anotação</button><button type="button" class="hv-secondary" id="mapper-reset-v20">Restaurar sugestões</button></div>`;
    $('mapper-close-v20')?.addEventListener('click', () => panel.hidden = true);
    $('mapper-undo-v20')?.addEventListener('click', undo);
    $('mapper-redo-v20')?.addEventListener('click', redo);
    $('mapper-reset-v20')?.addEventListener('click', () => { pushUndo(); state.mapping = extractMapping(state.preview, state.rowsInfo, state.columns); renderTable(); });
    $('mapper-apply-v20')?.addEventListener('click', applyAndValidate);
    $('mapper-download-v20')?.addEventListener('click', downloadConverted);
    renderTable(); updateUndoButtons(); panel.scrollIntoView({ behavior:'smooth', block:'start' });
  }

  function mappingPayload(){ return JSON.stringify(state.mapping); }
  async function convertBlob() {
    const fd = new FormData();
    fd.append('file', state.file, state.file.name || 'planilha.xlsx');
    fd.append('mapping', mappingPayload());
    fd.append('column_mapping', mappingPayload());
    fd.append('mapping_json', mappingPayload());
    const res = await fetch(API_BASE + '/converter/convert_tolerant_v28', { method:'POST', body: fd });
    if (!res.ok) throw new Error('Não foi possível converter: ' + res.status);
    return await res.blob();
  }
  async function uploadBlob(blob) {
    const fd = new FormData();
    fd.append('file', new File([blob], 'planilha_convertida_INPA.xlsx', { type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }));
    const res = await fetch(API_BASE + '/upload', { method:'POST', body: fd });
    if (!res.ok) throw new Error('Não foi possível validar: ' + res.status);
    return await res.json();
  }
  async function applyAndValidate(){
    const btn = $('mapper-apply-v20');
    try {
      if (btn) { btn.disabled = true; btn.textContent = 'Convertendo e validando...'; }
      setStatus('Convertendo e validando...');
      const blob = await convertBlob();
      const job = await uploadBlob(blob);
      const jobId = job.job_id || job.jobId || job.id;
      if (window.TsiinoValidatorBridge?.applyJob) await window.TsiinoValidatorBridge.applyJob(jobId);
      else if (window.TsiinoRenderResultFromJobResponse) await window.TsiinoRenderResultFromJobResponse(job);
      setStatus('Validação concluída.');
    } catch (err) {
      console.error('[Tsiino] Falha ao aplicar mapeamento e validar', err);
      setStatus('Não foi possível converter e validar: ' + (err.message || err));
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Aplicar mapeamento e validar'; }
    }
  }
  async function downloadConverted(){
    try {
      const blob = await convertBlob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = 'planilha_convertida_INPA.xlsx'; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1500);
    } catch (err) { setStatus('Não foi possível baixar: ' + (err.message || err)); }
  }
  async function openMapper(file) {
    state.file = file instanceof File ? file : $('spreadsheet-file')?.files?.[0];
    if (!state.file) throw new Error('Nenhuma planilha selecionada.');
    const panel = ensurePanel();
    panel.hidden = false;
    panel.innerHTML = '<div class="hv-mapper-v20-status">Carregando colunas e linhas da planilha enviada...</div>';
    const data = await getPreview(state.file);
    state.preview = data.preview; state.rowsInfo = data.rowsInfo; state.columns = data.columns; state.rows = data.rows; state.mapping = data.mapping; state.help = data.help; state.undo = []; state.redo = [];
    renderPanel();
  }

  document.addEventListener('click', e => { if(!e.target.closest('.hv-mapper-v20-help') && !e.target.closest('.hv-mapper-v20-popup')) closePopup(); });
  document.addEventListener('keydown', e => { if(e.key === 'Escape') closePopup(); if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'&&!e.shiftKey){e.preventDefault();undo();} if((e.ctrlKey||e.metaKey)&&(e.key.toLowerCase()==='y'||(e.shiftKey&&e.key.toLowerCase()==='z'))){e.preventDefault();redo();} });

  const integration = { open: openMapper, showFromFile: openMapper, openAfterValidationFailure: async function(x){ return openMapper(x instanceof File ? x : undefined); }, openFromFile: openMapper, openMapper, version:'mapper-rows-help-v20' };
  window.TsiinoConverterIntegration = integration;
  window.TsiinoConverter = Object.assign(window.TsiinoConverter || {}, { showFromFile: openMapper, open: openMapper, version:'mapper-rows-help-v20' });
  window.TsiinoMapperCompatReady = true;
})();
