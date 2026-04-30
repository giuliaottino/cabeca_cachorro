# scripts/check_site.R
# Checks pré-publicação para site Quarto/RStudio
# Rode a partir da raiz do projeto:
# source("scripts/check_site.R")
# check_site(render_site = TRUE)

check_site <- function(
    root = getwd(),
    render_site = FALSE,
    report_dir = "_check_reports",
    expected_files = c(
      "_input_data/diversidade_tsiino.xlsx",
      "logonovo.jpg"
    ),
    ignored_dirs = c(
      ".git", ".quarto", "_site", "_freeze", "_cache",
      ".Rproj.user", "renv", "packrat", "node_modules",
      ".cache", "docs", "_check_reports",
      "_quarantine_unused", "_quarantine_source_clutter",
      "_quarantine_generated_html"
    ),
    large_file_mb = 20,
    max_ref_chars = 180
) {
  required_pkgs <- c(
    "fs", "stringr", "purrr", "dplyr",
    "tibble", "readr", "knitr"
  )
  
  missing_pkgs <- required_pkgs[
    !vapply(required_pkgs, requireNamespace, logical(1), quietly = TRUE)
  ]
  
  if (length(missing_pkgs) > 0) {
    stop(
      "Instale os pacotes antes de rodar:\n",
      paste0(
        "install.packages(c(",
        paste(sprintf('"%s"', missing_pkgs), collapse = ", "),
        "))"
      ),
      call. = FALSE
    )
  }
  
  `%||%` <- function(x, y) {
    if (is.null(x) || length(x) == 0 || all(is.na(x))) y else x
  }
  
  root <- normalizePath(root, winslash = "/", mustWork = TRUE)
  report_path <- file.path(root, report_dir)
  dir.create(report_path, recursive = TRUE, showWarnings = FALSE)
  
  # Evita que refs de bibliotecas HTML geradas, leaflet, jquery etc. entrem no check.
  is_ignored <- function(paths) {
    rel <- fs::path_rel(paths, root)
    parts <- strsplit(rel, "/|\\\\")
    vapply(parts, function(x) {
      any(x %in% ignored_dirs) || any(stringr::str_detect(x, "_files$"))
    }, logical(1))
  }
  
  safe_read <- function(path) {
    tryCatch(
      paste(readLines(path, warn = FALSE, encoding = "UTF-8"), collapse = "\n"),
      error = function(e) ""
    )
  }
  
  safe_file_exists <- function(path) {
    tryCatch(file.exists(path), error = function(e) FALSE)
  }
  
  safe_dir_exists <- function(path) {
    tryCatch(dir.exists(path), error = function(e) FALSE)
  }
  
  safe_rel <- function(path) {
    tryCatch(
      fs::path_rel(path, root),
      error = function(e) NA_character_
    )
  }
  
  clean_ref <- function(ref) {
    ref <- stringr::str_trim(ref)
    ref <- stringr::str_remove_all(ref, "^['\"]|['\"]$")
    ref <- sub("[?#].*$", "", ref)
    ref <- tryCatch(utils::URLdecode(ref), error = function(e) ref)
    ref
  }
  
  is_external_ref <- function(ref) {
    stringr::str_detect(
      ref,
      stringr::regex(
        "^(https?:)?//|^mailto:|^tel:|^data:|^javascript:|^www\\.",
        ignore_case = TRUE
      )
    )
  }
  
  is_probably_generated_or_invalid_ref <- function(ref) {
    ref <- clean_ref(ref)
    
    is.na(ref) ||
      ref == "" ||
      nchar(ref) > max_ref_chars ||
      stringr::str_detect(ref, "[{}<>]") ||
      stringr::str_detect(ref, "\\n|\\r")
  }
  
  resolve_ref <- function(ref, source_file) {
    ref <- clean_ref(ref)
    
    if (
      is_probably_generated_or_invalid_ref(ref) ||
      stringr::str_starts(ref, "#") ||
      is_external_ref(ref)
    ) {
      return(NA_character_)
    }
    
    out <- tryCatch(
      {
        if (stringr::str_starts(ref, "/")) {
          normalizePath(
            file.path(root, stringr::str_remove(ref, "^/+")),
            winslash = "/",
            mustWork = FALSE
          )
        } else {
          normalizePath(
            file.path(dirname(source_file), ref),
            winslash = "/",
            mustWork = FALSE
          )
        }
      },
      error = function(e) NA_character_
    )
    
    out
  }
  
  extract_matches <- function(text, pattern, type, file) {
    matches <- stringr::str_match_all(text, pattern)[[1]]
    
    if (nrow(matches) == 0) {
      return(tibble::tibble(
        file = character(),
        type = character(),
        ref = character()
      ))
    }
    
    tibble::tibble(
      file = file,
      type = type,
      ref = matches[, 2]
    )
  }
  
  check_existing_refs <- function(ref_tbl, allow_html_as_qmd = FALSE) {
    if (nrow(ref_tbl) == 0) {
      return(tibble::tibble(
        file = character(),
        type = character(),
        ref = character(),
        file_abs = character(),
        target_abs = character(),
        target_rel = character(),
        exists = logical()
      ))
    }
    
    ref_tbl |>
      dplyr::mutate(
        file_abs = normalizePath(file, winslash = "/", mustWork = FALSE),
        target_abs = purrr::map2_chr(ref, file_abs, resolve_ref),
        target_rel = purrr::map_chr(target_abs, safe_rel),
        exists = dplyr::if_else(
          is.na(target_abs),
          TRUE,
          purrr::map_lgl(target_abs, safe_file_exists)
        )
      ) |>
      dplyr::mutate(
        exists = purrr::pmap_lgl(
          list(target_abs, exists, ref),
          function(target_abs, exists, ref) {
            if (isTRUE(exists) || is.na(target_abs)) {
              return(TRUE)
            }
            
            if (allow_html_as_qmd &&
                stringr::str_detect(clean_ref(ref), "\\.html$")) {
              qmd_alt <- fs::path_ext_set(target_abs, "qmd")
              rmd_alt <- fs::path_ext_set(target_abs, "Rmd")
              md_alt  <- fs::path_ext_set(target_abs, "md")
              
              return(any(vapply(
                c(qmd_alt, rmd_alt, md_alt),
                safe_file_exists,
                logical(1)
              )))
            }
            
            if (safe_dir_exists(target_abs)) {
              index_candidates <- file.path(
                target_abs,
                c("index.qmd", "index.Rmd", "index.md", "index.html")
              )
              return(any(vapply(index_candidates, safe_file_exists, logical(1))))
            }
            
            FALSE
          }
        )
      )
  }
  
  find_case_match <- function(target_rel, inventory) {
    if (is.na(target_rel)) {
      return(NA_character_)
    }
    
    match <- inventory$rel_path[
      tolower(inventory$rel_path) == tolower(target_rel)
    ]
    
    if (length(match) == 0) NA_character_ else match[1]
  }
  
  cat("\n==============================\n")
  cat("CHECK DO SITE\n")
  cat("==============================\n")
  cat("Raiz do projeto:", root, "\n\n")
  
  all_files <- fs::dir_ls(root, recurse = TRUE, type = "file", all = TRUE)
  all_files <- all_files[!is_ignored(all_files)]
  
  inventory <- tibble::tibble(
    abs_path = normalizePath(all_files, winslash = "/", mustWork = FALSE),
    rel_path = fs::path_rel(abs_path, root),
    ext = tolower(fs::path_ext(abs_path)),
    size_mb = as.numeric(fs::file_size(abs_path)) / 1024^2
  )
  
  text_ext <- c(
    "qmd", "rmd", "md", "html", "css", "scss",
    "yml", "yaml", "r"
  )
  
  text_files <- inventory |>
    dplyr::filter(ext %in% text_ext) |>
    dplyr::pull(abs_path)
  
  contents <- tibble::tibble(
    file = text_files,
    text = purrr::map_chr(text_files, safe_read)
  )
  
  image_ext <- c(
    "png", "jpg", "jpeg", "webp", "gif",
    "svg", "tif", "tiff", "bmp", "pdf"
  )
  
  image_ext_regex <- paste0("\\.(", paste(image_ext, collapse = "|"), ")([?#].*)?$")
  
  image_patterns <- list(
    markdown_image = "!\\[[^\\]]*\\]\\(([^)]+)\\)",
    html_img = "<img[^>]+src\\s*=\\s*['\"]([^'\"]+)['\"]",
    css_url = "url\\(\\s*['\"]?([^'\")]+)['\"]?\\s*\\)",
    quoted_image = paste0(
      "['\"]([^'\"]+\\.(",
      paste(image_ext, collapse = "|"),
      ")([?#][^'\"]*)?)['\"]"
    )
  )
  
  image_refs <- purrr::map2_dfr(
    contents$file,
    contents$text,
    function(file, text) {
      dplyr::bind_rows(lapply(names(image_patterns), function(nm) {
        extract_matches(
          text = text,
          pattern = stringr::regex(image_patterns[[nm]], ignore_case = TRUE),
          type = nm,
          file = file
        )
      }))
    }
  ) |>
    dplyr::mutate(ref = purrr::map_chr(ref, clean_ref)) |>
    dplyr::filter(
      !purrr::map_lgl(ref, is_probably_generated_or_invalid_ref),
      stringr::str_detect(ref, stringr::regex(image_ext_regex, ignore_case = TRUE))
    ) |>
    dplyr::distinct()
  
  image_refs_checked <- check_existing_refs(image_refs)
  
  image_refs_checked <- image_refs_checked |>
    dplyr::mutate(
      case_match = purrr::map_chr(
        target_rel,
        find_case_match,
        inventory = inventory
      ),
      case_problem = !exists & !is.na(case_match)
    )
  
  missing_images <- image_refs_checked |>
    dplyr::filter(!exists, !case_problem) |>
    dplyr::select(file, type, ref, target_rel)
  
  wrong_case_images <- image_refs_checked |>
    dplyr::filter(case_problem) |>
    dplyr::select(file, type, ref, target_rel, case_match)
  
  image_inventory <- inventory |>
    dplyr::filter(ext %in% image_ext)
  
  used_image_rel <- image_refs_checked |>
    dplyr::filter(exists | case_problem) |>
    dplyr::mutate(
      used_rel = dplyr::if_else(case_problem, case_match, target_rel)
    ) |>
    dplyr::pull(used_rel) |>
    tolower() |>
    unique()
  
  unused_images <- image_inventory |>
    dplyr::filter(!tolower(rel_path) %in% used_image_rel) |>
    dplyr::select(rel_path, size_mb)
  
  data_ext <- c(
    "csv", "tsv", "xls", "xlsx", "rds", "rda", "rdata",
    "json", "geojson", "gpkg", "shp", "sqlite", "db"
  )
  
  data_ext_regex <- paste0("\\.(", paste(data_ext, collapse = "|"), ")([?#].*)?$")
  
  data_pattern <- paste0(
    "['\"]([^'\"]+\\.(",
    paste(data_ext, collapse = "|"),
    ")([?#][^'\"]*)?)['\"]"
  )
  
  data_refs <- purrr::map2_dfr(
    contents$file,
    contents$text,
    function(file, text) {
      extract_matches(
        text = text,
        pattern = stringr::regex(data_pattern, ignore_case = TRUE),
        type = "quoted_data_file",
        file = file
      )
    }
  ) |>
    dplyr::mutate(ref = purrr::map_chr(ref, clean_ref)) |>
    dplyr::filter(!purrr::map_lgl(ref, is_probably_generated_or_invalid_ref)) |>
    dplyr::distinct()
  
  data_refs_checked <- check_existing_refs(data_refs)
  
  missing_data_files <- data_refs_checked |>
    dplyr::filter(!exists) |>
    dplyr::select(file, type, ref, target_rel)
  
  link_patterns <- list(
    markdown_link = "(?<!!)\\[[^\\]]*\\]\\(([^)]+)\\)",
    html_href = "<a[^>]+href\\s*=\\s*['\"]([^'\"]+)['\"]"
  )
  
  internal_links <- purrr::map2_dfr(
    contents$file,
    contents$text,
    function(file, text) {
      dplyr::bind_rows(lapply(names(link_patterns), function(nm) {
        extract_matches(
          text = text,
          pattern = stringr::regex(link_patterns[[nm]], ignore_case = TRUE),
          type = nm,
          file = file
        )
      }))
    }
  ) |>
    dplyr::mutate(ref_clean = purrr::map_chr(ref, clean_ref)) |>
    dplyr::filter(
      ref_clean != "",
      !purrr::map_lgl(ref_clean, is_probably_generated_or_invalid_ref),
      !stringr::str_starts(ref_clean, "#"),
      !is_external_ref(ref_clean),
      !stringr::str_detect(
        ref_clean,
        stringr::regex(image_ext_regex, ignore_case = TRUE)
      ),
      !stringr::str_detect(
        ref_clean,
        stringr::regex(data_ext_regex, ignore_case = TRUE)
      )
    ) |>
    dplyr::distinct(file, type, ref)
  
  internal_links_checked <- check_existing_refs(
    internal_links,
    allow_html_as_qmd = TRUE
  )
  
  broken_internal_links <- internal_links_checked |>
    dplyr::filter(!exists) |>
    dplyr::select(file, type, ref, target_rel)
  
  duplicate_case_paths <- inventory |>
    dplyr::mutate(lower_path = tolower(rel_path)) |>
    dplyr::group_by(lower_path) |>
    dplyr::filter(dplyr::n() > 1) |>
    dplyr::ungroup() |>
    dplyr::select(lower_path, rel_path)
  
  large_files <- inventory |>
    dplyr::filter(size_mb > large_file_mb) |>
    dplyr::select(rel_path, size_mb)
  
  empty_files <- inventory |>
    dplyr::filter(as.numeric(fs::file_size(abs_path)) == 0) |>
    dplyr::select(rel_path)
  
  expected_files_check <- tibble::tibble(
    expected_file = expected_files,
    abs_path = normalizePath(file.path(root, expected_files), winslash = "/", mustWork = FALSE),
    exists = vapply(abs_path, safe_file_exists, logical(1))
  ) |>
    dplyr::mutate(rel_path = purrr::map_chr(abs_path, safe_rel)) |>
    dplyr::select(expected_file, rel_path, exists)
  
  missing_expected_files <- expected_files_check |>
    dplyr::filter(!exists)
  
  parse_r_file <- function(file) {
    tryCatch(
      {
        parse(file = file)
        tibble::tibble(file = character(), error = character())
      },
      error = function(e) {
        tibble::tibble(
          file = as.character(file),
          error = conditionMessage(e)
        )
      }
    )
  }
  
  r_files <- inventory |>
    dplyr::filter(ext == "r") |>
    dplyr::pull(abs_path)
  
  r_parse_errors <- if (length(r_files) == 0) {
    tibble::tibble(file = character(), error = character())
  } else {
    purrr::map_dfr(r_files, parse_r_file)
  }
  
  qmd_rmd_files <- inventory |>
    dplyr::filter(ext %in% c("qmd", "rmd")) |>
    dplyr::pull(abs_path)
  
  chunk_parse_errors <- if (length(qmd_rmd_files) == 0) {
    tibble::tibble(file = character(), error = character())
  } else {
    purrr::map_dfr(qmd_rmd_files, function(file) {
      tmp <- tempfile(fileext = ".R")
      
      tryCatch(
        {
          knitr::purl(file, output = tmp, quiet = TRUE, documentation = 0)
          
          if (safe_file_exists(tmp)) {
            parse(file = tmp)
          }
          
          tibble::tibble(file = character(), error = character())
        },
        error = function(e) {
          tibble::tibble(
            file = as.character(file),
            error = conditionMessage(e)
          )
        }
      )
    })
  }
  
  parse_errors <- dplyr::bind_rows(
    r_parse_errors |>
      dplyr::mutate(source_type = "R script"),
    chunk_parse_errors |>
      dplyr::mutate(source_type = "QMD/RMD chunks")
  ) |>
    dplyr::select(source_type, file, error)
  
  package_pattern <- "(?:library|require)\\s*\\(\\s*['\"]?([A-Za-z][A-Za-z0-9.]+)['\"]?"
  
  # Só procura pacotes em arquivos-fonte R/QMD/RMD. Evita falsos positivos em JS/CSS.
  package_contents <- contents |>
    dplyr::filter(tolower(fs::path_ext(file)) %in% c("r", "qmd", "rmd"))
  
  packages_used <- purrr::map_dfr(
    package_contents$text,
    function(text) {
      matches <- stringr::str_match_all(
        text,
        stringr::regex(package_pattern, ignore_case = TRUE)
      )[[1]]
      
      if (nrow(matches) == 0) {
        return(tibble::tibble(package = character()))
      }
      
      tibble::tibble(package = matches[, 2])
    }
  ) |>
    dplyr::distinct(package) |>
    dplyr::filter(!is.na(package), package != "")
  
  missing_packages <- packages_used |>
    dplyr::mutate(
      installed = vapply(package, requireNamespace, logical(1), quietly = TRUE)
    ) |>
    dplyr::filter(!installed)
  
  quarto_check_status <- tibble::tibble(
    step = character(),
    status = integer(),
    log_file = character()
  )
  
  if (nzchar(Sys.which("quarto"))) {
    old_wd <- getwd()
    setwd(root)
    on.exit(setwd(old_wd), add = TRUE)
    
    quarto_check_log <- tryCatch(
      system2("quarto", c("check"), stdout = TRUE, stderr = TRUE),
      error = function(e) conditionMessage(e)
    )
    
    quarto_check_file <- file.path(report_path, "quarto_check.txt")
    writeLines(quarto_check_log, quarto_check_file)
    
    quarto_check_status <- dplyr::bind_rows(
      quarto_check_status,
      tibble::tibble(
        step = "quarto check",
        status = attr(quarto_check_log, "status") %||% 0,
        log_file = safe_rel(quarto_check_file)
      )
    )
    
    if (isTRUE(render_site)) {
      render_log <- tryCatch(
        system2("quarto", c("render"), stdout = TRUE, stderr = TRUE),
        error = function(e) conditionMessage(e)
      )
      
      render_log_file <- file.path(report_path, "quarto_render.txt")
      writeLines(render_log, render_log_file)
      
      quarto_check_status <- dplyr::bind_rows(
        quarto_check_status,
        tibble::tibble(
          step = "quarto render",
          status = attr(render_log, "status") %||% 0,
          log_file = safe_rel(render_log_file)
        )
      )
    }
  } else {
    quarto_check_status <- tibble::tibble(
      step = "quarto",
      status = 1,
      log_file = "Quarto não encontrado no PATH"
    )
  }
  
  reports <- list(
    missing_images = missing_images,
    wrong_case_images = wrong_case_images,
    unused_images = unused_images,
    missing_data_files = missing_data_files,
    broken_internal_links = broken_internal_links,
    duplicate_case_paths = duplicate_case_paths,
    large_files = large_files,
    empty_files = empty_files,
    expected_files = expected_files_check,
    missing_expected_files = missing_expected_files,
    parse_errors = parse_errors,
    missing_packages = missing_packages,
    quarto_check_status = quarto_check_status
  )
  
  purrr::iwalk(reports, function(df, nm) {
    readr::write_csv(df, file.path(report_path, paste0(nm, ".csv")))
  })
  
  critical <- list(
    "figuras faltando" = nrow(missing_images),
    "figuras com problema de maiúscula/minúscula" = nrow(wrong_case_images),
    "arquivos de dados faltando" = nrow(missing_data_files),
    "arquivos esperados faltando" = nrow(missing_expected_files),
    "links internos quebrados" = nrow(broken_internal_links),
    "caminhos duplicados por caixa" = nrow(duplicate_case_paths),
    "erros de sintaxe em R/QMD" = nrow(parse_errors),
    "pacotes R ausentes" = nrow(missing_packages),
    "problemas no Quarto" = sum(quarto_check_status$status != 0)
  )
  
  warnings <- stats::setNames(
    list(
      nrow(unused_images),
      nrow(large_files),
      nrow(empty_files)
    ),
    c(
      "imagens possivelmente órfãs",
      paste0("arquivos maiores que ", large_file_mb, " MB"),
      "arquivos vazios"
    )
  )
  
  summary_tbl <- tibble::tibble(
    tipo = c(rep("crítico", length(critical)), rep("aviso", length(warnings))),
    item = c(names(critical), names(warnings)),
    n = c(unlist(critical), unlist(warnings))
  )
  
  readr::write_csv(summary_tbl, file.path(report_path, "summary.csv"))
  
  cat("\nResumo dos checks:\n\n")
  print(summary_tbl)
  
  cat("\nRelatórios salvos em:\n")
  cat(fs::path_rel(report_path, root), "\n\n")
  
  total_critical <- sum(unlist(critical))
  
  if (total_critical > 0) {
    cat("⚠️  Há problemas críticos antes do push.\n")
    cat("Abra os CSVs em _check_reports/ para revisar.\n\n")
  } else {
    cat("✅ Nenhum problema crítico encontrado.\n\n")
  }
  
  invisible(reports)
}

# Permite rodar também via terminal:
# Rscript scripts/check_site.R
if (sys.nframe() == 0) {
  check_site(render_site = TRUE)
}
