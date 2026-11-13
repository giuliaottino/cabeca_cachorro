"""Correções a partir do resultado da validação.

1. ``detect_trailing_fill``: encontra linhas no fim da planilha em que só uma ou duas colunas
   estão preenchidas — o caso típico de alguém arrastar (preencher para baixo) uma coluna além
   da última coleta. Essas linhas não são espécimes, mas cada uma gera dezenas de erros de
   "campo obrigatório vazio".
2. ``apply_corrections``: regrava a planilha do job com as sugestões aceitas e com as linhas
   arrastadas limpas, preservando formatação, outras abas e macros (.xlsm).
"""
from __future__ import annotations

import re
from collections import Counter
from io import BytesIO
from statistics import median
from typing import Any, Iterable

from openpyxl import Workbook, load_workbook

# Campos numéricos no padrão INPA: texto vindo do navegador vira número ao gravar.
NUMERIC_FIELDS = {"lat", "long", "alt", "alt1", "colldd", "collmm", "collyy", "detdd", "detmm", "detyy", "initial"}
_NUMBER_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")


def _filled(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _pattern(values: list[Any]) -> str:
    """'repeated' (mesmo valor copiado), 'series' (sequência numérica do preenchimento em série) ou 'mixed'."""
    vals = [v for v in values if _filled(v)]
    if len(vals) < 2:
        return "repeated" if vals else "mixed"
    if len({str(v).strip() for v in vals}) == 1:
        return "repeated"
    nums: list[float] = []
    for v in vals:
        try:
            nums.append(float(str(v).replace(",", ".")))
        except ValueError:
            return "mixed"
    steps = {round(b - a, 9) for a, b in zip(nums, nums[1:])}
    return "series" if len(steps) == 1 else "mixed"


def detect_trailing_fill(records: list[dict[str, Any]], headers: Iterable[str],
                         field_by_header: dict[str, str] | None = None) -> dict[str, Any] | None:
    """Bloco final de linhas "quase vazias" (só a(s) coluna(s) arrastada(s) preenchida(s)).

    Regras, pensadas para não confundir com uma coleta real incompleta:
    - as linhas típicas da planilha têm pelo menos 5 campos preenchidos;
    - uma linha do bloco tem no máximo max(1, min(3, 25% do típico)) campos preenchidos;
    - o bloco vai da última linha "cheia" até o fim, e as colunas preenchidas nele são sempre as mesmas.
    """
    headers = [h for h in headers if h]
    if len(records) < 3:
        return None
    filled = [[h for h in headers if _filled((r.get("_raw") or {}).get(h))] for r in records]
    # O "típico" vem só das linhas com dados de verdade: quando a coluna foi arrastada por milhares
    # de linhas, as linhas vazias são maioria e puxariam a mediana para 1.
    dense = [len(f) for f in filled if len(f) > 3]
    if not dense:
        return None
    typical = median(dense)
    if typical < 5:
        return None
    limit = max(1, min(3, int(typical * 0.25)))
    i = len(records)
    while i > 0 and len(filled[i - 1]) <= limit:
        i -= 1
    if i == len(records) or i == 0:
        return None
    block = records[i:]
    block_filled = filled[i:]
    counts = Counter(h for f in block_filled for h in f)
    if not counts:
        return None
    # Colunas que aparecem em quase todo o bloco = colunas arrastadas.
    dragged = [h for h, n in counts.most_common() if n >= max(1, 0.6 * len(block))]
    if not dragged:
        return None
    covered = sum(1 for f in block_filled if set(f) <= set(dragged))
    if covered < 0.9 * len(block):
        return None
    field_by_header = field_by_header or {}
    columns = []
    for h in dragged:
        values = [(r.get("_raw") or {}).get(h) for r in block]
        sample = [v for v in values if _filled(v)][:3]
        columns.append({"header": h, "field": field_by_header.get(h, h), "pattern": _pattern(values),
                        "sample": [str(v) for v in sample]})
    rows = [int(r["_row_number"]) for r in block]
    return {
        "rows": rows,
        "first_row": rows[0],
        "last_row": rows[-1],
        "count": len(rows),
        "last_data_row": int(records[i - 1]["_row_number"]),
        "columns": columns,
        "typical_filled": typical,
    }


def _coerce(value: Any, field: str | None, current: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if text == "":
        return None
    wants_number = isinstance(current, (int, float)) or (current in (None, "") and field in NUMERIC_FIELDS)
    if wants_number and _NUMBER_RE.match(text):
        num = float(text.replace(",", "."))
        return int(num) if num.is_integer() and "." not in text and "," not in text else num
    return text


def apply_corrections(job: dict[str, Any], edits: list[dict[str, Any]], clear_rows: list[int]) -> bytes:
    """Devolve os bytes da planilha com as edições aplicadas e as linhas indicadas limpas.

    ``edits``: [{"row": nº da linha no Excel, "column": cabeçalho ou campo INPA, "value": novo valor}]
    ``clear_rows``: nº das linhas (no Excel) cujas células serão esvaziadas.
    """
    header_row = int(job["header_row"])
    raw_headers: list[str] = job["raw_headers"]
    field_to_header: dict[str, str] = job.get("field_to_header") or {}
    header_to_field = {h: f for f, h in field_to_header.items()}
    header_to_col = {h: i for i, h in enumerate(raw_headers, start=1) if h}
    is_xlsm = str(job.get("filename", "")).lower().endswith(".xlsm")

    def column_of(name: str) -> int | None:
        return header_to_col.get(name) or header_to_col.get(field_to_header.get(name, ""))

    known_rows = {int(r["_row_number"]) for r in job["table"]}
    clear = {int(r) for r in clear_rows if int(r) in known_rows}
    for e in edits:
        if int(e.get("row", 0)) not in known_rows:
            raise ValueError(f"Linha {e.get('row')} não existe nos dados validados.")
        if column_of(str(e.get("column", ""))) is None:
            raise ValueError(f"Coluna '{e.get('column')}' não existe na planilha.")

    try:
        wb = load_workbook(BytesIO(job["file_bytes"]), keep_vba=is_xlsm)
        ws = wb[job["sheet_name"]] if job.get("sheet_name") in wb.sheetnames else wb.worksheets[0]
        row_map = None
    except Exception:
        # Estruturas que o openpyxl não regrava: reconstrói só a aba de dados.
        wb = Workbook()
        ws = wb.active
        ws.title = str(job.get("sheet_name") or "Espécimes")[:31]
        ws.append(list(raw_headers))
        row_map = {}
        for record in job["table"]:
            raw = record.get("_raw") or {}
            ws.append([raw.get(h) if h else None for h in raw_headers])
            row_map[int(record["_row_number"])] = ws.max_row

    def target(row: int) -> int:
        return row_map[row] if row_map is not None else row

    for e in edits:
        row = int(e["row"])
        if row in clear:
            continue
        name = str(e["column"])
        col = column_of(name)
        header = raw_headers[col - 1]
        field = header_to_field.get(header, header if header in NUMERIC_FIELDS else name)
        cell = ws.cell(row=target(row), column=col)
        cell.value = _coerce(e.get("value"), field, cell.value)

    for row in clear:
        r = target(row)
        if r <= (header_row if row_map is None else 1):
            continue
        for col in range(1, ws.max_column + 1):
            cell = ws.cell(row=r, column=col)
            cell.value = None
            cell.comment = None

    out = BytesIO()
    wb.save(out)
    return out.getvalue()
