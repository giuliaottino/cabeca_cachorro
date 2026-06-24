
# tools/check_missing_assets.R

project_root <- normalizePath(getwd(), winslash = "/", mustWork = TRUE)

message("Diretório base do projeto: ", project_root)

qmd_files <- list.files(
  path = project_root,
  pattern = "^index\\.qmd$",
  recursive = TRUE,
  full.names = TRUE
)

# inclui também index.qmd da raiz, caso recursive não pegue corretamente em algum contexto
root_index <- file.path(project_root, "index.qmd")
if (file.exists(root_index)) {
  qmd_files <- unique(c(root_index, qmd_files))
}

if (length(qmd_files) == 0) {
  stop("Nenhum index.qmd encontrado.")
}

message("Arquivos index.qmd encontrados:")
for (f in qmd_files) message(" - ", normalizePath(f, winslash = "/", mustWork = FALSE))

extract_assets <- function(text) {
  patterns <- c(
    "src=[\"\']([^\"\']+)[\"\']",
    "poster=[\"\']([^\"\']+)[\"\']",
    "href=[\"\']([^\"\']+\\.(png|jpg|jpeg|webp|gif|svg|mp4|mov|webm|ico|json|geojson))[\"\']",
    "url\\([\"\']?([^\"\')]+)[\"\']?\\)"
  )

  out <- character()

  for (pat in patterns) {
    m <- gregexpr(pat, text, perl = TRUE, ignore.case = TRUE)
    hits <- regmatches(text, m)[[1]]

    if (length(hits) && hits[1] != "-1") {
      vals <- sub(pat, "\\1", hits, perl = TRUE, ignore.case = TRUE)
      out <- c(out, vals)
    }
  }

  unique(out)
}

is_external <- function(x) {
  grepl("^(https?:)?//|^data:|^mailto:|^#|^javascript:", x, ignore.case = TRUE)
}

clean_path <- function(x) {
  x <- trimws(x)
  x <- sub("[?#].*$", "", x)
  x <- gsub("\\", "/", x)
  x
}

check_one_file <- function(qmd) {
  txt <- paste(readLines(qmd, warn = FALSE, encoding = "UTF-8"), collapse = "\n")
  assets <- extract_assets(txt)
  assets <- clean_path(assets)
  assets <- assets[nzchar(assets)]
  assets <- assets[!is_external(assets)]

  # mantém só arquivos que parecem ser recursos locais úteis
  assets <- assets[grepl("\\.(png|jpg|jpeg|webp|gif|svg|mp4|mov|webm|ico|json|geojson)$", assets, ignore.case = TRUE)]

  if (!length(assets)) {
    return(data.frame())
  }

  qmd_dir <- dirname(qmd)

  rows <- lapply(unique(assets), function(asset) {
    asset_no_slash <- sub("^/", "", asset)

    # Possibilidades:
    # 1. caminho absoluto estilo /figures/x.png => relativo à raiz do projeto
    # 2. caminho relativo ao index.qmd
    # 3. caminho relativo à raiz do projeto
    candidates <- unique(c(
      file.path(project_root, asset_no_slash),
      file.path(qmd_dir, asset_no_slash),
      file.path(qmd_dir, asset)
    ))

    candidates <- normalizePath(candidates, winslash = "/", mustWork = FALSE)
    exists_any <- any(file.exists(candidates))

    data.frame(
      qmd = sub(paste0("^", gsub("([\\.\\+\\*\\?\\^\\$\\(\\)\\[\\]\\{\\}\\|\\\\])", "\\\\\\1", project_root), "/?"), "", normalizePath(qmd, winslash = "/", mustWork = FALSE)),
      chamada = asset,
      existe = exists_any,
      caminho_testado_1 = candidates[1],
      caminho_testado_2 = ifelse(length(candidates) >= 2, candidates[2], NA_character_),
      stringsAsFactors = FALSE
    )
  })

  do.call(rbind, rows)
}

resultado <- do.call(rbind, lapply(qmd_files, check_one_file))

if (is.null(resultado) || nrow(resultado) == 0) {
  message("Nenhum asset local encontrado nos index.qmd.")
  quit(save = "no", status = 0)
}

faltando <- resultado[!resultado$existe, ]

dir.create("_diagnostics", showWarnings = FALSE, recursive = TRUE)

write.csv(
  resultado,
  file = "_diagnostics/assets_chamados_todos_index.csv",
  row.names = FALSE,
  fileEncoding = "UTF-8"
)

write.csv(
  faltando,
  file = "_diagnostics/assets_faltando_todos_index.csv",
  row.names = FALSE,
  fileEncoding = "UTF-8"
)

message("")
message("Total de chamadas locais encontradas: ", nrow(resultado))
message("Total de arquivos faltando: ", nrow(faltando))
message("")
message("Relatório completo: _diagnostics/assets_chamados_todos_index.csv")
message("Relatório de faltantes: _diagnostics/assets_faltando_todos_index.csv")
message("")

if (nrow(faltando) > 0) {
  message("Arquivos faltando:")
  for (i in seq_len(nrow(faltando))) {
    message(" - [", faltando$qmd[i], "] ", faltando$chamada[i])
  }
} else {
  message("Nenhum arquivo faltando encontrado.")
}
 TRUE