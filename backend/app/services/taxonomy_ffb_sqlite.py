from __future__ import annotations

import difflib
import os
import re
import sqlite3
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.schemas.issues import ValidationIssue
from app.services.rule_engine import issue

SOURCE = "Flora e Funga do Brasil - Lista Oficial (IPT/JBRJ DwC-A; SQLite local)"


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def reference_db_path() -> Path:
    env = os.environ.get("TSIINO_REFERENCE_DB")
    if env:
        return Path(env)
    return _backend_dir() / "reference" / "tsiino_reference.sqlite"


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _connect() -> sqlite3.Connection:
    path = reference_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@lru_cache(maxsize=1)
def _db_available() -> bool:
    path = reference_db_path()
    return path.exists() and path.is_file()


@lru_cache(maxsize=1)
def reference_status() -> dict[str, Any]:
    path = reference_db_path()
    if not path.exists():
        return {
            "mode": "ffb_sqlite",
            "status": "missing_reference_db",
            "path": str(path),
            "message": "Banco SQLite da Flora e Funga ainda não foi construído.",
        }
    try:
        with _connect() as conn:
            rows = conn.execute("SELECT key, value FROM reference_metadata").fetchall()
            meta = {row["key"]: row["value"] for row in rows}
            taxon_count = conn.execute("SELECT COUNT(*) AS n FROM ffb_taxon").fetchone()["n"]
            index_count = conn.execute("SELECT COUNT(*) AS n FROM ffb_name_index").fetchone()["n"]
    except Exception as exc:
        return {
            "mode": "ffb_sqlite",
            "status": "error",
            "path": str(path),
            "error": str(exc),
        }
    return {
        "mode": "ffb_sqlite",
        "status": "ready",
        "path": str(path),
        "source": meta.get("source_name", "Flora e Funga do Brasil"),
        "source_url": meta.get("source_url"),
        "source_version": meta.get("source_version"),
        "created_at_utc": meta.get("created_at_utc"),
        "taxon_count": int(taxon_count),
        "name_index_count": int(index_count),
        "distribution_count": int(meta.get("distribution_count", "0") or 0),
    }


def _fetch_one_by_key(conn: sqlite3.Connection, normalized_key: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM ffb_name_index
        WHERE normalized_key = ?
          AND index_kind IN ('binomial', 'canonical', 'scientific')
        ORDER BY
          CASE lower(coalesce(taxonomic_status, ''))
            WHEN 'accepted' THEN 0
            WHEN 'aceito' THEN 0
            WHEN 'sinônimo' THEN 2
            WHEN 'synonym' THEN 2
            ELSE 1
          END,
          index_kind
        LIMIT 1
        """,
        (normalized_key,),
    ).fetchone()


def _genus_rows(conn: sqlite3.Connection, norm_genus: str, limit: int = 25) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT DISTINCT accepted_scientific_name, accepted_family, accepted_genus, scientific_name,
                        taxonomic_status, family, genus
        FROM ffb_name_index
        WHERE norm_genus = ?
          AND index_kind IN ('binomial', 'canonical', 'scientific')
        LIMIT ?
        """,
        (norm_genus, limit),
    ).fetchall()


def _genus_exists(conn: sqlite3.Connection, norm_genus: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM ffb_name_index
        WHERE normalized_key = ? AND index_kind = 'genus'
        LIMIT 1
        """,
        (norm_genus,),
    ).fetchone()


def _genus_suggestions(conn: sqlite3.Connection, norm_genus: str, limit: int = 6) -> str | None:
    if not norm_genus:
        return None
    prefix = norm_genus[:4] if len(norm_genus) >= 4 else norm_genus[:2]
    candidates = [
        row["accepted_genus"] or row["genus"] or row["normalized_key"]
        for row in conn.execute(
            """
            SELECT DISTINCT normalized_key, accepted_genus, genus
            FROM ffb_name_index
            WHERE index_kind = 'genus' AND normalized_key LIKE ?
            LIMIT 200
            """,
            (prefix + "%",),
        ).fetchall()
    ]
    if not candidates:
        return None
    matches = difflib.get_close_matches(norm_genus, [normalize_text(c) for c in candidates], n=limit, cutoff=0.72)
    if matches:
        out = []
        for m in matches:
            for c in candidates:
                if normalize_text(c) == m and c not in out:
                    out.append(c)
                    break
        return ", ".join(out[:limit])
    return ", ".join(candidates[:limit])


def _species_suggestions(conn: sqlite3.Connection, norm_genus: str, limit: int = 8) -> str | None:
    rows = _genus_rows(conn, norm_genus, limit=limit)
    suggestions = []
    for row in rows:
        name = row["accepted_scientific_name"] or row["scientific_name"]
        if name and name not in suggestions:
            suggestions.append(name)
    return ", ".join(suggestions[:limit]) if suggestions else None


def _status_is_accepted(status: str | None, accepted_taxon_id: str | None, taxon_id: str | None) -> bool:
    status_norm = normalize_text(status)
    if status_norm in {"accepted", "aceito"}:
        return True
    if accepted_taxon_id and taxon_id and accepted_taxon_id == taxon_id and status_norm not in {"synonym", "sinonimo", "sinônimo"}:
        return True
    return False


def validate_taxonomy_ffb(record: dict[str, Any]) -> list[ValidationIssue]:
    row_number = record.get("_row_number")
    family = record.get("family")
    genus = record.get("genus")
    sp1 = record.get("sp1")
    issues: list[ValidationIssue] = []

    if not genus:
        return issues

    if not _db_available():
        issues.append(
            issue(
                row_number,
                "genus",
                "info",
                "FFB_REFERENCE_NOT_BUILT",
                "A base SQLite da Flora e Funga ainda não foi construída neste ambiente.",
                genus,
                suggestion="Rode: cd backend && python scripts/build_ffb_sqlite.py --download",
                source=SOURCE,
            )
        )
        return issues

    norm_genus = normalize_text(genus)
    norm_sp1 = normalize_text(sp1)
    norm_family = normalize_text(family)
    name_key = normalize_text(f"{genus} {sp1}") if sp1 else ""

    with _connect() as conn:
        genus_hit = _genus_exists(conn, norm_genus)
        if not genus_hit:
            issues.append(
                issue(
                    row_number,
                    "genus",
                    "error",
                    "GENUS_NOT_FOUND_FFB",
                    "Gênero não encontrado na Flora e Funga do Brasil.",
                    genus,
                    suggestion=_genus_suggestions(conn, norm_genus),
                    source=SOURCE,
                )
            )
            return issues

        genus_rows = _genus_rows(conn, norm_genus, limit=1)
        expected_family = None
        if genus_rows:
            expected_family = genus_rows[0]["accepted_family"] or genus_rows[0]["family"]
        if family and expected_family and norm_family != normalize_text(expected_family):
            issues.append(
                issue(
                    row_number,
                    "family",
                    "warning",
                    "FAMILY_GENUS_MISMATCH_FFB",
                    f"Família informada não coincide com a família esperada para o gênero na Flora e Funga ({expected_family}).",
                    family,
                    suggestion=expected_family,
                    source=SOURCE,
                )
            )

        if not sp1:
            return issues

        hit = _fetch_one_by_key(conn, name_key)
        if not hit:
            issues.append(
                issue(
                    row_number,
                    "sp1",
                    "error",
                    "SPECIES_NOT_FOUND_FFB",
                    "Espécie não encontrada para este gênero na Flora e Funga do Brasil.",
                    f"{genus} {sp1}",
                    suggestion=_species_suggestions(conn, norm_genus),
                    source=SOURCE,
                )
            )
            return issues

        if family:
            accepted_family = hit["accepted_family"] or hit["family"]
            if accepted_family and norm_family != normalize_text(accepted_family):
                issues.append(
                    issue(
                        row_number,
                        "family",
                        "warning",
                        "FAMILY_TAXON_MISMATCH_FFB",
                        f"Família informada não coincide com a família do nome encontrado na Flora e Funga ({accepted_family}).",
                        family,
                        suggestion=accepted_family,
                        source=SOURCE,
                    )
                )

        accepted = _status_is_accepted(hit["taxonomic_status"], hit["accepted_taxon_id"], hit["taxon_id"])
        accepted_name = hit["accepted_scientific_name"] or hit["accepted_canonical_name"]
        current_name = hit["scientific_name"] or hit["canonical_name"]
        if not accepted and accepted_name and normalize_text(accepted_name) != normalize_text(current_name):
            issues.append(
                issue(
                    row_number,
                    "sp1",
                    "warning",
                    "TAXON_SYNONYM_FFB",
                    "Nome encontrado, mas não está como nome aceito na Flora e Funga do Brasil.",
                    current_name or f"{genus} {sp1}",
                    suggestion=accepted_name,
                    source=SOURCE,
                )
            )
        elif not accepted:
            issues.append(
                issue(
                    row_number,
                    "sp1",
                    "warning",
                    "TAXON_STATUS_REVIEW_FFB",
                    "Nome encontrado na Flora e Funga, mas o status taxonômico exige revisão curatorial.",
                    current_name or f"{genus} {sp1}",
                    suggestion=accepted_name,
                    source=SOURCE,
                )
            )

    return issues
