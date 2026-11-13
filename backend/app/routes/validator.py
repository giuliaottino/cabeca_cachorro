"""Rotas de validação. Endpoints síncronos: o FastAPI os executa no threadpool, sem bloquear o loop."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.config import settings
from app.services import geography_ibge_sqlite as geo
from app.services import taxonomy_ffb_sqlite as tax
from app.services.annotate import annotated_workbook
from app.services.job_store import JOBS
from app.services.spreadsheet_converter import convert_spreadsheet
from app.services.validation import ReferenceNotReady, run_validation

router = APIRouter()
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def read_upload(file: UploadFile) -> bytes:
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Envie uma planilha .xlsx ou .xlsm (arquivos .xls/.csv devem ser salvos como .xlsx).")
    limit = settings.max_upload_mb * 1024 * 1024
    content = file.file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(status_code=413, detail=f"Arquivo maior que {settings.max_upload_mb} MB.")
    if not content:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")
    return content


def _validate(content: bytes, filename: str, **kwargs: Any) -> dict[str, Any]:
    try:
        return run_validation(content, filename, **kwargs)
    except ReferenceNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Erro ao ler a planilha: {exc}") from exc


def _job(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Resultado não encontrado ou expirado. Valide a planilha novamente.")
    return job


@router.get("/status")
def status() -> dict[str, Any]:
    return {
        "mode": "sqlite",
        "taxonomy": tax.reference_status(),
        "geography": geo.reference_status(),
        "limits": {"max_upload_mb": settings.max_upload_mb, "max_rows": settings.max_rows,
                   "job_ttl_hours": settings.job_ttl_hours},
        "jobs_in_memory": len(JOBS),
    }


@router.post("/upload")
def upload_spreadsheet(
    file: Annotated[UploadFile, File(...)],
    validate_taxonomy: Annotated[bool, Form()] = True,
    validate_geography: Annotated[bool, Form()] = True,
    sheet_name: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """Valida e devolve tudo de uma vez (resumo, ocorrências e tabela)."""
    content = read_upload(file)
    return _validate(content, file.filename or "planilha.xlsx", sheet_name=sheet_name or None,
                     validate_taxonomy=validate_taxonomy, validate_geography=validate_geography)


@router.post("/validate_mapped")
def validate_mapped(
    file: Annotated[UploadFile, File(...)],
    mapping: Annotated[str | None, Form()] = None,
    validate_taxonomy: Annotated[bool, Form()] = True,
    validate_geography: Annotated[bool, Form()] = True,
    sheet_name: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """Converte com o mapeamento informado e valida a versão convertida, numa só requisição."""
    content = read_upload(file)
    try:
        converted = convert_spreadsheet(content, mapping=mapping, sheet_name=sheet_name or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível converter: {exc}") from exc
    base = (file.filename or "planilha").rsplit(".", 1)[0]
    return _validate(converted, f"{base}_convertida_INPA.xlsx", sheet_name="Espécimes",
                     validate_taxonomy=validate_taxonomy, validate_geography=validate_geography,
                     converted_from=file.filename)


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    return _job(job_id)["summary"]


@router.get("/jobs/{job_id}/issues")
def get_issues(job_id: str) -> list[dict[str, Any]]:
    return _job(job_id)["issues"]


@router.get("/jobs/{job_id}/table")
def get_table(job_id: str) -> list[dict[str, Any]]:
    return _job(job_id)["table"]


@router.get("/jobs/{job_id}/download.xlsx")
def download_annotated(job_id: str) -> StreamingResponse:
    job = _job(job_id)
    output = annotated_workbook(job)
    base = str(job.get("filename") or "planilha").rsplit(".", 1)[0]
    ext = "xlsm" if str(job.get("filename", "")).lower().endswith(".xlsm") else "xlsx"
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in base)[:80] or "planilha"
    return StreamingResponse(
        output,
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{safe}_anotada_tsiino.{ext}"'},
    )


@router.get("/jobs/{job_id}/map.geojson")
def get_map(job_id: str) -> dict[str, Any]:
    job = _job(job_id)
    severity_by_row: dict[int, str] = {}
    for item in job["issues"]:
        row, sev = item.get("row_number"), item.get("severity")
        if row and (sev == "error" or (sev == "warning" and severity_by_row.get(row) != "error")):
            severity_by_row[row] = sev
    features = []
    for record in job["table"]:
        lat, lon = record.get("lat"), record.get("long")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        row = record.get("_row_number")
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "row_number": row,
                "collector": record.get("collector"),
                "number": record.get("number"),
                "family": record.get("family"),
                "genus": record.get("genus"),
                "sp1": record.get("sp1"),
                "minorarea": record.get("minorarea"),
                "severity": severity_by_row.get(row, "ok"),
                "has_error": severity_by_row.get(row) == "error",
            },
        })
    return {"type": "FeatureCollection", "features": features}
