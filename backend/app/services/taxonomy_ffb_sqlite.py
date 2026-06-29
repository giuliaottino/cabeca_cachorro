from __future__ import annotations

import re
import sqlite3
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from app.schemas.issues import ValidationIssue
from app.services.rule_engine import issue

SOURCE_NAME = "Flora e Funga do Brasil - Lista Oficial"
SOURCE_URL = "https://ipt.jbrj.gov.br/jbrj/archive.do?r=lista_especies_flora_brasil"
DB_FILENAME = "tsiino_reference.sqlite"


def _backend_root() -> Path:
    # Local: <repo>/backend/app/services/taxonomy_ffb_sqlite.py -> parents[2] = backend
    # HF:    /app/app/services/taxonomy_ffb_sqlite.py       -> parents[2] = /app
    return Path(__file__).resolve().parents[2]


def _db_path() -> Path:
    return _backend_root() / "reference" / DB_FILENAME


def _norm(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _norm_status(value: Any) -> str:
    return _norm(value).replace(" ", "_").upper()


def _norm_rank(value: Any) -> str:
    return _norm(value).replace(" ", "_").upper()


def _canonical_binomial(genus: Any, sp1: Any) -> str:
    return _norm(f"{genus or ''} {sp1 or ''}")


def _is_accepted_status(status: Any) -> bool:
    s = _norm_status(status)
    return s in {
        "NOME_ACEITO",
        "NOME_CORRETO",
        "ACEITO",
        "ACCEPTED",
        "ACCEPTED_NAME",
        "CORRECT",
        "CORRECT_NAME",
    }


def _is_species_rank(rank: Any) -> bool:
    r = _norm_rank(rank)
    return r in {"ESPECIE", "SPECIES"}


def _is_infraspecific_rank(rank: Any) -> bool:
    r = _norm_rank(rank)
    return r in {"VARIEDADE", "VARIETY", "SUBSPECIE", "SUBSPECIES", "FORMA", "FORM"}


def _connect() -> sqlite3.Connection:
    path = _db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


@lru_cache(maxsize=1)
def reference_status() -> dict[str, Any]:
    path = _db_path()
    if not path.exists():
        return {
            "mode": "ffb_sqlite",
            "status": "missing",
            "path": str(path),
            "source": SOURCE_NAME,
            "source_url": SOURCE_URL,
        }

    try:
        with _connect() as con:
            metadata = {
                row["key"]: row["value"]
                for row in con.execute("SELECT key, value FROM reference_metadata")
            }
            taxon_count = con.execute("SELECT COUNT(*) FROM ffb_taxon").fetchone()[0]
            name_count = con.execute("SELECT COUNT(*) FROM ffb_name_index").fetchone()[0]
            dist_count = con.execute("SELECT COUNT(*) FROM ffb_distribution").fetchone()[0]
    except Exception as exc:
        return {
            "mode": "ffb_sqlite",
            "status": "error",
            "path": str(path),
            "source": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "error": str(exc),
        }

    return {
        "mode": "ffb_sqlite",
        "status": "ready",
        "path": str(path),
        "source": metadata.get("source", SOURCE_NAME),
        "source_url": metadata.get("source_url", SOURCE_URL),
        "source_version": metadata.get("source_version", "unspecified"),
        "created_at_utc": metadata.get("created_at_utc"),
        "taxon_count": taxon_count,
        "name_index_count": name_count,
        "distribution_count": dist_count,
    }


def _fetch_taxa_for_name(con: sqlite3.Connection, genus_norm: str, sp1_norm: str, sp2_norm: str = "") -> list[sqlite3.Row]:
    params: list[Any] = [genus_norm, sp1_norm]
    extra = ""
    if sp2_norm:
        extra = " AND lower(COALESCE(t.infraspecific_epithet, '')) = ?"
        params.append(sp2_norm)

    return con.execute(
        f"""
        SELECT
            t.taxon_id,
            t.scientific_name,
            t.canonical_name,
            t.family,
            t.genus,
            t.specific_epithet,
            t.infraspecific_epithet,
            t.taxon_rank,
            t.taxonomic_status,
            t.accepted_name_usage_id,
            COALESCE(a.taxon_id, t.taxon_id) AS accepted_taxon_id,
            COALESCE(a.scientific_name, t.scientific_name) AS accepted_scientific_name,
            COALESCE(a.canonical_name, t.canonical_name) AS accepted_canonical_name,
            COALESCE(a.family, t.family) AS accepted_family,
            COALESCE(a.genus, t.genus) AS accepted_genus
        FROM ffb_taxon AS t
        LEFT JOIN ffb_taxon AS a
          ON a.taxon_id = NULLIF(t.accepted_name_usage_id, '')
        WHERE lower(COALESCE(t.genus, '')) = ?
          AND lower(COALESCE(t.specific_epithet, '')) = ?
          {extra}
        """,
        params,
    ).fetchall()


def _choose_exact_match(rows: list[sqlite3.Row], has_infraspecific_input: bool) -> sqlite3.Row | None:
    if not rows:
        return None

    def priority(row: sqlite3.Row) -> tuple[int, int, int, str]:
        status_score = 0 if _is_accepted_status(row["taxonomic_status"]) else 1
        if has_infraspecific_input:
            rank_score = 0 if _is_infraspecific_rank(row["taxon_rank"]) else 1
        else:
            # Se a entrada é só genus + sp1, NUNCA priorizar variedade/subespécie.
            rank_score = 0 if _is_species_rank(row["taxon_rank"]) else 1
        accepted_id_score = 0 if not row["accepted_name_usage_id"] else 1
        return (rank_score, status_score, accepted_id_score, _norm(row["scientific_name"]))

    return sorted(rows, key=priority)[0]


def _genus_exists(con: sqlite3.Connection, genus_norm: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM ffb_taxon WHERE lower(COALESCE(genus, '')) = ? LIMIT 1",
        (genus_norm,),
    ).fetchone()
    return row is not None


def _expected_family_for_genus(con: sqlite3.Connection, genus_norm: str) -> str | None:
    row = con.execute(
        """
        SELECT family, COUNT(*) AS n
        FROM ffb_taxon
        WHERE lower(COALESCE(genus, '')) = ?
          AND family IS NOT NULL
          AND family <> ''
          AND taxonomic_status = 'NOME_ACEITO'
        GROUP BY family
        ORDER BY n DESC, family
        LIMIT 1
        """,
        (genus_norm,),
    ).fetchone()
    return row["family"] if row else None


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(
                curr[j - 1] + 1,
                prev[j] + 1,
                prev[j - 1] + (0 if ca == cb else 1),
            ))
        prev = curr
    return prev[-1]


def _candidate_species_for_genus(con: sqlite3.Connection, genus_norm: str) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT DISTINCT scientific_name, canonical_name, genus, specific_epithet, family, taxon_rank, taxonomic_status
        FROM ffb_taxon
        WHERE lower(COALESCE(genus, '')) = ?
          AND specific_epithet IS NOT NULL
          AND specific_epithet <> ''
          AND taxon_rank = 'ESPECIE'
          AND taxonomic_status = 'NOME_ACEITO'
        """,
        (genus_norm,),
    ).fetchall()


def _species_suggestions(con: sqlite3.Connection, genus_norm: str, sp1_norm: str, limit: int = 3) -> str | None:
    if not sp1_norm:
        return None

    candidates = _candidate_species_for_genus(con, genus_norm)
    scored: list[tuple[int, int, str, str]] = []
    for row in candidates:
        epithet_norm = _norm(row["specific_epithet"])
        if not epithet_norm:
            continue
        dist = _levenshtein(sp1_norm, epithet_norm)
        max_len = max(len(sp1_norm), len(epithet_norm), 1)
        # Evita sugestões aleatórias quando a grafia está muito distante.
        threshold = max(2, min(4, round(max_len * 0.34)))
        prefix_bonus = 0 if epithet_norm[:3] == sp1_norm[:3] else 1
        if dist <= threshold or prefix_bonus == 0 and dist <= threshold + 1:
            scored.append((dist, prefix_bonus, epithet_norm, row["scientific_name"] or row["canonical_name"]))

    if not scored:
        return None

    seen: set[str] = set()
    suggestions: list[str] = []
    for _, _, _, name in sorted(scored):
        key = _norm(name)
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(name)
        if len(suggestions) >= limit:
            break

    return ", ".join(suggestions) if suggestions else None


def _genus_suggestions(con: sqlite3.Connection, genus_norm: str, limit: int = 3) -> str | None:
    if not genus_norm:
        return None
    rows = con.execute(
        """
        SELECT DISTINCT genus
        FROM ffb_taxon
        WHERE genus IS NOT NULL
          AND genus <> ''
          AND genus <> 'NA'
        """
    ).fetchall()
    scored: list[tuple[int, str, str]] = []
    for row in rows:
        g = row["genus"]
        gn = _norm(g)
        dist = _levenshtein(genus_norm, gn)
        threshold = max(2, min(4, round(max(len(genus_norm), len(gn), 1) * 0.30)))
        if dist <= threshold:
            scored.append((dist, gn, g))
    if not scored:
        return None
    out: list[str] = []
    seen: set[str] = set()
    for _, _, genus in sorted(scored)[:limit]:
        key = _norm(genus)
        if key not in seen:
            seen.add(key)
            out.append(genus)
    return ", ".join(out) if out else None


def _same_canonical_input(row: sqlite3.Row, genus: Any, sp1: Any, sp2: Any = None) -> bool:
    input_key = _canonical_binomial(genus, sp1)
    accepted_key = _norm(row["accepted_canonical_name"] or row["accepted_scientific_name"])
    row_key = _norm(row["canonical_name"] or row["scientific_name"])
    # Para genus+sp1, comparar só binômio. Assim Cordia nodosa Lam. == Cordia nodosa.
    accepted_binomial = " ".join(accepted_key.split()[:2])
    row_binomial = " ".join(row_key.split()[:2])
    return input_key and (input_key == accepted_binomial or input_key == row_binomial)


def validate_taxonomy_ffb(record: dict[str, Any]) -> list[ValidationIssue]:
    row_number = record.get("_row_number")
    family = record.get("family")
    genus = record.get("genus")
    sp1 = record.get("sp1")
    rank1 = record.get("rank1")
    sp2 = record.get("sp2")

    issues: list[ValidationIssue] = []

    status = reference_status()
    if status.get("status") != "ready":
        issues.append(issue(
            row_number,
            "genus",
            "warning",
            "FFB_REFERENCE_NOT_READY",
            "Base taxonômica da Flora e Funga não está pronta; validação taxonômica completa não foi executada.",
            genus,
            source=SOURCE_NAME,
        ))
        return issues

    if not genus:
        return issues

    genus_norm = _norm(genus)
    sp1_norm = _norm(sp1)
    sp2_norm = _norm(sp2)
    has_infraspecific_input = bool(_norm(rank1) or sp2_norm)

    with _connect() as con:
        if not _genus_exists(con, genus_norm):
            issues.append(issue(
                row_number,
                "genus",
                "error",
                "GENUS_NOT_FOUND_FFB",
                "Gênero não encontrado na Flora e Funga do Brasil.",
                genus,
                suggestion=_genus_suggestions(con, genus_norm),
                source=SOURCE_NAME,
            ))
            return issues

        expected_family = _expected_family_for_genus(con, genus_norm)
        if family and expected_family and _norm(family) != _norm(expected_family):
            issues.append(issue(
                row_number,
                "family",
                "warning",
                "FAMILY_GENUS_MISMATCH",
                f"Família informada não coincide com a família esperada para o gênero na Flora e Funga ({expected_family}).",
                family,
                suggestion=expected_family,
                source=SOURCE_NAME,
            ))

        if not sp1:
            return issues

        exact_rows = _fetch_taxa_for_name(con, genus_norm, sp1_norm, sp2_norm if has_infraspecific_input else "")
        match = _choose_exact_match(exact_rows, has_infraspecific_input)

        if match is None:
            suggestion = _species_suggestions(con, genus_norm, sp1_norm)
            issues.append(issue(
                row_number,
                "sp1",
                "error",
                "SPECIES_NOT_FOUND_FFB",
                "Espécie não encontrada para este gênero na Flora e Funga do Brasil.",
                f"{genus} {sp1}",
                suggestion=suggestion,
                source=SOURCE_NAME,
            ))
            return issues

        if not _is_accepted_status(match["taxonomic_status"]):
            # Não marcar como sinônimo quando o nome aceito resolve para o mesmo binômio informado.
            # Isso evita falsos positivos como Cordia nodosa -> sugestão Cordia nodosa Lam.
            if _same_canonical_input(match, genus, sp1, sp2):
                return issues

            accepted = match["accepted_scientific_name"] or match["accepted_canonical_name"]
            issues.append(issue(
                row_number,
                "sp1",
                "warning",
                "TAXON_NOT_ACCEPTED",
                "Nome encontrado, mas não está como nome aceito na Flora e Funga do Brasil.",
                match["scientific_name"] or f"{genus} {sp1}",
                suggestion=accepted,
                source=SOURCE_NAME,
            ))

    return issues
