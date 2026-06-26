"""Importa o Darwin Core Archive da Flora e Funga do Brasil para PostgreSQL.

Uso local:
    python backend/scripts/import_ffb_dwca.py --dwca data/ffb.zip

Uso com download:
    python backend/scripts/import_ffb_dwca.py --url "https://ipt.jbrj.gov.br/jbrj/archive.do?r=lista_especies_flora_brasil"

Observação: confirme o nome dos arquivos dentro do DwC-A antes de rodar em produção.
Normalmente o core é Taxon e há extensões como Distribution/VernacularName.
"""

from __future__ import annotations

import argparse
import csv
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import get_settings

TAXON_COLUMNS = {
    'taxonID': 'taxon_id',
    'parentNameUsageID': 'parent_name_usage_id',
    'acceptedNameUsageID': 'accepted_name_usage_id',
    'scientificName': 'scientific_name',
    'canonicalName': 'canonical_name',
    'scientificNameAuthorship': 'scientific_name_authorship',
    'kingdom': 'kingdom',
    'phylum': 'phylum',
    'class': 'class_name',
    'order': 'order_name',
    'family': 'family',
    'genus': 'genus',
    'specificEpithet': 'specific_epithet',
    'infraspecificEpithet': 'infraspecific_epithet',
    'taxonRank': 'taxon_rank',
    'taxonomicStatus': 'taxonomic_status',
    'nomenclaturalStatus': 'nomenclatural_status',
    'nameAccordingTo': 'name_according_to',
}


def download(url: str, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, output)
    return output


def find_table(extract_dir: Path, candidates: list[str]) -> Path:
    names = {item.lower() for item in candidates}
    for path in extract_dir.rglob('*'):
        if path.is_file() and path.name.lower() in names:
            return path
    raise FileNotFoundError(f'Nenhuma tabela encontrada entre: {candidates}')


def read_tsv(path: Path):
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        yield from csv.DictReader(handle, delimiter='\t')


def import_taxon(db: Session, path: Path, source_version: str | None = None) -> int:
    db.execute(text('TRUNCATE ffb_distribution, ffb_taxon RESTART IDENTITY CASCADE'))
    total = 0
    for row in read_tsv(path):
        mapped = {db_col: row.get(dwca_col) for dwca_col, db_col in TAXON_COLUMNS.items()}
        mapped['source_version'] = source_version
        if not mapped.get('taxon_id'):
            continue
        db.execute(text("""
            INSERT INTO ffb_taxon (
              taxon_id, parent_name_usage_id, accepted_name_usage_id, scientific_name, canonical_name,
              scientific_name_authorship, kingdom, phylum, class_name, order_name, family, genus,
              specific_epithet, infraspecific_epithet, taxon_rank, taxonomic_status,
              nomenclatural_status, name_according_to, source_version
            ) VALUES (
              :taxon_id, :parent_name_usage_id, :accepted_name_usage_id, :scientific_name, :canonical_name,
              :scientific_name_authorship, :kingdom, :phylum, :class_name, :order_name, :family, :genus,
              :specific_epithet, :infraspecific_epithet, :taxon_rank, :taxonomic_status,
              :nomenclatural_status, :name_according_to, :source_version
            ) ON CONFLICT (taxon_id) DO UPDATE SET
              scientific_name = EXCLUDED.scientific_name,
              canonical_name = EXCLUDED.canonical_name,
              family = EXCLUDED.family,
              genus = EXCLUDED.genus,
              specific_epithet = EXCLUDED.specific_epithet,
              taxonomic_status = EXCLUDED.taxonomic_status,
              accepted_name_usage_id = EXCLUDED.accepted_name_usage_id
        """), mapped)
        total += 1
        if total % 5000 == 0:
            db.commit()
    db.commit()
    return total


def import_distribution(db: Session, path: Path) -> int:
    total = 0
    for row in read_tsv(path):
        taxon_id = row.get('coreid') or row.get('taxonID') or row.get('id')
        if not taxon_id:
            continue
        db.execute(text("""
            INSERT INTO ffb_distribution (
              taxon_id, location_id, locality, state_province, establishment_means,
              occurrence_status, raw
            ) VALUES (
              :taxon_id, :location_id, :locality, :state_province, :establishment_means,
              :occurrence_status, '{}'::jsonb
            )
        """), {
            'taxon_id': taxon_id,
            'location_id': row.get('locationID'),
            'locality': row.get('locality'),
            'state_province': row.get('stateProvince'),
            'establishment_means': row.get('establishmentMeans'),
            'occurrence_status': row.get('occurrenceStatus'),
        })
        total += 1
        if total % 5000 == 0:
            db.commit()
    db.commit()
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dwca', type=Path)
    parser.add_argument('--url')
    parser.add_argument('--source-version')
    args = parser.parse_args()

    if not args.dwca and not args.url:
        raise SystemExit('Informe --dwca ou --url')

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        archive = args.dwca or download(args.url, tmpdir / 'ffb_dwca.zip')
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(tmpdir / 'dwca')
        extract_dir = tmpdir / 'dwca'
        taxon_path = find_table(extract_dir, ['taxon.txt', 'Taxon.txt'])
        dist_path = None
        try:
            dist_path = find_table(extract_dir, ['distribution.txt', 'Distribution.txt'])
        except FileNotFoundError:
            pass

        engine = create_engine(get_settings().database_url)
        with Session(engine) as db:
            taxon_total = import_taxon(db, taxon_path, args.source_version)
            dist_total = import_distribution(db, dist_path) if dist_path else 0
        print(f'Importados {taxon_total} táxons e {dist_total} distribuições.')


if __name__ == '__main__':
    main()
