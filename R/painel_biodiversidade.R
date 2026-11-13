# =============================================================================
# painel_biodiversidade.R
# Funções reaproveitáveis para sintetizar catálogos Darwin Core (DwC) de plantas e
# fungos em painéis HTML leves (Quarto/R Markdown).
#
# Uso mínimo em outro projeto:
#   source("R/painel_biodiversidade.R")
#   cat <- carregar_catalogo_dwc(list(
#     list(arquivos = "dados/minhas_coletas.xlsx", rotulo = "Expedições"),
#     list(arquivos = "dados/gbif.xlsx",           rotulo = "Coleções existentes / GBIF")
#   ), fonte_projeto = "Expedições")
#   catalog_all_dwc <- cat$todos; catalog_species_dwc <- cat$especies
#   exportar_catalogo_json(catalog_species_dwc, "assets/data/meu_painel")
#   render_dashboard("Painel geral", "Texto...", data_dir = "../assets/data/meu_painel")
#
# Dependências: dplyr, tidyr, stringr, readxl, lubridate, htmltools, jsonlite.
# Sem htmlwidgets/plotly: os gráficos são SVG estático (não exigem JavaScript).
# Componente da lista no navegador: assets/js/catalogo-especies.js
# Estilos: assets/css/painel-biodiversidade.css
# =============================================================================

suppressPackageStartupMessages({
  library(dplyr)
  library(tidyr)
  library(stringr)
  library(readxl)
  library(lubridate)
  library(jsonlite)
  library(htmltools)
  library(scales)
})

# Rótulos padrão das fontes (troque em outro projeto antes de chamar as funções).
PROJECT_SOURCE <- "Expedições Tsiino Hiiwiida"
valid_groups <- c("Fanerógamas", "Criptógamas", "Fungos")

nz <- function(x) !is.na(x) & nzchar(trimws(as.character(x)))

clean_text <- function(x) {
  x <- as.character(x)
  x[is.na(x)] <- NA_character_
  stringr::str_squish(x)
}

format_int <- function(x) {
  if (length(x) == 0) return("—")
  out <- rep("—", length(x))
  x_chr <- as.character(x)
  x_chr[is.na(x_chr)] <- NA_character_
  x_num <- suppressWarnings(as.numeric(gsub("\\.", "", x_chr)))
  ok_num <- !is.na(x_num)
  out[ok_num] <- format(
    x_num[ok_num],
    big.mark = ".",
    decimal.mark = ",",
    scientific = FALSE,
    trim = TRUE
  )
  ok_text <- !ok_num & !is.na(x_chr) & nzchar(trimws(x_chr))
  out[ok_text] <- x_chr[ok_text]
  if (length(out) == 1) out[[1]] else out
}

`%||%` <- function(x, y) if (is.null(x)) y else x

find_up <- function(rel_path, start = getwd(), max_levels = 8) {
  d <- normalizePath(start, winslash = "/", mustWork = FALSE)
  for (i in 0:max_levels) {
    cand <- file.path(d, rel_path)
    if (file.exists(cand)) return(cand)
    parent <- dirname(d)
    if (identical(parent, d)) break
    d <- parent
  }
  NA_character_
}

find_first <- function(paths) {
  paths <- unique(paths[!is.na(paths) & nzchar(paths)])
  found <- vapply(paths, find_up, character(1))
  hit <- found[!is.na(found)]
  if (length(hit) == 0) return(NA_character_)
  hit[1]
}

as_num <- function(x) {
  suppressWarnings(as.numeric(stringr::str_replace(as.character(x), ",", ".")))
}

to_year <- function(x) {
  if (length(x) == 0) return(integer())
  if (is.numeric(x)) {
    y <- suppressWarnings(as.integer(x))
    y[y < 1500 | y > lubridate::year(Sys.Date()) + 2] <- NA_integer_
    return(y)
  }
  x_chr <- stringr::str_squish(as.character(x))
  y1 <- suppressWarnings(as.integer(x_chr))
  y1[y1 < 1500 | y1 > lubridate::year(Sys.Date()) + 2] <- NA_integer_
  needs_parse <- is.na(y1) & nz(x_chr)
  if (any(needs_parse)) {
    parsed <- suppressWarnings(lubridate::parse_date_time(
      x_chr[needs_parse],
      orders = c("ymd", "dmy", "mdy", "Y", "Ym", "Ymd", "dmY", "mdY"),
      quiet = TRUE
    ))
    y1[needs_parse] <- lubridate::year(parsed)
  }
  y1
}

empty_catalog <- function() {
  tibble::tibble(
    source = character(),
    scientificName = character(),
    taxonRank = character(),
    taxon_resolution = character(),
    is_species_level = logical(),
    species_key = character(),
    genus = character(),
    family = character(),
    kingdom = character(),
    phylum = character(),
    class = character(),
    order = character(),
    group = character(),
    year = integer(),
    eventDate = character(),
    record_id = character(),
    gbif_id = character(),
    collector = character(),
    collector_display = character(),
    recordNumber = character(),
    catalogNumber = character(),
    locality = character(),
    institution = character(),
    collection = character(),
    basisOfRecord = character(),
    ffb_taxon_url = character(),
    powo_taxon_url = character(),
    gbif_taxon_url = character(),
    opentree_url = character(),
    pubchem_url = character(),
    ncbi_taxonomy_url = character(),
    ncbi_nucleotide_url = character(),
    ebi_search_url = character(),
    bold_taxon_url = character(),
    mycobank_taxon_url = character(),
    wfo_taxon_url = character(),
    col_url = character(),
    globi_url = character(),
    europepmc_url = character(),
    inaturalist_url = character(),
    index_fungorum_taxon_url = character(),
    latitude = numeric(),
    longitude = numeric(),
    has_coordinates = logical(),
    is_project_source = logical()
  )
}

read_dwc_xlsx <- function(path) {
  sheets <- readxl::excel_sheets(path)
  sheet <- if ("DwC_records" %in% sheets) "DwC_records" else sheets[[1]]
  dat <- readxl::read_xlsx(path, sheet = sheet, col_types = "text", .name_repair = "unique") |>
    tibble::as_tibble(.name_repair = "unique")
  names(dat) <- trimws(gsub("^\ufeff", "", names(dat)))
  dat
}


col_or_na <- function(dat, nm) {
  if (nm %in% names(dat)) dat[[nm]] else rep(NA_character_, nrow(dat))
}

coalesce_nz <- function(...) {
  xs <- list(...)
  xs <- lapply(xs, function(x) {
    x <- as.character(x)
    x[is.na(x) | !nzchar(trimws(x))] <- NA_character_
    stringr::str_squish(x)
  })
  dplyr::coalesce(!!!xs)
}

standardize_dwc_cols <- function(dat) {
  if (nrow(dat) == 0) return(dat)

  col <- function(nm) col_or_na(dat, nm)

  fill_col <- function(target, ...) {
    novo <- coalesce_nz(...)
    if (!target %in% names(dat)) return(novo)

    atual <- as.character(dat[[target]])
    atual[is.na(atual) | !nzchar(trimws(atual))] <- NA_character_
    dplyr::coalesce(stringr::str_squish(atual), novo)
  }

  dat$scientificName <- fill_col(
    "scientificName",
    col("scientificName"),
    col("acceptedScientificName"),
    col("species"),
    col("genus"),
    col("family")
  )

  dat$taxonRank <- fill_col(
    "taxonRank",
    col("taxonRank"),
    col("verbatimTaxonRank")
  )

  dat$species_key <- fill_col(
    "species_key",
    col("species_key"),
    col("species"),
    col("acceptedScientificName"),
    col("scientificName")
  )

  dat$record_id <- fill_col(
    "record_id",
    col("record_id"),
    col("occurrenceID"),
    col("gbifID"),
    col("key"),
    col("catalogNumber")
  )
  dat$gbif_id <- fill_col("gbif_id", col("gbifID"), col("gbif_id"))

  dat$collector <- fill_col("collector", col("collector"), col("recordedBy"))
  dat$collector_display <- fill_col("collector_display", col("collector_display"))
  dat$recordNumber <- fill_col("recordNumber", col("recordNumber"))
  dat$catalogNumber <- fill_col("catalogNumber", col("catalogNumber"))
  dat$eventDate <- fill_col("eventDate", col("eventDate"), col("verbatimEventDate"), col("date"))
  dat$locality <- fill_col("locality", col("locality"), col("verbatimLocality"))
  dat$institution <- fill_col("institution", col("institution"), col("institutionCode"))
  dat$collection <- fill_col("collection", col("collection"), col("collectionCode"))
  dat$basisOfRecord <- fill_col("basisOfRecord", col("basisOfRecord"))
  dat$ffb_taxon_url <- fill_col("ffb_taxon_url", col("ffb_taxon_url"))
  dat$powo_taxon_url <- fill_col("powo_taxon_url", col("powo_taxon_url"))
  dat$gbif_taxon_url <- fill_col("gbif_taxon_url", col("gbif_taxon_url"))
  dat$opentree_url <- fill_col("opentree_url", col("opentree_url"))
  dat$pubchem_url <- fill_col("pubchem_url", col("pubchem_url"))
  dat$ncbi_taxonomy_url <- fill_col("ncbi_taxonomy_url", col("ncbi_taxonomy_url"))
  dat$ncbi_nucleotide_url <- fill_col("ncbi_nucleotide_url", col("ncbi_nucleotide_url"))
  dat$ebi_search_url <- fill_col("ebi_search_url", col("ebi_search_url"))
  dat$bold_taxon_url <- fill_col("bold_taxon_url", col("bold_taxon_url"))
  dat$mycobank_taxon_url <- fill_col("mycobank_taxon_url", col("mycobank_taxon_url"))
  dat$index_fungorum_taxon_url <- fill_col("index_fungorum_taxon_url", col("index_fungorum_taxon_url"))
  dat$wfo_taxon_url <- fill_col("wfo_taxon_url", col("wfo_taxon_url"), col("wfo_url"))
  dat$col_url <- fill_col("col_url", col("col_url"))
  dat$globi_url <- fill_col("globi_url", col("globi_url"))
  dat$europepmc_url <- fill_col("europepmc_url", col("europepmc_url"))
  dat$inaturalist_url <- fill_col("inaturalist_url", col("inaturalist_url"))

  dat$latitude <- fill_col(
    "latitude",
    col("latitude"),
    col("decLat_final"),
    col("decimalLatitude"),
    col("decimalLatitude.new"),
    col("decimalLatitude_plantR")
  )

  dat$longitude <- fill_col(
    "longitude",
    col("longitude"),
    col("decLon_final"),
    col("decimalLongitude"),
    col("decimalLongitude.new"),
    col("decimalLongitude_plantR")
  )

  if (!"genus" %in% names(dat)) dat$genus <- col("genericName")
  if (!"family" %in% names(dat)) dat$family <- col("family")
  if (!"kingdom" %in% names(dat)) dat$kingdom <- col("kingdom")
  if (!"phylum" %in% names(dat)) dat$phylum <- col("phylum")
  if (!"class" %in% names(dat)) dat$class <- col("class")
  if (!"order" %in% names(dat)) dat$order <- col("order")

  rank <- stringr::str_to_upper(clean_text(dat$taxonRank))

  if (!"is_species_level" %in% names(dat) || !any(dat$is_species_level %in% c(TRUE, "TRUE", "true", "1", 1), na.rm = TRUE)) {
    dat$is_species_level <- rank %in% c("SPECIES", "SUBSPECIES", "VARIETY", "FORM")
  }

  if (!"taxon_resolution" %in% names(dat) || !any(nz(dat$taxon_resolution))) {
    dat$taxon_resolution <- dplyr::case_when(
      rank %in% c("SPECIES", "SUBSPECIES", "VARIETY", "FORM") ~ "Até espécie",
      rank == "GENUS" ~ "Até gênero",
      rank == "FAMILY" ~ "Até família",
      TRUE ~ "Indeterminados"
    )
  }

  kingdom <- stringr::str_to_upper(clean_text(col("kingdom")))
  classe <- stringr::str_to_upper(clean_text(col("class")))
  phylum <- stringr::str_to_upper(clean_text(col("phylum")))

  seed_classes <- c(
    "MAGNOLIOPSIDA",
    "LILIOPSIDA",
    "PINOPSIDA",
    "CYCADOPSIDA",
    "GNETOPSIDA",
    "GINKGOOPSIDA"
  )

  cryptogam_phyla <- c(
    "BRYOPHYTA",
    "MARCHANTIOPHYTA",
    "ANTHOCEROTOPHYTA",
    "POLYPODIOPHYTA",
    "LYCOPODIOPHYTA",
    "PTERIDOPHYTA"
  )

  derived_group <- dplyr::case_when(
    kingdom == "FUNGI" ~ "Fungos",
    kingdom == "PLANTAE" & classe %in% seed_classes ~ "Fanerógamas",
    kingdom == "PLANTAE" & phylum %in% cryptogam_phyla ~ "Criptógamas",
    kingdom == "PLANTAE" & !(classe %in% seed_classes) ~ "Criptógamas",
    TRUE ~ NA_character_
  )

  dat$group <- fill_col(
    "group",
    col("group"),
    derived_group
  )

  dat
}

ensure_catalog_cols <- function(dat, source_label = NA_character_) {
  req <- names(empty_catalog())
  for (cc in req) {
    if (!cc %in% names(dat)) dat[[cc]] <- NA
  }

  dat <- dat |>
    mutate(
      source = ifelse(nz(source), clean_text(source), source_label),
      scientificName = clean_text(scientificName),
      taxonRank = clean_text(taxonRank),
      taxon_resolution = clean_text(taxon_resolution),
      species_key = clean_text(species_key),
      genus = clean_text(genus),
      family = clean_text(family),
      kingdom = clean_text(kingdom),
      phylum = clean_text(phylum),
      class = clean_text(class),
      order = clean_text(order),
      group = clean_text(group),
      record_id = clean_text(record_id),
      gbif_id = clean_text(gbif_id),
      eventDate = clean_text(eventDate),
      collector = clean_text(collector),
      collector_display = clean_text(collector_display),
      recordNumber = clean_text(recordNumber),
      catalogNumber = clean_text(catalogNumber),
      locality = clean_text(locality),
      institution = clean_text(institution),
      collection = clean_text(collection),
      basisOfRecord = clean_text(basisOfRecord),
      year = to_year(year),
      latitude = as_num(latitude),
      longitude = as_num(longitude),
      is_species_level = is_species_level %in% c(TRUE, "TRUE", "true", "1", 1),
      has_coordinates = (!is.na(latitude) & !is.na(longitude)) | has_coordinates %in% c(TRUE, "TRUE", "true", "1", 1),
      is_project_source = is_project_source %in% c(TRUE, "TRUE", "true", "1", 1) |
        source == PROJECT_SOURCE,
      taxon_resolution = case_when(
        taxon_resolution %in% c("Até espécie", "Até gênero", "Até família", "Indeterminados") ~ taxon_resolution,
        TRUE ~ "Indeterminados"
      ),
      group = case_when(
        group %in% c("Fanerógamas", "Criptógamas", "Fungos") ~ group,
        TRUE ~ "Indeterminado"
      ),
      species_key = ifelse(is_species_level & nz(species_key), species_key, NA_character_)
    ) |>
    select(any_of(req), everything())

  dat
}

read_validated_dwc_input <- function(paths, label, source_label) {
  path <- find_first(paths)
  if (is.na(path)) {
    return(list(
      data = empty_catalog(),
      path = NA_character_,
      label = label,
      found = FALSE,
      read_ok = FALSE,
      rows = 0L,
      usable_rows = 0L,
      message = paste0(
        "Arquivo validado não encontrado para ", label,
        ". Nomes esperados: ", paste(basename(paths), collapse = ", ")
      )
    ))
  }

  read_error <- NULL

  dat <- tryCatch(
    read_dwc_xlsx(path),
    error = function(e) {
      read_error <<- conditionMessage(e)
      empty_catalog()
    }
  )

  if (!is.null(read_error)) {
    return(list(
      data = empty_catalog(),
      path = normalizePath(path, winslash = "/", mustWork = FALSE),
      label = label,
      found = TRUE,
      read_ok = FALSE,
      rows = 0L,
      usable_rows = 0L,
      message = paste0(
        label, " encontrado em ", normalizePath(path, winslash = "/", mustWork = FALSE),
        ", mas não pôde ser lido. Erro: ", read_error
      )
    ))
  }

  dat <- standardize_dwc_cols(dat)
  dat <- ensure_catalog_cols(dat, source_label = source_label)
  dat$source <- source_label
  dat$is_project_source <- source_label == PROJECT_SOURCE

  usable_rows <- dat |>
    filter(group %in% c("Fanerógamas", "Criptógamas", "Fungos")) |>
    nrow()

  list(
    data = dat,
    path = normalizePath(path, winslash = "/", mustWork = FALSE),
    label = label,
    found = TRUE,
    read_ok = TRUE,
    rows = nrow(dat),
    usable_rows = usable_rows,
    message = paste0(
      label, " lido em ", normalizePath(path, winslash = "/", mustWork = FALSE),
      ". ", format_int(nrow(dat)), " registros lidos; ",
      format_int(usable_rows), " registros classificados para o painel."
    )
  )
}

#' Lê uma ou mais fontes DwC (.xlsx) e devolve o catálogo completo e só espécies.
#' @param fontes lista de list(arquivos = c(caminhos candidatos), rotulo = "Nome da fonte")
#' @param fonte_projeto rótulo da fonte que representa as coletas do próprio projeto
carregar_catalogo_dwc <- function(fontes, fonte_projeto = PROJECT_SOURCE) {
  inputs <- lapply(fontes, function(f) read_validated_dwc_input(f$arquivos, f$rotulo, f$rotulo))
  todos <- dplyr::bind_rows(lapply(inputs, function(x) x$data))
  if (nrow(todos)) todos$is_project_source <- todos$source == fonte_projeto
  especies <- todos |>
    dplyr::filter(group %in% valid_groups, is_species_level, nz(species_key))
  list(todos = todos, especies = especies, inputs = inputs)
}

input_status_panel <- function(inputs) {
  file_card <- function(input) {
    tags$div(
      class = paste("input-file", ifelse(input$found, "input-ok", "input-missing")),
      tags$span(ifelse(input$found, "Encontrado", "Aguardando")),
      tags$strong(input$label),
      tags$p(input$message)
    )
  }

  tags$div(
    class = "input-status-grid reveal",
    `data-reveal` = "",
    lapply(inputs, file_card)
  )
}

taxon_resolution_df <- function(dat) {
  if (nrow(dat) == 0 || !"taxon_resolution" %in% names(dat)) {
    return(tibble::tibble(resolucao = character(), registros = integer()))
  }
  levels <- c("Até espécie", "Até gênero", "Até família", "Indeterminados")
  dat |>
    mutate(
      resolucao = case_when(
        taxon_resolution %in% levels ~ taxon_resolution,
        TRUE ~ "Indeterminados"
      ),
      resolucao = factor(resolucao, levels = levels)
    ) |>
    count(resolucao, name = "registros") |>
    tidyr::complete(resolucao = factor(levels, levels = levels), fill = list(registros = 0L)) |>
    mutate(resolucao = as.character(resolucao)) |>
    filter(registros > 0)
}

calc_stats <- function(group_filter = NULL, catalog = catalog_all_dwc, species = catalog_species_dwc) {
  catalog_all_dwc <- catalog
  catalog_species_dwc <- species
  all_dat <- catalog_all_dwc |>
    filter(group %in% valid_groups)
  species_dat <- catalog_species_dwc
  exp_all <- catalog_all_dwc |>
    filter(group %in% valid_groups, source == PROJECT_SOURCE)
  gbif_all <- catalog_all_dwc |>
    filter(group %in% valid_groups, source != PROJECT_SOURCE)
  exp_species <- catalog_species_dwc |>
    filter(source == PROJECT_SOURCE)
  gbif_species <- catalog_species_dwc |>
    filter(source != PROJECT_SOURCE)

  if (!is.null(group_filter)) {
    all_dat <- all_dat |> filter(group == group_filter)
    species_dat <- species_dat |> filter(group == group_filter)
    exp_all <- exp_all |> filter(group == group_filter)
    gbif_all <- gbif_all |> filter(group == group_filter)
    exp_species <- exp_species |> filter(group == group_filter)
    gbif_species <- gbif_species |> filter(group == group_filter)
  }

  list(
    data = species_dat,
    all_data = all_dat,
    exp_data = exp_species,
    gbif_data = gbif_species,
    exp_all_data = exp_all,
    gbif_all_data = gbif_all,
    group = group_filter %||% "Geral",
    records = nrow(all_dat),
    species = species_dat |> filter(nz(species_key)) |> summarise(n = n_distinct(species_key)) |> pull(n),
    genera = all_dat |> filter(nz(genus)) |> summarise(n = n_distinct(genus)) |> pull(n),
    families = all_dat |> filter(nz(family)) |> summarise(n = n_distinct(family)) |> pull(n),
    exp_records = nrow(exp_all),
    gbif_records = nrow(gbif_all),
    georef_records = all_dat |> filter(has_coordinates) |> nrow(),
    resolution = taxon_resolution_df(all_dat)
  )
}

kpi_card <- function(value, label, note = NULL) {
  raw_value <- suppressWarnings(as.numeric(gsub("\\.", "", as.character(value))))
  final_text <- as.character(value)
  tags$div(
    class = "kpi-card reveal",
    `data-reveal` = "",
    tags$strong(
      class = "kpi-number",
      `data-count-final` = ifelse(is.na(raw_value), "", raw_value),
      `data-final-text` = final_text,
      final_text
    ),
    tags$span(label),
    if (!is.null(note)) tags$p(note)
  )
}

empty_state <- function(text) {
  tags$div(class = "empty-state", text)
}

top_genus_df <- function(dat, n = 8) {
  dat |>
    filter(nz(genus), nz(species_key)) |>
    distinct(genus, species_key) |>
    count(genus, name = "species") |>
    arrange(desc(species), genus) |>
    slice_head(n = n)
}

top_family_df <- function(dat, n = 8) {
  dat |>
    filter(nz(family), nz(species_key)) |>
    distinct(family, species_key) |>
    count(family, name = "species") |>
    arrange(desc(species), family) |>
    slice_head(n = n)
}

rank_list_card <- function(dat, type = c("family", "genus"), n = 7) {
  type <- match.arg(type)
  top <- if (type == "family") top_family_df(dat, n) else top_genus_df(dat, n)
  label_col <- if (type == "family") "family" else "genus"
  title <- if (type == "family") "Famílias com maior riqueza" else "Gêneros com maior riqueza"
  empty_msg <- if (type == "family") "Inclua espécies com família validada para listar famílias mais ricas." else "Inclua espécies com gênero validado para listar gêneros mais ricos."
  body <- if (nrow(top) == 0) {
    empty_state(empty_msg)
  } else {
    tags$ol(
      class = "rank-list",
      lapply(seq_len(nrow(top)), function(i) {
        tags$li(
          tags$span(top[[label_col]][i]),
          tags$b(paste0(format_int(top$species[i]), " spp."))
        )
      })
    )
  }
  tags$div(
    class = "chart-card rank-card reveal",
    `data-reveal` = "",
    tags$h4(title),
    body
  )
}

# ---------------------------------------------------------------------------
# Gráficos em SVG puro (leves, acessíveis, sem JavaScript)
# ---------------------------------------------------------------------------
svg_esc <- function(x) htmltools::htmlEscape(as.character(x), attribute = TRUE)

#' Rosca (donut) em SVG com legenda. `cores` na mesma ordem de `rotulos`.
svg_donut <- function(rotulos, valores, cores, titulo, hole = 0.58) {
  ok <- !is.na(valores) & valores > 0
  rotulos <- rotulos[ok]; valores <- valores[ok]; cores <- cores[ok]
  total <- sum(valores)
  if (!length(valores) || total == 0) return(empty_state("Sem dados para este gráfico."))
  r <- 100; ri <- r * hole; cx <- 120; cy <- 120
  ang <- c(0, cumsum(valores) / total) * 2 * pi - pi / 2
  arc <- function(a0, a1) {
    if (a1 - a0 >= 2 * pi - 1e-6) a1 <- a0 + 2 * pi - 1e-4
    large <- if (a1 - a0 > pi) 1 else 0
    p <- function(rr, a) sprintf("%.2f %.2f", cx + rr * cos(a), cy + rr * sin(a))
    sprintf("M %s A %d %d 0 %d 1 %s L %s A %.2f %.2f 0 %d 0 %s Z",
            p(r, a0), r, r, large, p(r, a1), p(ri, a1), ri, ri, large, p(ri, a0))
  }
  pct <- function(v) paste0(format(round(100 * v / total, 1), decimal.mark = ",", nsmall = 1), "%")
  fatias <- vapply(seq_along(valores), function(i) sprintf(
    '<path d="%s" fill="%s" style="--i:%d"><title>%s: %s registros (%s)</title></path>',
    arc(ang[i], ang[i + 1]), cores[i], i, svg_esc(rotulos[i]), format_int(valores[i]), pct(valores[i])), "")
  legenda <- vapply(seq_along(valores), function(i) sprintf(
    '<li><i style="background:%s"></i><span>%s</span><b>%s · %s</b></li>',
    cores[i], svg_esc(rotulos[i]), format_int(valores[i]), pct(valores[i])), "")
  htmltools::HTML(sprintf(paste0(
    '<figure class="svg-chart svg-donut"><figcaption>%s</figcaption>',
    '<svg viewBox="0 0 240 240" role="img" aria-label="%s">%s',
    '<text x="120" y="118" class="svg-donut-total">%s</text><text x="120" y="140" class="svg-donut-sub">registros</text></svg>',
    '<ul class="svg-legend">%s</ul></figure>'),
    svg_esc(titulo), svg_esc(titulo), paste(fatias, collapse = ""), format_int(total), paste(legenda, collapse = "")))
}

#' Série anual em SVG (área + faixas com dica por ano).
svg_serie_anual <- function(anos, valores, titulo, cor = "#A93632") {
  if (!length(anos)) return(empty_state("Inclua eventDate ou year para visualizar o histórico de coletas."))
  W <- 640; H <- 260; ml <- 44; mr <- 14; mt <- 14; mb <- 34
  x0 <- min(anos); x1 <- max(anos); if (x0 == x1) { x0 <- x0 - 1; x1 <- x1 + 1 }
  ymax <- max(valores, 1)
  sx <- function(x) ml + (x - x0) / (x1 - x0) * (W - ml - mr)
  sy <- function(y) H - mb - y / ymax * (H - mt - mb)
  pts <- paste(sprintf("%.1f,%.1f", sx(anos), sy(valores)), collapse = " ")
  area <- sprintf("M %.1f,%.1f L %s L %.1f,%.1f Z", sx(anos[1]), sy(0), pts, sx(anos[length(anos)]), sy(0))
  bw <- max((W - ml - mr) / max(length(anos), 1), 2)
  hits <- vapply(seq_along(anos), function(i) sprintf(
    '<rect x="%.1f" y="%d" width="%.1f" height="%d" class="svg-hit"><title>%d: %s registros</title></rect>',
    sx(anos[i]) - bw / 2, mt, bw, H - mt - mb, anos[i], format_int(valores[i])), "")
  passos <- c(5, 10, 20, 25, 50, 100)
  passo <- passos[which.max(passos >= (x1 - x0) / 7)]
  ticks <- seq(ceiling(x0 / passo) * passo, x1, by = passo)
  xt <- vapply(ticks, function(t) sprintf('<text x="%.1f" y="%d" class="svg-axis">%d</text>', sx(t), H - 10, as.integer(t)), "")
  htmltools::HTML(sprintf(paste0(
    '<figure class="svg-chart svg-serie"><figcaption>%s</figcaption>',
    '<svg viewBox="0 0 %d %d" role="img" aria-label="%s" preserveAspectRatio="xMidYMid meet">',
    '<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" class="svg-baseline"/>',
    '<path d="%s" class="svg-area" fill="%s"/><polyline points="%s" class="svg-line" stroke="%s"/>',
    '%s<text x="%d" y="%d" class="svg-axis svg-axis-y">%s</text>%s</svg>',
    '<p class="svg-note">Pico: %s registros em um ano · série %d–%d</p></figure>'),
    svg_esc(titulo), W, H, svg_esc(titulo), ml, W - mr, sy(0), sy(0), area, cor, pts, cor,
    paste(xt, collapse = ""), ml - 6, mt + 10, format_int(ymax), paste(hits, collapse = ""),
    format_int(ymax), as.integer(min(anos)), as.integer(max(anos))))
}

plot_source_balance <- function(stats) {
  svg_donut(c("Expedições", "Coleções/GBIF"), c(stats$exp_records, stats$gbif_records),
            c("#A93632", "#626A38"), "Registros por fonte")
}

plot_taxon_resolution <- function(stats) {
  dat <- stats$resolution
  if (is.null(dat) || nrow(dat) == 0) return(empty_state("Inclua nomes científicos, gêneros, famílias ou taxonRank para visualizar o nível de identificação dos registros."))
  palette <- c("Até espécie" = "#A93632", "Até gênero" = "#D99A27", "Até família" = "#626A38", "Indeterminados" = "#2E3B24")
  svg_donut(dat$resolucao, dat$registros, unname(palette[dat$resolucao]), "Nível de identificação dos registros")
}

plot_group_balance <- function(dat) {
  gd <- dat |> filter(group %in% valid_groups) |> count(group, name = "registros") |> arrange(match(group, valid_groups))
  palette <- c("Fanerógamas" = "#626A38", "Criptógamas" = "#D99A27", "Fungos" = "#A93632")
  svg_donut(gd$group, gd$registros, unname(palette[gd$group]), "Registros por grupo biológico")
}

plot_years <- function(dat) {
  yy <- dat |> filter(!is.na(year)) |> count(year = as.integer(year), name = "records") |> arrange(year)
  if (nrow(yy) == 0) return(empty_state("Inclua eventDate ou year para visualizar o histórico de coletas."))
  yy <- tidyr::complete(yy, year = seq(min(year), max(year)), fill = list(records = 0L))
  svg_serie_anual(yy$year, yy$records, "Registros ao longo do tempo")
}

collect_taxon_links <- function(x) {
  urls <- as.character(x[nz(x) & grepl("^https?://", x)])
  unique(urls)
}

occurrence_record_url <- function(rec) {
  candidates <- c(rec$gbif_id, rec$record_id)
  candidates <- candidates[!is.na(candidates) & nzchar(trimws(candidates))]
  if (length(candidates) == 0) return(NA_character_)

  for (candidate in candidates) {
    candidate <- trimws(as.character(candidate))
    if (grepl("^https?://", candidate, ignore.case = TRUE)) return(candidate)
    if (grepl("gbif", rec$source, ignore.case = TRUE) && grepl("^[0-9]+$", candidate)) {
      return(paste0("https://www.gbif.org/occurrence/", candidate))
    }
  }
  NA_character_
}

occurrence_gbif_lookup_id <- function(rec) {
  if (!grepl("gbif", rec$source, ignore.case = TRUE)) return(NA_character_)
  candidates <- c(rec$gbif_id, rec$record_id)
  candidates <- candidates[!is.na(candidates) & nzchar(trimws(candidates))]
  if (length(candidates) == 0) return(NA_character_)
  for (candidate in candidates) {
    candidate <- trimws(as.character(candidate))
    if (grepl("^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$", candidate)) {
      return(candidate)
    }
  }
  NA_character_
}

occurrence_label <- function(rec) {
  if (nz(rec$collector)) {
    paste0(rec$collector, " · nº ", if (nz(rec$recordNumber)) rec$recordNumber else "não informado")
  } else if (nz(rec$collector_display)) {
    rec$collector_display
  } else {
    paste0("Coletor não informado · nº ", if (nz(rec$recordNumber)) rec$recordNumber else "não informado")
  }
}

occurrence_date_label <- function(rec) {
  if (nz(rec$eventDate)) return(rec$eventDate)
  if (!is.na(rec$year)) return(as.character(rec$year))
  "Data não informada"
}

occurrence_locality_label <- function(rec) {
  if (nz(rec$locality)) return(rec$locality)
  if (!is.na(rec$latitude) && !is.na(rec$longitude)) {
    return(paste0("Coordenadas: ", format(rec$latitude, digits = 6), ", ", format(rec$longitude, digits = 6)))
  }
  "Localidade não informada"
}

render_occurrence_record <- function(rec) {
  url <- occurrence_record_url(rec)
  gbif_lookup_id <- occurrence_gbif_lookup_id(rec)
  label <- occurrence_label(rec)
  primary_link <- if (!is.na(url)) {
    tags$a(class = "occurrence-record-primary", label, href = url, target = "_blank", rel = "noopener noreferrer")
  } else if (!is.na(gbif_lookup_id)) {
    tags$a(
      class = "occurrence-record-primary gbif-occurrence-lookup",
      label,
      href = paste0("https://www.gbif.org/occurrence/search?OCCURRENCE_ID=", utils::URLencode(gbif_lookup_id, reserved = TRUE)),
      `data-occurrence-id` = gbif_lookup_id,
      target = "_blank",
      rel = "noopener noreferrer"
    )
  } else {
    tags$strong(class = "occurrence-record-primary", label)
  }
  tags$li(
    primary_link,
    tags$div(class = "occurrence-record-meta", paste0("Data: ", occurrence_date_label(rec))),
    if (nz(rec$institution) || nz(rec$collection) || nz(rec$catalogNumber) || nz(rec$basisOfRecord)) tags$div(
      class = "occurrence-record-meta",
      paste(c(
        if (nz(rec$institution)) paste0("Instituição: ", rec$institution),
        if (nz(rec$collection)) paste0("Coleção: ", rec$collection),
        if (nz(rec$catalogNumber)) paste0("Catálogo: ", rec$catalogNumber),
        if (nz(rec$basisOfRecord)) paste0("Tipo: ", rec$basisOfRecord)
      ), collapse = " · ")
    ),
    tags$div(class = "occurrence-record-locality", occurrence_locality_label(rec)),
    tags$small(rec$source)
  )
}

taxon_link_sources <- list(
  list(label = "Flora e Funga do Brasil", column = "ffb_taxon_url", group = "Taxonomia e ocorrência"),
  list(label = "Plants of the World Online (POWO)", column = "powo_taxon_url", group = "Taxonomia e ocorrência"),
  list(label = "GBIF", column = "gbif_taxon_url", group = "Taxonomia e ocorrência"),
  list(label = "World Flora Online (WFO)", column = "wfo_taxon_url", group = "Taxonomia e ocorrência"),
  list(label = "Catalogue of Life", column = "col_url", group = "Taxonomia e ocorrência"),
  list(label = "Open Tree of Life", column = "opentree_url", group = "Taxonomia e ocorrência"),
  list(label = "iNaturalist", column = "inaturalist_url", group = "Taxonomia e ocorrência"),
  list(label = "NCBI Taxonomy", column = "ncbi_taxonomy_url", group = "Sequências, literatura e interações"),
  list(label = "NCBI Nucleotide", column = "ncbi_nucleotide_url", group = "Sequências, literatura e interações"),
  list(label = "EMBL-EBI", column = "ebi_search_url", group = "Sequências, literatura e interações"),
  list(label = "BOLD Systems", column = "bold_taxon_url", group = "Sequências, literatura e interações"),
  list(label = "PubChem", column = "pubchem_url", group = "Sequências, literatura e interações"),
  list(label = "Europe PMC", column = "europepmc_url", group = "Sequências, literatura e interações"),
  list(label = "Global Biotic Interactions (GloBI)", column = "globi_url", group = "Sequências, literatura e interações"),
  list(label = "Index Fungorum", column = "index_fungorum_taxon_url", group = "Taxonomia de fungos"),
  list(label = "MycoBank", column = "mycobank_taxon_url", group = "Taxonomia de fungos")
)

species_list_df <- function(dat) {
  species <- dat |>
    filter(nz(species_key)) |>
    mutate(
      family = ifelse(nz(family), family, "Família não informada"),
      species_key = stringr::str_to_sentence(species_key)
    ) |>
    group_by(family, species_key) |>
    summarise(
      records = n(),
      ffb_taxon_url = list(collect_taxon_links(ffb_taxon_url)),
      powo_taxon_url = list(collect_taxon_links(powo_taxon_url)),
      gbif_taxon_url = list(collect_taxon_links(gbif_taxon_url)),
      opentree_url = list(collect_taxon_links(opentree_url)),
      pubchem_url = list(collect_taxon_links(pubchem_url)),
      ncbi_taxonomy_url = list(collect_taxon_links(ncbi_taxonomy_url)),
      ncbi_nucleotide_url = list(collect_taxon_links(ncbi_nucleotide_url)),
      ebi_search_url = list(collect_taxon_links(ebi_search_url)),
      bold_taxon_url = list(collect_taxon_links(bold_taxon_url)),
      mycobank_taxon_url = list(collect_taxon_links(mycobank_taxon_url)),
      wfo_taxon_url = list(collect_taxon_links(wfo_taxon_url)),
      col_url = list(collect_taxon_links(col_url)),
      globi_url = list(collect_taxon_links(globi_url)),
      europepmc_url = list(collect_taxon_links(europepmc_url)),
      inaturalist_url = list(collect_taxon_links(inaturalist_url)),
      index_fungorum_taxon_url = list(collect_taxon_links(index_fungorum_taxon_url)),
      occurrences = list(tibble::tibble(
        collector = collector, collector_display = collector_display,
        recordNumber = recordNumber, record_id = record_id, gbif_id = gbif_id,
        eventDate = eventDate, year = year, locality = locality, latitude = latitude, longitude = longitude,
        institution = institution, collection = collection, catalogNumber = catalogNumber,
        basisOfRecord = basisOfRecord, source = source
      )),
      .groups = "drop"
    ) |>
    arrange(family, species_key)

  species$external_links <- lapply(seq_len(nrow(species)), function(i) {
    links <- list()
    for (source in taxon_link_sources) {
      urls <- species[[source$column]][[i]]
      if (length(urls) == 0) next
      for (j in seq_along(urls)) {
        label <- if (length(urls) > 1) paste0(source$label, " · ", j) else source$label
        links[[length(links) + 1]] <- list(
          label = label,
          url = urls[[j]],
          group = source$group
        )
      }
    }
    links
  })
  species$external_link_count <- lengths(species$external_links)
  species
}

render_taxon_link <- function(link) {
  tags$a(
    class = "species-source-link",
    href = link$url,
    target = "_blank",
    rel = "noopener noreferrer",
    `aria-label` = paste("Abrir", link$label),
    tags$span(link$label),
    tags$span(class = "species-source-arrow", "↗", `aria-hidden` = "true")
  )
}

render_taxon_link_group <- function(group_name, links) {
  group_links <- Filter(function(link) identical(link$group, group_name), links)
  if (length(group_links) == 0) return(NULL)
  tags$div(
    class = "taxon-link-group",
    tags$h6(group_name),
    tags$div(class = "taxon-link-list", lapply(group_links, render_taxon_link))
  )
}

# ---------------------------------------------------------------------------
# Lista de espécies: exportada como JSON e montada no navegador sob demanda
# (antes: ~18 MB de HTML e ~4 min de render só para fanerógamas).
# ---------------------------------------------------------------------------

#' Exporta o catálogo de espécies em dois arquivos JSON compactos:
#'  - especies.json  (índice leve, carregado ao abrir a lista)
#'  - detalhes.json  (links e registros; carregado ao expandir a 1ª espécie)
exportar_catalogo_json <- function(species_dat, out_dir) {
  dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
  sp <- species_list_df(species_dat)
  extras <- species_dat |>
    mutate(species_key = stringr::str_to_sentence(species_key),
           family = ifelse(nz(family), family, "Família não informada")) |>
    group_by(family, species_key) |>
    summarise(group = dplyr::first(group),
              exp = sum(source == PROJECT_SOURCE), ext = sum(source != PROJECT_SOURCE),
              y0 = suppressWarnings(min(year, na.rm = TRUE)), y1 = suppressWarnings(max(year, na.rm = TRUE)),
              .groups = "drop")
  sp <- dplyr::left_join(sp, extras, by = c("family", "species_key"))
  int_or_na <- function(x) ifelse(is.finite(x), as.integer(x), NA_integer_)
  link_keys <- vapply(taxon_link_sources, function(x) x$column, "")

  indice <- list(
    versao = 1L,
    gerado_em = format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z"),
    fonte_projeto = PROJECT_SOURCE,
    colunas = c("familia", "especie", "grupo", "registros", "reg_projeto", "reg_externos", "ano_min", "ano_max", "n_links"),
    linhas = lapply(seq_len(nrow(sp)), function(i) list(
      sp$family[i], sp$species_key[i], sp$group[i], sp$records[i], sp$exp[i], sp$ext[i],
      int_or_na(sp$y0[i]), int_or_na(sp$y1[i]), sp$external_link_count[i]))
  )
  detalhes <- list(
    versao = 1L,
    fontes_links = lapply(taxon_link_sources, function(x) list(chave = x$column, rotulo = x$label, grupo = x$group)),
    colunas_registro = c("rotulo", "url", "gbif_occurrence_id", "data", "meta", "localidade", "fonte"),
    especies = lapply(seq_len(nrow(sp)), function(i) {
      links <- list()
      for (k in link_keys) { u <- sp[[k]][[i]]; if (length(u)) links[[k]] <- unname(u) }
      occ <- sp$occurrences[[i]]
      regs <- lapply(seq_len(nrow(occ)), function(j) {
        rec <- occ[j, ]
        meta <- paste(c(
          if (nz(rec$institution)) paste0("Instituição: ", rec$institution),
          if (nz(rec$collection)) paste0("Coleção: ", rec$collection),
          if (nz(rec$catalogNumber)) paste0("Catálogo: ", rec$catalogNumber),
          if (nz(rec$basisOfRecord)) paste0("Tipo: ", rec$basisOfRecord)), collapse = " · ")
        list(occurrence_label(rec), occurrence_record_url(rec), occurrence_gbif_lookup_id(rec),
             occurrence_date_label(rec), if (nzchar(meta)) meta else NA_character_,
             occurrence_locality_label(rec), rec$source)
      })
      list(l = links, r = regs)
    })
  )
  jsonlite::write_json(indice, file.path(out_dir, "especies.json"), auto_unbox = TRUE, na = "null", digits = NA)
  jsonlite::write_json(detalhes, file.path(out_dir, "detalhes.json"), auto_unbox = TRUE, na = "null", digits = NA)
  invisible(list(especies = nrow(sp), dir = out_dir))
}

#' Gaveta da lista de espécies: só o "esqueleto"; o conteúdo vem do JSON ao abrir.
species_drawer <- function(stats, data_dir) {
  n <- stats$data |>
    filter(nz(species_key)) |>
    mutate(k = paste(ifelse(nz(family), family, "Família não informada"), stringr::str_to_sentence(species_key))) |>
    summarise(n = n_distinct(k)) |>
    pull(n)
  if (!n) {
    return(tags$div(class = "species-drawer-empty reveal", `data-reveal` = "", "Inclua nomes científicos em nível de espécie no input tratado para gerar a lista completa deste grupo."))
  }
  tags$details(
    class = "species-drawer reveal",
    `data-reveal` = "",
    `data-catalogo-especies` = "",
    `data-indice` = file.path(data_dir, "especies.json"),
    `data-detalhes` = file.path(data_dir, "detalhes.json"),
    `data-grupo` = stats$group,
    tags$summary(
      tags$span(class = "species-summary-label", "Ver lista completa de espécies"),
      tags$span(class = "species-summary-count", paste0(format_int(n), " espécies"))
    ),
    tags$div(class = "species-drawer-panel", tags$p(class = "species-search-status", role = "status", "Carregando a lista..."))
  )
}

render_dashboard <- function(title, subtitle, group_filter = NULL, compact = FALSE, data_dir = NULL) {
  stats <- calc_stats(group_filter)
  dat <- stats$data
  all_dat <- stats$all_data
  kpis <- tags$div(
    class = "kpi-grid",
    kpi_card(format_int(stats$species), "espécies", "Apenas nomes completos identificados em nível de espécie."),
    kpi_card(format_int(stats$genera), "gêneros", "Gêneros distintos considerando registros até espécie ou até gênero."),
    kpi_card(format_int(stats$families), "famílias", "Famílias distintas considerando registros até espécie, gênero ou família."),
    kpi_card(format_int(stats$records), "registros", "Todas as ocorrências do grupo, incluindo espécie, gênero, família e indeterminados."),
    kpi_card(format_int(stats$exp_records), "registros das expedições", paste0(
      if (stats$records > 0) format(round(100 * stats$exp_records / stats$records, 1), decimal.mark = ",", trim = TRUE) else "0",
      "% dos registros deste painel foram coletados nas expedições Tsiino Hiiwiida."
    )),
    kpi_card(format_int(stats$georef_records), "georreferenciados", "Todos os registros do grupo com latitude e longitude disponíveis.")
  )

  family_card <- rank_list_card(dat, "family", 7)
  genus_card <- rank_list_card(dat, "genus", 7)

  if (is.null(group_filter)) {
    visual_cards <- list(
      tags$div(class = "chart-card reveal", `data-reveal` = "", plot_source_balance(stats)),
      tags$div(class = "chart-card reveal", `data-reveal` = "", plot_taxon_resolution(stats)),
      tags$div(class = "chart-card reveal", `data-reveal` = "", plot_years(all_dat)),
      tags$div(class = "chart-card reveal", `data-reveal` = "", plot_group_balance(all_dat)),
      family_card,
      genus_card
    )
  } else {
    visual_cards <- list(
      tags$div(class = "chart-card reveal", `data-reveal` = "", plot_source_balance(stats)),
      tags$div(class = "chart-card reveal", `data-reveal` = "", plot_years(all_dat)),
      family_card,
      genus_card
    )
  }

  tagList(
    tags$section(
      class = paste("dashboard-block", if (compact) "dashboard-compact" else ""),
      tags$div(
        class = "dashboard-heading reveal",
        `data-reveal` = "",
        tags$span(class = "eyebrow", ifelse(is.null(group_filter), "Painel integrado", group_filter)),
        tags$h3(title),
        tags$p(subtitle)
      ),
      kpis,
      do.call(tags$div, c(list(class = "dashboard-visual-grid"), visual_cards)),
      if (!is.null(group_filter) && !is.null(data_dir)) species_drawer(stats, data_dir)
    )
  )
}
