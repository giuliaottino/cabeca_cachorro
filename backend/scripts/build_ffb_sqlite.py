"""Build a fast local SQLite reference database from the Flora e Funga do Brasil DwC-A.

Examples, from the repository root:

    cd backend
    python scripts/build_ffb_sqlite.py --download

Or using a local DwC-A archive:

    cd backend
    python scripts/build_ffb_sqlite.py --dwca C:\\path\\to\\ffb.zip

The resulting database is written to backend/reference/tsiino_reference.sqlite by default.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import tempfile
import unicodedata
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_FFB_DWCA_URL = "https://ipt.jbrj.gov.br/jbrj/archive.do?r=lista_especies_flora_brasil"

TAXON_COLUMNS = [
    "taxonID",
    "parentNameUsageID",
    "acceptedNameUsageID",
    "scientificName",
    "canonicalName",
    "scientificNameAuthorship",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "specificEpithet",
    "infraspecificEpithet",
    "taxonRank",
    "taxonomicStatus",
    "nomenclaturalStatus",
    "nameAccordingTo",
]


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_key(value: Any) -> str:
    return normalize_text(value).replace(" ", "")


def first_nonempty(*values: Any) -> str | None:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def find_table(extract_dir: Path, candidates: list[str]) -> Path:
    names = {item.lower() for item in candidates}
    for path in extract_dir.rglob("*"):
        if path.is_file() and path.name.lower() in names:
            return path
    raise FileNotFoundError(f"Nenhuma tabela encontrada entre: {candidates}")


def sniff_delimiter(path: Path) -> str:
    sample = path.read_text(encoding="utf-8-sig", errors="replace")[:4096]
    if "\t" in sample:
        return "\t"
    if ";" in sample and sample.count(";") > sample.count(","):
        return ";"
    return ","


def read_table(path: Path):
    delimiter = sniff_delimiter(path)
    with path.open("r", encoding="utf-8-sig", newline="", errors="replace") as handle:
        yield from csv.DictReader(handle, delimiter=delimiter)


def download(url: str, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"Baixando DwC-A: {url}")
    urllib.request.urlretrieve(url, output)
    return output


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_from_row(row: dict[str, str | None]) -> str | None:
    canonical = first_nonempty(row.get("canonicalName"))
    if canonical:
        return canonical
    genus = first_nonempty(row.get("genus"))
    epithet = first_nonempty(row.get("specificEpithet"))
    infra = first_nonempty(row.get("infraspecificEpithet"))
    if genus and epithet and infra:
        return f"{genus} {epithet} {infra}"
    if genus and epithet:
        return f"{genus} {epithet}"
    return first_nonempty(row.get("scientificName"))


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous = NORMAL;
        PRAGMA temp_store = MEMORY;

        DROP TABLE IF EXISTS reference_metadata;
        DROP TABLE IF EXISTS ffb_distribution;
        DROP TABLE IF EXISTS ffb_name_index;
        DROP TABLE IF EXISTS ffb_taxon;

        CREATE TABLE reference_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE ffb_taxon (
            taxon_id TEXT PRIMARY KEY,
            parent_name_usage_id TEXT,
            accepted_name_usage_id TEXT,
            accepted_taxon_id TEXT,
            scientific_name TEXT,
            canonical_name TEXT,
            scientific_name_authorship TEXT,
            kingdom TEXT,
            phylum TEXT,
            class_name TEXT,
            order_name TEXT,
            family TEXT,
            genus TEXT,
            specific_epithet TEXT,
            infraspecific_epithet TEXT,
            taxon_rank TEXT,
            taxonomic_status TEXT,
            nomenclatural_status TEXT,
            name_according_to TEXT,
            accepted_scientific_name TEXT,
            accepted_canonical_name TEXT,
            accepted_family TEXT,
            accepted_genus TEXT,
            accepted_specific_epithet TEXT,
            norm_scientific_name TEXT,
            norm_canonical_name TEXT,
            norm_family TEXT,
            norm_genus TEXT,
            norm_binomial TEXT,
            source_version TEXT
        );

        CREATE TABLE ffb_name_index (
            normalized_key TEXT NOT NULL,
            index_kind TEXT NOT NULL,
            taxon_id TEXT NOT NULL,
            accepted_taxon_id TEXT,
            scientific_name TEXT,
            canonical_name TEXT,
            family TEXT,
            genus TEXT,
            specific_epithet TEXT,
            taxon_rank TEXT,
            taxonomic_status TEXT,
            accepted_scientific_name TEXT,
            accepted_canonical_name TEXT,
            accepted_family TEXT,
            accepted_genus TEXT,
            norm_genus TEXT,
            source_version TEXT
        );

        CREATE TABLE ffb_distribution (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            taxon_id TEXT,
            location_id TEXT,
            locality TEXT,
            state_province TEXT,
            establishment_means TEXT,
            occurrence_status TEXT,
            raw_json TEXT
        );

        CREATE INDEX idx_ffb_taxon_norm_binomial ON ffb_taxon(norm_binomial);
        CREATE INDEX idx_ffb_taxon_norm_genus ON ffb_taxon(norm_genus);
        CREATE INDEX idx_ffb_taxon_accepted ON ffb_taxon(accepted_taxon_id);
        CREATE INDEX idx_ffb_name_key_kind ON ffb_name_index(normalized_key, index_kind);
        CREATE INDEX idx_ffb_name_genus ON ffb_name_index(norm_genus);
        CREATE INDEX idx_ffb_name_taxon ON ffb_name_index(taxon_id);
        CREATE INDEX idx_ffb_dist_taxon ON ffb_distribution(taxon_id);
        CREATE INDEX idx_ffb_dist_state ON ffb_distribution(state_province);
        """
    )


def build_database(dwca_path: Path, sqlite_path: Path, source_url: str | None, source_version: str | None) -> None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="tsiino_ffb_dwca_") as tmp:
        tmpdir = Path(tmp)
        extract_dir = tmpdir / "dwca"
        print(f"Extraindo: {dwca_path}")
        with zipfile.ZipFile(dwca_path) as zf:
            zf.extractall(extract_dir)

        taxon_path = find_table(extract_dir, ["taxon.txt", "Taxon.txt"])
        try:
            dist_path = find_table(extract_dir, ["distribution.txt", "Distribution.txt"])
        except FileNotFoundError:
            dist_path = None

        print(f"Taxon: {taxon_path.name}")
        if dist_path:
            print(f"Distribution: {dist_path.name}")
        else:
            print("Distribution: não encontrada")

        rows: list[dict[str, Any]] = []
        for raw in read_table(taxon_path):
            taxon_id = first_nonempty(raw.get("taxonID"), raw.get("id"), raw.get("coreid"))
            if not taxon_id:
                continue
            row = {col: first_nonempty(raw.get(col)) for col in TAXON_COLUMNS}
            row["taxonID"] = taxon_id
            row["canonicalName"] = canonical_from_row(row)
            rows.append(row)

        by_id = {str(row["taxonID"]): row for row in rows}

        def accepted_id_for(row: dict[str, Any]) -> str:
            accepted = first_nonempty(row.get("acceptedNameUsageID"))
            if accepted and accepted in by_id:
                return accepted
            return str(row["taxonID"])

        records: list[tuple[Any, ...]] = []
        index_records: list[tuple[Any, ...]] = []

        for row in rows:
            taxon_id = str(row["taxonID"])
            accepted_taxon_id = accepted_id_for(row)
            accepted = by_id.get(accepted_taxon_id, row)

            scientific = first_nonempty(row.get("scientificName"))
            canonical = first_nonempty(row.get("canonicalName"), scientific)
            family = first_nonempty(row.get("family"))
            genus = first_nonempty(row.get("genus"))
            epithet = first_nonempty(row.get("specificEpithet"))
            binomial = f"{genus} {epithet}" if genus and epithet else canonical

            accepted_scientific = first_nonempty(accepted.get("scientificName"), accepted.get("canonicalName"))
            accepted_canonical = first_nonempty(accepted.get("canonicalName"), accepted_scientific)
            accepted_family = first_nonempty(accepted.get("family"), family)
            accepted_genus = first_nonempty(accepted.get("genus"), genus)
            accepted_epithet = first_nonempty(accepted.get("specificEpithet"), epithet)

            norm_scientific = normalize_text(scientific)
            norm_canonical = normalize_text(canonical)
            norm_family = normalize_text(family)
            norm_genus = normalize_text(genus)
            norm_binomial = normalize_text(binomial)

            records.append(
                (
                    taxon_id,
                    row.get("parentNameUsageID"),
                    row.get("acceptedNameUsageID"),
                    accepted_taxon_id,
                    scientific,
                    canonical,
                    row.get("scientificNameAuthorship"),
                    row.get("kingdom"),
                    row.get("phylum"),
                    row.get("class"),
                    row.get("order"),
                    family,
                    genus,
                    epithet,
                    row.get("infraspecificEpithet"),
                    row.get("taxonRank"),
                    row.get("taxonomicStatus"),
                    row.get("nomenclaturalStatus"),
                    row.get("nameAccordingTo"),
                    accepted_scientific,
                    accepted_canonical,
                    accepted_family,
                    accepted_genus,
                    accepted_epithet,
                    norm_scientific,
                    norm_canonical,
                    norm_family,
                    norm_genus,
                    norm_binomial,
                    source_version,
                )
            )

            keys: list[tuple[str, str]] = []
            if norm_scientific:
                keys.append((norm_scientific, "scientific"))
            if norm_canonical and norm_canonical != norm_scientific:
                keys.append((norm_canonical, "canonical"))
            if norm_binomial and norm_binomial not in {norm_scientific, norm_canonical}:
                keys.append((norm_binomial, "binomial"))
            if norm_genus:
                keys.append((norm_genus, "genus"))

            seen = set()
            for normalized_key, kind in keys:
                key = (normalized_key, kind, taxon_id)
                if key in seen:
                    continue
                seen.add(key)
                index_records.append(
                    (
                        normalized_key,
                        kind,
                        taxon_id,
                        accepted_taxon_id,
                        scientific,
                        canonical,
                        family,
                        genus,
                        epithet,
                        row.get("taxonRank"),
                        row.get("taxonomicStatus"),
                        accepted_scientific,
                        accepted_canonical,
                        accepted_family,
                        accepted_genus,
                        norm_genus,
                        source_version,
                    )
                )

        if sqlite_path.exists():
            sqlite_path.unlink()

        conn = sqlite3.connect(sqlite_path)
        try:
            create_schema(conn)
            conn.executemany(
                """
                INSERT INTO ffb_taxon (
                    taxon_id, parent_name_usage_id, accepted_name_usage_id, accepted_taxon_id,
                    scientific_name, canonical_name, scientific_name_authorship, kingdom, phylum,
                    class_name, order_name, family, genus, specific_epithet, infraspecific_epithet,
                    taxon_rank, taxonomic_status, nomenclatural_status, name_according_to,
                    accepted_scientific_name, accepted_canonical_name, accepted_family, accepted_genus,
                    accepted_specific_epithet, norm_scientific_name, norm_canonical_name, norm_family,
                    norm_genus, norm_binomial, source_version
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                records,
            )
            conn.executemany(
                """
                INSERT INTO ffb_name_index (
                    normalized_key, index_kind, taxon_id, accepted_taxon_id, scientific_name,
                    canonical_name, family, genus, specific_epithet, taxon_rank, taxonomic_status,
                    accepted_scientific_name, accepted_canonical_name, accepted_family, accepted_genus,
                    norm_genus, source_version
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                index_records,
            )

            dist_total = 0
            if dist_path:
                batch: list[tuple[Any, ...]] = []
                for raw in read_table(dist_path):
                    taxon_id = first_nonempty(raw.get("coreid"), raw.get("taxonID"), raw.get("id"))
                    if not taxon_id:
                        continue
                    batch.append(
                        (
                            taxon_id,
                            first_nonempty(raw.get("locationID")),
                            first_nonempty(raw.get("locality")),
                            first_nonempty(raw.get("stateProvince")),
                            first_nonempty(raw.get("establishmentMeans")),
                            first_nonempty(raw.get("occurrenceStatus")),
                            json.dumps(raw, ensure_ascii=False),
                        )
                    )
                    if len(batch) >= 10000:
                        conn.executemany(
                            """INSERT INTO ffb_distribution
                            (taxon_id, location_id, locality, state_province, establishment_means, occurrence_status, raw_json)
                            VALUES (?,?,?,?,?,?,?)""",
                            batch,
                        )
                        dist_total += len(batch)
                        batch.clear()
                if batch:
                    conn.executemany(
                        """INSERT INTO ffb_distribution
                        (taxon_id, location_id, locality, state_province, establishment_means, occurrence_status, raw_json)
                        VALUES (?,?,?,?,?,?,?)""",
                        batch,
                    )
                    dist_total += len(batch)

            metadata = {
                "source_name": "Flora e Funga do Brasil - Lista Oficial",
                "source_url": source_url or "local_dwca",
                "source_version": source_version or "unspecified",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "dwca_sha256": sha256_file(dwca_path),
                "taxon_count": str(len(records)),
                "name_index_count": str(len(index_records)),
                "distribution_count": str(dist_total),
                "builder": "backend/scripts/build_ffb_sqlite.py",
            }
            conn.executemany(
                "INSERT INTO reference_metadata(key, value) VALUES (?, ?)",
                list(metadata.items()),
            )
            conn.commit()
            conn.execute("VACUUM")
        finally:
            conn.close()

    print(f"SQLite criado: {sqlite_path}")
    print(f"Táxons: {len(records)}")
    print(f"Índices de nomes: {len(index_records)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dwca", type=Path, help="Arquivo DwC-A local, .zip")
    parser.add_argument("--download", action="store_true", help="Baixar DwC-A do IPT/JBRJ")
    parser.add_argument("--url", default=DEFAULT_FFB_DWCA_URL)
    parser.add_argument("--output", type=Path, default=Path("reference") / "tsiino_reference.sqlite")
    parser.add_argument("--source-version", default=None)
    args = parser.parse_args()

    if args.dwca:
        dwca = args.dwca
        source_url = None
    elif args.download:
        tmp_download = Path("reference") / "downloads" / "ffb_dwca.zip"
        dwca = download(args.url, tmp_download)
        source_url = args.url
    else:
        raise SystemExit("Use --download ou --dwca CAMINHO_DO_ZIP")

    if not dwca.exists():
        raise SystemExit(f"Arquivo DwC-A não encontrado: {dwca}")

    build_database(dwca, args.output, source_url=source_url, source_version=args.source_version)


if __name__ == "__main__":
    main()
