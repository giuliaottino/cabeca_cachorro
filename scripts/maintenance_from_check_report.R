# scripts/maintenance_from_check_report.R
# Organiza os relatórios de _check_reports e move arquivos não usados para quarentena.
# Uso recomendado, a partir da raiz do projeto:
# source("scripts/maintenance_from_check_report.R")
# summarize_check_report()
# quarantine_unused_assets(dry_run = TRUE)   # primeiro só simula
# quarantine_unused_assets(dry_run = FALSE)  # depois move para _quarantine_unused/
# quarantine_source_clutter(dry_run = TRUE)
# quarantine_source_clutter(dry_run = FALSE)

.ensure_pkgs <- function(pkgs) {
  missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]
  if (length(missing) > 0) {
    stop(
      "Instale os pacotes antes de rodar:\n",
      paste0("install.packages(c(", paste(sprintf('"%s"', missing), collapse = ", "), "))"),
      call. = FALSE
    )
  }
}

.ensure_pkgs(c("fs", "readr", "dplyr", "stringr", "purrr", "tibble"))

.read_report <- function(path) {
  if (!fs::file_exists(path)) {
    return(tibble::tibble())
  }
  suppressMessages(readr::read_csv(path, show_col_types = FALSE, progress = FALSE))
}

.norm_slash <- function(x) {
  gsub("\\\\", "/", as.character(x))
}

.source_rel <- function(x, root = getwd()) {
  x <- .norm_slash(x)
  root <- .norm_slash(fs::path_abs(root))
  # Remove a raiz do projeto quando o CSV veio com caminho absoluto.
  stringr::str_remove(x, paste0("^", stringr::str_replace_all(root, "([\\^$.|?*+(){}\\[\\]\\\\])", "\\\\\\1"), "/?"))
}

.is_generated_or_checker <- function(source_rel) {
  stringr::str_detect(source_rel, "(^|/)[^/]+_files/|\\.js$|\\.html$|^scripts/check_site\\.R$")
}

.is_optional_doc <- function(source_rel) {
  stringr::str_detect(source_rel, "^README\\.(md|Rmd)$")
}

report_action_plan <- function(root = getwd(), report_dir = "_check_reports") {
  report_path <- fs::path(root, report_dir)
  
  missing_images <- .read_report(fs::path(report_path, "missing_images.csv"))
  missing_data <- .read_report(fs::path(report_path, "missing_data_files.csv"))
  missing_expected <- .read_report(fs::path(report_path, "missing_expected_files.csv"))
  broken_links <- .read_report(fs::path(report_path, "broken_internal_links.csv"))
  missing_packages <- .read_report(fs::path(report_path, "missing_packages.csv"))
  quarto_status <- .read_report(fs::path(report_path, "quarto_check_status.csv"))
  large_files <- .read_report(fs::path(report_path, "large_files.csv"))
  empty_files <- .read_report(fs::path(report_path, "empty_files.csv"))
  unused_images <- .read_report(fs::path(report_path, "unused_images.csv"))
  
  if (nrow(missing_images) > 0) {
    missing_images <- missing_images |>
      dplyr::mutate(
        source_rel = .source_rel(file, root),
        is_generated = .is_generated_or_checker(source_rel),
        is_optional = .is_optional_doc(source_rel)
      )
  }
  
  if (nrow(missing_data) > 0) {
    missing_data <- missing_data |>
      dplyr::mutate(
        source_rel = .source_rel(file, root),
        is_generated = .is_generated_or_checker(source_rel),
        is_optional = .is_optional_doc(source_rel)
      )
  }
  
  if (nrow(broken_links) > 0) {
    broken_links <- broken_links |>
      dplyr::mutate(
        source_rel = .source_rel(file, root),
        is_generated = .is_generated_or_checker(source_rel),
        is_optional = .is_optional_doc(source_rel)
      )
  }
  
  real_missing_images <- missing_images |>
    dplyr::filter(!is_generated, !is_optional) |>
    dplyr::distinct(source_rel, target_rel, ref) |>
    dplyr::arrange(source_rel, target_rel)
  
  real_missing_data <- missing_data |>
    dplyr::filter(!is_generated, !is_optional) |>
    dplyr::distinct(source_rel, target_rel, ref) |>
    dplyr::arrange(source_rel, target_rel)
  
  real_broken_links <- broken_links |>
    dplyr::filter(!is_generated, !is_optional) |>
    dplyr::distinct(source_rel, target_rel, ref) |>
    dplyr::arrange(source_rel, target_rel)
  
  # jquery aparece como falso positivo quando o checker lê JS gerado.
  real_missing_packages <- missing_packages |>
    dplyr::filter(!package %in% c("jquery"))
  
  action_plan <- dplyr::bind_rows(
    if (nrow(missing_expected) > 0) {
      missing_expected |>
        dplyr::transmute(
          prioridade = "alta",
          tipo = "arquivo esperado ausente",
          arquivo = rel_path,
          problema = paste0("Arquivo esperado não encontrado: ", expected_file),
          acao_sugerida = "Adicionar o arquivo no caminho indicado ou remover esse item de expected_files no check_site.R."
        )
    },
    if (nrow(real_missing_images) > 0) {
      real_missing_images |>
        dplyr::transmute(
          prioridade = "alta",
          tipo = "imagem referenciada ausente",
          arquivo = source_rel,
          problema = paste0("Referência aponta para arquivo inexistente: ", target_rel),
          acao_sugerida = "Adicionar a imagem no caminho indicado ou alterar/remover a referência no arquivo fonte."
        )
    },
    if (nrow(real_missing_data) > 0) {
      real_missing_data |>
        dplyr::transmute(
          prioridade = "alta",
          tipo = "dado referenciado ausente ou caminho relativo incorreto",
          arquivo = source_rel,
          problema = paste0("Referência aponta para arquivo inexistente: ", target_rel),
          acao_sugerida = "Em páginas dentro de subpastas, usar ../_input_data/arquivo.ext ou here::here('_input_data', 'arquivo.ext')."
        )
    },
    if (nrow(real_broken_links) > 0) {
      real_broken_links |>
        dplyr::transmute(
          prioridade = "média",
          tipo = "link interno quebrado",
          arquivo = source_rel,
          problema = paste0("Link interno não encontrado: ", ref),
          acao_sugerida = "Trocar links como team.html/expedicoes.html por team/ e expedicoes/, ou apontar para o arquivo correto."
        )
    },
    if (nrow(real_missing_packages) > 0) {
      real_missing_packages |>
        dplyr::transmute(
          prioridade = "alta",
          tipo = "pacote R ausente",
          arquivo = package,
          problema = paste0("Pacote R não instalado: ", package),
          acao_sugerida = paste0("Rodar install.packages('", package, "') ou remover o library()/require() se não for usado.")
        )
    },
    if (nrow(large_files) > 0) {
      large_files |>
        dplyr::transmute(
          prioridade = "baixa",
          tipo = "arquivo grande",
          arquivo = rel_path,
          problema = paste0("Arquivo tem ", round(size_mb, 2), " MB."),
          acao_sugerida = "Comprimir, substituir por versão web ou confirmar que precisa ficar no repositório."
        )
    },
    if (nrow(empty_files) > 0) {
      empty_files |>
        dplyr::transmute(
          prioridade = dplyr::if_else(rel_path == ".nojekyll", "manter", "baixa"),
          tipo = "arquivo vazio",
          arquivo = rel_path,
          problema = "Arquivo vazio encontrado.",
          acao_sugerida = dplyr::if_else(rel_path == ".nojekyll", "Manter se o site usa GitHub Pages.", "Remover se não for intencional.")
        )
    }
  ) |>
    dplyr::arrange(factor(prioridade, levels = c("alta", "média", "baixa", "manter")), tipo, arquivo)
  
  fs::dir_create(report_path)
  readr::write_csv(action_plan, fs::path(report_path, "action_plan_curado.csv"))
  
  list(
    action_plan = action_plan,
    real_missing_images = real_missing_images,
    real_missing_data = real_missing_data,
    real_broken_links = real_broken_links,
    real_missing_packages = real_missing_packages,
    unused_images = unused_images,
    quarto_status = quarto_status
  )
}

summarize_check_report <- function(root = getwd(), report_dir = "_check_reports") {
  x <- report_action_plan(root = root, report_dir = report_dir)
  
  cat("\n==============================\n")
  cat("RELATÓRIO CURADO DO SITE\n")
  cat("==============================\n\n")
  
  cat("Problemas reais encontrados nos arquivos-fonte:\n")
  cat("- Imagens ausentes:", nrow(x$real_missing_images), "\n")
  cat("- Dados ausentes/caminhos incorretos:", nrow(x$real_missing_data), "\n")
  cat("- Links internos quebrados:", nrow(x$real_broken_links), "\n")
  cat("- Pacotes R ausentes reais:", nrow(x$real_missing_packages), "\n\n")
  
  if (nrow(x$real_missing_images) > 0) {
    cat("Imagens ausentes por alvo:\n")
    print(x$real_missing_images |> dplyr::count(target_rel, sort = TRUE), n = Inf)
    cat("\n")
  }
  
  if (nrow(x$real_missing_data) > 0) {
    cat("Dados ausentes/caminhos incorretos por alvo:\n")
    print(x$real_missing_data |> dplyr::count(target_rel, sort = TRUE), n = Inf)
    cat("\n")
  }
  
  if (nrow(x$real_broken_links) > 0) {
    cat("Links internos quebrados reais:\n")
    print(x$real_broken_links, n = Inf)
    cat("\n")
  }
  
  cat("Plano curado salvo em:", fs::path(report_dir, "action_plan_curado.csv"), "\n")
  invisible(x)
}

quarantine_unused_assets <- function(
    root = getwd(),
    report_dir = "_check_reports",
    dry_run = TRUE,
    quarantine_dir = "_quarantine_unused",
    extra_keep_patterns = character(),
    extra_move_patterns = character()
) {
  unused <- .read_report(fs::path(root, report_dir, "unused_images.csv"))
  
  if (nrow(unused) == 0) {
    message("Nenhuma imagem órfã listada em unused_images.csv.")
    return(invisible(tibble::tibble()))
  }
  
  # Padrões que NÃO devem ser movidos automaticamente.
  # Eles incluem dependências geradas, logos, ícones e insumos dinâmicos.
  keep_patterns <- c(
    "^expedicoes/.+_files/",
    "^figures/brand/",
    "^figures/logo_inst/",
    "^figures/logo_",
    "^figures/video/",
    "^_input_data/",
    "^docs/",
    "^_site/",
    extra_keep_patterns
  )
  
  keep_regex <- paste(keep_patterns, collapse = "|")
  
  candidates <- unused |>
    dplyr::mutate(
      keep_by_rule = stringr::str_detect(rel_path, keep_regex),
      move_by_extra_rule = if (length(extra_move_patterns) == 0) FALSE else stringr::str_detect(rel_path, paste(extra_move_patterns, collapse = "|")),
      action = dplyr::case_when(
        move_by_extra_rule ~ "quarantine_candidate",
        keep_by_rule ~ "keep",
        TRUE ~ "quarantine_candidate"
      )
    ) |>
    dplyr::arrange(action, rel_path)
  
  manifest_dir <- fs::path(root, report_dir)
  fs::dir_create(manifest_dir)
  readr::write_csv(candidates, fs::path(manifest_dir, "unused_images_quarantine_plan.csv"))
  
  to_move <- candidates |>
    dplyr::filter(action == "quarantine_candidate") |>
    dplyr::mutate(
      src = fs::path(root, rel_path),
      exists = fs::file_exists(src)
    ) |>
    dplyr::filter(exists)
  
  cat("\nArquivos candidatos à quarentena:", nrow(to_move), "\n")
  if (nrow(to_move) > 0) {
    print(to_move |> dplyr::select(rel_path, size_mb), n = Inf)
  }
  
  if (isTRUE(dry_run)) {
    cat("\nDRY RUN: nada foi movido. Revise _check_reports/unused_images_quarantine_plan.csv.\n")
    cat("Para mover, rode: quarantine_unused_assets(dry_run = FALSE)\n")
    return(invisible(candidates))
  }
  
  stamp <- format(Sys.time(), "%Y%m%d_%H%M%S")
  quarantine_path <- fs::path(root, quarantine_dir, stamp)
  
  purrr::pwalk(
    list(to_move$src, to_move$rel_path),
    function(src, rel_path) {
      dest <- fs::path(quarantine_path, rel_path)
      fs::dir_create(fs::path_dir(dest))
      fs::file_move(src, dest)
    }
  )
  
  readr::write_csv(to_move, fs::path(quarantine_path, "manifest_moved_files.csv"))
  cat("\nArquivos movidos para:", fs::path_rel(quarantine_path, root), "\n")
  cat("Renderize o site novamente. Se tudo estiver certo, a pasta de quarentena pode ser apagada depois.\n")
  
  invisible(to_move)
}

quarantine_source_clutter <- function(
    root = getwd(),
    dry_run = TRUE,
    quarantine_dir = "_quarantine_source_clutter",
    include_root_index_html = FALSE
) {
  all_files <- fs::dir_ls(root, recurse = TRUE, type = "file", all = TRUE)
  rel <- fs::path_rel(all_files, root) |> .norm_slash()
  
  ignored <- stringr::str_detect(
    rel,
    "^(\\.git|_site|docs|_freeze|_cache|_check_reports|_quarantine_unused|_quarantine_source_clutter|\\.Rproj.user|renv|node_modules)/"
  )
  
  clutter <- tibble::tibble(abs_path = all_files, rel_path = rel) |>
    dplyr::filter(!ignored) |>
    dplyr::mutate(
      is_copy = stringr::str_detect(rel_path, " - (Copia|Copy|copia|copy)\\.(qmd|Rmd|md|html|css|js|R)$"),
      is_root_index_html = rel_path == "index.html" & fs::file_exists(fs::path(root, "index.qmd")) & isTRUE(include_root_index_html),
      action = dplyr::case_when(
        is_copy ~ "quarantine_candidate",
        is_root_index_html ~ "quarantine_candidate",
        TRUE ~ "keep"
      )
    ) |>
    dplyr::filter(action == "quarantine_candidate")
  
  cat("\nArquivos-fonte candidatos à quarentena:", nrow(clutter), "\n")
  if (nrow(clutter) > 0) {
    print(clutter |> dplyr::select(rel_path), n = Inf)
  }
  
  fs::dir_create(fs::path(root, "_check_reports"))
  readr::write_csv(clutter, fs::path(root, "_check_reports", "source_clutter_quarantine_plan.csv"))
  
  if (isTRUE(dry_run)) {
    cat("\nDRY RUN: nada foi movido.\n")
    cat("Para mover as cópias antigas, rode: quarantine_source_clutter(dry_run = FALSE)\n")
    cat("Para incluir index.html da raiz, rode: quarantine_source_clutter(dry_run = FALSE, include_root_index_html = TRUE)\n")
    return(invisible(clutter))
  }
  
  stamp <- format(Sys.time(), "%Y%m%d_%H%M%S")
  quarantine_path <- fs::path(root, quarantine_dir, stamp)
  
  purrr::pwalk(
    list(clutter$abs_path, clutter$rel_path),
    function(src, rel_path) {
      dest <- fs::path(quarantine_path, rel_path)
      fs::dir_create(fs::path_dir(dest))
      fs::file_move(src, dest)
    }
  )
  
  readr::write_csv(clutter, fs::path(quarantine_path, "manifest_moved_files.csv"))
  cat("\nArquivos movidos para:", fs::path_rel(quarantine_path, root), "\n")
  invisible(clutter)
}

# Aplica correções textuais seguras e frequentes detectadas no check report.
# Por padrão faz DRY RUN e só mostra o que seria alterado.
apply_common_site_fixes <- function(
    root = getwd(),
    dry_run = TRUE,
    backup_dir = "_backup_before_auto_fixes"
) {
  root <- fs::path_abs(root)
  
  read_text <- function(path) paste(readLines(path, warn = FALSE, encoding = "UTF-8"), collapse = "\n")
  write_text <- function(text, path) writeLines(text, path, useBytes = TRUE)
  
  replace_if_file_exists <- function(text, old, new, condition_path = NULL) {
    if (!is.null(condition_path) && !fs::file_exists(fs::path(root, condition_path))) return(text)
    gsub(old, new, text, fixed = TRUE)
  }
  
  plan <- tibble::tribble(
    ~rel_file, ~descricao,
    "index.qmd", "Corrigir links internos team.html/expedicoes.html e caminhos de CSVs da raiz quando existirem em _input_data/.",
    "diversidade/index.qmd", "Corrigir caminho da planilha diversidade_tsiino.xlsx para ../_input_data/.",
    "expedicoes/index.qmd", "Corrigir caminhos de expedicoes_tsiino.csv e geojson para ../_input_data/.",
    "team/index.qmd", "Corrigir caminho da planilha C2_team.xlsx para ../_input_data/."
  ) |>
    dplyr::mutate(abs_file = fs::path(root, rel_file), exists = fs::file_exists(abs_file))
  
  cat("\nArquivos que podem receber correções textuais:\n")
  print(plan |> dplyr::select(rel_file, exists, descricao), n = Inf)
  
  changes <- list()
  
  for (i in seq_len(nrow(plan))) {
    if (!plan$exists[[i]]) next
    rel_file <- plan$rel_file[[i]]
    abs_file <- plan$abs_file[[i]]
    old_text <- read_text(abs_file)
    new_text <- old_text
    
    if (rel_file == "index.qmd") {
      new_text <- gsub('href="team.html"', 'href="team/"', new_text, fixed = TRUE)
      new_text <- gsub("href='team.html'", "href='team/'", new_text, fixed = TRUE)
      new_text <- gsub("(team.html)", "(team/)", new_text, fixed = TRUE)
      new_text <- gsub('href="expedicoes.html"', 'href="expedicoes/"', new_text, fixed = TRUE)
      new_text <- gsub("href='expedicoes.html'", "href='expedicoes/'", new_text, fixed = TRUE)
      new_text <- gsub("(expedicoes.html)", "(expedicoes/)", new_text, fixed = TRUE)
      new_text <- replace_if_file_exists(new_text, '"expedicoes_tsiino.csv"', '"_input_data/expedicoes_tsiino.csv"', "_input_data/expedicoes_tsiino.csv")
      new_text <- replace_if_file_exists(new_text, "'expedicoes_tsiino.csv'", "'_input_data/expedicoes_tsiino.csv'", "_input_data/expedicoes_tsiino.csv")
      new_text <- replace_if_file_exists(new_text, '"divulgacao_instagram.csv"', '"_input_data/divulgacao_instagram.csv"', "_input_data/divulgacao_instagram.csv")
      new_text <- replace_if_file_exists(new_text, "'divulgacao_instagram.csv'", "'_input_data/divulgacao_instagram.csv'", "_input_data/divulgacao_instagram.csv")
      new_text <- replace_if_file_exists(new_text, '"divulgacao_reportagens.csv"', '"_input_data/divulgacao_reportagens.csv"', "_input_data/divulgacao_reportagens.csv")
      new_text <- replace_if_file_exists(new_text, "'divulgacao_reportagens.csv'", "'_input_data/divulgacao_reportagens.csv'", "_input_data/divulgacao_reportagens.csv")
    }
    
    if (rel_file == "diversidade/index.qmd") {
      new_text <- gsub('"diversidade_tsiino.xlsx"', '"../_input_data/diversidade_tsiino.xlsx"', new_text, fixed = TRUE)
      new_text <- gsub("'diversidade_tsiino.xlsx'", "'../_input_data/diversidade_tsiino.xlsx'", new_text, fixed = TRUE)
      new_text <- gsub('"_input_data/diversidade_tsiino.xlsx"', '"../_input_data/diversidade_tsiino.xlsx"', new_text, fixed = TRUE)
      new_text <- gsub("'_input_data/diversidade_tsiino.xlsx'", "'../_input_data/diversidade_tsiino.xlsx'", new_text, fixed = TRUE)
    }
    
    if (rel_file == "expedicoes/index.qmd") {
      new_text <- gsub('"expedicoes_tsiino.csv"', '"../_input_data/expedicoes_tsiino.csv"', new_text, fixed = TRUE)
      new_text <- gsub("'expedicoes_tsiino.csv'", "'../_input_data/expedicoes_tsiino.csv'", new_text, fixed = TRUE)
      new_text <- gsub('"_input_data/expedicoes_tsiino.csv"', '"../_input_data/expedicoes_tsiino.csv"', new_text, fixed = TRUE)
      new_text <- gsub("'_input_data/expedicoes_tsiino.csv'", "'../_input_data/expedicoes_tsiino.csv'", new_text, fixed = TRUE)
      new_text <- gsub('"sao_gabriel_da_cachoeira.geojson"', '"../_input_data/sao_gabriel_da_cachoeira.geojson"', new_text, fixed = TRUE)
      new_text <- gsub("'sao_gabriel_da_cachoeira.geojson'", "'../_input_data/sao_gabriel_da_cachoeira.geojson'", new_text, fixed = TRUE)
    }
    
    if (rel_file == "team/index.qmd") {
      new_text <- gsub('"C2_team.xlsx"', '"../_input_data/C2_team.xlsx"', new_text, fixed = TRUE)
      new_text <- gsub("'C2_team.xlsx'", "'../_input_data/C2_team.xlsx'", new_text, fixed = TRUE)
      new_text <- gsub('"_input_data/C2_team.xlsx"', '"../_input_data/C2_team.xlsx"', new_text, fixed = TRUE)
      new_text <- gsub("'_input_data/C2_team.xlsx'", "'../_input_data/C2_team.xlsx'", new_text, fixed = TRUE)
    }
    
    changed <- !identical(old_text, new_text)
    changes[[length(changes) + 1]] <- tibble::tibble(rel_file = rel_file, changed = changed)
    
    if (changed && !isTRUE(dry_run)) {
      stamp <- format(Sys.time(), "%Y%m%d_%H%M%S")
      backup_path <- fs::path(root, backup_dir, stamp, rel_file)
      fs::dir_create(fs::path_dir(backup_path))
      fs::file_copy(abs_file, backup_path, overwrite = TRUE)
      write_text(new_text, abs_file)
    }
  }
  
  changes_tbl <- dplyr::bind_rows(changes)
  cat("\nResumo das correções textuais:\n")
  print(changes_tbl, n = Inf)
  if (isTRUE(dry_run)) {
    cat("\nDRY RUN: nada foi alterado. Para aplicar, rode: apply_common_site_fixes(dry_run = FALSE)\n")
  } else {
    cat("\nCorreções aplicadas. Backups salvos em ", backup_dir, "/\n", sep = "")
  }
  invisible(changes_tbl)
}

# Move HTMLs gerados que ficaram nas pastas-fonte quando existe index.qmd no mesmo diretório.
# Útil quando o site usa output-dir: docs e sobram arquivos como diversidade/index.html.
quarantine_generated_index_html <- function(
    root = getwd(),
    dry_run = TRUE,
    quarantine_dir = "_quarantine_source_clutter"
) {
  root <- fs::path_abs(root)
  all_index_html <- fs::dir_ls(root, recurse = TRUE, type = "file", regexp = "index\\.html$", all = TRUE)
  rel <- fs::path_rel(all_index_html, root) |> .norm_slash()
  
  ignored <- stringr::str_detect(
    rel,
    "^(\\.git|_site|docs|_freeze|_cache|_check_reports|_quarantine_unused|_quarantine_source_clutter|\\.Rproj.user|renv|node_modules)/"
  )
  
  candidates <- tibble::tibble(abs_path = all_index_html, rel_path = rel) |>
    dplyr::filter(!ignored) |>
    dplyr::mutate(
      qmd_sibling = fs::path(fs::path_dir(abs_path), "index.qmd"),
      has_qmd_sibling = fs::file_exists(qmd_sibling)
    ) |>
    dplyr::filter(has_qmd_sibling)
  
  cat("\nHTMLs gerados candidatos à quarentena:", nrow(candidates), "\n")
  if (nrow(candidates) > 0) print(candidates |> dplyr::select(rel_path), n = Inf)
  
  fs::dir_create(fs::path(root, "_check_reports"))
  readr::write_csv(candidates, fs::path(root, "_check_reports", "generated_index_html_quarantine_plan.csv"))
  
  if (isTRUE(dry_run)) {
    cat("\nDRY RUN: nada foi movido. Para mover, rode: quarantine_generated_index_html(dry_run = FALSE)\n")
    return(invisible(candidates))
  }
  
  stamp <- format(Sys.time(), "%Y%m%d_%H%M%S")
  quarantine_path <- fs::path(root, quarantine_dir, stamp)
  
  purrr::pwalk(
    list(candidates$abs_path, candidates$rel_path),
    function(src, rel_path) {
      dest <- fs::path(quarantine_path, rel_path)
      fs::dir_create(fs::path_dir(dest))
      fs::file_move(src, dest)
    }
  )
  
  readr::write_csv(candidates, fs::path(quarantine_path, "manifest_generated_index_html.csv"))
  cat("\nHTMLs movidos para:", fs::path_rel(quarantine_path, root), "\n")
  invisible(candidates)
}
