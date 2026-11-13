/* catalogo-especies.js — lista de espécies sob demanda, reaproveitável em outros painéis.
 *
 * Marcação esperada (gerada por species_drawer() em R/painel_biodiversidade.R):
 *   <details class="species-drawer" data-catalogo-especies
 *            data-indice="../assets/data/acesso/especies.json"
 *            data-detalhes="../assets/data/acesso/detalhes.json"
 *            data-grupo="Fungos">            <!-- "Geral" ou vazio = todos os grupos -->
 *     <summary>...</summary><div class="species-drawer-panel"></div>
 *   </details>
 *
 * - especies.json só é baixado quando a gaveta é aberta (e uma única vez para todas as gavetas);
 * - detalhes.json (links e registros) só ao expandir a primeira espécie;
 * - renderiza em lotes (paginação) para manter a página leve mesmo com milhares de espécies.
 */
(function () {
  'use strict';
  const LOTE = 60;
  const cache = new Map();
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = new Intl.NumberFormat('pt-BR');
  const norm = (v) => String(v || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

  function carregar(url) {
    if (!cache.has(url)) {
      cache.set(url, fetch(url, { cache: 'force-cache' }).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      }).catch((err) => { cache.delete(url); throw err; }));
    }
    return cache.get(url);
  }

  function linhasDoIndice(indice) {
    const cols = indice.colunas;
    return indice.linhas.map((row, id) => {
      const o = { id };
      cols.forEach((c, k) => { o[c] = row[k]; });
      o.busca = norm(o.especie + ' ' + o.familia);
      return o;
    });
  }

  function cartao(sp) {
    const regs = sp.registros === 1 ? '1 registro' : `${fmt.format(sp.registros)} registros`;
    const links = sp.n_links === 1 ? '1 link' : `${fmt.format(sp.n_links)} links`;
    const anos = sp.ano_min ? (sp.ano_min === sp.ano_max ? ` · ${sp.ano_min}` : ` · ${sp.ano_min}–${sp.ano_max}`) : '';
    const projeto = sp.reg_projeto ? `<span class="catalogo-badge" title="Registrada nas expedições do projeto">expedições</span>` : '';
    return `<article class="species-list-card" data-id="${sp.id}">
      <div class="species-family-line"><span>${esc(sp.familia)}</span>${projeto}</div>
      <div class="species-taxon-line">
        <span class="species-name"><em>${esc(sp.especie)}</em></span>
        <button type="button" class="species-card-expand" aria-expanded="false" aria-label="Expandir links e registros para ${esc(sp.especie)}">
          <span class="species-expand-symbol" aria-hidden="true">+</span>
          <span class="species-expand-count">${links} · ${regs}</span>
        </button>
      </div>
      <div class="species-card-meta"><small>${regs}${anos}</small></div>
      <div class="species-expanded-content" hidden></div>
    </article>`;
  }

  function detalheHtml(det, info) {
    const grupos = new Map();
    det.fontes_links.forEach((f) => {
      [].concat(info.l[f.chave] || []).forEach((url, j, arr) => {
        if (!grupos.has(f.grupo)) grupos.set(f.grupo, []);
        const rotulo = arr.length > 1 ? `${f.rotulo} · ${j + 1}` : f.rotulo;
        grupos.get(f.grupo).push(`<a class="species-source-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer" aria-label="Abrir ${esc(rotulo)}"><span>${esc(rotulo)}</span><span class="species-source-arrow" aria-hidden="true">↗</span></a>`);
      });
    });
    const links = grupos.size ? `<div class="species-links-panel">${[...grupos].map(([g, items]) =>
      `<div class="taxon-link-group"><h6>${esc(g)}</h6><div class="taxon-link-list">${items.join('')}</div></div>`).join('')}</div>` : '';
    const regs = info.r.map(([rotulo, url, gbifId, data, meta, local, fonte]) => {
      const href = url || (gbifId ? `https://www.gbif.org/occurrence/search?OCCURRENCE_ID=${encodeURIComponent(gbifId)}` : '');
      const titulo = href
        ? `<a class="occurrence-record-primary${!url && gbifId ? ' gbif-occurrence-lookup' : ''}" href="${esc(href)}" target="_blank" rel="noopener noreferrer"${!url && gbifId ? ` data-occurrence-id="${esc(gbifId)}"` : ''}>${esc(rotulo)}</a>`
        : `<strong class="occurrence-record-primary">${esc(rotulo)}</strong>`;
      return `<li>${titulo}<div class="occurrence-record-meta">Data: ${esc(data)}</div>${meta ? `<div class="occurrence-record-meta">${esc(meta)}</div>` : ''}<div class="occurrence-record-locality">${esc(local)}</div><small>${esc(fonte)}</small></li>`;
    }).join('');
    return links + `<section class="species-occurrences-panel"><h6>Registros de ocorrência · ${fmt.format(info.r.length)}</h6>
      <details class="species-occurrence-details"><summary>Mostrar registros</summary><ul>${regs}</ul></details></section>` +
      (!links && !info.r.length ? '<p class="taxon-links-empty">Nenhum link ou registro disponível para esta espécie.</p>' : '');
  }

  function montar(drawer) {
    const painel = drawer.querySelector('.species-drawer-panel');
    const grupo = drawer.dataset.grupo || '';
    const titulo = grupo && grupo !== 'Geral' ? grupo : 'completa';
    painel.innerHTML = '<p class="species-search-status" role="status">Carregando a lista...</p>';

    carregar(drawer.dataset.indice).then((indice) => {
      const todas = linhasDoIndice(indice).filter((s) => !grupo || grupo === 'Geral' || s.grupo === grupo);
      const st = { q: '', fonte: 'todas', ordem: 'familia', mostradas: LOTE, filtradas: todas };
      painel.innerHTML = `
        <div class="species-drawer-intro">
          <div><span class="eyebrow">Lista ${esc(titulo)}</span><h4>Espécies registradas no painel</h4></div>
          <p>Nomes completos em nível de espécie. Use + para abrir os links para bases taxonômicas e os registros de coleta (data, localidade e acesso ao registro original quando disponível).</p>
        </div>
        <div class="species-search-row catalogo-controles">
          <label class="species-search"><span>Buscar por espécie ou família</span>
            <input type="search" class="species-search-input" placeholder="Ex.: Pouteria ou Sapotaceae" autocomplete="off"></label>
          <label class="species-search catalogo-select"><span>Fonte</span>
            <select data-filtro="fonte"><option value="todas">Todas</option><option value="projeto">Registradas nas expedições</option><option value="so-projeto">Só nas expedições</option><option value="externas">Só em coleções/GBIF</option></select></label>
          <label class="species-search catalogo-select"><span>Ordenar</span>
            <select data-filtro="ordem"><option value="familia">Família e espécie</option><option value="registros">Mais registros</option><option value="recentes">Registro mais recente</option></select></label>
          <p class="species-search-status" role="status" aria-live="polite"></p>
        </div>
        <div class="species-list-grid"></div>
        <div class="catalogo-mais"></div>`;
      const grid = painel.querySelector('.species-list-grid');
      const status = painel.querySelector('.species-search-status');
      const mais = painel.querySelector('.catalogo-mais');

      function aplicar() {
        const q = norm(st.q.trim());
        let lista = todas.filter((s) => (!q || s.busca.includes(q)) && (
          st.fonte === 'todas' ||
          (st.fonte === 'projeto' && s.reg_projeto > 0) ||
          (st.fonte === 'so-projeto' && s.reg_projeto > 0 && s.reg_externos === 0) ||
          (st.fonte === 'externas' && s.reg_projeto === 0)));
        if (st.ordem === 'registros') lista = lista.slice().sort((a, b) => b.registros - a.registros || a.especie.localeCompare(b.especie));
        if (st.ordem === 'recentes') lista = lista.slice().sort((a, b) => (b.ano_max || 0) - (a.ano_max || 0) || a.especie.localeCompare(b.especie));
        st.filtradas = lista;
        desenhar();
      }
      function desenhar() {
        const vis = st.filtradas.slice(0, st.mostradas);
        grid.innerHTML = vis.map(cartao).join('') || '<p class="taxon-links-empty">Nenhuma espécie encontrada.</p>';
        status.textContent = `${fmt.format(st.filtradas.length)} de ${fmt.format(todas.length)} espécies`;
        const resto = st.filtradas.length - vis.length;
        mais.innerHTML = resto > 0 ? `<button type="button" class="catalogo-btn-mais">Mostrar mais ${fmt.format(Math.min(resto, LOTE))} (restam ${fmt.format(resto)})</button>` : '';
      }

      let t;
      painel.querySelector('.species-search-input').addEventListener('input', (e) => {
        clearTimeout(t);
        t = setTimeout(() => { st.q = e.target.value; st.mostradas = LOTE; aplicar(); }, 120);
      });
      painel.querySelectorAll('select[data-filtro]').forEach((sel) => sel.addEventListener('change', () => {
        st[sel.dataset.filtro] = sel.value; st.mostradas = LOTE; aplicar();
      }));
      mais.addEventListener('click', () => { st.mostradas += LOTE; desenhar(); });
      grid.addEventListener('click', (e) => {
        const btn = e.target.closest('.species-card-expand');
        if (btn) expandir(btn, drawer);
      });
      aplicar();
    }).catch((err) => {
      painel.innerHTML = `<p class="species-drawer-empty">Não foi possível carregar a lista de espécies (${esc(err.message)}). Recarregue a página para tentar de novo.</p>`;
    });
  }

  function expandir(btn, drawer) {
    const card = btn.closest('.species-list-card');
    const conteudo = card.querySelector('.species-expanded-content');
    const abrir = btn.getAttribute('aria-expanded') !== 'true';
    drawer.querySelectorAll('.species-card-expand[aria-expanded="true"]').forEach((b) => {
      if (b === btn) return;
      b.setAttribute('aria-expanded', 'false');
      b.querySelector('.species-expand-symbol').textContent = '+';
      const c = b.closest('.species-list-card');
      c.classList.remove('is-expanded');
      c.querySelector('.species-expanded-content').hidden = true;
    });
    btn.setAttribute('aria-expanded', String(abrir));
    btn.querySelector('.species-expand-symbol').textContent = abrir ? '−' : '+';
    card.classList.toggle('is-expanded', abrir);
    conteudo.hidden = !abrir;
    if (!abrir || conteudo.dataset.pronto) return;
    conteudo.innerHTML = '<p class="species-search-status">Carregando links e registros...</p>';
    carregar(drawer.dataset.detalhes).then((det) => {
      conteudo.innerHTML = detalheHtml(det, det.especies[Number(card.dataset.id)]);
      conteudo.dataset.pronto = '1';
    }).catch((err) => {
      conteudo.innerHTML = `<p class="taxon-links-empty">Não foi possível carregar os detalhes (${esc(err.message)}).</p>`;
    });
  }

  // Links GBIF por occurrenceID: resolve a chave do registro antes de abrir.
  document.addEventListener('click', (event) => {
    const link = event.target.closest && event.target.closest('a.gbif-occurrence-lookup[data-occurrence-id]');
    if (!link) return;
    event.preventDefault();
    const destino = window.open('about:blank', '_blank');
    if (!destino) { window.location.assign(link.href); return; }
    destino.opener = null;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    fetch(`https://api.gbif.org/v1/occurrence/search?occurrenceId=${encodeURIComponent(link.dataset.occurrenceId)}&limit=1`, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((res) => { const k = res.results && res.results[0] && res.results[0].key; destino.location.replace(k ? `https://www.gbif.org/occurrence/${k}` : link.href); })
      .catch(() => destino.location.replace(link.href))
      .finally(() => clearTimeout(timer));
  });

  function iniciar() {
    document.querySelectorAll('details[data-catalogo-especies]').forEach((drawer) => {
      drawer.addEventListener('toggle', () => {
        if (drawer.open && !drawer.dataset.montado) { drawer.dataset.montado = '1'; montar(drawer); }
      });
      if (drawer.open && !drawer.dataset.montado) { drawer.dataset.montado = '1'; montar(drawer); }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar);
  else iniciar();
  window.CatalogoEspecies = { iniciar };
})();
