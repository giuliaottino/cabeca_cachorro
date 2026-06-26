from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.services.job_service import JobService

router = APIRouter()
settings = get_settings()


@router.post('/upload')
async def upload_spreadsheet(
    file: Annotated[UploadFile, File(...)],
    validate_taxonomy: Annotated[bool, Form()] = True,
    validate_geography: Annotated[bool, Form()] = True,
    sheet_name: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not file.filename or not file.filename.lower().endswith(('.xlsx', '.xlsm')):
        raise HTTPException(status_code=400, detail='Envie uma planilha .xlsx ou .xlsm.')

    options = {
        'validate_taxonomy': validate_taxonomy,
        'validate_geography': validate_geography,
        'sheet_name': sheet_name or None,
    }
    job_id = await JobService(db).create_and_run(file, options)
    return {'job_id': job_id, 'status_url': f'/api/validator/jobs/{job_id}'}


@router.get('/jobs/{job_id}')
def get_job(job_id: str, db: Session = Depends(get_db)) -> dict:
    summary = JobService(db).summary(job_id)
    if not summary:
        raise HTTPException(status_code=404, detail='Job não encontrado.')
    return summary


@router.get('/jobs/{job_id}/issues')
def get_issues(job_id: str, db: Session = Depends(get_db)) -> list[dict]:
    return JobService(db).issues(job_id)


@router.get('/jobs/{job_id}/table')
def get_table(job_id: str, db: Session = Depends(get_db)) -> list[dict]:
    return JobService(db).table(job_id)


@router.get('/jobs/{job_id}/map.geojson')
def get_map(job_id: str, db: Session = Depends(get_db)) -> dict:
    return JobService(db).geojson(job_id)
