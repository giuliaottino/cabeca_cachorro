---
title: Tsiino Herbarium Validator API
sdk: docker
app_port: 7860
---

# Tsiino Herbarium Validator API

API (FastAPI) do validador de planilhas de depósito em herbário usado em
<https://tsiinohiiwiida.net/ferramentas/validador-herbario/>. Em produção o site acessa
`https://api.tsiinohiiwiida.net`, um Cloudflare Worker que encaminha para este Space.

## O que é validado

| Grupo | Verificações |
|---|---|
| Estrutura | colunas obrigatórias do template INPA/BRAHMS, colunas desconhecidas, limite de linhas |
| Preenchimento | obrigatórios, datas de coleta/determinação, `s.n.`, número com letra, coletor principal, `sp.` em `sp1`, `cf./aff.`, `var./ssp.`, altitude, projeto > 60 caracteres, número de coleta duplicado |
| Coordenadas | graus decimais ou GMS (convertidos, com alerta), faixa, sinal x NS/EW, baixa precisão |
| Taxonomia (Flora e Funga do Brasil) | família, gênero e espécie inexistentes (com sugestões), família incompatível com o gênero, nomes alternativos de família, sinônimos com nome aceito, infraespecíficos, ocorrência no estado |
| Geografia (IBGE) | estado e município (com sugestão de grafia), município fora da UF, ponto fora do município/UF/Brasil, lat/long invertidas ou com sinal trocado, distância até a divisa |

Severidades: **erro** (corrigir antes do depósito), **alerta** (revisão curatorial) e **nota** (padronização).

## Endpoints (`/api/validator`)

- `POST /upload` — valida a planilha e devolve `summary`, `issues` e `table` numa única resposta.
- `POST /validate_mapped` — converte com um mapeamento de colunas e valida a versão convertida.
- `GET /jobs/{id}`, `/jobs/{id}/issues`, `/jobs/{id}/table`, `/jobs/{id}/map.geojson`
- `GET /jobs/{id}/download.xlsx` — planilha anotada (comentários nas células, valores preservados, aba "Validação Tsiino").
- `POST /converter/preview`, `POST /converter/convert`, `POST /converter/standard_check`, `GET /converter/template`
- `GET /status`, `GET /health`

Os resultados ficam em memória por `JOB_TTL_HOURS` (padrão 6 h, até `MAX_JOBS` = 64); por isso o contêiner
roda com um único processo.

## Desenvolvimento

```bash
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
pytest
```

Bases de referência em `reference/` (Git LFS): `tsiino_reference.sqlite` (gerada por
`scripts/build_ffb_sqlite.py`) e `ibge_geography.sqlite` (gerada por `scripts/build_ibge_sqlite.py`,
requer `pip install -e ".[build]"`).
