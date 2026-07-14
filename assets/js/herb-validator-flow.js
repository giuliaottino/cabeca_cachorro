// TSIINO_STABLE_SUBMIT_FLOW_20260701
(function () {
  const LOCAL_API = 'http://127.0.0.1:8000/api/validator';
  const PROD_API = 'https://api.tsiinohiiwiida.net/api/validator';
  const host = window.location.hostname;
  const API_BASE = (!host || host === '127.0.0.1' || host === 'localhost') ? LOCAL_API : PROD_API;
  let running = false;
  let lastJobId = null;
  function $(id) { return document.getElementById(id); }
  function setStatus(message, type) {
    if (window.TsiinoValidatorBridge && typeof window.TsiinoValidatorBridge.setStatus === 'function') { window.TsiinoValidatorBridge.setStatus(message, type || 'info'); return; }
    const el = $('validator-status'); if (el) { el.hidden = false; el.className = 'hv-status ' + (type || 'info'); el.textContent = message; }
  }
  function setBusy(flag) { const btn = $('validate-button'); if (!btn) return; btn.disabled = !!flag; btn.textContent = flag ? 'Validando...' : 'Validar planilha'; }
  function getFile() { const input = $('spreadsheet-file'); return input && input.files ? input.files[0] : null; }
  function sheetName() { const el = $('sheet-name'); return el && el.value ? el.value.trim() : ''; }
  async function fetchOk(url, options) {
    const response = await fetch(url, options || {});
    if (!response.ok) { let detail = ''; try { const data = await response.json(); detail = data.detail || JSON.stringify(data); } catch (_) { detail = await response.text(); } throw new Error(detail || ('HTTP ' + response.status)); }
    return response;
  }
  function formDataForFile(file) { const fd = new FormData(); fd.append('file', file, file.name || 'planilha.xlsx'); if (sheetName()) fd.append('sheet_name', sheetName()); return fd; }
  async function previewFile(file) { const response = await fetchOk(API_BASE + '/converter/preview', { method: 'POST', body: formDataForFile(file) }); return await response.json(); }
  async function convertFile(file, mapping, includeRecommendationRow) {
    const fd = formDataForFile(file); fd.append('mapping', JSON.stringify(mapping || {})); fd.append('include_recommendation_row', includeRecommendationRow ? 'true' : 'false');
    const response = await fetchOk(API_BASE + '/converter/convert', { method: 'POST', body: fd });
    const blob = await response.blob(); const base = (file.name || 'planilha.xlsx').replace(/\.[^.]+$/, '');
    return new File([blob], base + '_convertida_INPA.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  }
  async function uploadForValidation(file) {
    const fd = new FormData(); fd.append('file', file, file.name || 'planilha_convertida_INPA.xlsx');
    const collection = $('collection'), tax = $('validate-taxonomy'), geo = $('validate-geography');
    if (collection) fd.append('collection', collection.value || 'INPA'); if (sheetName()) fd.append('sheet_name', sheetName());
    if (tax) fd.append('validate_taxonomy', tax.checked ? 'true' : 'false'); if (geo) fd.append('validate_geography', geo.checked ? 'true' : 'false');
    const response = await fetchOk(API_BASE + '/upload', { method: 'POST', body: fd }); const data = await response.json();
    const jobId = data.job_id || data.jobId || data.id || (data.job && (data.job.job_id || data.job.id)); if (!jobId) throw new Error('A API validou, mas não retornou job_id.'); return jobId;
  }
  async function renderJob(jobId) {
    lastJobId = jobId;
    if (window.TsiinoValidatorBridge && typeof window.TsiinoValidatorBridge.applyJob === 'function') await window.TsiinoValidatorBridge.applyJob(jobId); else throw new Error('TsiinoValidatorBridge.applyJob não está disponível.');
    const download = $('download-annotated');
    if (download) { download.href = API_BASE + '/jobs/' + encodeURIComponent(jobId) + '/download.xlsx'; download.setAttribute('download', 'tsiino_planilha_anotada_' + jobId + '.xlsx'); download.classList.remove('is-disabled'); download.setAttribute('aria-disabled', 'false'); }
    const results = $('validator-results'); if (results) results.hidden = false; setTimeout(cleanRenderedTable, 50);
  }
  function cleanRenderedTable() {
    const table = $('validator-sheet'); if (!table) return;
    const headers = Array.from(table.querySelectorAll('thead th, tr:first-child th, tr:first-child td')); const hideIndexes = [];
    headers.forEach((th, idx) => { const text = (th.textContent || '').trim().toLowerCase(); if (text === '_raw' || text === '_row_number') hideIndexes.push(idx + 1); });
    hideIndexes.forEach((idx) => { table.querySelectorAll('tr').forEach((tr) => { const cell = tr.children[idx - 1]; if (cell) cell.style.display = 'none'; }); });
    table.querySelectorAll('*').forEach((el) => { if (el.childNodes.length === 1 && el.firstChild.nodeType === Node.TEXT_NODE) el.textContent = fixMojibake(el.textContent); });
  }
  function fixMojibake(text) { if (!text || (!text.includes('Ã') && !text.includes('Â'))) return text; try { return decodeURIComponent(escape(text)); } catch (_) { return text; } }
  async function handleSubmit(event) {
    event.preventDefault(); event.stopImmediatePropagation(); if (running) return;
    const file = getFile(); if (!file) { setStatus('Selecione uma planilha .xlsx ou .xlsm.', 'error'); return; }
    running = true; setBusy(true);
    try {
      setStatus('Analisando estrutura da planilha...', 'info'); const preview = await previewFile(file);
      if (!preview.detected_standard) {
        setStatus('Planilha fora do padrão detectada. Faça o mapeamento das colunas e valide a versão convertida.', 'warning');
        if (typeof window.TsiinoInstallMapperOpenAlias === 'function') window.TsiinoInstallMapperOpenAlias();
        const mapper = window.TsiinoConverterIntegration || window.TsiinoConverter;
        const openMapper = mapper && (mapper.open || mapper.openAfterValidationFailure || mapper.showFromFile || mapper.openFromPreview || mapper.openMapper);
        if (typeof openMapper !== 'function') {
          console.error('[Tsiino] Mapper indisponível no hotfix v10:', {
            integration: window.TsiinoConverterIntegration,
            converter: window.TsiinoConverter,
            compatReady: window.TsiinoMapperCompatReady
          });
          throw new Error('O mapeador de colunas não carregou.');
        }
        await openMapper.call(mapper, preview, file);
        return;
      }
      setStatus('Planilha padrão INPA/BRAHMS reconhecida. Normalizando cabeçalho técnico e validando...', 'info');
      const normalized = await convertFile(file, preview.suggested_mapping || {}, false); const jobId = await uploadForValidation(normalized); await renderJob(jobId);
      setStatus('Validação concluída. Corrija as células destacadas ou baixe a cópia .xlsx anotada.', 'ok');
    } catch (err) { console.error('[Tsiino] Falha na validação:', err); setStatus('Não foi possível validar: ' + (err && err.message ? err.message : err), 'error'); }
    finally { running = false; setBusy(false); }
  }
  function resetOnFileChange() { running = false; setBusy(false); const results = $('validator-results'); if (results) results.hidden = true; const download = $('download-annotated'); if (download) { download.href = '#'; download.classList.add('is-disabled'); download.setAttribute('aria-disabled', 'true'); } const map = $('map-button'); if (map) { map.classList.add('is-disabled'); map.setAttribute('aria-disabled', 'true'); } if (window.TsiinoConverterIntegration && typeof window.TsiinoConverterIntegration.close === 'function') window.TsiinoConverterIntegration.close(); setStatus('Selecione uma planilha e clique em Validar planilha.', 'info'); }
  function init() { document.documentElement.style.overflowY = 'auto'; document.body.style.overflowY = 'auto'; const form = $('herb-validator-form'); if (form) form.addEventListener('submit', handleSubmit, true); const file = $('spreadsheet-file'); if (file) file.addEventListener('change', resetOnFileChange); }
  window.TsiinoStableValidatorFlow = { previewFile, convertFile, uploadForValidation, renderJob, apiBase: API_BASE, get lastJobId() { return lastJobId; } };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
