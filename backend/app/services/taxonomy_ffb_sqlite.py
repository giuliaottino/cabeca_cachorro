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

# TSIINO_COMPAT_TAXONOMY_ALIASES
if "reference_status" not in globals():
    def reference_status():
        for name in ("ffb_reference_status", "taxonomy_reference_status", "get_reference_status", "status"):
            fn = globals().get(name)
            if callable(fn):
                return fn()
        return {"mode": "ffb_sqlite", "status": "unknown"}

if "validate_taxonomy_ffb" not in globals():
    def validate_taxonomy_ffb(*args, **kwargs):
        for name in ("validate_taxonomy", "validate_row_taxonomy", "validate_ffb_taxonomy"):
            fn = globals().get(name)
            if callable(fn):
                return fn(*args, **kwargs)
        return []

# TSIINO_TAXONOMY_VALIDATION_V25
# Ajustes de qualidade taxonomica:
# - nao emitir alerta taxonomico quando a identificacao esta vazia/incompleta;
# - nao repetir a mesma mensagem na mesma celula;
# - suprimir falso conflito familia-genero quando o genero pertence a familia informada.
try:
    _tsiino_original_validate_taxonomy_ffb_v25 = validate_taxonomy_ffb
except NameError:  # pragma: no cover
    _tsiino_original_validate_taxonomy_ffb_v25 = None

_TSIINO_GENUS_FAMILY_OVERRIDES_V25 = {
    "miconia": {"melastomataceae"},
}


def _tsiino_norm_v25(value):
    import re as _re
    import unicodedata as _unicodedata
    if value is None:
        return ""
    s = str(value).strip()
    s = _unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not _unicodedata.combining(ch))
    s = _re.sub(r"[^a-zA-Z0-9]+", " ", s).strip().lower()
    return s


def _tsiino_issue_text_v25(obj):
    bits = []
    for name in ("message", "detail", "description", "code", "field", "column"):
        try:
            value = getattr(obj, name, None)
        except Exception:
            value = None
        if value:
            bits.append(str(value))
    if isinstance(obj, dict):
        for name in ("message", "detail", "description", "code", "field", "column"):
            value = obj.get(name)
            if value:
                bits.append(str(value))
    return " | ".join(bits)


def _tsiino_issue_field_v25(obj):
    for name in ("field", "column"):
        try:
            value = getattr(obj, name, None)
        except Exception:
            value = None
        if value:
            return str(value)
    if isinstance(obj, dict):
        return str(obj.get("field") or obj.get("column") or "")
    return ""


def _tsiino_row_from_args_v25(args, kwargs):
    for obj in list(args) + list(kwargs.values()):
        if isinstance(obj, dict):
            return obj
    return {}


def _tsiino_row_value_v25(row, *names):
    if not isinstance(row, dict):
        return ""
    wanted = {_tsiino_norm_v25(n).replace(" ", "") for n in names}
    for key, value in row.items():
        k = _tsiino_norm_v25(key).replace(" ", "")
        if k in wanted:
            return "" if value is None else str(value).strip()
    return ""


def _tsiino_families_for_genus_v25(genus):
    gnorm = _tsiino_norm_v25(genus).replace(" ", "")
    if not gnorm:
        return set()
    families = set(_TSIINO_GENUS_FAMILY_OVERRIDES_V25.get(gnorm, set()))
    conn = None
    try:
        conn = _connect()  # type: ignore[name-defined]
        tables = [r[0] for r in conn.execute("select name from sqlite_master where type='table'").fetchall()]
        for table in tables:
            try:
                cols = [r[1] for r in conn.execute(f'pragma table_info("{table}")').fetchall()]
            except Exception:
                continue
            lower = {c.lower(): c for c in cols}
            family_col = None
            for cand in ("family", "familia", "family_name"):
                if cand in lower:
                    family_col = lower[cand]
                    break
            if not family_col:
                continue
            genus_col = None
            for cand in ("genus", "genero"):
                if cand in lower:
                    genus_col = lower[cand]
                    break
            if genus_col:
                try:
                    for r in conn.execute(f'select distinct "{family_col}" from "{table}" where lower("{genus_col}") = ? limit 20', (gnorm,)).fetchall():
                        if r and r[0]:
                            families.add(_tsiino_norm_v25(r[0]).replace(" ", ""))
                except Exception:
                    pass
            # fallback for canonical/scientific name columns: first word == genus
            for cand in ("canonical", "canonical_name", "scientificname", "scientific_name", "name", "accepted_name"):
                if cand in lower:
                    name_col = lower[cand]
                    try:
                        like = genus.strip() + "%"
                        for r in conn.execute(f'select distinct "{family_col}" from "{table}" where "{name_col}" like ? limit 20', (like,)).fetchall():
                            if r and r[0]:
                                families.add(_tsiino_norm_v25(r[0]).replace(" ", ""))
                    except Exception:
                        pass
    except Exception:
        pass
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
    return families


def _tsiino_should_drop_taxonomy_issue_v25(issue_obj, row):
    family = _tsiino_row_value_v25(row, "family", "familia", "família")
    genus = _tsiino_row_value_v25(row, "genus", "genero", "gênero")
    sp1 = _tsiino_row_value_v25(row, "sp1", "species", "especie", "espécie", "epiteto", "epíteto", "epiteto especifico", "epíteto específico")
    field = _tsiino_norm_v25(_tsiino_issue_field_v25(issue_obj)).replace(" ", "")
    text = _tsiino_norm_v25(_tsiino_issue_text_v25(issue_obj))

    # Sem identificacao suficiente: nao acusar taxonomia. Campos obrigatorios, se existirem,
    # continuam sendo responsabilidade do rule_engine, nao da Flora e Funga.
    if not genus and not sp1:
        if any(w in text for w in ("familia", "genero", "especie", "taxon", "flora", "fung")) or field in {"family", "familia", "genus", "genero", "sp1", "species"}:
            return True
    if genus and not sp1:
        # Validar genero/familia pode continuar, mas nao procurar especie inexistente.
        if field in {"sp1", "species", "especie", "epiteto"} or "especie nao encontrada" in text or "epiteto" in text:
            return True
    if not genus:
        if "genero" in text or field in {"genus", "genero"}:
            return True

    # Mensagem ampla e barulhenta: nao ajuda quando ha identificacao parcial.
    if "familia e genero" in text and (family or genus or sp1):
        return True

    # Falso positivo familia-genero. Ex.: Miconia pertence a Melastomataceae.
    if family and genus and ("familia informada" in text or "familia esperada" in text or "nao coincide" in text):
        allowed = _tsiino_families_for_genus_v25(genus)
        if _tsiino_norm_v25(family).replace(" ", "") in allowed:
            return True
    return False


def _tsiino_dedupe_issues_v25(items):
    out = []
    seen = set()
    for item in items or []:
        key = (_tsiino_norm_v25(_tsiino_issue_field_v25(item)), _tsiino_norm_v25(_tsiino_issue_text_v25(item)))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


if _tsiino_original_validate_taxonomy_ffb_v25 is not None:
    def validate_taxonomy_ffb(*args, **kwargs):  # type: ignore[no-redef]
        row = _tsiino_row_from_args_v25(args, kwargs)
        family = _tsiino_row_value_v25(row, "family", "familia", "família")
        genus = _tsiino_row_value_v25(row, "genus", "genero", "gênero")
        sp1 = _tsiino_row_value_v25(row, "sp1", "species", "especie", "espécie", "epiteto", "epíteto")
        if not genus and not sp1:
            return []
        try:
            raw = _tsiino_original_validate_taxonomy_ffb_v25(*args, **kwargs)
        except TypeError:
            raw = _tsiino_original_validate_taxonomy_ffb_v25(row)
        kept = [i for i in (raw or []) if not _tsiino_should_drop_taxonomy_issue_v25(i, row)]
        return _tsiino_dedupe_issues_v25(kept)

# TSIINO_TAXONOMY_FFB_V27
# Correção curatorial: validação taxonômica conservadora, com busca de gênero
# no SQLite da Flora e Funga, sugestões fuzzy e sem alerta quando a identificação
# está vazia/incompleta.
try:
    _tsiino_original_validate_taxonomy_ffb_v27 = validate_taxonomy_ffb
except Exception:  # pragma: no cover
    _tsiino_original_validate_taxonomy_ffb_v27 = None

import difflib as _tsiino_difflib
import inspect as _tsiino_inspect
import re as _tsiino_re
import sqlite3 as _tsiino_sqlite3
import unicodedata as _tsiino_unicodedata
from functools import lru_cache as _tsiino_lru_cache
from pathlib import Path as _tsiino_Path


def _tsiino_norm_taxon_v27(value):
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    text = _tsiino_unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not _tsiino_unicodedata.combining(ch))
    text = text.replace("×", "x")
    text = _tsiino_re.sub(r"[^A-Za-z0-9]+", " ", text).strip().lower()
    return text


def _tsiino_key_taxon_v27(value):
    return _tsiino_re.sub(r"[^a-z0-9]+", "", _tsiino_norm_taxon_v27(value))


def _tsiino_title_taxon_v27(value):
    text = str(value or "").strip()
    if not text:
        return ""
    return text[:1].upper() + text[1:]


def _tsiino_get_row_value_v27(row, *names):
    if row is None:
        return ""
    if isinstance(row, dict):
        lower_map = {str(k).lower(): v for k, v in row.items()}
        norm_map = {_tsiino_key_taxon_v27(k): v for k, v in row.items()}
        for name in names:
            if name in row and row.get(name) not in (None, ""):
                return row.get(name)
            lname = str(name).lower()
            if lname in lower_map and lower_map[lname] not in (None, ""):
                return lower_map[lname]
            nname = _tsiino_key_taxon_v27(name)
            if nname in norm_map and norm_map[nname] not in (None, ""):
                return norm_map[nname]
    else:
        for name in names:
            if hasattr(row, name):
                value = getattr(row, name)
                if value not in (None, ""):
                    return value
    return ""


def _tsiino_row_number_v27(args, kwargs, row):
    for key in ("row_number", "row", "linha"):
        if kwargs.get(key) is not None:
            return kwargs.get(key)
    if len(args) > 1 and isinstance(args[1], int):
        return args[1]
    if isinstance(row, dict):
        for key in ("_row_number", "row_number", "linha", "LINHA"):
            try:
                value = row.get(key)
            except Exception:
                value = None
            if value not in (None, ""):
                return value
    return None


def _tsiino_make_issue_v27(row_number, field, severity, code, message, suggestion=None):
    # Usa o helper issue() do projeto quando disponível, adaptando-se à assinatura.
    factory = globals().get("issue")
    if callable(factory):
        try:
            sig = _tsiino_inspect.signature(factory)
            kwargs = {}
            for name in sig.parameters:
                lname = name.lower()
                if lname in {"row", "row_number", "rownumber", "linha"}:
                    kwargs[name] = row_number
                elif lname in {"field", "column", "col", "campo"}:
                    kwargs[name] = field
                elif lname == "severity":
                    kwargs[name] = severity
                elif lname == "code":
                    kwargs[name] = code
                elif lname in {"message", "msg", "mensagem"}:
                    kwargs[name] = message
                elif lname == "suggestion":
                    kwargs[name] = suggestion
            return factory(**kwargs)
        except Exception:
            pass
        for call in (
            lambda: factory(row_number=row_number, field=field, severity=severity, code=code, message=message, suggestion=suggestion),
            lambda: factory(row_number=row_number, field=field, severity=severity, code=code, message=message),
            lambda: factory(row_number, field, severity, code, message, suggestion),
            lambda: factory(row_number, field, severity, code, message),
        ):
            try:
                return call()
            except Exception:
                continue
    cls = globals().get("ValidationIssue")
    if cls is not None:
        for kwargs in (
            dict(row_number=row_number, field=field, severity=severity, code=code, message=message, suggestion=suggestion),
            dict(row=row_number, field=field, severity=severity, code=code, message=message, suggestion=suggestion),
            dict(row_number=row_number, column=field, severity=severity, code=code, message=message),
        ):
            try:
                return cls(**{k: v for k, v in kwargs.items() if v is not None})
            except Exception:
                continue
    return {"row_number": row_number, "field": field, "severity": severity, "code": code, "message": message, "suggestion": suggestion}


def _tsiino_db_path_v27():
    # Reaproveita constantes existentes quando presentes.
    for name in ("DEFAULT_DB", "DB_PATH", "REFERENCE_DB", "FFB_DB", "SQLITE_PATH"):
        value = globals().get(name)
        if value:
            try:
                p = _tsiino_Path(value)
                if p.exists():
                    return p
            except Exception:
                pass
    here = _tsiino_Path(__file__).resolve()
    candidates = [
        here.parents[3] / "reference" / "tsiino_reference.sqlite",
        here.parents[2] / "reference" / "tsiino_reference.sqlite",
        _tsiino_Path.cwd() / "reference" / "tsiino_reference.sqlite",
        _tsiino_Path.cwd() / "backend" / "reference" / "tsiino_reference.sqlite",
    ]
    for p in candidates:
        try:
            if p.exists():
                return p
        except Exception:
            pass
    return candidates[0]


@_tsiino_lru_cache(maxsize=1)
def _tsiino_schema_v27():
    path = _tsiino_db_path_v27()
    out = {}
    if not path.exists():
        return out
    try:
        conn = _tsiino_sqlite3.connect(str(path))
        conn.row_factory = _tsiino_sqlite3.Row
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for row in tables:
            name = row[0]
            cols = [c[1] for c in conn.execute(f'PRAGMA table_info("{name}")').fetchall()]
            out[name] = cols
        conn.close()
    except Exception:
        return {}
    return out


def _tsiino_connect_v27():
    path = _tsiino_db_path_v27()
    if not path.exists():
        return None
    try:
        conn = _tsiino_sqlite3.connect(str(path))
        conn.row_factory = _tsiino_sqlite3.Row
        return conn
    except Exception:
        return None


def _tsiino_col_v27(cols, *candidates):
    low = {c.lower(): c for c in cols}
    key = {_tsiino_key_taxon_v27(c): c for c in cols}
    for cand in candidates:
        if cand.lower() in low:
            return low[cand.lower()]
        kc = _tsiino_key_taxon_v27(cand)
        if kc in key:
            return key[kc]
    return None


_TSIINO_GENUS_FAMILY_OVERRIDES_V27 = {
    "miconia": "Melastomataceae",
    "piper": "Piperaceae",
    "peperomia": "Piperaceae",
    "passiflora": "Passifloraceae",
    "sarcoglottis": "Orchidaceae",
    "saccoglottis": "Humiriaceae",
    "tillandsia": "Bromeliaceae",
    "guzmania": "Bromeliaceae",
}


def _tsiino_query_genus_rows_v27(genus):
    gkey = _tsiino_key_taxon_v27(genus)
    if not gkey:
        return []
    rows = []
    conn = _tsiino_connect_v27()
    if conn is None:
        fam = _TSIINO_GENUS_FAMILY_OVERRIDES_V27.get(gkey)
        return [{"genus": _tsiino_title_taxon_v27(genus), "family": fam}] if fam else []
    try:
        schema = _tsiino_schema_v27()
        for table, cols in schema.items():
            genus_col = _tsiino_col_v27(cols, "genus")
            family_col = _tsiino_col_v27(cols, "family", "familia")
            canonical_col = _tsiino_col_v27(cols, "canonical_name", "canonical", "scientific_name", "scientificname", "name")
            rank_col = _tsiino_col_v27(cols, "rank", "taxon_rank", "taxonrank")
            status_col = _tsiino_col_v27(cols, "taxonomic_status", "status", "taxon_status", "taxonomicstatus")
            if genus_col:
                select = f'"{genus_col}" as genus'
                if family_col:
                    select += f', "{family_col}" as family'
                else:
                    select += ', NULL as family'
                sql = f'SELECT DISTINCT {select} FROM "{table}" WHERE lower("{genus_col}") = lower(?) LIMIT 50'
                try:
                    rows.extend(dict(r) for r in conn.execute(sql, (str(genus).strip(),)).fetchall())
                except Exception:
                    pass
            if canonical_col:
                where = f'lower("{canonical_col}") = lower(?)'
                params = [str(genus).strip()]
                if rank_col:
                    where += f' AND lower("{rank_col}") LIKE ?'
                    params.append('%gen%')
                select = f'"{canonical_col}" as genus'
                if family_col:
                    select += f', "{family_col}" as family'
                else:
                    select += ', NULL as family'
                sql = f'SELECT DISTINCT {select} FROM "{table}" WHERE {where} LIMIT 50'
                try:
                    rows.extend(dict(r) for r in conn.execute(sql, params).fetchall())
                except Exception:
                    pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    # Normaliza e remove duplicatas.
    clean = []
    seen = set()
    for r in rows:
        rg = r.get("genus") or r.get("GENUS") or genus
        # Se canonical/scientific_name veio como binômio, pega só a primeira palavra.
        rg = str(rg or "").strip().split()[0] if str(rg or "").strip() else str(genus).strip()
        rf = r.get("family") or r.get("FAMILY")
        key = (_tsiino_key_taxon_v27(rg), _tsiino_key_taxon_v27(rf))
        if key not in seen and key[0] == gkey:
            seen.add(key)
            clean.append({"genus": _tsiino_title_taxon_v27(rg), "family": rf})
    if not clean and gkey in _TSIINO_GENUS_FAMILY_OVERRIDES_V27:
        clean.append({"genus": _tsiino_title_taxon_v27(genus), "family": _TSIINO_GENUS_FAMILY_OVERRIDES_V27[gkey]})
    return clean


@_tsiino_lru_cache(maxsize=1)
def _tsiino_all_genera_v27():
    genera = {}
    conn = _tsiino_connect_v27()
    if conn is not None:
        try:
            schema = _tsiino_schema_v27()
            for table, cols in schema.items():
                genus_col = _tsiino_col_v27(cols, "genus")
                family_col = _tsiino_col_v27(cols, "family", "familia")
                canonical_col = _tsiino_col_v27(cols, "canonical_name", "canonical", "scientific_name", "scientificname", "name")
                rank_col = _tsiino_col_v27(cols, "rank", "taxon_rank", "taxonrank")
                if genus_col:
                    select = f'"{genus_col}" as genus'
                    select += f', "{family_col}" as family' if family_col else ', NULL as family'
                    try:
                        for r in conn.execute(f'SELECT DISTINCT {select} FROM "{table}" WHERE "{genus_col}" IS NOT NULL'):
                            g = str(r["genus"] or "").strip().split()[0]
                            if g:
                                genera.setdefault(_tsiino_key_taxon_v27(g), {"genus": _tsiino_title_taxon_v27(g), "families": set()})
                                if r["family"]:
                                    genera[_tsiino_key_taxon_v27(g)]["families"].add(str(r["family"]))
                    except Exception:
                        pass
                if canonical_col and rank_col:
                    select = f'"{canonical_col}" as genus'
                    select += f', "{family_col}" as family' if family_col else ', NULL as family'
                    try:
                        for r in conn.execute(f'SELECT DISTINCT {select} FROM "{table}" WHERE lower("{rank_col}") LIKE "%gen%" AND "{canonical_col}" IS NOT NULL'):
                            g = str(r["genus"] or "").strip().split()[0]
                            if g:
                                genera.setdefault(_tsiino_key_taxon_v27(g), {"genus": _tsiino_title_taxon_v27(g), "families": set()})
                                if r["family"]:
                                    genera[_tsiino_key_taxon_v27(g)]["families"].add(str(r["family"]))
                    except Exception:
                        pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
    for gkey, fam in _TSIINO_GENUS_FAMILY_OVERRIDES_V27.items():
        genera.setdefault(gkey, {"genus": _tsiino_title_taxon_v27(gkey), "families": set()})
        if fam:
            genera[gkey]["families"].add(fam)
    return genera


def _tsiino_suggest_genus_v27(genus, family=None):
    gkey = _tsiino_key_taxon_v27(genus)
    if not gkey:
        return None
    all_genera = _tsiino_all_genera_v27()
    if not all_genera:
        return None
    # Preferir candidatos da mesma família quando família estiver preenchida.
    fkey = _tsiino_key_taxon_v27(family)
    keys = list(all_genera.keys())
    if fkey:
        same_family = [k for k, v in all_genera.items() if any(_tsiino_key_taxon_v27(f) == fkey for f in v.get("families", []))]
        if same_family:
            keys = same_family
    # Reduz a busca por prefixo para evitar sugestão absurda.
    prefix = gkey[:2]
    local = [k for k in keys if k.startswith(prefix[:1])]
    if local:
        keys = local
    matches = _tsiino_difflib.get_close_matches(gkey, keys, n=3, cutoff=0.72)
    if not matches:
        # fallback: contém prefixo de 3 ou distância visual aceitável
        scored = []
        for k in keys:
            score = _tsiino_difflib.SequenceMatcher(None, gkey, k).ratio()
            if score >= 0.70:
                scored.append((score, k))
        scored.sort(reverse=True)
        matches = [k for _, k in scored[:3]]
    if matches:
        return all_genera[matches[0]]["genus"]
    return None


def _tsiino_query_species_exists_v27(genus, sp1):
    genus = str(genus or "").strip()
    sp1 = str(sp1 or "").strip()
    if not genus or not sp1:
        return True
    binom = f"{genus} {sp1}".strip()
    conn = _tsiino_connect_v27()
    if conn is None:
        return None
    try:
        schema = _tsiino_schema_v27()
        for table, cols in schema.items():
            genus_col = _tsiino_col_v27(cols, "genus")
            epi_col = _tsiino_col_v27(cols, "specific_epithet", "specificepithet", "sp1", "epithet", "epiteto")
            canonical_col = _tsiino_col_v27(cols, "canonical_name", "canonical", "scientific_name", "scientificname", "name")
            if genus_col and epi_col:
                try:
                    row = conn.execute(f'SELECT 1 FROM "{table}" WHERE lower("{genus_col}") = lower(?) AND lower("{epi_col}") = lower(?) LIMIT 1', (genus, sp1)).fetchone()
                    if row:
                        return True
                except Exception:
                    pass
            if canonical_col:
                try:
                    row = conn.execute(f'SELECT 1 FROM "{table}" WHERE lower("{canonical_col}") = lower(?) LIMIT 1', (binom.lower(),)).fetchone()
                    if row:
                        return True
                except Exception:
                    pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return False


def _tsiino_suggest_species_v27(genus, sp1):
    genus = str(genus or "").strip()
    sp1 = str(sp1 or "").strip()
    if not genus or not sp1:
        return None
    conn = _tsiino_connect_v27()
    if conn is None:
        return None
    candidates = set()
    try:
        schema = _tsiino_schema_v27()
        for table, cols in schema.items():
            genus_col = _tsiino_col_v27(cols, "genus")
            epi_col = _tsiino_col_v27(cols, "specific_epithet", "specificepithet", "sp1", "epithet", "epiteto")
            canonical_col = _tsiino_col_v27(cols, "canonical_name", "canonical", "scientific_name", "scientificname", "name")
            if genus_col and epi_col:
                try:
                    for r in conn.execute(f'SELECT DISTINCT "{epi_col}" as epithet FROM "{table}" WHERE lower("{genus_col}") = lower(?) AND "{epi_col}" IS NOT NULL LIMIT 3000', (genus,)):
                        ep = str(r["epithet"] or "").strip()
                        if ep:
                            candidates.add(ep)
                except Exception:
                    pass
            elif canonical_col:
                try:
                    like = genus + " %"
                    for r in conn.execute(f'SELECT DISTINCT "{canonical_col}" as name FROM "{table}" WHERE "{canonical_col}" LIKE ? LIMIT 3000', (like,)):
                        parts = str(r["name"] or "").split()
                        if len(parts) >= 2 and _tsiino_key_taxon_v27(parts[0]) == _tsiino_key_taxon_v27(genus):
                            candidates.add(parts[1])
                except Exception:
                    pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    cmap = {_tsiino_key_taxon_v27(c): c for c in candidates if c}
    matches = _tsiino_difflib.get_close_matches(_tsiino_key_taxon_v27(sp1), list(cmap.keys()), n=1, cutoff=0.74)
    if matches:
        return f"{_tsiino_title_taxon_v27(genus)} {cmap[matches[0]]}"
    return None


def _tsiino_dedupe_issues_v27(items):
    out = []
    seen = set()
    for it in items or []:
        if isinstance(it, dict):
            row = it.get("row_number") or it.get("row") or it.get("linha")
            field = it.get("field") or it.get("column") or it.get("campo")
            msg = it.get("message") or it.get("mensagem") or ""
            code = it.get("code") or ""
        else:
            row = getattr(it, "row_number", None) or getattr(it, "row", None)
            field = getattr(it, "field", None) or getattr(it, "column", None)
            msg = getattr(it, "message", "")
            code = getattr(it, "code", "")
        key = (_tsiino_key_taxon_v27(row), _tsiino_key_taxon_v27(field), _tsiino_key_taxon_v27(code), _tsiino_key_taxon_v27(msg))
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def validate_taxonomy_ffb(*args, **kwargs):  # noqa: D401 - assinatura compatível com o projeto
    row = args[0] if args else kwargs.get("row") or kwargs.get("record") or kwargs.get("data")
    row_number = _tsiino_row_number_v27(args, kwargs, row)

    family = _tsiino_get_row_value_v27(row, "family", "familia", "current family", "corrected family")
    genus = _tsiino_get_row_value_v27(row, "genus", "genero", "gênero", "current genus", "corrected genus")
    sp1 = _tsiino_get_row_value_v27(row, "sp1", "species", "especie", "espécie", "epiteto", "epíteto", "specific_epithet")

    family_key = _tsiino_key_taxon_v27(family)
    genus_key = _tsiino_key_taxon_v27(genus)
    sp1_key = _tsiino_key_taxon_v27(sp1)

    # Identificação vazia ou só família: não é erro taxonômico da FFB.
    # A validação estrutural pode acusar campo obrigatório; aqui evitamos falso alerta taxonômico.
    if not genus_key:
        return []

    genus_rows = _tsiino_query_genus_rows_v27(genus)
    if not genus_rows:
        suggestion = _tsiino_suggest_genus_v27(genus, family)
        msg = "Gênero não encontrado na Flora e Funga do Brasil."
        if suggestion:
            msg += f" Sugestão: {suggestion}."
        return [_tsiino_make_issue_v27(row_number, "genus", "error", "TAXON_GENUS_NOT_FOUND", msg, suggestion)]

    # Se família preenchida e há família conhecida para o gênero, só alerta se houver conflito real.
    families = [r.get("family") for r in genus_rows if r.get("family")]
    if family_key and families:
        fam_keys = {_tsiino_key_taxon_v27(f) for f in families if f}
        # Overrides seguros e normalização para casos conhecidos como Miconia/Melastomataceae e Piper/Piperaceae.
        override_family = _TSIINO_GENUS_FAMILY_OVERRIDES_V27.get(genus_key)
        if override_family:
            fam_keys.add(_tsiino_key_taxon_v27(override_family))
        if family_key not in fam_keys:
            expected = sorted({str(f) for f in families if f})[0] if families else None
            # Só emite se houver uma família esperada confiável.
            if expected:
                msg = f"Família informada não coincide com a família esperada para o gênero na Flora e Funga ({expected}). Sugestão: {expected}."
                return [_tsiino_make_issue_v27(row_number, "family", "warning", "TAXON_FAMILY_GENUS_MISMATCH", msg, expected)]

    # Se não há epíteto específico, não dispara alerta de espécie. Gênero válido basta.
    if not sp1_key:
        return []

    species_exists = _tsiino_query_species_exists_v27(genus, sp1)
    if species_exists is True:
        return []
    if species_exists is False:
        suggestion = _tsiino_suggest_species_v27(genus, sp1)
        msg = "Espécie não encontrada para este gênero na Flora e Funga do Brasil."
        if suggestion:
            msg += f" Sugestão: {suggestion}."
        return [_tsiino_make_issue_v27(row_number, "sp1", "error", "TAXON_SPECIES_NOT_FOUND", msg, suggestion)]
    return []

# TSIINO_TAXONOMY_ROW_STRICT_V29
# Hotfix conservador: remove falsos positivos taxonômicos quando a identificação
# está vazia/incompleta e impede que uma sugestão de espécie de outro gênero seja
# exibida na linha corrente.
try:
    _tsiino_validate_taxonomy_ffb_original_v29
except NameError:
    _tsiino_validate_taxonomy_ffb_original_v29 = validate_taxonomy_ffb

import re as _tsiino_re_v29
import unicodedata as _tsiino_unicodedata_v29


def _tsiino_norm_v29(value):
    if value is None:
        return ''
    txt = str(value).strip()
    txt = ''.join(ch for ch in _tsiino_unicodedata_v29.normalize('NFKD', txt) if not _tsiino_unicodedata_v29.combining(ch))
    txt = _tsiino_re_v29.sub(r'\s+', ' ', txt).strip().lower()
    return txt


def _tsiino_row_value_v29(row, *names):
    if row is None:
        return ''
    keys = []
    for name in names:
        keys.append(name)
        keys.append(str(name).lower())
        keys.append(str(name).upper())
    if isinstance(row, dict):
        lower_map = {str(k).lower(): v for k, v in row.items()}
        for key in keys:
            if key in row and row.get(key) not in (None, ''):
                return str(row.get(key)).strip()
            lk = str(key).lower()
            if lk in lower_map and lower_map.get(lk) not in (None, ''):
                return str(lower_map.get(lk)).strip()
    else:
        for key in keys:
            if hasattr(row, key):
                val = getattr(row, key)
                if val not in (None, ''):
                    return str(val).strip()
    return ''


def _tsiino_issue_text_v29(issue):
    parts = []
    if isinstance(issue, dict):
        for k in ('message', 'detail', 'description', 'suggestion', 'code'):
            if issue.get(k):
                parts.append(str(issue.get(k)))
    else:
        for k in ('message', 'detail', 'description', 'suggestion', 'code'):
            if hasattr(issue, k):
                val = getattr(issue, k)
                if val:
                    parts.append(str(val))
    return ' '.join(parts)


def _tsiino_issue_key_v29(issue):
    if isinstance(issue, dict):
        return (
            issue.get('row_number') or issue.get('row') or issue.get('line_number'),
            issue.get('field') or issue.get('column'),
            issue.get('code'),
            issue.get('message'),
        )
    return (
        getattr(issue, 'row_number', None) or getattr(issue, 'row', None) or getattr(issue, 'line_number', None),
        getattr(issue, 'field', None) or getattr(issue, 'column', None),
        getattr(issue, 'code', None),
        getattr(issue, 'message', None),
    )


def _tsiino_suggestion_genus_v29(text):
    m = _tsiino_re_v29.search(r'sugest(?:a|ã)o\s*:\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-zÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç-]+)', text, flags=_tsiino_re_v29.I)
    if not m:
        return ''
    return _tsiino_norm_v29(m.group(1))


def _tsiino_is_taxonomy_text_v29(text):
    n = _tsiino_norm_v29(text)
    return any(x in n for x in ('flora e funga', 'genero', 'especie', 'familia informada', 'familia e genero'))


_TSIINO_VALID_FAMILY_BY_GENUS_V29 = {
    'miconia': 'melastomataceae',
    'piper': 'piperaceae',
    'peperomia': 'piperaceae',
    'guzmania': 'bromeliaceae',
    'tillandsia': 'bromeliaceae',
    'passiflora': 'passifloraceae',
    'sarcoglottis': 'orchidaceae',
    'saccoglottis': 'humiriaceae',
    'zamia': 'zamiaceae',
    'pariana': 'poaceae',
}


def validate_taxonomy_ffb(*args, **kwargs):
    issues = _tsiino_validate_taxonomy_ffb_original_v29(*args, **kwargs)
    row = None
    for arg in args:
        if isinstance(arg, dict) or hasattr(arg, 'get'):
            row = arg
            break
    if row is None:
        row = kwargs.get('row') or kwargs.get('record') or kwargs.get('data')

    family = _tsiino_row_value_v29(row, 'family', 'familia', 'current family', 'corrected family')
    genus = _tsiino_row_value_v29(row, 'genus', 'genero', 'gênero', 'current genus', 'corrected genus')
    sp1 = _tsiino_row_value_v29(row, 'sp1', 'species', 'especie', 'espécie', 'epiteto', 'epíteto', 'specific_epithet')

    nfam = _tsiino_norm_v29(family)
    ngen = _tsiino_norm_v29(genus)
    nsp1 = _tsiino_norm_v29(sp1)

    if not isinstance(issues, list):
        try:
            issues = list(issues)
        except Exception:
            return issues

    out = []
    seen = set()
    for issue in issues:
        txt = _tsiino_issue_text_v29(issue)
        ntxt = _tsiino_norm_v29(txt)
        is_tax = _tsiino_is_taxonomy_text_v29(txt)

        # Identificação vazia/incompleta: não gerar ruído taxonômico.
        if is_tax and not ngen:
            continue
        if is_tax and ('especie' in ntxt or 'para este genero' in ntxt) and not nsp1:
            continue
        if 'familia e genero estao vazios' in ntxt:
            continue

        # Família-gênero: não avisar quando o par conhecido está coerente.
        expected_family = _TSIINO_VALID_FAMILY_BY_GENUS_V29.get(ngen)
        if expected_family and nfam == expected_family and ('familia' in ntxt or 'genero' in ntxt):
            if 'nao encontrado' in ntxt or 'nao coincide' in ntxt or 'familia informada' in ntxt:
                continue

        # Sugestão de espécie de outro gênero é quase sempre eco/alocação errada.
        sugg_genus = _tsiino_suggestion_genus_v29(txt)
        if sugg_genus and ngen and sugg_genus != ngen:
            if 'especie' in ntxt and 'para este genero' in ntxt:
                continue

        # Alguns gêneros válidos comuns não devem receber alerta genérico de gênero.
        if ngen in _TSIINO_VALID_FAMILY_BY_GENUS_V29 and 'genero nao encontrado' in ntxt:
            continue

        key = _tsiino_issue_key_v29(issue)
        if key in seen:
            continue
        seen.add(key)
        out.append(issue)
    return out

# TSIINO_TAXONOMY_FFB_STRICT_DB_V34
# Validação taxonômica conservadora e genérica: consulta a própria base SQLite da Flora e Funga.
# Não usa pares família–gênero hardcoded de planilhas. Só alerta com evidência da base.
def _tsiino_strip_accents_v34(value):
    import unicodedata, re
    s = '' if value is None else str(value).strip()
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def _tsiino_norm_tax_v34(value):
    import re
    s = _tsiino_strip_accents_v34(value).lower()
    s = re.sub(r'[^a-z0-9]+', ' ', s).strip()
    return s

def _tsiino_get_row_value_v34(row, *names):
    if not isinstance(row, dict):
        return ''
    for name in names:
        if name in row and row.get(name) not in (None, ''):
            return row.get(name)
    norm_map = {_tsiino_norm_tax_v34(k).replace(' ', '_'): v for k, v in row.items()}
    for name in names:
        key = _tsiino_norm_tax_v34(name).replace(' ', '_')
        if key in norm_map and norm_map[key] not in (None, ''):
            return norm_map[key]
    return ''

def _tsiino_row_number_v34(row, kwargs):
    for k in ('_ROW_NUMBER', 'row_number', 'row', 'linha'):
        try:
            v = row.get(k) if isinstance(row, dict) else None
            if v not in (None, ''):
                return int(v)
        except Exception:
            pass
    for k in ('row_number', 'row', 'linha'):
        try:
            v = kwargs.get(k)
            if v not in (None, ''):
                return int(v)
        except Exception:
            pass
    return None

def _tsiino_default_db_v34():
    try:
        return DEFAULT_DB
    except Exception:
        from pathlib import Path
        return Path(__file__).resolve().parents[2] / 'reference' / 'tsiino_reference.sqlite'

def _tsiino_connect_v34():
    import sqlite3
    db = _tsiino_default_db_v34()
    return sqlite3.connect(str(db))

from functools import lru_cache as _tsiino_lru_cache_v34

@_tsiino_lru_cache_v34(maxsize=1)
def _tsiino_table_columns_v34():
    out = []
    try:
        con = _tsiino_connect_v34()
        cur = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        for (table,) in cur.fetchall():
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")').fetchall()]
            lower = {c.lower(): c for c in cols}
            out.append((table, cols, lower))
        con.close()
    except Exception:
        pass
    return out

def _tsiino_col_v34(lower, *candidates):
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    for c in candidates:
        c_norm = c.lower().replace('_', '')
        for lc, orig in lower.items():
            if lc.replace('_', '') == c_norm:
                return orig
    return None

@_tsiino_lru_cache_v34(maxsize=4096)
def _tsiino_families_for_genus_v34(genus_norm):
    families = set()
    if not genus_norm:
        return tuple()
    try:
        con = _tsiino_connect_v34()
        for table, cols, lower in _tsiino_table_columns_v34():
            fam_col = _tsiino_col_v34(lower, 'family', 'familia')
            gen_col = _tsiino_col_v34(lower, 'genus', 'genero')
            sci_col = _tsiino_col_v34(lower, 'scientificName', 'scientific_name', 'canonicalName', 'canonical_name', 'accepted_name', 'name')
            if fam_col and gen_col:
                try:
                    q = f'SELECT DISTINCT "{fam_col}" FROM "{table}" WHERE lower("{gen_col}") = ? AND "{fam_col}" IS NOT NULL LIMIT 20'
                    for (fam,) in con.execute(q, (genus_norm,)).fetchall():
                        if fam:
                            families.add(str(fam).strip())
                except Exception:
                    pass
            elif fam_col and sci_col:
                try:
                    q = f'SELECT DISTINCT "{fam_col}", "{sci_col}" FROM "{table}" WHERE lower("{sci_col}") LIKE ? LIMIT 100'
                    for fam, sci in con.execute(q, (genus_norm + ' %',)).fetchall():
                        if fam and _tsiino_norm_tax_v34(str(sci).split()[0] if sci else '') == genus_norm:
                            families.add(str(fam).strip())
                except Exception:
                    pass
        con.close()
    except Exception:
        pass
    return tuple(sorted(families))

@_tsiino_lru_cache_v34(maxsize=1)
def _tsiino_all_genera_v34():
    genera = set()
    try:
        con = _tsiino_connect_v34()
        for table, cols, lower in _tsiino_table_columns_v34():
            gen_col = _tsiino_col_v34(lower, 'genus', 'genero')
            sci_col = _tsiino_col_v34(lower, 'scientificName', 'scientific_name', 'canonicalName', 'canonical_name', 'accepted_name', 'name')
            if gen_col:
                try:
                    for (g,) in con.execute(f'SELECT DISTINCT "{gen_col}" FROM "{table}" WHERE "{gen_col}" IS NOT NULL').fetchall():
                        if g:
                            genera.add(str(g).strip())
                except Exception:
                    pass
            elif sci_col:
                try:
                    for (sci,) in con.execute(f'SELECT DISTINCT "{sci_col}" FROM "{table}" WHERE "{sci_col}" IS NOT NULL LIMIT 250000').fetchall():
                        if sci:
                            first = str(sci).strip().split()[0] if str(sci).strip() else ''
                            if first and first[0].isalpha():
                                genera.add(first)
                except Exception:
                    pass
        con.close()
    except Exception:
        pass
    return tuple(sorted(genera, key=lambda x: x.lower()))

@_tsiino_lru_cache_v34(maxsize=8192)
def _tsiino_species_epithets_for_genus_v34(genus_norm):
    eps = {}
    if not genus_norm:
        return tuple()
    try:
        con = _tsiino_connect_v34()
        for table, cols, lower in _tsiino_table_columns_v34():
            gen_col = _tsiino_col_v34(lower, 'genus', 'genero')
            ep_col = _tsiino_col_v34(lower, 'specificEpithet', 'specific_epithet', 'specificepithet', 'sp1', 'epithet')
            sci_col = _tsiino_col_v34(lower, 'scientificName', 'scientific_name', 'canonicalName', 'canonical_name', 'accepted_name', 'name')
            if gen_col and ep_col:
                try:
                    q = f'SELECT DISTINCT "{ep_col}", "{gen_col}" FROM "{table}" WHERE lower("{gen_col}") = ? AND "{ep_col}" IS NOT NULL LIMIT 5000'
                    for ep, g in con.execute(q, (genus_norm,)).fetchall():
                        epn = _tsiino_norm_tax_v34(ep)
                        if epn:
                            eps.setdefault(epn, f'{str(g).strip()} {str(ep).strip()}')
                except Exception:
                    pass
            elif sci_col:
                try:
                    q = f'SELECT DISTINCT "{sci_col}" FROM "{table}" WHERE lower("{sci_col}") LIKE ? LIMIT 5000'
                    for (sci,) in con.execute(q, (genus_norm + ' %',)).fetchall():
                        parts = str(sci or '').strip().split()
                        if len(parts) >= 2 and _tsiino_norm_tax_v34(parts[0]) == genus_norm:
                            epn = _tsiino_norm_tax_v34(parts[1])
                            if epn:
                                eps.setdefault(epn, f'{parts[0]} {parts[1]}')
                except Exception:
                    pass
        con.close()
    except Exception:
        pass
    return tuple(sorted(eps.items()))

def _tsiino_best_match_v34(query_norm, candidates, cutoff=0.88):
    if not query_norm or not candidates:
        return None
    import difflib
    cand_norm = []
    back = {}
    for c in candidates:
        if isinstance(c, tuple):
            norm, label = c
        else:
            norm, label = _tsiino_norm_tax_v34(c), c
        cand_norm.append(norm)
        back[norm] = label
    hit = difflib.get_close_matches(query_norm, cand_norm, n=1, cutoff=cutoff)
    return back.get(hit[0]) if hit else None

def _tsiino_make_issue_v34(row_number, field, severity, code, message, value=None, suggestion=None):
    fn = globals().get('issue')
    attempts = []
    kw = dict(row_number=row_number, field=field, severity=severity, code=code, message=message, value=value, suggestion=suggestion)
    attempts.append(lambda: fn(**kw) if callable(fn) else None)
    attempts.append(lambda: fn(row_number, field, severity, code, message, value, suggestion) if callable(fn) else None)
    attempts.append(lambda: fn(row_number, field, severity, code, message) if callable(fn) else None)
    for call in attempts:
        try:
            obj = call()
            if obj is not None:
                return obj
        except TypeError:
            pass
        except Exception:
            pass
    cls = globals().get('ValidationIssue')
    if cls:
        for payload in (kw, {k:v for k,v in kw.items() if v is not None}):
            try:
                return cls(**payload)
            except Exception:
                pass
    return {k:v for k,v in kw.items() if v is not None}

def validate_taxonomy_ffb(*args, **kwargs):
    row = None
    for a in args:
        if isinstance(a, dict):
            row = a
            break
    if row is None:
        row = kwargs.get('row') or {}
    row_number = _tsiino_row_number_v34(row, kwargs)
    family = _tsiino_strip_accents_v34(_tsiino_get_row_value_v34(row, 'family', 'familia', 'Current Family', 'Corrected Family'))
    genus = _tsiino_strip_accents_v34(_tsiino_get_row_value_v34(row, 'genus', 'genero', 'gênero'))
    sp1 = _tsiino_strip_accents_v34(_tsiino_get_row_value_v34(row, 'sp1', 'species', 'epiteto', 'epíteto', 'epiteto especifico'))
    if not genus:
        return []
    genus_norm = _tsiino_norm_tax_v34(genus)
    family_norm = _tsiino_norm_tax_v34(family)
    issues_out = []
    families = _tsiino_families_for_genus_v34(genus_norm)
    families_norm = {_tsiino_norm_tax_v34(f) for f in families}
    if not families:
        suggestion = _tsiino_best_match_v34(genus_norm, _tsiino_all_genera_v34(), cutoff=0.91)
        if suggestion and _tsiino_norm_tax_v34(suggestion) != genus_norm:
            msg = f'Gênero não encontrado na Flora e Funga do Brasil. Sugestão: {suggestion}.'
            issues_out.append(_tsiino_make_issue_v34(row_number, 'genus', 'warning', 'TAXONOMY_GENUS_NOT_FOUND', msg, genus, suggestion))
        return issues_out
    if family and families_norm and family_norm not in families_norm:
        suggestion_family = families[0]
        msg = f'Família informada não coincide com a família esperada para o gênero na Flora e Funga ({suggestion_family}). Sugestão: {suggestion_family}.'
        issues_out.append(_tsiino_make_issue_v34(row_number, 'family', 'warning', 'TAXONOMY_FAMILY_MISMATCH', msg, family, suggestion_family))
    if not sp1:
        return _tsiino_dedup_issues_v34(issues_out)
    sp_norm = _tsiino_norm_tax_v34(sp1).split()[0] if _tsiino_norm_tax_v34(sp1) else ''
    if not sp_norm:
        return _tsiino_dedup_issues_v34(issues_out)
    epithets = _tsiino_species_epithets_for_genus_v34(genus_norm)
    ep_norms = {e for e, label in epithets}
    if sp_norm in ep_norms:
        return _tsiino_dedup_issues_v34(issues_out)
    suggestion = _tsiino_best_match_v34(sp_norm, epithets, cutoff=0.88)
    if suggestion:
        sgen = _tsiino_norm_tax_v34(str(suggestion).split()[0] if str(suggestion).split() else '')
        if sgen == genus_norm:
            msg = f'Espécie não encontrada para este gênero na Flora e Funga do Brasil. Sugestão: {suggestion}.'
            issues_out.append(_tsiino_make_issue_v34(row_number, 'sp1', 'warning', 'TAXONOMY_SPECIES_NOT_FOUND', msg, sp1, suggestion))
    return _tsiino_dedup_issues_v34(issues_out)

def _tsiino_dedup_issues_v34(items):
    seen = set()
    out = []
    for it in items:
        try:
            key = (getattr(it, 'row_number', None) or (it.get('row_number') if isinstance(it, dict) else None), getattr(it, 'field', None) or (it.get('field') if isinstance(it, dict) else None), getattr(it, 'message', None) or (it.get('message') if isinstance(it, dict) else None))
        except Exception:
            key = str(it)
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out

