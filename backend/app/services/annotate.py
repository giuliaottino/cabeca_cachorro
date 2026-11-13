"""Gera a planilha anotada: células destacadas + comentários, sem alterar os valores originais."""
from __future__ import annotations

from io import BytesIO
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill

from app.services.inpa_schema import FIELD_LABELS
from app.services.spreadsheet_reader import REPORT_SHEET

FILLS = {
    "error": PatternFill("solid", fgColor="F8D7DA"),
    "warning": PatternFill("solid", fgColor="FFE5B4"),
    "info": PatternFill("solid", fgColor="E4ECD7"),
}
RANK = {"error": 0, "warning": 1, "info": 2}
ICONS = {"error": "Erro", "warning": "Alerta", "info": "Nota"}


def _column_for(issue: dict[str, Any], field_to_header: dict[str, str], header_to_col: dict[str, int]) -> int | None:
    col = issue.get("column_name")
    if not col:
        return None
    header = field_to_header.get(col, col)
    return header_to_col.get(header)


def annotated_workbook(job: dict[str, Any]) -> BytesIO:
    header_row = int(job["header_row"])
    raw_headers: list[str] = job["raw_headers"]
    field_to_header: dict[str, str] = job["field_to_header"]
    is_xlsm = str(job.get("filename", "")).lower().endswith(".xlsm")

    try:
        wb = load_workbook(BytesIO(job["file_bytes"]), keep_vba=is_xlsm)
        ws = wb[job["sheet_name"]] if job.get("sheet_name") in wb.sheetnames else wb.worksheets[0]
        row_offset = 0
    except Exception:
        # Planilhas com estruturas que o openpyxl não regrava: reconstrói a partir dos dados lidos.
        wb = Workbook()
        ws = wb.active
        ws.title = "Planilha anotada"
        ws.append([h for h in raw_headers])
        for record in job["table"]:
            raw = record.get("_raw") or {}
            ws.append([raw.get(h) for h in raw_headers])
        row_offset = None

    header_to_col = {h: i for i, h in enumerate(raw_headers, start=1) if h}
    by_cell: dict[tuple[int, int], list[dict[str, Any]]] = {}
    if row_offset is None:
        new_row = {rec["_row_number"]: i for i, rec in enumerate(job["table"], start=2)}
    for item in job["issues"]:
        row = item.get("row_number")
        col = _column_for(item, field_to_header, header_to_col)
        if not row or not col:
            continue
        target = new_row.get(row) if row_offset is None else row
        if target:
            by_cell.setdefault((target, col), []).append(item)

    for (row, col), items in by_cell.items():
        items.sort(key=lambda i: RANK.get(i.get("severity"), 3))
        cell = ws.cell(row=row, column=col)
        cell.fill = FILLS.get(items[0].get("severity"), FILLS["info"])
        lines = []
        for it in items:
            line = f"[{ICONS.get(it.get('severity'), 'Nota')}] {it.get('message', '')}"
            if it.get("suggestion"):
                line += f" Sugestão: {it['suggestion']}"
            lines.append(line)
        comment = Comment("\n".join(lines)[:30000], "Tsiino Validator")
        comment.width = 360
        comment.height = min(60 + 40 * len(lines), 400)
        cell.comment = comment

    if row_offset is not None:
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1).coordinate

    if REPORT_SHEET in wb.sheetnames:
        del wb[REPORT_SHEET]
    rep = wb.create_sheet(REPORT_SHEET)  # no fim: a planilha anotada pode ser revalidada sem ajustes
    s = job["summary"]
    rep.append(["Resumo da validação Tsiino"])
    rep["A1"].font = Font(bold=True, size=13)
    rep.append(["Arquivo", job.get("filename")])
    rep.append(["Aba", job.get("sheet_name")])
    rep.append(["Linhas", s.get("total_rows")])
    rep.append(["Erros", s.get("error_count")])
    rep.append(["Alertas", s.get("warning_count")])
    rep.append(["Notas", s.get("info_count")])
    rep.append([])
    rep.append(["Linha", "Campo", "Tipo", "Código", "Mensagem", "Valor", "Sugestão", "Fonte"])
    for c in rep[rep.max_row]:
        c.font = Font(bold=True)
    for item in job["issues"]:
        col = item.get("column_name")
        rep.append([item.get("row_number"), f"{col} ({FIELD_LABELS[col]})" if col in FIELD_LABELS else col,
                    ICONS.get(item.get("severity"), item.get("severity")), item.get("code"), item.get("message"),
                    item.get("value"), item.get("suggestion"), item.get("source")])
        rep.cell(row=rep.max_row, column=3).fill = FILLS.get(item.get("severity"), FILLS["info"])
    for letter, width in zip("ABCDEFGH", (8, 26, 10, 30, 70, 26, 34, 30)):
        rep.column_dimensions[letter].width = width
    for row in rep.iter_rows(min_row=10):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    rep.freeze_panes = "A10"
    rep.auto_filter.ref = f"A9:H{max(rep.max_row, 9)}"

    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out
