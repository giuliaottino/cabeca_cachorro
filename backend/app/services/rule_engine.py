"""Regras estruturais e de preenchimento do padrão INPA/BRAHMS (sem bases externas)."""
from __future__ import annotations

import datetime as _dt
import re
from collections import defaultdict
from typing import Any

from app.schemas.issues import ValidationIssue
from app.services.inpa_schema import FIELD_LABELS
from app.services.normalization import Coordinate, cell_text, norm, parse_coordinate

MIN_YEAR = 1750


def _blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def issue(row: int | None, column: str | None, severity: str, code: str, message: str,
          value: Any = None, suggestion: str | None = None, source: str | None = None) -> ValidationIssue:
    return ValidationIssue(
        row_number=row,
        column_name=column,
        severity=severity,  # type: ignore[arg-type]
        code=code,
        message=message,
        value=None if _blank(value) else cell_text(value),
        suggestion=suggestion,
        source=source,
    )


# ---------------------------------------------------------------------------
# Estrutura
# ---------------------------------------------------------------------------
def validate_structure(records: list[dict[str, Any]], missing_minimum: list[str], unknown_headers: list[str],
                       *, truncated: bool = False, max_rows: int = 0) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for col in missing_minimum:
        issues.append(issue(None, col, "error", "MISSING_COLUMN",
                            f"Coluna obrigatória ausente: {col} ({FIELD_LABELS.get(col, col)})."))
    for col in unknown_headers:
        issues.append(issue(None, col, "info", "UNKNOWN_COLUMN",
                            f"Coluna não reconhecida no padrão INPA/BRAHMS e ignorada na validação: {col}."))
    if not records:
        issues.append(issue(None, None, "error", "NO_DATA_ROWS", "A planilha não contém linhas de dados após o cabeçalho."))
    if truncated:
        issues.append(issue(None, None, "warning", "ROW_LIMIT_REACHED",
                            f"A planilha tem mais de {max_rows} linhas; somente as primeiras {max_rows} foram validadas. "
                            "Divida o arquivo para validar o restante."))
    return issues


# ---------------------------------------------------------------------------
# Campos por linha
# ---------------------------------------------------------------------------
_REQUIRED_MESSAGES = {
    "collector": "Coletor principal é obrigatório.",
    "number": "Número de coleta é obrigatório (evite s.n.).",
    "colldd": "Dia da coleta é obrigatório.",
    "collmm": "Mês da coleta é obrigatório.",
    "collyy": "Ano da coleta é obrigatório.",
    "country": "País é obrigatório.",
    "majorarea": "Estado é obrigatório.",
    "minorarea": "Município é obrigatório.",
    "lat": "Latitude é obrigatória.",
    "long": "Longitude é obrigatória.",
}

_SN = {"sn", "s n", "sem numero", "sem n"}
_SP_PLACEHOLDERS = {"sp", "sp1", "sp2", "spp", "sp nov", "indet", "indeterminada", "ni", "n i"}
_DETSTATUS_OK = {"cf": "cf.", "aff": "aff.", "cf.": "cf.", "aff.": "aff."}
_RANK_OK = {"var": "var.", "variedade": "var.", "ssp": "ssp.", "subsp": "ssp.", "subespecie": "ssp.",
            "f": "f.", "forma": "f.", "fo": "f."}
_COLLECTOR_FMT = re.compile(r"^[^,;]+,\s*\S")


def _int_value(value: Any) -> int | None:
    if _blank(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip()
    return int(text) if re.fullmatch(r"\d{1,4}", text) else None


def validate_required_fields(record: dict[str, Any]) -> list[ValidationIssue]:
    row = record["_row_number"]
    issues: list[ValidationIssue] = []
    for col, message in _REQUIRED_MESSAGES.items():
        if _blank(record.get(col)):
            issues.append(issue(row, col, "error", f"{col.upper()}_REQUIRED", message))
    if _blank(record.get("plantdesc")):
        issues.append(issue(row, "plantdesc", "warning", "PLANTDESC_EMPTY",
                            "Descrição da planta vazia; descreva hábito, tamanho, cores, odores e exsudatos."))
    if _blank(record.get("family")) and _blank(record.get("genus")):
        issues.append(issue(row, "family", "warning", "TAXON_EMPTY",
                            "Família e gênero vazios; informe ao menos a família."))
    return issues


def _validate_one_date(record: dict[str, Any], prefix: str, label: str, required: bool) -> list[ValidationIssue]:
    row = record["_row_number"]
    dd_key, mm_key, yy_key = f"{prefix}dd", f"{prefix}mm", f"{prefix}yy"
    raw = [record.get(dd_key), record.get(mm_key), record.get(yy_key)]
    if all(_blank(v) for v in raw):
        return []
    issues: list[ValidationIssue] = []
    dd, mm, yy = (_int_value(v) for v in raw)
    shown = "/".join(cell_text(v) or "?" for v in raw)
    for key, val, original in ((dd_key, dd, raw[0]), (mm_key, mm, raw[1]), (yy_key, yy, raw[2])):
        if not _blank(original) and val is None:
            issues.append(issue(row, key, "error", f"{key.upper()}_NOT_NUMERIC",
                                f"{label}: use somente números neste campo.", original))
    if issues:
        return issues
    today = _dt.date.today()
    if yy is not None:
        if yy < 100:
            issues.append(issue(row, yy_key, "error", f"{yy_key.upper()}_TWO_DIGITS",
                                f"{label}: informe o ano com quatro dígitos.", raw[2]))
            return issues
        if yy < MIN_YEAR or yy > today.year:
            issues.append(issue(row, yy_key, "error", f"{yy_key.upper()}_OUT_OF_RANGE",
                                f"{label}: ano fora do intervalo plausível ({MIN_YEAR}–{today.year}).", raw[2]))
            return issues
    if mm is not None and not 1 <= mm <= 12:
        issues.append(issue(row, mm_key, "error", f"{mm_key.upper()}_OUT_OF_RANGE", f"{label}: mês deve estar entre 1 e 12.", raw[1]))
        return issues
    if dd is not None and not 1 <= dd <= 31:
        issues.append(issue(row, dd_key, "error", f"{dd_key.upper()}_OUT_OF_RANGE", f"{label}: dia deve estar entre 1 e 31.", raw[0]))
        return issues
    if dd is not None and mm is not None and yy is not None:
        try:
            parsed = _dt.date(yy, mm, dd)
        except ValueError:
            code = "INVALID_DATE" if prefix == "coll" else "INVALID_DET_DATE"
            issues.append(issue(row, dd_key, "error", code, f"{label} inexistente no calendário: {shown}.", shown))
            return issues
        if parsed > today:
            issues.append(issue(row, yy_key, "error", "DATE_IN_FUTURE" if prefix == "coll" else "DET_DATE_IN_FUTURE",
                                f"{label} está no futuro: {shown}.", shown))
        return issues
    if not required and yy is None:
        issues.append(issue(row, yy_key, "warning", f"{yy_key.upper()}_MISSING", f"{label} incompleta: informe ao menos o ano.", shown))
    return issues


def validate_dates(record: dict[str, Any]) -> list[ValidationIssue]:
    issues = _validate_one_date(record, "coll", "Data de coleta", True)
    det = _validate_one_date(record, "det", "Data de determinação", False)
    issues.extend(det)
    # Determinação anterior à coleta
    try:
        coll = _dt.date(int(record["collyy"]), int(record["collmm"]), int(record["colldd"]))
        dety = _int_value(record.get("detyy"))
        if dety and dety < coll.year and not det:
            issues.append(issue(record["_row_number"], "detyy", "warning", "DET_BEFORE_COLLECTION",
                                "Ano de determinação anterior ao ano de coleta.", record.get("detyy")))
    except (KeyError, TypeError, ValueError):
        pass
    return issues


def _coord_issues(record: dict[str, Any], key: str, coord: Coordinate, label: str, limit: float) -> list[ValidationIssue]:
    row = record["_row_number"]
    if coord.fmt == "empty":
        return []
    if coord.fmt == "invalid":
        return [issue(row, key, "error", f"{key.upper()}_INVALID",
                      f"{label} não reconhecida. Use graus decimais (ex.: -0.1531).", coord.raw)]
    out: list[ValidationIssue] = []
    value = coord.value
    if value is not None and not -limit <= value <= limit:
        out.append(issue(row, key, "error", f"{key.upper()}_OUT_OF_RANGE",
                         f"{label} fora do intervalo -{limit:g} a {limit:g}.", coord.raw))
        return out
    if coord.fmt == "dms":
        out.append(issue(row, key, "warning", f"{key.upper()}_DMS_FORMAT",
                         f"{label} em graus/minutos/segundos; o padrão INPA usa graus decimais.", coord.raw,
                         suggestion=f"{value:.6f}"))
    elif coord.hemisphere and isinstance(coord.raw, str):
        out.append(issue(row, key, "warning", f"{key.upper()}_HEMISPHERE_IN_VALUE",
                         f"{label} com letra de hemisfério no valor; use apenas o número com sinal.", coord.raw,
                         suggestion=f"{value:g}"))
    elif coord.decimals is not None and coord.decimals <= 1 and value not in (0, None):
        out.append(issue(row, key, "info", f"{key.upper()}_LOW_PRECISION",
                         f"{label} com no máximo uma casa decimal (precisão de ~11 km). "
                         "Confira se a coordenada não foi arredondada.", coord.raw))
    return out


def validate_coordinates(record: dict[str, Any]) -> list[ValidationIssue]:
    row = record["_row_number"]
    lat: Coordinate = record.get("_lat") or parse_coordinate(record.get("lat"))
    lon: Coordinate = record.get("_long") or parse_coordinate(record.get("long"))
    issues = _coord_issues(record, "lat", lat, "Latitude", 90) + _coord_issues(record, "long", lon, "Longitude", 180)

    ns = norm(record.get("NS")).upper()
    ew = norm(record.get("EW")).upper()
    if ns and ns not in {"N", "S"}:
        issues.append(issue(row, "NS", "warning", "NS_INVALID", "Use N (Norte) ou S (Sul).", record.get("NS")))
    if ew and ew not in {"E", "W", "L", "O"}:
        issues.append(issue(row, "EW", "warning", "EW_INVALID", "Use E (Leste) ou W (Oeste).", record.get("EW")))
    if lat.value is not None and not lat.hemisphere:
        if ns == "S" and lat.value > 0:
            issues.append(issue(row, "lat", "warning", "NS_SIGN_MISMATCH",
                                "NS = S, mas a latitude está positiva; latitudes ao sul devem ter sinal negativo.",
                                lat.raw, suggestion=f"{-lat.value:g}"))
        elif ns == "N" and lat.value < 0:
            issues.append(issue(row, "lat", "warning", "NS_SIGN_MISMATCH",
                                "NS = N, mas a latitude está negativa.", lat.raw, suggestion=f"{-lat.value:g}"))
    if lon.value is not None and not lon.hemisphere:
        if ew in {"W", "O"} and lon.value > 0:
            issues.append(issue(row, "long", "warning", "EW_SIGN_MISMATCH",
                                "EW = W, mas a longitude está positiva; longitudes a oeste devem ter sinal negativo.",
                                lon.raw, suggestion=f"{-lon.value:g}"))
        elif ew in {"E", "L"} and lon.value < 0:
            issues.append(issue(row, "long", "warning", "EW_SIGN_MISMATCH",
                                "EW = E, mas a longitude está negativa.", lon.raw, suggestion=f"{-lon.value:g}"))
    return issues


def validate_inpa_conventions(record: dict[str, Any]) -> list[ValidationIssue]:
    """Convenções do template INPA/BRAHMS que costumam causar retrabalho na curadoria."""
    row = record["_row_number"]
    issues: list[ValidationIssue] = []

    number = record.get("number")
    if not _blank(number):
        n = norm(number)
        if n in _SN:
            issues.append(issue(row, "number", "warning", "NUMBER_SN",
                                "Evite \"s.n.\": use um número sequencial do coletor.", number))
        elif re.fullmatch(r"\d+\s*[a-zA-Z]", str(number).strip()):
            issues.append(issue(row, "number", "warning", "NUMBER_WITH_LETTER",
                                "Número de coleta com letra; use a coluna suffix para A, B, C...", number,
                                suggestion=re.sub(r"\D", "", str(number))))

    collector = record.get("collector")
    if not _blank(collector):
        text = str(collector)
        if ";" in text:
            issues.append(issue(row, "collector", "warning", "COLLECTOR_MULTIPLE",
                                "Informe somente o coletor principal; os demais vão em addcoll.", collector))
        elif not _COLLECTOR_FMT.match(text):
            issues.append(issue(row, "collector", "info", "COLLECTOR_FORMAT",
                                "Formato recomendado: Sobrenome, Iniciais (ex.: Silva, L.L.).", collector))

    sp1 = record.get("sp1")
    if not _blank(sp1):
        sp1_norm = norm(sp1)
        if sp1_norm in _SP_PLACEHOLDERS or re.fullmatch(r"sp\s*\d*|morfo\s*\w*", sp1_norm):
            issues.append(issue(row, "sp1", "warning", "SP1_PLACEHOLDER",
                                "Não escreva \"sp.\"/\"indet.\" no epíteto: deixe a coluna sp1 em branco.", sp1))

    detstatus = record.get("detstatus")
    if not _blank(detstatus):
        key = str(detstatus).strip().lower()
        if key not in _DETSTATUS_OK:
            issues.append(issue(row, "detstatus", "warning", "DETSTATUS_INVALID",
                                "Use somente \"cf.\" ou \"aff.\".", detstatus))
        elif _DETSTATUS_OK[key] != str(detstatus).strip():
            issues.append(issue(row, "detstatus", "info", "DETSTATUS_FORMAT", "Escreva com ponto final.", detstatus,
                                suggestion=_DETSTATUS_OK[key]))

    rank1, sp2 = record.get("rank1"), record.get("sp2")
    if not _blank(rank1):
        key = norm(rank1)
        if key not in _RANK_OK:
            issues.append(issue(row, "rank1", "warning", "RANK1_INVALID", "Use \"var.\" ou \"ssp.\".", rank1))
        elif _blank(sp2):
            issues.append(issue(row, "sp2", "warning", "SP2_MISSING", "rank1 preenchido, mas sp2 está vazio.", sp2))
    elif not _blank(sp2):
        issues.append(issue(row, "rank1", "warning", "RANK1_MISSING",
                            "sp2 preenchido, mas rank1 (var./ssp.) está vazio.", rank1))
    if not _blank(sp2) and _blank(sp1):
        issues.append(issue(row, "sp1", "error", "SP1_MISSING_FOR_SP2", "Epíteto infraespecífico sem epíteto específico.", sp1))
    if not _blank(sp1) and _blank(record.get("genus")):
        issues.append(issue(row, "genus", "error", "GENUS_MISSING_FOR_SP1", "Epíteto específico sem gênero.", sp1))

    for key in ("alt", "alt1"):
        value = record.get(key)
        if _blank(value) or isinstance(value, (int, float)):
            continue
        digits = re.sub(r"[^\d.,-]", "", str(value)).replace(",", ".")
        issues.append(issue(row, key, "warning", f"{key.upper()}_NOT_NUMERIC",
                            "Altitude deve conter somente o número em metros (sem \"m\").", value,
                            suggestion=digits or None))
    alt, alt1 = record.get("alt"), record.get("alt1")
    if isinstance(alt, (int, float)) and isinstance(alt1, (int, float)) and alt1 < alt:
        issues.append(issue(row, "alt1", "warning", "ALT1_LOWER_THAN_ALT", "Altitude máxima menor que a mínima.", alt1))

    if not _blank(record.get("accession")):
        issues.append(issue(row, "accession", "info", "ACCESSION_FILLED",
                            "accession costuma ficar em branco: o número de registro é atribuído pelo herbário.",
                            record.get("accession")))
    if not _blank(record.get("llunit")):
        issues.append(issue(row, "llunit", "info", "LLUNIT_FILLED", "No padrão INPA/BRAHMS, llunit fica em branco.",
                            record.get("llunit")))
    project = record.get("project")
    if not _blank(project) and len(str(project)) > 60:
        issues.append(issue(row, "project", "warning", "PROJECT_TOO_LONG",
                            f"Projeto com {len(str(project))} caracteres; o limite é 60.", project))
    return issues


def validate_basic_row(record: dict[str, Any]) -> list[ValidationIssue]:
    return (validate_required_fields(record) + validate_dates(record)
            + validate_coordinates(record) + validate_inpa_conventions(record))


# ---------------------------------------------------------------------------
# Regras entre linhas
# ---------------------------------------------------------------------------
def validate_duplicates(records: list[dict[str, Any]]) -> list[ValidationIssue]:
    """Mesmo coletor + prefixo + número + sufixo em mais de uma linha."""
    groups: dict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    for record in records:
        collector, number = norm(record.get("collector")), norm(record.get("number"))
        if not collector or not number or number in _SN:
            continue
        key = (collector, norm(record.get("prefix")), number, norm(record.get("suffix")))
        groups[key].append(record["_row_number"])
    issues: list[ValidationIssue] = []
    for key, rows in groups.items():
        if len(rows) < 2:
            continue
        for row in rows:
            others = ", ".join(str(r) for r in rows if r != row)
            issues.append(issue(row, "number", "error", "DUPLICATE_COLLECTION_NUMBER",
                                f"Coletor e número de coleta repetidos (linhas {others}). "
                                "Se for a mesma coleta dividida, use suffix (A, B...).", key[2]))
    return issues
