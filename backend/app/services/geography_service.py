from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.issues import ValidationIssue
from app.services.rule_engine import issue


class GeographyService:
    def __init__(self, db: Session):
        self.db = db

    def validate_record(self, record: dict[str, Any]) -> list[ValidationIssue]:
        row = record['_row_number']
        lat = record.get('lat')
        lon = record.get('long')
        majorarea = record.get('majorarea')
        minorarea = record.get('minorarea')
        issues: list[ValidationIssue] = []

        if lat is None or lon is None:
            return issues

        if majorarea:
            state = self.db.execute(
                text("""
                    SELECT name, abbrev,
                           ST_Contains(geom, ST_SetSRID(ST_Point(:lon, :lat), 4326)) AS inside
                    FROM br_state
                    WHERE lower(unaccent(name)) = lower(unaccent(:majorarea))
                       OR upper(abbrev) = upper(:majorarea)
                    LIMIT 1
                """),
                {'lat': lat, 'lon': lon, 'majorarea': majorarea},
            ).mappings().first()
            if not state:
                issues.append(issue(row, 'majorarea', 'warning', 'STATE_NOT_FOUND', 'Estado/área maior não encontrado na base geográfica local.', majorarea, source='PostGIS'))
            elif not state['inside']:
                issues.append(issue(row, 'lat', 'error', 'POINT_OUTSIDE_STATE', f'Coordenada não cai dentro do estado informado ({state["name"]}).', f'{lat}, {lon}', source='PostGIS'))

        if minorarea:
            municipality = self.db.execute(
                text("""
                    SELECT name, state_abbrev,
                           ST_Contains(geom, ST_SetSRID(ST_Point(:lon, :lat), 4326)) AS inside
                    FROM br_municipality
                    WHERE lower(unaccent(name)) = lower(unaccent(:minorarea))
                    ORDER BY CASE
                      WHEN :majorarea IS NOT NULL AND (upper(state_abbrev) = upper(:majorarea) OR lower(unaccent(state_name)) = lower(unaccent(:majorarea))) THEN 0
                      ELSE 1
                    END
                    LIMIT 1
                """),
                {'lat': lat, 'lon': lon, 'minorarea': minorarea, 'majorarea': majorarea},
            ).mappings().first()
            if not municipality:
                issues.append(issue(row, 'minorarea', 'warning', 'MUNICIPALITY_NOT_FOUND', 'Município/área menor não encontrado na base geográfica local.', minorarea, source='PostGIS'))
            elif not municipality['inside']:
                issues.append(issue(row, 'long', 'error', 'POINT_OUTSIDE_MUNICIPALITY', f'Coordenada não cai dentro do município informado ({municipality["name"]}).', f'{lat}, {lon}', source='PostGIS'))

        return issues
