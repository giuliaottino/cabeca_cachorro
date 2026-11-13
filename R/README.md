# Kit de painel de biodiversidade (DwC → página Quarto leve)

Usado em `acesso/index.qmd`. Para reaproveitar em outro projeto, copie estes quatro arquivos:

| Arquivo | Papel |
|---|---|
| `R/painel_biodiversidade.R` | leitura e padronização Darwin Core, indicadores, gráficos SVG, exportação JSON |
| `assets/js/catalogo-especies.js` | lista de espécies sob demanda (busca, filtros, paginação, links e registros) |
| `assets/css/painel-biodiversidade.css` | estilos dos gráficos SVG e dos controles da lista |
| `tools/otimizar_imagens_acesso.py` | (opcional) gera versões web das imagens (`pip install pillow`) |

## Uso

```r
source("R/painel_biodiversidade.R")
PROJECT_SOURCE <- "Minhas expedições"          # rótulo da fonte do próprio projeto

catalogo <- carregar_catalogo_dwc(list(
  list(rotulo = "Minhas expedições", arquivos = "_input_data/minhas_coletas_dwc.xlsx"),
  list(rotulo = "Coleções / GBIF",   arquivos = "_input_data/gbif_dwc.xlsx")
), fonte_projeto = PROJECT_SOURCE)
catalog_all_dwc <- catalogo$todos
catalog_species_dwc <- catalogo$especies

exportar_catalogo_json(catalog_species_dwc, "assets/data/meu_painel")
render_dashboard("Painel geral", "Texto de apoio")
render_dashboard("Fungos", "Texto de apoio", group_filter = "Fungos", compact = TRUE,
                 data_dir = "../assets/data/meu_painel")
```

Na página, declare os JSON como recursos (para serem publicados já na primeira renderização)
e inclua o componente:

```yaml
resources:
  - ../assets/data/meu_painel/especies.json
  - ../assets/data/meu_painel/detalhes.json
```

```html
<link rel="stylesheet" href="../assets/css/painel-biodiversidade.css">
<script src="../assets/js/catalogo-especies.js" defer></script>
```

## Entradas esperadas

Planilhas `.xlsx` em Darwin Core (aba `DwC_records` ou a primeira aba). Colunas reconhecidas incluem
`scientificName`, `taxonRank`, `family`, `genus`, `kingdom`, `class`, `phylum`, `year`/`eventDate`,
`recordedBy`, `recordNumber`, `decimalLatitude`/`decimalLongitude`, `occurrenceID`, `gbifID` e as
colunas de links mineradas (`ffb_taxon_url`, `gbif_taxon_url`, `wfo_taxon_url`, ...). Veja
`standardize_dwc_cols()` para a lista completa de sinônimos aceitos.

## Por que JSON em vez de HTML

A versão anterior gerava a lista de espécies como HTML: ~17 MB de página, ~700 mil elementos no DOM e
~4 minutos de renderização só para fanerógamas. Agora a página tem ~190 KB; `especies.json` (~40 KB
comprimido) só é baixado quando a lista é aberta, e `detalhes.json` (~640 KB comprimido) quando a
primeira espécie é expandida.
