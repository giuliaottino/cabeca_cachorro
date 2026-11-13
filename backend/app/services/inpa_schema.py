# -*- coding: utf-8 -*-
"""Fonte única do padrão INPA/BRAHMS: campos, rótulos, recomendações e aliases de cabeçalho."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from app.services.normalization import norm

# (nome técnico, rótulo, obrigatório, recomendação do template INPA)
_FIELDS: list[tuple[str, str, bool, str]] = [
    ("accession", "Registro INPA", False, "Deixar em branco. Aqui será incluído o número de registro no Herbário INPA."),
    ("collector", "Coletor principal", True, "Nome do coletor principal. Formato: Silva, LIL da. Inclua o nome completo na aba Pessoas-Coletores."),
    ("prefix", "Prefixo", False, "Usar somente no caso de séries diferentes. Não colocar suas iniciais."),
    ("number", "Número de coleta", True, "Número de coleta do coletor principal. Evite \"s.n.\"; use números sequenciais."),
    ("suffix", "Sufixo", False, "Usar somente se o número de coleta foi repetido por engano (A, B, C...)."),
    ("addcoll", "Coletores adicionais", False, "Demais pessoas presentes na coleta, no formato do coletor, separadas por ponto e vírgula."),
    ("colldd", "Dia da coleta", True, "Dia da coleta, em número."),
    ("collmm", "Mês da coleta", True, "Mês da coleta, em número."),
    ("collyy", "Ano da coleta", True, "Ano da coleta com quatro dígitos."),
    ("initial", "Nº de amostras", False, "Em quantas amostras a coleta foi dividida."),
    ("family", "Família", True, "Família. Verifique a grafia na Flora e Funga do Brasil e/ou MOBOT."),
    ("genus", "Gênero", True, "Gênero. Verifique a grafia na Flora e Funga do Brasil e/ou MOBOT."),
    ("detstatus", "cf./aff.", False, "Use \"cf.\" para conferir e \"aff.\" para material afim quando não tiver certeza do táxon."),
    ("sp1", "Epíteto específico", False, "Epíteto específico. Se não souber, deixe em branco; não escreva \"sp.\"."),
    ("rank1", "Rank infraespecífico", False, "Use \"ssp.\" para subespécie ou \"var.\" para variedade."),
    ("sp2", "Epíteto infraespecífico", False, "Epíteto da subespécie ou variedade."),
    ("detby", "Determinador", False, "Nome do determinador, no formato do coletor. Separe vários nomes por ponto e vírgula."),
    ("detdd", "Dia da determinação", False, "Dia da determinação."),
    ("detmm", "Mês da determinação", False, "Mês da determinação."),
    ("detyy", "Ano da determinação", False, "Ano da determinação."),
    ("country", "País", True, "País."),
    ("majorarea", "Estado", True, "Estado por extenso. Não usar sigla."),
    ("minorarea", "Município", True, "Município."),
    ("gazetteer", "Localidade", False, "Localidade, por exemplo Reserva Florestal Adolfo Ducke, BR-174 etc."),
    ("locnotes", "Notas da localidade", False, "Detalhes de onde a coleta foi feita."),
    ("habitattxt", "Habitat", False, "Descrição do tipo de habitat onde a planta foi coletada."),
    ("lat", "Latitude", True, "Latitude em graus decimais. Sinal negativo para Sul."),
    ("NS", "N/S", False, "N para Norte e S para Sul."),
    ("long", "Longitude", True, "Longitude em graus decimais. Sinal negativo para Oeste."),
    ("EW", "E/W", False, "E para Leste e W para Oeste."),
    ("llunit", "Unidade lat/long", False, "Deixar em branco no padrão INPA/BRAHMS."),
    ("alt", "Altitude", False, "Altitude em metros. Não incluir \"m\"."),
    ("alt1", "Altitude máxima", False, "Altitude máxima em metros, somente quando houver duas medidas."),
    ("plantdesc", "Descrição da planta", True, "Descrição do indivíduo coletado: hábito, tamanho, exsudatos, odores, cores etc."),
    ("vernacular", "Nome popular", False, "Nome popular, em minúsculas; vários separados por ponto e vírgula."),
    ("dups", "Duplicatas", False, "Siglas dos herbários onde o material será depositado. Para INPA, preencher com INPA."),
    ("project", "Projeto", False, "Nome do projeto e órgão financiador, até 60 caracteres."),
    ("genbank", "GenBank", False, "Gene, primers ou número de acesso no GenBank, se houver."),
]

INPA_FIELDS: list[dict[str, Any]] = [
    {"name": n, "key": n, "code": n.upper(), "label": lbl, "required": req, "help": hlp} for n, lbl, req, hlp in _FIELDS
]
CANONICAL_COLUMNS: list[str] = [f[0] for f in _FIELDS]
INPA_FIELD_NAMES = CANONICAL_COLUMNS
FIELD_LABELS: dict[str, str] = {f[0]: f[1] for f in _FIELDS}
FIELD_HELP: dict[str, str] = {f[0]: f[3] for f in _FIELDS}
REQUIRED_FIELDS: list[str] = [f[0] for f in _FIELDS if f[2]]
# Colunas mínimas para considerar a planilha utilizável (plantdesc só gera alerta).
REQUIRED_MINIMUM: list[str] = [c for c in REQUIRED_FIELDS if c != "plantdesc"]

_CANON_BY_NORM = {norm(c): c for c in CANONICAL_COLUMNS}

# Aliases exatos (após norm). Cobrem cabeçalhos em português, Darwin Core e variações comuns.
_EXACT_ALIASES: dict[str, str] = {
    "registro inpa": "accession", "tombo": "accession", "numtombo": "accession", "num tombo": "accession",
    "catalognumber": "accession", "catalog number": "accession",
    "coletor": "collector", "coletor principal": "collector", "nome do coletor principal": "collector",
    "recordedby": "collector", "recorded by": "collector", "coletores": "collector",
    "prefixo": "prefix", "serie": "prefix",
    "numero": "number", "numero de coleta": "number", "n coleta": "number", "no coleta": "number", "n de coleta": "number",
    "num coleta": "number", "numcoleta": "number", "numero coleta": "number", "recordnumber": "number",
    "record number": "number", "seu numero de coleta": "number",
    "sufixo": "suffix",
    "coletores adicionais": "addcoll", "coletor adicional": "addcoll", "outros coletores": "addcoll",
    "associated collectors": "addcoll",
    "dia": "colldd", "dia da coleta": "colldd", "dia coleta": "colldd", "day": "colldd",
    "mes": "collmm", "mes da coleta": "collmm", "mes coleta": "collmm", "month": "collmm",
    "ano": "collyy", "ano da coleta": "collyy", "ano coleta": "collyy", "year": "collyy",
    "n de amostras": "initial", "numero de amostras": "initial", "no de amostras": "initial",
    "familia": "family", "family": "family",
    "genero": "genus",
    "cf aff": "detstatus", "cf": "detstatus", "aff": "detstatus", "identificationqualifier": "detstatus",
    "especie": "sp1", "epiteto": "sp1", "epiteto especifico": "sp1", "epiteto da especie": "sp1",
    "specificepithet": "sp1", "specific epithet": "sp1",
    "rank infraespecifico": "rank1", "categoria infraespecifica": "rank1", "taxonrank": "rank1",
    "epiteto infraespecifico": "sp2", "infraespecifico": "sp2", "infraspecificepithet": "sp2",
    "subespecie": "sp2", "variedade": "sp2",
    "determinador": "detby", "determinado por": "detby", "identifiedby": "detby", "identified by": "detby",
    "dia da determinacao": "detdd", "dia de determinacao": "detdd",
    "mes da determinacao": "detmm", "mes de determinacao": "detmm",
    "ano da determinacao": "detyy", "ano de determinacao": "detyy",
    "pais": "country", "country": "country",
    "estado": "majorarea", "uf": "majorarea", "estado por extenso": "majorarea", "stateprovince": "majorarea",
    "state province": "majorarea",
    "municipio": "minorarea", "cidade": "minorarea", "county": "minorarea", "municipality": "minorarea",
    "localidade": "gazetteer", "locality": "gazetteer",
    "notas da localidade": "locnotes", "notas de localidade": "locnotes", "notas localidade": "locnotes",
    "habitat": "habitattxt", "ambiente": "habitattxt", "vegetacao": "habitattxt",
    "latitude": "lat", "decimallatitude": "lat", "decimal latitude": "lat", "lat dec": "lat",
    "n s": "NS", "hemisferio latitude": "NS",
    "longitude": "long", "lon": "long", "lng": "long", "decimallongitude": "long", "decimal longitude": "long",
    "longitud": "long",
    "e w": "EW", "hemisferio longitude": "EW",
    "unidade lat long": "llunit",
    "altitude": "alt", "elevacao": "alt", "altitude m": "alt", "minimumelevationinmeters": "alt",
    "altitude maxima": "alt1", "maximumelevationinmeters": "alt1",
    "descricao": "plantdesc", "descricao da planta": "plantdesc", "descricao planta": "plantdesc",
    "occurrenceremarks": "plantdesc",
    "nome popular": "vernacular", "nome vernacular": "vernacular", "vernacularname": "vernacular",
    "duplicatas": "dups", "herbarios": "dups", "herbario": "dups",
    "projeto": "project",
}

# Padrões de contenção, avaliados em ordem (do mais específico ao mais geral).
# Servem para cabeçalhos descritivos, como a linha de recomendações do template INPA.
_CONTAINS_RULES: list[tuple[re.Pattern[str], str]] = [(re.compile(p), f) for p, f in [
    (r"registro (no )?herbario|numero de registro", "accession"),
    (r"coletores adicionais|demais pessoas|quem estava presente", "addcoll"),
    (r"nome do coletor|coletor principal", "collector"),
    (r"numero de coleta foi repetido|repetido por engano", "suffix"),
    (r"series diferentes|\bprefixo\b", "prefix"),
    (r"numero de duplicatas|duplicatas coletadas|herbario de deposito", "dups"),
    (r"numero de amostras|amostras por coleta", "initial"),
    (r"(dia|mes|ano) (de|da) determinacao", None),  # tratado abaixo
    (r"\bdeterminador\b", "detby"),
    (r"(numero|n) (de )?coleta", "number"),
    (r"dia da coleta", "colldd"),
    (r"mes da coleta", "collmm"),
    (r"ano da coleta", "collyy"),
    (r"epiteto (da )?(subespecie|variedade|infra)", "sp2"),
    (r"\bssp\b.*\bvar\b|\bvar\b.*\bssp\b|rank infra", "rank1"),
    (r"epiteto especifico|epiteto da especie", "sp1"),
    (r"nao tem certeza|\bcf\b.*\baff\b", "detstatus"),
    (r"grafia correta do nome da familia|^familia\b", "family"),
    (r"grafia correta do nome do genero|^genero\b", "genus"),
    (r"estado por extenso|^estado\b", "majorarea"),
    (r"^municipio\b", "minorarea"),
    (r"detalhes de onde", "locnotes"),
    (r"^localidade\b", "gazetteer"),
    (r"tipo de habitat", "habitattxt"),
    (r"^latitude\b|latitude em graus", "lat"),
    (r"^longitude\b|longitude em graus", "long"),
    (r"norte e s para sul|\bn para norte\b", "NS"),
    (r"leste e w para oeste|\be para leste\b", "EW"),
    (r"altitude maxima", "alt1"),
    (r"^altitude\b|altitude em metros", "alt"),
    (r"descricao detalhada|descricao da planta|descricao do individuo", "plantdesc"),
    (r"nome (vernacular|popular)", "vernacular"),
    (r"projeto|financiamento", "project"),
    (r"genbank|sequencias", "genbank"),
    (r"^pais\b", "country"),
]]

_DET_DATE = re.compile(r"(dia|mes|ano) (de|da) determinacao")
_HELPER_HEADERS = {"nome do campo no brahms", "recomendacoes no preenchimento", "recomendacao", "linha de exemplo"}


def map_exact(header: Any) -> str | None:
    """Nome técnico exato (accession, collector, ...), sem considerar aliases."""
    return _CANON_BY_NORM.get(norm(header))


def guess_field(header: Any) -> str | None:
    """Sugere o campo INPA para um cabeçalho qualquer."""
    n = norm(header)
    if not n or n in _HELPER_HEADERS or n.startswith("linha de exemplo") or n.startswith("recomendacoes"):
        return None
    if n in _CANON_BY_NORM:
        return _CANON_BY_NORM[n]
    if n in _EXACT_ALIASES:
        return _EXACT_ALIASES[n]
    if len(n) > 300:
        return None
    m = _DET_DATE.search(n)
    if m:
        return {"dia": "detdd", "mes": "detmm", "ano": "detyy"}[m.group(1)]
    for pattern, field in _CONTAINS_RULES:
        if field and pattern.search(n):
            return field
    return None


@dataclass
class HeaderDetection:
    header_row: int                 # 1-based
    mapping: dict[str, str]         # cabeçalho bruto (único) -> campo canônico
    raw_headers: list[str]          # cabeçalhos únicos por posição ("" para vazios)
    missing_minimum: list[str]
    unknown_headers: list[str]
    exact_count: int = 0
    is_standard: bool = False

    @property
    def field_to_header(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for raw, canon in self.mapping.items():
            out.setdefault(canon, raw)
        return out


def unique_headers(values: Iterable[Any]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for value in values:
        text = "" if value is None else str(value).replace("﻿", "").strip()
        if not text:
            out.append("")
            continue
        seen[text] = seen.get(text, 0) + 1
        out.append(text if seen[text] == 1 else f"{text} ({seen[text]})")
    return out


def _analyse_row(row_idx: int, values: list[Any], *, technical_only: bool) -> tuple[float, HeaderDetection]:
    headers = unique_headers(values)
    mapping: dict[str, str] = {}
    used: set[str] = set()
    exact = 0
    data_like = 0
    for raw, value in zip(headers, values):
        if not raw:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            data_like += 1
            continue
        canon = map_exact(raw)
        if canon:
            exact += 1
        elif not technical_only:
            canon = guess_field(raw)
        if canon and canon not in used:
            mapping[raw] = canon
            used.add(canon)
    required_hits = len(used & set(REQUIRED_MINIMUM))
    score = exact * 10 + required_hits * 6 + len(used) * 2 - data_like * 3
    detection = HeaderDetection(
        header_row=row_idx,
        mapping=mapping,
        raw_headers=headers,
        missing_minimum=[c for c in REQUIRED_MINIMUM if c not in used],
        unknown_headers=[h for h in headers if h and h not in mapping and norm(h) not in _HELPER_HEADERS],
        exact_count=exact,
        is_standard=exact >= 8 and len(used & set(REQUIRED_MINIMUM)) >= 5,
    )
    return score, detection


def detect_header(rows: list[list[Any]], *, max_scan_rows: int = 30, technical_only: bool = False) -> HeaderDetection:
    """Escolhe a linha de cabeçalho com mais evidência.

    Com ``technical_only=True`` só nomes técnicos exatos contam (padrão INPA/BRAHMS estrito).
    """
    best: tuple[float, HeaderDetection] | None = None
    for idx, values in enumerate(rows[:max_scan_rows], start=1):
        if not any(v is not None and str(v).strip() for v in values):
            continue
        scored = _analyse_row(idx, list(values), technical_only=technical_only)
        if best is None or scored[0] > best[0]:
            best = scored
    if best is None or len(best[1].mapping) < 3:
        raise ValueError("Não foi possível detectar a linha de cabeçalho da planilha.")
    return best[1]


def detect_standard_header(rows: list[list[Any]], max_scan_rows: int = 30) -> HeaderDetection | None:
    """Retorna a detecção somente se a planilha estiver no padrão técnico INPA/BRAHMS."""
    try:
        det = detect_header(rows, max_scan_rows=max_scan_rows, technical_only=True)
    except ValueError:
        return None
    return det if det.is_standard else None
