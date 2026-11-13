"""Pipeline completo de validação de uma planilha (usado por /upload e /validate_mapped)."""
from __future__ import annotations

import time
import uuid
from typing import Any

from app.config import settings
from app.services import geography_ibge_sqlite as geo
from app.services import taxonomy_ffb_sqlite as tax
from app.services.issue_postprocess import postprocess_issues
from app.services.job_store import JOBS
from app.services.rule_engine import validate_basic_row, validate_duplicates, validate_structure
from app.services.spreadsheet_reader import parse_xlsx, public_record


class ReferenceNotReady(RuntimeError):
    pass


def ensure_references(validate_taxonomy: bool, validate_geography: bool) -> None:
    if validate_taxonomy and tax.reference_status().get("status") != "ready":
        raise ReferenceNotReady("A base da Flora e Funga do Brasil não está disponível no servidor.")
    if validate_geography and geo.reference_status().get("status") != "ready":
        raise ReferenceNotReady("A base geográfica do IBGE não está disponível no servidor.")


def run_validation(content: bytes, filename: str, *, sheet_name: str | None = None,
                   validate_taxonomy: bool = True, validate_geography: bool = True,
                   converted_from: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    ensure_references(validate_taxonomy, validate_geography)
    parsed = parse_xlsx(content, sheet_name=sheet_name, max_rows=settings.max_rows)
    header = parsed.header

    issues = list(validate_structure(parsed.records, header.missing_minimum, header.unknown_headers,
                                     truncated=parsed.sheet.truncated, max_rows=settings.max_rows))
    issues.extend(validate_duplicates(parsed.records))
    for record in parsed.records:
        issues.extend(validate_basic_row(record))
        uf = geo.resolve_uf(record) if (validate_taxonomy or validate_geography) and geo.REFERENCE.available() else None
        if validate_taxonomy:
            issues.extend(tax.validate_taxonomy_ffb(record, uf_sigla=uf))
        if validate_geography:
            issues.extend(geo.validate_geography_ibge(record))

    issue_dicts = postprocess_issues(issues)
    counts = {sev: sum(1 for i in issue_dicts if i["severity"] == sev) for sev in ("error", "warning", "info")}
    rows_with_error = {i["row_number"] for i in issue_dicts if i["severity"] == "error" and i["row_number"]}
    job_id = str(uuid.uuid4())
    table = [public_record(r) for r in parsed.records]
    summary = {
        "id": job_id,
        "job_id": job_id,
        "status": "finished",
        "filename": filename,
        "sheet_name": parsed.sheet.sheet_name,
        "sheet_names": parsed.sheet.sheet_names,
        "header_row": header.header_row,
        "is_standard": header.is_standard,
        "converted_from": converted_from,
        "total_rows": len(parsed.records),
        "rows_with_errors": len(rows_with_error),
        "error_count": counts["error"],
        "warning_count": counts["warning"],
        "info_count": counts["info"],
        "validate_taxonomy": validate_taxonomy,
        "validate_geography": validate_geography,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    JOBS.put(job_id, {
        "summary": summary,
        "issues": issue_dicts,
        "table": table,
        "file_bytes": content,
        "filename": filename,
        "sheet_name": parsed.sheet.sheet_name,
        "header_row": header.header_row,
        "mapping": header.mapping,
        "field_to_header": header.field_to_header,
        "raw_headers": header.raw_headers,
    })
    return {
        "job_id": job_id,
        "status_url": f"/api/validator/jobs/{job_id}",
        "summary": summary,
        "issues": issue_dicts,
        "table": table,
        "header": {
            "row": header.header_row,
            "columns": [h for h in header.raw_headers if h],
            "mapping": header.mapping,
            "field_to_header": header.field_to_header,
        },
    }


def warm_up() -> None:
    """Carrega índices em memória ao iniciar o servidor (reduz a latência da primeira validação)."""
    for ref in (tax.REFERENCE, geo.REFERENCE):
        try:
            if ref.available():
                ref.load()
        except Exception as exc:  # pragma: no cover
            print(f"AVISO: falha ao pré-carregar {ref.__class__.__name__}: {exc}")
