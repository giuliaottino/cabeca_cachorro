from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.issues import ValidationIssue
from app.services.rule_engine import issue


class TaxonomyService:
    def __init__(self, db: Session):
        self.db = db

    def validate_record(self, record: dict[str, Any]) -> list[ValidationIssue]:
        row = record['_row_number']
        family = record.get('family')
        genus = record.get('genus')
        sp1 = record.get('sp1')
        issues: list[ValidationIssue] = []

        if not genus:
            return issues

        genus_match = self.db.execute(
            text("""
                SELECT taxon_id, family, genus, taxonomic_status
                FROM ffb_taxon
                WHERE lower(unaccent(genus)) = lower(unaccent(:genus))
                LIMIT 1
            """),
            {'genus': genus},
        ).mappings().first()

        if not genus_match:
            suggestions = self.suggest_name(str(genus), limit=3)
            issues.append(issue(
                row, 'genus', 'error', 'GENUS_NOT_FOUND_FFB',
                'Gênero não encontrado na Flora e Funga do Brasil.', genus,
                suggestion=', '.join(suggestions) if suggestions else None,
                source='Flora e Funga do Brasil'
            ))
            return issues

        if family and genus_match['family'] and str(family).strip().lower() != str(genus_match['family']).strip().lower():
            issues.append(issue(
                row, 'family', 'warning', 'FAMILY_GENUS_MISMATCH',
                f'Família informada não coincide com a família do gênero na base local ({genus_match["family"]}).',
                family, suggestion=str(genus_match['family']), source='Flora e Funga do Brasil'
            ))

        if not sp1:
            return issues

        taxon = self.db.execute(
            text("""
                SELECT taxon_id, scientific_name, canonical_name, family, genus, specific_epithet,
                       taxonomic_status, accepted_name_usage_id, scientific_name_authorship
                FROM ffb_taxon
                WHERE lower(unaccent(genus)) = lower(unaccent(:genus))
                  AND lower(unaccent(specific_epithet)) = lower(unaccent(:sp1))
                ORDER BY CASE WHEN taxonomic_status ILIKE 'accepted' THEN 0 ELSE 1 END
                LIMIT 1
            """),
            {'genus': genus, 'sp1': sp1},
        ).mappings().first()

        if not taxon:
            suggestions = self.suggest_name(f'{genus} {sp1}', limit=5)
            issues.append(issue(
                row, 'sp1', 'error', 'SPECIES_NOT_FOUND_FFB',
                'Espécie não encontrada na Flora e Funga do Brasil.', f'{genus} {sp1}',
                suggestion=', '.join(suggestions) if suggestions else None,
                source='Flora e Funga do Brasil'
            ))
            return issues

        status = str(taxon.get('taxonomic_status') or '').lower()
        if status and 'accepted' not in status and taxon.get('accepted_name_usage_id'):
            accepted = self.get_taxon(taxon['accepted_name_usage_id'])
            suggestion = accepted.get('scientific_name') if accepted else None
            issues.append(issue(
                row, 'sp1', 'warning', 'TAXON_NOT_ACCEPTED',
                'Nome encontrado, mas não está marcado como nome aceito.',
                taxon.get('scientific_name'), suggestion=suggestion,
                source='Flora e Funga do Brasil'
            ))
        return issues

    def get_taxon(self, taxon_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            text('SELECT * FROM ffb_taxon WHERE taxon_id = :taxon_id'),
            {'taxon_id': taxon_id},
        ).mappings().first()
        return dict(row) if row else None

    def suggest_name(self, name: str, limit: int = 5) -> list[str]:
        rows = self.db.execute(
            text("""
                SELECT scientific_name, similarity(lower(unaccent(scientific_name)), lower(unaccent(:name))) AS score
                FROM ffb_taxon
                WHERE lower(unaccent(scientific_name)) % lower(unaccent(:name))
                ORDER BY score DESC
                LIMIT :limit
            """),
            {'name': name, 'limit': limit},
        ).mappings().all()
        return [str(row['scientific_name']) for row in rows if row.get('scientific_name')]
