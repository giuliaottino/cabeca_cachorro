"""Leitura de planilhas .xlsx/.xlsm em uma única passada (modo streaming do openpyxl)."""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.services.inpa_schema import HeaderDetection, detect_header, detect_standard_header
from app.services.normalization import clean_cell, json_value, norm, parse_coordinate

REPORT_SHEET = "Validação Tsiino"
PREFERRED_SHEETS = ("Espécimes", "Especimes", "Specimens", "Sheet1", "Planilha1")
EXAMPLE_MARKERS = ("linha de exemplo", "exemplo ->", "a. coletor", "b. auxiliar", "encholirium horridum")


@dataclass
class SheetData:
    sheet_name: str
    sheet_names: list[str]
    rows: list[list[Any]]           # valores já limpos (clean_cell), linha 1 = índice 0
    truncated: bool = False
    max_rows: int = 0


@dataclass
class ParsedSpreadsheet:
    header: HeaderDetection
    records: list[dict[str, Any]]
    sheet: SheetData
    skipped_example_rows: list[int] = field(default_factory=list)


def _select_sheet(names: list[str], sheet_name: str | None) -> str:
    if sheet_name:
        if sheet_name in names:
            return sheet_name
        wanted = norm(sheet_name)
        for name in names:
            if norm(name) == wanted:
                return name
        raise ValueError(f"A aba '{sheet_name}' não foi encontrada. Abas disponíveis: {', '.join(names)}")
    for preferred in PREFERRED_SHEETS:
        if preferred in names:
            return preferred
    for name in names:
        if name != REPORT_SHEET:
            return name
    return names[0]


def read_sheet(source: bytes | Path, sheet_name: str | None = None, max_rows: int = 5000,
               header_allowance: int = 30) -> SheetData:
    """Lê a aba escolhida inteira para memória (até ``max_rows`` linhas de dados)."""
    handle = BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    try:
        wb = load_workbook(handle, read_only=True, data_only=True)
    except Exception as exc:  # arquivo corrompido, senha, formato antigo .xls renomeado etc.
        raise ValueError(f"Não foi possível abrir a planilha ({exc.__class__.__name__}). "
                         "Confirme que é um arquivo .xlsx/.xlsm válido e sem senha.") from exc
    try:
        names = list(wb.sheetnames)
        title = _select_sheet(names, sheet_name)
        ws = wb[title]
        limit = max_rows + header_allowance
        rows: list[list[Any]] = []
        truncated = False
        for row in ws.iter_rows(values_only=True):
            values = [clean_cell(v) for v in row]
            while values and values[-1] is None:
                values.pop()
            if len(rows) >= limit:
                if values:
                    truncated = True
                    break
                continue
            rows.append(values)
    finally:
        wb.close()
    while rows and not rows[-1]:
        rows.pop()
    if not rows:
        raise ValueError("A planilha está vazia.")
    return SheetData(sheet_name=title, sheet_names=names, rows=rows, truncated=truncated, max_rows=max_rows)


def _is_example_row(raw: dict[str, Any]) -> bool:
    joined = " ".join(str(v).lower() for v in list(raw.values())[:6] if v is not None)
    return any(marker in joined for marker in EXAMPLE_MARKERS)


def records_from_sheet(sheet: SheetData, header: HeaderDetection, max_rows: int | None = None) -> ParsedSpreadsheet:
    headers = header.raw_headers
    mapping = header.mapping
    records: list[dict[str, Any]] = []
    skipped: list[int] = []
    limit = max_rows or sheet.max_rows or 5000
    for idx0 in range(header.header_row, len(sheet.rows)):
        values = sheet.rows[idx0]
        if not any(v is not None for v in values):
            continue
        row_number = idx0 + 1
        raw: dict[str, Any] = {}
        record: dict[str, Any] = {"_row_number": row_number}
        for pos, name in enumerate(headers):
            if not name:
                continue
            value = values[pos] if pos < len(values) else None
            raw[name] = json_value(value)
            canon = mapping.get(name)
            if canon and canon not in record:
                record[canon] = value
        if not any(v not in (None, "") for v in raw.values()):
            continue
        if idx0 == header.header_row and _is_example_row(raw):
            skipped.append(row_number)
            continue
        lat = parse_coordinate(record.get("lat"))
        lon = parse_coordinate(record.get("long"))
        record["_lat"] = lat
        record["_long"] = lon
        record["lat"] = lat.value if lat.value is not None else record.get("lat")
        record["long"] = lon.value if lon.value is not None else record.get("long")
        record["_raw"] = raw
        records.append(record)
        if len(records) >= limit:
            break
    return ParsedSpreadsheet(header=header, records=records, sheet=sheet, skipped_example_rows=skipped)


def parse_xlsx(source: bytes | Path, sheet_name: str | None = None, *, max_rows: int = 5000,
               strict: bool = False) -> ParsedSpreadsheet:
    sheet = read_sheet(source, sheet_name=sheet_name, max_rows=max_rows)
    if strict:
        header = detect_standard_header(sheet.rows)
        if header is None:
            raise ValueError("Não foi possível detectar o cabeçalho técnico INPA/BRAHMS. Use o mapeador de colunas.")
    else:
        header = detect_standard_header(sheet.rows) or detect_header(sheet.rows)
    return records_from_sheet(sheet, header, max_rows=max_rows)


def public_record(record: dict[str, Any]) -> dict[str, Any]:
    """Versão do registro para JSON (sem objetos internos)."""
    out: dict[str, Any] = {}
    for key, value in record.items():
        if key in ("_lat", "_long"):
            continue
        out[key] = value if key == "_raw" else json_value(value)
    return out
