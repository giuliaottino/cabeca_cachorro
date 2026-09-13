// TSIINO_STANDARD_FIRST_FLOW_V36
(function () {
  if (window.TsiinoStandardFirstFlowV36) return;
  window.TsiinoStandardFirstFlowV36 = { ready: true };

  const LOCAL_API = 'http://127.0.0.1:8000/api/validator';
  const PROD_API = 'https://api.tsiinohiiwiida.net/api/validator';
  const host = window.location.hostname;
  const API_BASE = (!host || host === '127.0.0.1' || host === 'localhost') ? LOCAL_API : PROD_API;

  function $(id) { return document.getElementById(id); }
  function selectedFile() {
    const input = $('spreadsheet-file') || document.querySelector('input[type="file"]');
    return input && input.files ? input.files[0] : null;
  }
  function setStatus(message, kind) {
    const el = $('validator-status') || document.querySelector('.hv-status');
    if (!el) return;
    el.hidden = false;
    el.textContent = message;
    el.className = 'hv-status ' + (kind || 'info');
  }
  function formValue(id) {
    const el = $(id);
    return el ? (el.value || '').trim() : '';
  }
  function checked(id, fallback) {
    const el = $(id);
    return el ? !!el.checked : fallback;
  }
  function buildFormData(file) {
    const fd = new FormData();
    fd.append('file', file, file.name || 'planilha.xlsx');
    const sheetName = formValue('sheet-name') || formValue('sheet_name');
    if (sheetName) fd.append('sheet_name', sheetName);
    const collection = formValue('collection') || formValue('collection-code') || 'INPA';
    if (collection) fd.append('collection', collection);
    fd.append('validate_taxonomy', checked('validate-taxonomy', true) ? 'true' : 'false');
    fd.append('validate_geography', checked('validate-geography', true) ? 'true' : 'false');
    return fd;
  }
  async function postJson(url, fd) {
    const resp = await fetch(url, { method: 'POST', body: fd });
    const text = await resp.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (_) { data = { detail: text }; }
    if (!resp.ok) {
      const msg = (data && (data.detail || data.error || data.message)) || text || ('HTTP ' + resp.status);
      const err = new Error(String(msg));
      err.status = resp.status;
      err.data = data;
      throw err;
    }
    return data || {};
  }
  function hideMapper() {
    const selectors = [
      '#inpa-mapper-panel', '#mapper-panel', '#converter-panel', '#column-mapper',
      '.tsiino-mapper-panel', '.tsiino-converter-panel', '.hv-mapper-panel',
      '[data-tsiino-mapper]', '[data-mapper-panel]'
    ];
    selectors.forEach((sel) => document.querySelectorAll(sel).forEach((node) => {
      if (!node) return;
      node.hidden = true;
      node.style.display = 'none';
      node.setAttribute('aria-hidden', 'true');
    }));
  }
  function moveDownloadButton() {
    const btn = $('download-button') || document.querySelector('[data-download-annotated]') || document.querySelector('.hv-download-annotated');
    if (!btn) return;
    const filters = document.querySelector('.hv-filters') || document.querySelector('.hv-filter-row') || document.querySelector('.hv-results-filters');
    if (filters && !filters.contains(btn)) {
      btn.classList.add('hv-filter', 'hv-download-inline');
      filters.appendChild(btn);
    }
  }
async function renderJob(job) {
  const jobId =
    job &&
    (
      job.job_id ||
      job.id ||
      job.jobId ||
      (job.job && (job.job.job_id || job.job.id))
    );

  if (!jobId) {
    throw new Error('A API validou, mas não retornou job_id.');
  }

  console.log('[Tsiino] Renderizando job:', jobId);

  hideMapper();

  if (
    !window.TsiinoValidatorBridge ||
    typeof window.TsiinoValidatorBridge.applyJob !== 'function'
  ) {
    throw new Error(
      'TsiinoValidatorBridge.applyJob não está disponível.'
    );
  }

  await window.TsiinoValidatorBridge.applyJob(jobId);

  hideMapper();
  moveDownloadButton();

  const results =
    $('validator-results') ||
    document.querySelector('#resultado-da-validacao') ||
    document.querySelector('.hv-results');

  if (results) {
    results.hidden = false;
    results.removeAttribute('hidden');

    if (typeof results.scrollIntoView === 'function') {
      results.scrollIntoView({
        behavior: 'smooth',
        block: 'start'
      });
    }
  }
}
async function openMapper(file) {
  const mapper =
    window.TsiinoConverterIntegration ||
    window.TsiinoConverter;

  const open = mapper && (
    mapper.open ||
    mapper.showFromFile ||
    mapper.openAfterValidationFailure ||
    mapper.openMapper
  );

  if (typeof open !== 'function') {
    throw new Error('O mapeador de colunas não carregou.');
  }

  await open.call(mapper, file);
}

async function handleSubmit(event) {
  const form = event.target;

  if (!form || form.id !== 'herb-validator-form') {
    return;
  }

  event.preventDefault();
  event.stopPropagation();

  if (typeof event.stopImmediatePropagation === 'function') {
    event.stopImmediatePropagation();
  }

  const file = selectedFile();

  if (!file) {
    setStatus('Selecione uma planilha .xlsx ou .xlsm.', 'error');
    return false;
  }

  const collection =
    formValue('collection') ||
    formValue('collection-code') ||
    'INPA';

  const submit =
    form.querySelector('[type="submit"]') ||
    $('validate-button');

  if (submit) {
    submit.disabled = true;
    submit.dataset.oldText = submit.textContent || '';
    submit.textContent = 'Processando...';
  }

  try {
    if (collection === 'CUSTOM') {
      setStatus(
        'Leia as colunas da planilha e confirme o mapeamento para o padrão INPA/BRAHMS.',
        'info'
      );

      await openMapper(file);
      return false;
    }

    setStatus(
      'Verificando estrutura da planilha...',
      'info'
    );

    const standard = await postJson(
      API_BASE + '/converter/standard_check',
      buildFormData(file)
    );

    if (!standard || !standard.detected_standard) {
      setStatus(
        'Planilha fora do padrão INPA/BRAHMS. Confira o mapeamento das colunas.',
        'warning'
      );

      await openMapper(file);
      return false;
    }

    setStatus(
      'Planilha padrão INPA/BRAHMS reconhecida. Validando...',
      'info'
    );

    const job = await postJson(
      API_BASE + '/upload',
      buildFormData(file)
    );

    await renderJob(job);

    setStatus(
      'Validação concluída. Corrija as células destacadas ou baixe a cópia .xlsx anotada.',
      'ok'
    );

  } catch (error) {
    console.error(
      '[Tsiino] Falha no fluxo do validador:',
      error
    );

    setStatus(
      'Não foi possível processar a planilha: ' +
        (error.message || String(error)),
      'error'
    );

  } finally {
    if (submit) {
      submit.disabled = false;

      if (submit.dataset.oldText) {
        submit.textContent = submit.dataset.oldText;
      }
    }
  }

  return false;
}

  document.addEventListener('submit', handleSubmit, true);
  document.addEventListener('DOMContentLoaded', moveDownloadButton);
  window.addEventListener('load', moveDownloadButton);
  const obs = new MutationObserver(() => {
    const status = $('validator-status');
    if (status && /Validação concluída/i.test(status.textContent || '')) hideMapper();
    moveDownloadButton();
  });
  obs.observe(document.documentElement, { childList: true, subtree: true });
})();
