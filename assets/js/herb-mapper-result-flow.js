
// TSIINO_MAPPER_RESULT_FLOW_V34
(function () {
  const MARK = 'TSIINO_MAPPER_RESULT_FLOW_V34';
  function text(el) { return (el && el.textContent || '').replace(/\s+/g, ' ').trim(); }
  function isVisible(el) {
    if (!el || el.hidden || el.getAttribute('aria-hidden') === 'true') return false;
    const st = window.getComputedStyle(el);
    return st.display !== 'none' && st.visibility !== 'hidden' && el.getClientRects().length > 0;
  }
  function resultIsReady() {
    const status = document.getElementById('validator-status');
    if (status && /Validação concluída|Planilha processada|Resultado recebido/i.test(text(status))) return true;
    const heads = Array.from(document.querySelectorAll('h1,h2,h3,.anchorjs-link'));
    if (heads.some(h => /RESULTADO DA VALIDAÇÃO|Resultado da validação/i.test(text(h.closest('h1,h2,h3') || h)))) return true;
    const results = document.getElementById('validator-results') || document.querySelector('.hv-results, .validator-results');
    return !!(results && isVisible(results) && /Planilha anotada|Resultado da validação|ocorrências/i.test(text(results)));
  }
  function mapperRoots() {
    const roots = new Set();
    document.querySelectorAll('[id*="mapper" i], [class*="mapper" i], [id*="mape" i], [class*="mape" i]').forEach(el => {
      const root = el.closest('section, article, .hv-card, .card, .container, main > div, div') || el;
      if (/Mapear colunas|padrão INPA|SUA PLANILHA/i.test(text(root))) roots.add(root);
    });
    document.querySelectorAll('h1,h2,h3').forEach(h => {
      if (/Mapear colunas para o padrão INPA/i.test(text(h))) {
        const root = h.closest('section, article, .hv-card, .card, .container, main > div, div') || h.parentElement;
        if (root) roots.add(root);
      }
    });
    return Array.from(roots).filter(r => /Mapear colunas|SUA PLANILHA|Aplicar mapeamento/i.test(text(r)));
  }
  function hideMapperAfterValidation() {
    if (!resultIsReady()) return;
    mapperRoots().forEach(root => {
      root.hidden = true;
      root.setAttribute('aria-hidden', 'true');
      root.style.display = 'none';
      root.dataset.tsiinoMapperHiddenAfterValidation = '1';
    });
  }
  function moveDownloadButton() {
    const btn = document.getElementById('download-button') || Array.from(document.querySelectorAll('button,a')).find(b => /Baixar planilha anotada/i.test(text(b)));
    if (!btn) return;
    const filters = Array.from(document.querySelectorAll('button,.hv-filter')).filter(b => /Todos|Só erros|Só alertas|Sem problemas/i.test(text(b)));
    const sem = filters.find(b => /Sem problemas/i.test(text(b)));
    if (sem && btn.parentElement !== sem.parentElement) {
      btn.classList.add('hv-download-inline-v34');
      sem.insertAdjacentElement('afterend', btn);
    }
  }
  function tick() {
    hideMapperAfterValidation();
    moveDownloadButton();
  }
  document.addEventListener('click', function (ev) {
    const t = ev.target && ev.target.closest && ev.target.closest('button,a');
    if (t && /Aplicar mapeamento e validar|Validar planilha/i.test(text(t))) {
      for (let i = 1; i <= 12; i++) setTimeout(tick, i * 500);
    }
  }, true);
  document.addEventListener('DOMContentLoaded', () => { tick(); setTimeout(tick, 800); });
  window.addEventListener('load', () => { tick(); setTimeout(tick, 1200); });
  new MutationObserver(() => tick()).observe(document.documentElement, {childList: true, subtree: true, attributes: true});
  window.TsiinoMapperResultFlowV34 = { ready: true, hideMapperAfterValidation, moveDownloadButton, marker: MARK };
})();
