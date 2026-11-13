"""Rotas do mapeador/conversor.

Os caminhos antigos (/preview_rows, /convert_tolerant, /convert_tolerant_v28) continuam respondendo
para que a versão anterior do site funcione até ser republicada.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app.routes.validator import XLSX, read_upload
from app.services.inpa_schema import detect_standard_header
from app.services.spreadsheet_converter import build_template_workbook, convert_spreadsheet, preview_spreadsheet
from app.services.spreadsheet_reader import read_sheet

router = APIRouter(prefix="/converter", tags=["converter"])


@router.get("/template")
def download_template() -> Response:
    return Response(build_template_workbook(), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="template_inpa_brahms.xlsx"'})


@router.post("/standard_check")
def standard_check(file: Annotated[UploadFile, File(...)],
                   sheet_name: Annotated[str | None, Form()] = None) -> dict[str, Any]:
    content = read_upload(file)
    try:
        sheet = read_sheet(content, sheet_name=sheet_name or None, max_rows=50)
    except ValueError as exc:
        return {"detected_standard": False, "is_standard": False, "error": str(exc)}
    det = detect_standard_header(sheet.rows)
    if det is None:
        return {"detected_standard": False, "is_standard": False, "sheet_name": sheet.sheet_name,
                "sheet_names": sheet.sheet_names}
    return {
        "detected_standard": True,
        "is_standard": True,
        "sheet_name": sheet.sheet_name,
        "sheet_names": sheet.sheet_names,
        "header_row": det.header_row,
        "mapped_fields": sorted(set(det.mapping.values())),
        "missing_minimum": det.missing_minimum,
    }


def _preview(file: UploadFile, sheet_name: str | None, max_rows: int) -> dict[str, Any]:
    content = read_upload(file)
    try:
        return preview_spreadsheet(content, sheet_name=sheet_name or None, max_rows=max_rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/preview")
def preview_converter(file: Annotated[UploadFile, File(...)],
                      sheet_name: Annotated[str | None, Form()] = None,
                      max_rows: Annotated[int, Form()] = 80) -> dict[str, Any]:
    return _preview(file, sheet_name, max_rows)


@router.post("/preview_rows")
def preview_rows(file: Annotated[UploadFile, File(...)],
                 sheet_name: Annotated[str | None, Form()] = None,
                 max_rows: Annotated[int, Form()] = 80) -> dict[str, Any]:
    """Compatibilidade com o mapeador antigo: source_columns como lista de nomes."""
    data = _preview(file, sheet_name, max_rows)
    data["source_columns_meta"] = data["source_columns"]
    data["source_columns"] = data["headers"]
    return data


async def _convert(request: Request, file: UploadFile) -> Response:
    form = await request.form()
    mapping = next((form.get(k) for k in ("mapping_json", "mapping", "column_mapping", "mappings") if form.get(k)), None)
    sheet_name = form.get("sheet_name") or form.get("sheet") or None
    include = str(form.get("include_recommendations") or form.get("include_recommendation_row") or "").lower() in {"true", "1", "on"}
    content = read_upload(file)
    try:
        from starlette.concurrency import run_in_threadpool
        out = await run_in_threadpool(convert_spreadsheet, content, mapping, sheet_name, include_recommendations=include)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível converter: {exc}") from exc
    base = (file.filename or "planilha").rsplit(".", 1)[0]
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in base)[:80] or "planilha"
    return Response(out, media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{safe}_convertida_INPA.xlsx"'})


@router.post("/convert")
async def convert(request: Request, file: Annotated[UploadFile, File(...)]) -> Response:
    return await _convert(request, file)


@router.post("/convert_tolerant", include_in_schema=False)
async def convert_tolerant(request: Request, file: Annotated[UploadFile, File(...)]) -> Response:
    return await _convert(request, file)


@router.post("/convert_tolerant_v28", include_in_schema=False)
async def convert_tolerant_v28(request: Request, file: Annotated[UploadFile, File(...)]) -> Response:
    return await _convert(request, file)
