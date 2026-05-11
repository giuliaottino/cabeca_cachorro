#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Patch cirúrgico para index.qmd · Tsiino Hiiwiida.

Uso recomendado:
  python patch_index_tsiino.py index_original.qmd index_ajustado.qmd

Segurança:
  - não sobrescreve o arquivo de entrada;
  - substitui apenas as seções/blocos solicitados no prompt;
  - aborta se o resultado ficar com menos de 90% das linhas do original.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


EXP_COLLAGE_HTML = r'''```{=html}
<section id="expedicoes-recentes" class="exp-collage-section" aria-label="Expedições recentes">
  <div class="exp-collage-grid">
    <div class="exp-collage-item exp-main">
      <img src="figures/exp_1.jpg" alt="Expedição 1"
           onerror="this.src='figures/exp_1.jpeg'; this.onerror=function(){this.src='figures/exp_1.png'; this.onerror=null;};"
           loading="lazy">
    </div>
    <div class="exp-collage-item">
      <img src="figures/exp_2.jpg" alt="Expedição 2"
           onerror="this.src='figures/exp_2.jpeg'; this.onerror=function(){this.src='figures/exp_2.png'; this.onerror=null;};"
           loading="lazy">
    </div>
    <div class="exp-collage-item">
      <img src="figures/exp_3.jpg" alt="Expedição 3"
           onerror="this.src='figures/exp_3.jpeg'; this.onerror=function(){this.src='figures/exp_3.png'; this.onerror=null;};"
           loading="lazy">
    </div>
    <div class="exp-collage-item exp-tall">
      <img src="figures/exp_4.jpg" alt="Expedição 4"
           onerror="this.src='figures/exp_4.jpeg'; this.onerror=function(){this.src='figures/exp_4.png'; this.onerror=null;};"
           loading="lazy">
    </div>
    <div class="exp-collage-item">
      <img src="figures/exp_5.jpg" alt="Expedição 5"
           onerror="this.src='figures/exp_5.jpeg'; this.onerror=function(){this.src='figures/exp_5.png'; this.onerror=null;};"
           loading="lazy">
    </div>
    <div class="exp-collage-item exp-wide">
      <img src="figures/exp_6.jpg" alt="Expedição 6"
           onerror="this.src='figures/exp_6.jpeg'; this.onerror=function(){this.src='figures/exp_6.png'; this.onerror=null;};"
           loading="lazy">
    </div>
    <div class="exp-collage-item">
      <img src="figures/exp_7.jpg" alt="Expedição 7"
           onerror="this.src='figures/exp_7.jpeg'; this.onerror=function(){this.src='figures/exp_7.png'; this.onerror=null;};"
           loading="lazy">
    </div>
    <div class="exp-collage-item">
      <img src="figures/exp_8.jpg" alt="Expedição 8"
           onerror="this.src='figures/exp_8.jpeg'; this.onerror=function(){this.src='figures/exp_8.png'; this.onerror=null;};"
           loading="lazy">
    </div>
  </div>

  <div class="exp-collage-overlay">
    <div class="exp-collage-cta">
      <h2 class="exp-collage-heading">Expedições recentes</h2>
      <a class="btn-main" href="expedicoes.html">Mapa e fotos das expedições</a>
    </div>
  </div>
</section>
```

```{=html}
<style>
/* Desktop largo (≥ 1400px): objetivos e expedições maiores */
@media (min-width: 1400px) {
  .objectives-section {
    width: min(1560px, calc(100vw - 2rem)) !important;
    max-width: calc(100vw - 2rem) !important;
  }

  #expedicoes-recentes {
    width: min(1480px, calc(100vw - 2rem)) !important;
    max-width: calc(100vw - 2rem) !important;
  }

  .objective-slide {
    grid-template-columns: 1fr minmax(420px, 0.72fr) !important;
    min-height: clamp(480px, 42vw, 640px) !important;
    padding: clamp(2rem, 3.5vw, 3.2rem) clamp(1.5rem, 3vw, 3rem) 5rem !important;
  }

  .objective-text h2 {
    font-size: clamp(2.4rem, 3.8vw, 4.2rem) !important;
  }

  .objective-image {
    width: min(480px, 90%) !important;
  }

  .expedition-preview-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
    gap: 1.5rem !important;
  }

  .expedition-preview-card {
    padding: 1.4rem !important;
    min-height: 200px !important;
  }
}

/* ── Colagem de expedições full-bleed ── */
#expedicoes-recentes.exp-collage-section {
  position: relative;
  left: 50%;
  transform: translateX(-50%);
  width: 100vw !important;
  max-width: 100vw !important;
  margin-top: 2.5rem;
  padding: 0 !important;
  overflow: hidden;
  background: var(--green-dark);
  height: clamp(480px, 56vw, 780px);
  border-top: none !important;
  box-shadow: none !important;
}

.exp-collage-grid {
  display: grid;
  width: 100%;
  height: 100%;
  grid-template-columns: repeat(4, 1fr);
  grid-template-rows: repeat(2, 1fr);
  gap: 3px;
}

.exp-collage-item {
  overflow: hidden;
  background: var(--green-dark);
}

.exp-collage-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
  display: block;
  transition: transform 400ms ease;
}

.exp-collage-item:hover img {
  transform: scale(1.04);
}

.exp-collage-item.exp-main {
  grid-column: 1 / 3;
  grid-row: 1 / 3;
}

.exp-collage-item.exp-wide {
  grid-column: 3 / 5;
  grid-row: 2 / 3;
}

.exp-collage-item.exp-tall {
  grid-row: 1 / 3;
}

.exp-collage-overlay {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(180deg,
      rgba(0,0,0,0.08) 0%,
      rgba(0,0,0,0.18) 40%,
      rgba(0,0,0,0.62) 100%
    );
  display: flex;
  align-items: flex-end;
  justify-content: center;
  padding-bottom: clamp(1.5rem, 4vw, 3rem);
  pointer-events: none;
}

.exp-collage-cta {
  pointer-events: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
  text-align: center;
}

.exp-collage-heading {
  margin: 0;
  color: #fff;
  font-family: 'Montserrat', Arial, sans-serif;
  font-size: clamp(1.35rem, 2.8vw, 2.2rem);
  font-weight: 900;
  letter-spacing: -0.03em;
  text-shadow: 0 2px 16px rgba(0,0,0,0.72);
}

.exp-collage-cta .btn-main {
  box-shadow: 0 8px 24px rgba(0,0,0,0.38);
  font-size: 0.78rem;
}

@media (max-width: 900px) {
  #expedicoes-recentes.exp-collage-section {
    height: clamp(360px, 72vw, 560px);
  }

  .exp-collage-grid {
    grid-template-columns: repeat(2, 1fr);
    grid-template-rows: repeat(4, 1fr);
  }

  .exp-collage-item.exp-main {
    grid-column: 1 / 3;
    grid-row: 1 / 2;
  }

  .exp-collage-item.exp-wide {
    grid-column: 1 / 3;
    grid-row: auto;
  }

  .exp-collage-item.exp-tall {
    grid-row: auto;
  }
}

@media (max-width: 560px) {
  #expedicoes-recentes.exp-collage-section {
    height: clamp(320px, 96vw, 480px);
  }

  .exp-collage-grid {
    grid-template-columns: 1fr 1fr;
    grid-template-rows: repeat(4, 1fr);
  }

  .exp-collage-item.exp-main {
    grid-column: 1 / 3;
  }

  .exp-collage-item.exp-wide,
  .exp-collage-item.exp-tall {
    grid-column: auto;
    grid-row: auto;
  }
}

#expedicoes-recentes.exp-collage-section.reveal-ready {
  transform: translateX(-50%) translateY(44px) !important;
}

#expedicoes-recentes.exp-collage-section.reveal-ready.is-visible {
  transform: translateX(-50%) translateY(0) !important;
}
</style>
```
'''

CAROUSEL_CSS = r'''<style>
/* ── Divulgação: carrossel full-bleed ── */
#divulgacao.content-card {
  width: min(100vw, 100%) !important;
  max-width: 100% !important;
  padding-left: 0 !important;
  padding-right: 0 !important;
  border-top: none !important;
  overflow: hidden !important;
}

#divulgacao .section-title,
#divulgacao .lead {
  padding-left: clamp(1.2rem, 4vw, 3.5rem);
  padding-right: clamp(1.2rem, 4vw, 3.5rem);
  max-width: 100%;
}

.divulg-carousel-wrapper {
  position: relative;
  width: 100%;
  overflow: hidden;
  padding-bottom: 2.5rem;
}

.divulg-track-container {
  overflow: hidden;
  width: 100%;
}

.divulg-track {
  display: flex;
  gap: 0;
  transition: transform 400ms cubic-bezier(0.4, 0, 0.2, 1);
  will-change: transform;
}

.carousel-slide {
  flex: 0 0 33.333%;
  min-width: 0;
  position: relative;
  cursor: pointer;
  overflow: hidden;
  background: #1a2210;
}

.carousel-thumb {
  width: 100%;
  aspect-ratio: 16/9;
  overflow: hidden;
  background:
    linear-gradient(135deg, rgba(46,59,36,0.92), rgba(98,106,56,0.76)),
    url("figures/tsiino_bg.png");
  background-size: cover;
}

.carousel-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
  display: block;
  transition: transform 320ms ease;
}

.carousel-slide:hover .carousel-thumb img {
  transform: scale(1.04);
}

.carousel-play-icon {
  display: none;
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -60%);
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: rgba(255,255,255,0.88);
  color: var(--green-dark);
  font-size: 1.5rem;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  box-shadow: 0 8px 24px rgba(0,0,0,0.28);
}

.carousel-slide.is-video .carousel-play-icon {
  display: flex;
}

.carousel-body {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: clamp(0.85rem, 1.5vw, 1.25rem);
  background: linear-gradient(0deg, rgba(0,0,0,0.82) 0%, rgba(0,0,0,0.42) 60%, transparent 100%);
  color: #fff;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.carousel-type-pill {
  display: inline-flex;
  align-self: flex-start;
  padding: 0.22rem 0.58rem;
  border-radius: 999px;
  font-family: 'Space Mono', monospace;
  font-size: 0.62rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  background: var(--red);
  color: #fff;
}

.carousel-type-pill.is-reportagem {
  background: var(--green);
}

.carousel-title {
  margin: 0;
  font-size: clamp(0.9rem, 1.15vw, 1.1rem);
  font-weight: 800;
  line-height: 1.2;
  color: #fff;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.carousel-link {
  font-family: 'Space Mono', monospace;
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ochre) !important;
  text-decoration: none !important;
  align-self: flex-start;
}

.divulg-arrow {
  position: absolute;
  top: calc(50% - 2.5rem);
  transform: translateY(-50%);
  z-index: 10;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  border: 2px solid rgba(255,255,255,0.60);
  background: rgba(46,59,36,0.72);
  color: #fff;
  font-size: 1.4rem;
  font-weight: 700;
  display: grid;
  place-items: center;
  cursor: pointer;
  backdrop-filter: blur(6px);
  transition: background 180ms ease, transform 180ms ease;
}

.divulg-prev { left: 0.65rem; }
.divulg-next { right: 0.65rem; }

.divulg-arrow:hover {
  background: rgba(169,54,50,0.82);
  transform: translateY(-50%) scale(1.06);
}

.divulg-dots {
  position: absolute;
  bottom: 0.6rem;
  left: 0;
  right: 0;
  display: flex;
  justify-content: center;
  gap: 0.4rem;
}

.divulg-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  border: none;
  background: rgba(255,255,255,0.38);
  cursor: pointer;
  transition: background 200ms ease, transform 200ms ease;
}

.divulg-dot.active {
  background: var(--red);
  transform: scale(1.25);
}

@media (max-width: 900px) {
  .carousel-slide { flex: 0 0 50%; }
}

@media (max-width: 560px) {
  .carousel-slide { flex: 0 0 100%; }
  .divulg-arrow { width: 38px; height: 38px; font-size: 1.1rem; }
}
</style>'''

CAROUSEL_R = r'''```{r divulgacao-dinamica}
library(htmltools)

`%or_blank%` <- function(x, y = "") {
  if (is.null(x) || length(x) == 0 || is.na(x[1]) || !nzchar(as.character(x[1]))) y else as.character(x[1])
}

make_carousel_data <- function(path, type) {
  data <- read_optional_csv(path)
  if (nrow(data) == 0) {
    return(data.frame(
      type = character(),
      title = character(),
      url = character(),
      image = character(),
      description = character(),
      date = character(),
      source = character(),
      stringsAsFactors = FALSE
    ))
  }

  title <- col_or(data, c("titulo", "título", "title", "post"), "")
  url <- col_or(data, c("url", "link", "href"), "#")
  image <- col_or(data, c("imagem", "image", "thumb", "thumbnail", "capa"), "")
  description <- col_or(data, c("descricao", "descrição", "resumo", "caption", "texto"), "")
  date <- col_or(data, c("data", "date", "ano"), "")
  source <- col_or(data, c("veiculo", "veículo", "fonte", "source"), "")

  out <- data.frame(
    type = rep(type, nrow(data)),
    title = as.character(title),
    url = as.character(url),
    image = as.character(image),
    description = as.character(description),
    date = as.character(date),
    source = as.character(source),
    stringsAsFactors = FALSE
  )

  if (exists("fetch_link_preview", mode = "function")) {
    for (i in seq_len(nrow(out))) {
      if (!nz(out$url[i]) || identical(out$url[i], "#")) next
      preview <- tryCatch(fetch_link_preview(out$url[i]), error = function(e) NULL)
      if (is.null(preview)) next

      if (!nz(out$title[i])) {
        out$title[i] <- preview$title %or_blank% out$title[i]
      }
      if (!nz(out$description[i])) {
        out$description[i] <- preview$description %or_blank% out$description[i]
      }
      if (!nz(out$image[i])) {
        out$image[i] <- preview$image %or_blank% out$image[i]
      }
      if (!nz(out$source[i])) {
        out$source[i] <- preview$site_name %or_blank% out$source[i]
      }
    }
  }

  out$title[!nz(out$title)] <- ifelse(type == "instagram", "Post no Instagram", ifelse(type == "youtube", "Vídeo no YouTube", "Reportagem"))
  out
}

make_carousel_items <- function() {
  items <- rbind(
    make_carousel_data(file.path("_input_data", "divulgacao_instagram.csv"), "instagram"),
    make_carousel_data(file.path("_input_data", "divulgacao_reportagens.csv"), "reportagem"),
    make_carousel_data(file.path("_input_data", "divulgacao_youtube.csv"), "youtube")
  )

  if (nrow(items) == 0) {
    return(tags$div(
      class = "empty-media",
      "Nenhum item encontrado em _input_data/divulgacao_instagram.csv, _input_data/divulgacao_reportagens.csv ou _input_data/divulgacao_youtube.csv. Ao adicionar linhas nesses CSVs e renderizar o site novamente, os slides aparecerão automaticamente aqui."
    ))
  }

  parsed_dates <- suppressWarnings(as.Date(items$date, tryFormats = c("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%m/%d/%Y")))
  items <- items[order(is.na(parsed_dates), parsed_dates, decreasing = TRUE), , drop = FALSE]

  tagList(lapply(seq_len(nrow(items)), function(i) {
    type_label <- switch(items$type[i],
      instagram = "Instagram",
      reportagem = "Reportagem",
      youtube = "YouTube",
      "Divulgação"
    )

    link_label <- switch(items$type[i],
      instagram = "Ver no Instagram →",
      reportagem = "Ler reportagem →",
      youtube = "Assistir no YouTube →",
      "Abrir link →"
    )

    pill_class <- paste("carousel-type-pill", ifelse(items$type[i] == "reportagem", "is-reportagem", ""))
    article_class <- paste("carousel-slide", ifelse(items$type[i] == "youtube", "is-video", ""))

    thumb <- if (nz(items$image[i])) {
      tags$div(class = "carousel-thumb", tags$img(src = items$image[i], alt = items$title[i], loading = "lazy"))
    } else {
      tags$div(class = "carousel-thumb", role = "img", `aria-label` = items$title[i])
    }

    tags$article(
      class = article_class,
      onclick = sprintf("window.open('%s', '_blank', 'noopener')", htmlEscape(items$url[i], attribute = TRUE)),
      thumb,
      tags$div(class = "carousel-play-icon", "▶"),
      tags$div(
        class = "carousel-body",
        tags$span(class = pill_class, type_label),
        tags$p(class = "carousel-title", items$title[i]),
        tags$a(class = "carousel-link", href = items$url[i], target = "_blank", rel = "noopener", link_label)
      )
    )
  }))
}

make_carousel_items()
```'''

CAROUSEL_CLOSE_AND_JS = r'''```{=html}
    </div>
  </div>
  <button class="divulg-arrow divulg-next" type="button" aria-label="Próximo item">›</button>
  <div class="divulg-dots" id="divulg-dots" aria-label="Navegação do carrossel"></div>
</div>
</section>

<script>
(function() {
  document.addEventListener("DOMContentLoaded", function () {
    const track = document.getElementById("divulg-track");
    const dotsContainer = document.getElementById("divulg-dots");
    if (!track || !dotsContainer) return;

    const slides = Array.from(track.querySelectorAll(".carousel-slide"));
    const slidesPerView = () => window.innerWidth <= 560 ? 1 : window.innerWidth <= 900 ? 2 : 3;
    let current = 0;

    const totalGroups = () => Math.max(1, Math.ceil(slides.length / slidesPerView()));

    function buildDots() {
      dotsContainer.innerHTML = "";
      for (let i = 0; i < totalGroups(); i++) {
        const btn = document.createElement("button");
        btn.className = "divulg-dot" + (i === 0 ? " active" : "");
        btn.setAttribute("type", "button");
        btn.setAttribute("aria-label", "Grupo " + (i + 1));
        btn.addEventListener("click", () => goTo(i));
        dotsContainer.appendChild(btn);
      }
    }

    function updateDots() {
      Array.from(dotsContainer.querySelectorAll(".divulg-dot")).forEach((d, i) => {
        d.classList.toggle("active", i === current);
      });
    }

    function goTo(index) {
      const total = totalGroups();
      current = (index + total) % total;
      const offset = current * slidesPerView();
      const slideWidth = slides[0] ? slides[0].offsetWidth : 0;
      track.style.transform = `translateX(-${offset * slideWidth}px)`;
      updateDots();
    }

    document.querySelector(".divulg-prev")?.addEventListener("click", () => goTo(current - 1));
    document.querySelector(".divulg-next")?.addEventListener("click", () => goTo(current + 1));

    window.addEventListener("resize", () => { buildDots(); goTo(0); });
    buildDots();
    goTo(0);
  });
})();
</script>
```'''

LOGOS_CHUNK = r'''```{r instituicoes-projeto, results='asis'}
library(htmltools)

institutions <- read_institutions_yml()

if (nrow(institutions) == 0) {
  tags$section(
    id = "logos-institucionais",
    class = "logos-strip",
    tags$div(
      class = "logos-group",
      tags$h3(class = "logos-group-title", "Instituições"),
      tags$div(class = "empty-media", "Nenhuma instituição encontrada no YAML de instituições.")
    )
  )
} else {
  institutions <- institutions[order(
    institutions$group,
    suppressWarnings(as.numeric(institutions$order)),
    institutions$name
  ), , drop = FALSE]

  fomento_data <- institutions[institutions$group == "fomento", , drop = FALSE]
  participante_data <- institutions[institutions$group == "participante", , drop = FALSE]
  cnpq_row <- institutions[institutions$id == "cnpq", , drop = FALSE]

  if (nrow(cnpq_row) > 0 && !"cnpq" %in% fomento_data$id) {
    fomento_display <- rbind(fomento_data, cnpq_row)
  } else {
    fomento_display <- fomento_data
  }

  parceira_data <- institutions[institutions$group == "parceira" & institutions$id != "cnpq", , drop = FALSE]

  make_logo_items <- function(data) {
    if (nrow(data) == 0) return(tags$span(class = "logo-fallback", "Sem instituições cadastradas"))

    tagList(lapply(seq_len(nrow(data)), function(i) {
      acronym <- data$acronym[i]
      if (!nz(acronym)) acronym <- data$name[i]
      url <- data$url[i]
      if (!nz(url) || grepl("não localizado", url, ignore.case = TRUE)) url <- "#"

      tags$a(
        href = url,
        target = ifelse(url == "#", "_self", "_blank"),
        rel = ifelse(url == "#", NULL, "noopener"),
        class = "logo-item",
        `aria-label` = acronym,
        tags$img(
          src = data$logo[i],
          alt = paste("Logo", acronym),
          loading = "lazy",
          onerror = "this.style.display='none'; this.parentElement.classList.add('logo-missing');"
        ),
        tags$span(class = "logo-fallback", acronym)
      )
    }))
  }

  tagList(
    tags$style(HTML('
/* ── Faixa de logos institucionais ── */
#logos-institucionais.logos-strip {
  position: relative;
  left: 50%;
  transform: translateX(-50%);
  width: 100vw;
  background: #fff;
  padding: clamp(2rem, 4vw, 3.5rem) clamp(1.2rem, 4vw, 4rem);
  margin-top: 0;
  border-top: 1px solid rgba(98,106,56,0.14);
  border-bottom: 1px solid rgba(98,106,56,0.14);
  box-sizing: border-box;
}

.logos-group {
  margin-bottom: clamp(1.5rem, 3vw, 2.5rem);
}

.logos-group:last-child {
  margin-bottom: 0;
}

.logos-group-title {
  font-family: "Space Mono", monospace;
  font-size: clamp(0.68rem, 0.9vw, 0.82rem);
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 0 0 1rem 0;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid rgba(98,106,56,0.18);
}

.logos-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: clamp(0.75rem, 2vw, 1.5rem);
}

.logo-item {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0.5rem;
  border-radius: 8px;
  text-decoration: none !important;
  transition: transform 220ms ease;
}

.logo-item img {
  display: block;
  height: clamp(32px, 4vw, 52px);
  width: auto;
  max-width: 140px;
  object-fit: contain;
  filter: grayscale(100%) opacity(0.62);
  transition: filter 240ms ease, transform 240ms ease;
}

.logo-item:hover img {
  filter: grayscale(0%) opacity(1);
  transform: scale(1.10);
}

.logo-fallback {
  display: none;
  font-family: "Space Mono", monospace;
  font-size: 0.7rem;
  font-weight: 800;
  color: var(--muted);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.logo-item.logo-missing .logo-fallback {
  display: block;
}

.logo-item.logo-missing img {
  display: none;
}

@media (max-width: 640px) {
  .logos-row { gap: 0.75rem; }
  .logo-item img {
    height: clamp(26px, 8vw, 38px);
    max-width: 110px;
  }
}
')),
    tags$section(
      id = "logos-institucionais",
      class = "logos-strip",
      `aria-label` = "Logos institucionais",
      tags$div(
        class = "logos-group",
        tags$h3(class = "logos-group-title", "Financiadores"),
        tags$div(class = "logos-row", make_logo_items(fomento_display))
      ),
      tags$div(
        class = "logos-group",
        tags$h3(class = "logos-group-title", "Instituições Participantes"),
        tags$div(class = "logos-row", make_logo_items(participante_data))
      ),
      tags$div(
        class = "logos-group",
        tags$h3(class = "logos-group-title", "Instituições Parceiras"),
        tags$div(class = "logos-row", make_logo_items(parceira_data))
      )
    )
  )
}
```'''


def replace_exactly_one(text: str, pattern: str, repl: str, label: str) -> tuple[str, int]:
    new, count = re.subn(pattern, repl, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"Não encontrei exatamente 1 bloco para substituir: {label} (encontrados: {count}).")
    return new, count


def patch_divulgacao(text: str) -> tuple[str, int]:
    pattern = (
        r'```\{=html\}\s*'
        r'(?P<section_start><section id="divulgacao" class="content-card">.*?</p>\s*)'
        r'```\s*'
        r'```\{r divulgacao-dinamica[^}]*\}.*?```\s*'
        r'```\{=html\}\s*</section>\s*```'
    )

    def repl(m: re.Match) -> str:
        start = m.group('section_start')
        return (
            '```{=html}\n' + CAROUSEL_CSS + '\n' + start +
            '<div class="divulg-carousel-wrapper" aria-label="Carrossel de divulgação">\n'
            '  <button class="divulg-arrow divulg-prev" type="button" aria-label="Item anterior">‹</button>\n'
            '  <div class="divulg-track-container">\n'
            '    <div class="divulg-track" id="divulg-track">\n'
            '```\n\n' + CAROUSEL_R + '\n\n' + CAROUSEL_CLOSE_AND_JS
        )

    new, count = re.subn(pattern, repl, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError("Não encontrei exatamente 1 seção #divulgacao no formato esperado.")
    return new, count


def patch_file(input_path: Path, output_path: Path) -> None:
    original = input_path.read_text(encoding='utf-8')
    original_lines = original.count('\n') + 1
    text = original

    text, n_exp = replace_exactly_one(
        text,
        r'```\{=html\}\s*<section id="expedicoes-recentes" class="content-card">.*?```\s*```\{r expedicoes-recentes[^}]*\}.*?```\s*```\{=html\}\s*</section>\s*```',
        EXP_COLLAGE_HTML,
        '#expedicoes-recentes + chunk expedicoes-recentes'
    )

    text, n_div = patch_divulgacao(text)

    text, n_inst = replace_exactly_one(
        text,
        r'```\{r instituicoes-projeto[^}]*\}.*?```',
        LOGOS_CHUNK,
        'chunk instituicoes-projeto'
    )

    # Ajuste mínimo no sistema reveal, sem reescrever o bloco inteiro.
    text = text.replace('    "#expedicoes-recentes .lead",\n', '    "#expedicoes-recentes.exp-collage-section",\n    ".exp-collage-cta",\n')
    text = text.replace('    "#divulgacao .lead",\n    ".media-panel",\n', '    "#divulgacao .lead",\n    "#divulgacao .divulg-carousel-wrapper",\n    ".carousel-slide",\n')

    new_lines = text.count('\n') + 1
    if new_lines < int(original_lines * 0.90):
      raise RuntimeError(
          f"ABORTADO: saída teria {new_lines} linhas, menos de 90% do original ({original_lines}). "
          "Isso sugere substituição ampla demais; nada foi salvo."
      )

    required = [
        'make_carousel_items',
        'id="logos-institucionais"',
        'class="exp-collage-section"',
        'divulg-carousel-wrapper',
    ]
    missing = [token for token in required if token not in text]
    if missing:
        raise RuntimeError('ABORTADO: faltaram marcadores esperados no resultado: ' + ', '.join(missing))

    output_path.write_text(text, encoding='utf-8', newline='\n')
    print(f"OK: {input_path} -> {output_path}")
    print(f"Linhas: original={original_lines}; ajustado={new_lines}; diferença={new_lines - original_lines}")
    print(f"Substituições: expedicoes={n_exp}; divulgacao={n_div}; instituicoes={n_inst}")


if __name__ == '__main__':
    if len(sys.argv) not in (2, 3):
        print('Uso: python patch_index_tsiino.py index_original.qmd [index_ajustado.qmd]', file=sys.stderr)
        sys.exit(2)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) == 3 else input_path.with_name(input_path.stem + '_ajustado.qmd')

    if not input_path.exists():
        print(f'Arquivo não encontrado: {input_path}', file=sys.stderr)
        sys.exit(2)

    if input_path.resolve() == output_path.resolve():
        print('Por segurança, escolha um arquivo de saída diferente do original.', file=sys.stderr)
        sys.exit(2)

    try:
        patch_file(input_path, output_path)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
