from dataclasses import dataclass
from typing import Any

from openpyxl.worksheet.worksheet import Worksheet

from app.services.normalization import clean_cell, normalize_key

# Campos canônicos da planilha INPA/BRAHMS observada no template.
CANONICAL_COLUMNS = [
    'accession', 'collector', 'prefix', 'number', 'suffix', 'addcoll',
    'colldd', 'collmm', 'collyy', 'initial', 'family', 'genus', 'detstatus',
    'sp1', 'rank1', 'sp2', 'detby', 'detdd', 'detmm', 'detyy', 'country',
    'majorarea', 'minorarea', 'gazetteer', 'locnotes', 'habitattxt', 'lat',
    'NS', 'long', 'EW', 'llunit', 'alt', 'alt1', 'plantdesc', 'vernacular',
    'dups', 'project', 'genbank'
]

# Aliases tolerados para aceitar pequenas modificações sem perder o significado.
COLUMN_ALIASES = {
    'numtombo': 'accession',
    'tombo': 'accession',
    'coletor': 'collector',
    'coletores': 'collector',
    'numero': 'number',
    'numcoleta': 'number',
    'numero_coleta': 'number',
    'sufixo': 'suffix',
    'coletores_adicionais': 'addcoll',
    'add_collector': 'addcoll',
    'dia': 'colldd',
    'dia_coleta': 'colldd',
    'mes': 'collmm',
    'mes_coleta': 'collmm',
    'ano': 'collyy',
    'ano_coleta': 'collyy',
    'familia': 'family',
    'genero': 'genus',
    'especie': 'sp1',
    'epiteto': 'sp1',
    'epiteto_especifico': 'sp1',
    'autor': 'author1',
    'author1': 'author1',
    'pais': 'country',
    'estado': 'majorarea',
    'uf': 'majorarea',
    'municipio': 'minorarea',
    'localidade': 'gazetteer',
    'notas_localidade': 'locnotes',
    'habitat': 'habitattxt',
    'latitude': 'lat',
    'longitude': 'long',
    'longitud': 'long',
    'unidade_latlong': 'llunit',
    'altitude': 'alt',
    'descricao': 'plantdesc',
    'descricao_planta': 'plantdesc',
    'nome_popular': 'vernacular',
    'duplicatas': 'dups',
    'herbario': 'dups',
    'herbarios': 'dups',
    'projeto': 'project',
}

REQUIRED_MINIMUM = [
    'collector', 'number', 'colldd', 'collmm', 'collyy', 'family', 'genus',
    'country', 'majorarea', 'minorarea', 'lat', 'long', 'plantdesc'
]


@dataclass
class HeaderDetection:
    header_row: int
    mapping: dict[str, str]
    raw_headers: list[str]
    missing_minimum: list[str]
    unknown_headers: list[str]


def _map_header(value: Any) -> str | None:
    raw = clean_cell(value)
    if raw is None:
        return None
    if raw in CANONICAL_COLUMNS:
        return raw
    key = normalize_key(raw)
    if key in CANONICAL_COLUMNS:
        return key
    return COLUMN_ALIASES.get(key)


def detect_header(ws: Worksheet, max_scan_rows: int = 12) -> HeaderDetection:
    best: HeaderDetection | None = None
    best_score = -1

    for row_idx in range(1, min(ws.max_row, max_scan_rows) + 1):
        raw_headers = [clean_cell(cell.value) or '' for cell in ws[row_idx]]
        mapped: dict[str, str] = {}
        unknown: list[str] = []

        for raw in raw_headers:
            if not raw:
                continue
            canonical = _map_header(raw)
            if canonical:
                mapped[raw] = canonical
            else:
                unknown.append(raw)

        score = len(set(mapped.values()) & set(REQUIRED_MINIMUM)) + len(set(mapped.values()) & set(CANONICAL_COLUMNS))
        if score > best_score:
            missing = [col for col in REQUIRED_MINIMUM if col not in set(mapped.values())]
            best = HeaderDetection(row_idx, mapped, raw_headers, missing, unknown)
            best_score = score

    if best is None or best_score < 3:
        raise ValueError('Não foi possível detectar a linha de cabeçalho da planilha.')
    return best
