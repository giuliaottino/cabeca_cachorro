import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.issues import ValidationIssue
from app.services.geography_service import GeographyService
from app.services.rule_engine import validate_basic_row, validate_structure
from app.services.spreadsheet_reader import parse_xlsx
from app.services.taxonomy_service import TaxonomyService


class JobService:
    def __init__(self, db: Session):
        self.db = db

    async def create_and_run(self, file: UploadFile, options: dict[str, Any]) -> str:
        job_id = str(uuid.uuid4())
        self.db.execute(
            text("""
                INSERT INTO validation_job (id, original_filename, status, options)
                VALUES (:id, :filename, 'running', CAST(:options AS jsonb))
            """),
            {'id': job_id, 'filename': file.filename or 'upload.xlsx', 'options': '{}'},
        )
        self.db.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / (file.filename or 'upload.xlsx')
            content = await file.read()
            path.write_bytes(content)
            parsed = parse_xlsx(path, sheet_name=options.get('sheet_name'))

        structure_issues = validate_structure(
            parsed.records,
            parsed.header.missing_minimum,
            parsed.header.unknown_headers,
        )

        taxonomy = TaxonomyService(self.db) if options.get('validate_taxonomy', True) else None
        geography = GeographyService(self.db) if options.get('validate_geography', True) else None

        all_issues: list[ValidationIssue] = list(structure_issues)
        specimen_ids: dict[int, int] = {}

        for record in parsed.records:
            specimen_id = self._insert_specimen(job_id, record)
            specimen_ids[record['_row_number']] = specimen_id
            all_issues.extend(validate_basic_row(record))
            if taxonomy:
                all_issues.extend(taxonomy.validate_record(record))
            if geography:
                all_issues.extend(geography.validate_record(record))

        for validation_issue in all_issues:
            specimen_id = specimen_ids.get(validation_issue.row_number or -1)
            self._insert_issue(job_id, specimen_id, validation_issue)

        error_count = sum(1 for item in all_issues if item.severity == 'error')
        warning_count = sum(1 for item in all_issues if item.severity == 'warning')
        self.db.execute(
            text("""
                UPDATE validation_job
                SET status = 'finished', total_rows = :total_rows, error_count = :error_count,
                    warning_count = :warning_count, finished_at = now()
                WHERE id = :id
            """),
            {'id': job_id, 'total_rows': len(parsed.records), 'error_count': error_count, 'warning_count': warning_count},
        )
        self.db.commit()
        return job_id

    def summary(self, job_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            text('SELECT id, status, total_rows, error_count, warning_count FROM validation_job WHERE id = :id'),
            {'id': job_id},
        ).mappings().first()
        return dict(row) if row else None

    def issues(self, job_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            text("""
                SELECT row_number, column_name, severity, code, message, value, suggestion, source, payload
                FROM validation_issue
                WHERE job_id = :job_id
                ORDER BY row_number NULLS FIRST, severity, column_name
            """),
            {'job_id': job_id},
        ).mappings().all()
        return [dict(row) for row in rows]

    def table(self, job_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            text("""
                SELECT id, row_number, raw, accession, collector, number, family, genus, sp1,
                       country, majorarea, minorarea, lat, long
                FROM uploaded_specimen
                WHERE job_id = :job_id
                ORDER BY row_number
            """),
            {'job_id': job_id},
        ).mappings().all()
        return [dict(row) for row in rows]

    def geojson(self, job_id: str) -> dict[str, Any]:
        rows = self.db.execute(
            text("""
                SELECT row_number, collector, number, family, genus, sp1, lat, long,
                       EXISTS (
                         SELECT 1 FROM validation_issue i
                         WHERE i.uploaded_specimen_id = s.id AND i.severity = 'error'
                       ) AS has_error
                FROM uploaded_specimen s
                WHERE s.job_id = :job_id AND s.lat IS NOT NULL AND s.long IS NOT NULL
                ORDER BY s.row_number
            """),
            {'job_id': job_id},
        ).mappings().all()
        features = []
        for row in rows:
            features.append({
                'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': [row['long'], row['lat']]},
                'properties': {k: row[k] for k in row.keys() if k not in {'lat', 'long'}},
            })
        return {'type': 'FeatureCollection', 'features': features}

    def _insert_specimen(self, job_id: str, record: dict[str, Any]) -> int:
        row = self.db.execute(
            text("""
                INSERT INTO uploaded_specimen (
                  job_id, row_number, raw, accession, collector, number, addcoll, colldd, collmm, collyy,
                  family, genus, sp1, author1, country, majorarea, minorarea, gazetteer, locnotes,
                  plantdesc, lat, long, geom
                ) VALUES (
                  :job_id, :row_number, CAST(:raw AS jsonb), :accession, :collector, :number, :addcoll, :colldd, :collmm, :collyy,
                  :family, :genus, :sp1, :author1, :country, :majorarea, :minorarea, :gazetteer, :locnotes,
                  :plantdesc, :lat, :long,
                  CASE WHEN :lat IS NOT NULL AND :long IS NOT NULL THEN ST_SetSRID(ST_Point(:long, :lat), 4326) ELSE NULL END
                ) RETURNING id
            """),
            {
                'job_id': job_id,
                'row_number': record['_row_number'],
                'raw': '{}',
                **{key: record.get(key) for key in [
                    'accession', 'collector', 'number', 'addcoll', 'colldd', 'collmm', 'collyy',
                    'family', 'genus', 'sp1', 'author1', 'country', 'majorarea', 'minorarea',
                    'gazetteer', 'locnotes', 'plantdesc', 'lat', 'long'
                ]},
            },
        ).scalar_one()
        return int(row)

    def _insert_issue(self, job_id: str, specimen_id: int | None, item: ValidationIssue) -> None:
        self.db.execute(
            text("""
                INSERT INTO validation_issue (
                  job_id, uploaded_specimen_id, row_number, column_name, severity, code,
                  message, value, suggestion, source, payload
                ) VALUES (
                  :job_id, :specimen_id, :row_number, :column_name, :severity, :code,
                  :message, :value, :suggestion, :source, CAST(:payload AS jsonb)
                )
            """),
            {
                'job_id': job_id,
                'specimen_id': specimen_id,
                'row_number': item.row_number,
                'column_name': item.column_name,
                'severity': item.severity,
                'code': item.code,
                'message': item.message,
                'value': item.value,
                'suggestion': item.suggestion,
                'source': item.source,
                'payload': '{}',
            },
        )
