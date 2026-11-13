"""Mapeador/conversor de planilhas fora do padrão para o template INPA/BRAHMS."""
from __future__ import annotations

import json
import re
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import column_index_from_string, get_column_letter

from app.services.inpa_schema import (
    CANONICAL_COLUMNS, FIELD_HELP, FIELD_LABELS, INPA_FIELDS, REQUIRED_FIELDS, HeaderDetection, detect_header,
    detect_standard_header, unique_headers,
)
from app.services.normalization import cell_text, json_value, norm, parse_coordinate
from app.services.spreadsheet_reader import EXAMPLE_MARKERS, SheetData, read_sheet

RECOMMENDATIONS = [FIELD_HELP[c] for c in CANONICAL_COLUMNS]


def _fallback_header(sheet: SheetData) -> HeaderDetection:
    for idx, values in enumerate(sheet.rows[:30], start=1):
        if sum(1 for v in values if v is not None) >= 2:
            headers = unique_headers(values)
            return HeaderDetection(idx, {}, headers, list(REQUIRED_FIELDS), [h for h in headers if h])
    raise ValueError("Não encontrei uma linha de cabeçalho na planilha.")


def _infer_coordinates(sheet: SheetData, header: HeaderDetection) -> dict[str, str]:
    """Quando latitude/longitude não foram reconhecidas pelo nome, tenta pelos valores."""
    have = set(header.mapping.values())
    extra: dict[str, str] = {}
    if {"lat", "long"} <= have:
        return extra
    data = sheet.rows[header.header_row: header.header_row + 30]
    used = set(header.mapping)
    scores: dict[str, tuple[int, int]] = {}
    for pos, name in enumerate(header.raw_headers):
        if not name or name in used:
            continue
        vals = [parse_coordinate(r[pos]).value for r in data if pos < len(r)]
        vals = [v for v in vals if v is not None]
        if len(vals) < 3:
            continue
        lat_like = sum(1 for v in vals if -34 <= v <= 6 and v != int(v))
        lon_like = sum(1 for v in vals if -74 <= v <= -28 and v != int(v))
        scores[name] = (lat_like, lon_like)
    if "lat" not in have and scores:
        name, (s, _) = max(scores.items(), key=lambda kv: kv[1][0])
        if s >= 3:
            extra[name] = "lat"
    if "long" not in have and scores:
        name, (_, s) = max(scores.items(), key=lambda kv: kv[1][1])
        if s >= 3 and name not in extra:
            extra[name] = "long"
    return extra


def analyse(content: bytes, sheet_name: str | None = None, max_rows: int = 5000) -> tuple[SheetData, HeaderDetection]:
    sheet = read_sheet(content, sheet_name=sheet_name, max_rows=max_rows)
    header = detect_standard_header(sheet.rows)
    if header is None:
        try:
            header = detect_header(sheet.rows)
        except ValueError:
            header = _fallback_header(sheet)
        header.mapping.update(_infer_coordinates(sheet, header))
    return sheet, header


def _data_rows(sheet: SheetData, header: HeaderDetection):
    for idx0 in range(header.header_row, len(sheet.rows)):
        values = sheet.rows[idx0]
        if any(v is not None for v in values):
            yield idx0 + 1, values


def preview_spreadsheet(content: bytes, sheet_name: str | None = None, max_rows: int = 80) -> dict[str, Any]:
    sheet, header = analyse(content, sheet_name)
    field_to_header = header.field_to_header
    header_to_field = header.mapping
    samples: dict[str, list[Any]] = {h: [] for h in header.raw_headers if h}
    rows: list[dict[str, Any]] = []
    limit = max(1, min(int(max_rows or 80), 300))
    for row_number, values in _data_rows(sheet, header):
        if len(rows) >= limit:
            break
        row: dict[str, Any] = {"_row_number": row_number}
        for pos, name in enumerate(header.raw_headers):
            if not name:
                continue
            value = json_value(values[pos]) if pos < len(values) else None
            row[name] = "" if value is None else value
            if value not in (None, "") and len(samples[name]) < 5:
                samples[name].append(value)
        rows.append(row)

    columns = []
    for pos, name in enumerate(header.raw_headers):
        if not name:
            continue
        columns.append({
            "index": pos + 1, "column_index": pos, "letter": get_column_letter(pos + 1),
            "key": name, "name": name, "header": name,
            "mapped_field": header_to_field.get(name), "canonical": header_to_field.get(name),
            "samples": samples.get(name, []),
        })
    return {
        "status": "ok",
        "detected_standard": header.is_standard,
        "is_standard": header.is_standard,
        "sheet_name": sheet.sheet_name,
        "sheet_names": sheet.sheet_names,
        "header_row": header.header_row,
        "data_start_row": header.header_row + 1,
        "row_count": len(rows),
        "fields": INPA_FIELDS,
        "standard_fields": INPA_FIELDS,
        "canonical_fields": CANONICAL_COLUMNS,
        "field_help": FIELD_HELP,
        "recommendations": FIELD_HELP,
        "source_columns": columns,
        "columns": columns,
        "headers": [c["name"] for c in columns],
        "mapping": field_to_header,
        "suggested_mapping": field_to_header,
        "canonical_mapping": field_to_header,
        "missing_required": [f for f in REQUIRED_FIELDS if f not in field_to_header],
        "rows": rows,
        "preview_rows": rows,
        "data_rows": rows,
    }


# ---------------------------------------------------------------------------
# Conversão
# ---------------------------------------------------------------------------
def parse_mapping(value: Any) -> dict[str, Any]:
    """Aceita {campo: origem}, {origem: campo}, {"mapping": {...}} ou [{canonical, source}]."""
    if not value:
        return {}
    if isinstance(value, (str, bytes)):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    if isinstance(value, dict) and isinstance(value.get("mapping"), (dict, list)):
        value = value["mapping"]
    out: dict[str, Any] = {}
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                canon = item.get("canonical") or item.get("target") or item.get("field") or item.get("inpa")
                src = item.get("source") or item.get("header") or item.get("name") or item.get("column") or item.get("index")
                if canon in CANONICAL_COLUMNS and src not in (None, ""):
                    out[canon] = src
        return out
    if isinstance(value, dict):
        for key, src in value.items():
            if isinstance(src, dict):
                src = src.get("source") or src.get("header") or src.get("name") or src.get("column") or src.get("index")
            if src in (None, ""):
                continue
            if key in CANONICAL_COLUMNS:
                out[key] = src
            elif isinstance(src, str) and src in CANONICAL_COLUMNS:
                out[src] = key
    return out


def _resolve(source: Any, headers: list[str]) -> int | None:
    """Posição (0-based) da coluna de origem: por nome, letra da coluna ou índice 1-based."""
    if isinstance(source, bool):
        return None
    if isinstance(source, int):
        return source - 1 if 1 <= source <= len(headers) else None
    text = str(source).strip()
    if text in headers:
        return headers.index(text)
    n = norm(text)
    for pos, h in enumerate(headers):
        if h and norm(h) == n:
            return pos
    if re.fullmatch(r"[A-Za-z]{1,3}", text):
        pos = column_index_from_string(text.upper()) - 1
        return pos if pos < max(len(headers), 1) + 200 else None
    if text.isdigit():
        return int(text) - 1
    return None


def build_canonical_rows(sheet: SheetData, header: HeaderDetection, mapping: dict[str, Any]) -> tuple[list[list[Any]], dict[str, int]]:
    headers = header.raw_headers
    if mapping:
        positions = {f: p for f, src in mapping.items() if (p := _resolve(src, headers)) is not None}
    else:
        positions = {f: headers.index(h) for f, h in header.field_to_header.items()}
    out: list[list[Any]] = []
    meaningful = [positions[f] for f in ("collector", "number", "family", "genus", "lat", "long", "minorarea") if f in positions]
    for _, values in _data_rows(sheet, header):
        row = [values[positions[f]] if f in positions and positions[f] < len(values) else None for f in CANONICAL_COLUMNS]
        check = meaningful or list(positions.values())
        if not any(values[p] is not None for p in check if p < len(values)):
            continue
        joined = " ".join(str(v).lower() for v in row[:6] if v is not None)
        if any(m in joined for m in EXAMPLE_MARKERS):
            continue
        out.append(row)
    return out, positions


def convert_spreadsheet(content: bytes, mapping: Any = None, sheet_name: str | None = None, *,
                        include_recommendations: bool = False) -> bytes:
    sheet, header = analyse(content, sheet_name)
    rows, positions = build_canonical_rows(sheet, header, parse_mapping(mapping))

    wb = Workbook()
    ws = wb.active
    ws.title = "Espécimes"
    if include_recommendations:
        ws.append(RECOMMENDATIONS)
    ws.append(CANONICAL_COLUMNS)
    head = ws.max_row
    for cell in ws[head]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="E4ECD7")
    for row in rows:
        ws.append([v if not hasattr(v, "isoformat") else cell_text(v) for v in row])
    for col in range(1, len(CANONICAL_COLUMNS) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 16
    ws.freeze_panes = ws.cell(row=head + 1, column=1).coordinate

    audit = wb.create_sheet("Mapeamento")
    audit.append(["Campo INPA/BRAHMS", "Descrição", "Coluna de origem", "Cabeçalho de origem"])
    for field in CANONICAL_COLUMNS:
        pos = positions.get(field)
        audit.append([field, FIELD_LABELS[field], get_column_letter(pos + 1) if pos is not None else None,
                      header.raw_headers[pos] if pos is not None and pos < len(header.raw_headers) else None])
    audit.append([])
    audit.append(["Planilha de origem", sheet.sheet_name, "Linha de cabeçalho", header.header_row])
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


def build_template_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Espécimes"
    ws.append(RECOMMENDATIONS)
    ws.append(CANONICAL_COLUMNS)
    for cell in ws[2]:
        cell.font = Font(bold=True)
    for col in range(1, len(CANONICAL_COLUMNS) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 18
    ws.freeze_panes = "A3"
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()
