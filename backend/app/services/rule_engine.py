from datetime import date
from typing import Any

from app.schemas.issues import ValidationIssue


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ''


def issue(row: int | None, column: str | None, severity: str, code: str, message: str,
          value: Any = None, suggestion: str | None = None, source: str | None = None) -> ValidationIssue:
    return ValidationIssue(
        row_number=row,
        column_name=column,
        severity=severity,  # type: ignore[arg-type]
        code=code,
        message=message,
        value=None if value is None else str(value),
        suggestion=suggestion,
        source=source,
    )


def validate_structure(records: list[dict[str, Any]], missing_minimum: list[str], unknown_headers: list[str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for col in missing_minimum:
        issues.append(issue(None, col, 'error', 'MISSING_COLUMN', f'Coluna obrigatória ausente: {col}.'))
    for col in unknown_headers:
        issues.append(issue(None, col, 'info', 'UNKNOWN_COLUMN', f'Coluna não reconhecida: {col}.'))
    if not records:
        issues.append(issue(None, None, 'error', 'NO_DATA_ROWS', 'A planilha não contém linhas de dados após o cabeçalho.'))
    return issues


def validate_required_fields(record: dict[str, Any]) -> list[ValidationIssue]:
    row = record['_row_number']
    required = {
        'collector': 'Coletor é obrigatório.',
        'number': 'Número de coleta é obrigatório.',
        'colldd': 'Dia de coleta é obrigatório.',
        'collmm': 'Mês de coleta é obrigatório.',
        'collyy': 'Ano de coleta é obrigatório.',
        'country': 'País é obrigatório.',
        'majorarea': 'Estado/área maior é obrigatório.',
        'minorarea': 'Município/área menor é obrigatório.',
        'lat': 'Latitude é obrigatória.',
        'long': 'Longitude é obrigatória.',
        'plantdesc': 'Descrição da planta é obrigatória.',
    }
    issues: list[ValidationIssue] = []
    for col, message in required.items():
        if _is_blank(record.get(col)):
            issues.append(issue(row, col, 'error', f'{col.upper()}_REQUIRED', message, record.get(col)))

    if _is_blank(record.get('genus')) and _is_blank(record.get('family')):
        issues.append(issue(row, 'genus', 'warning', 'TAXON_EMPTY', 'Família e gênero estão vazios; a determinação ficará incompleta.'))
    return issues


def validate_date(record: dict[str, Any]) -> list[ValidationIssue]:
    row = record['_row_number']
    issues: list[ValidationIssue] = []
    dd, mm, yy = record.get('colldd'), record.get('collmm'), record.get('collyy')
    if any(_is_blank(x) for x in [dd, mm, yy]):
        return issues
    try:
        year = int(str(yy))
        if year < 100:
            year += 2000 if year < 50 else 1900
        parsed = date(year, int(str(mm)), int(str(dd)))
        if parsed > date.today():
            issues.append(issue(row, 'collyy', 'warning', 'DATE_IN_FUTURE', 'Data de coleta está no futuro.', f'{dd}/{mm}/{yy}'))
    except Exception:
        issues.append(issue(row, 'colldd', 'error', 'INVALID_DATE', 'Data de coleta inválida.', f'{dd}/{mm}/{yy}'))
    return issues


def validate_coordinates(record: dict[str, Any]) -> list[ValidationIssue]:
    row = record['_row_number']
    issues: list[ValidationIssue] = []
    lat = record.get('lat')
    lon = record.get('long')

    if lat is not None and not (-90 <= lat <= 90):
        issues.append(issue(row, 'lat', 'error', 'LAT_OUT_OF_RANGE', 'Latitude fora do intervalo -90 a 90.', lat))
    if lon is not None and not (-180 <= lon <= 180):
        issues.append(issue(row, 'long', 'error', 'LONG_OUT_OF_RANGE', 'Longitude fora do intervalo -180 a 180.', lon))

    country = str(record.get('country') or '').lower()
    if 'brasil' in country or 'brazil' in country:
        if lat is not None and lat > 6:
            issues.append(issue(row, 'lat', 'warning', 'LAT_SUSPICIOUS_BRAZIL', 'Latitude positiva é suspeita para a maioria das coletas no Brasil.', lat))
        if lon is not None and lon > 0:
            issues.append(issue(row, 'long', 'warning', 'LONG_SUSPICIOUS_BRAZIL', 'Longitude positiva é suspeita para coletas no Brasil.', lon))

    ns = str(record.get('NS') or record.get('ns') or '').strip().upper()
    ew = str(record.get('EW') or record.get('ew') or '').strip().upper()
    if ns == 'S' and lat is not None and lat > 0:
        issues.append(issue(row, 'NS', 'warning', 'NS_SIGN_MISMATCH', 'Campo NS=S, mas latitude está positiva.', ns))
    if ew == 'W' and lon is not None and lon > 0:
        issues.append(issue(row, 'EW', 'warning', 'EW_SIGN_MISMATCH', 'Campo EW=W, mas longitude está positiva.', ew))
    return issues


def validate_basic_row(record: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issues.extend(validate_required_fields(record))
    issues.extend(validate_date(record))
    issues.extend(validate_coordinates(record))
    return issues

# TSIINO_RULE_ENGINE_DEDUPE_V25
# Dedupe de mensagens repetidas por campo/linha e supressao de alertas taxonomicos amplos
# para identificacao vazia. Nao altera validacao geografica real.
def _tsiino_re_norm_v25(value):
    import re as _re
    import unicodedata as _unicodedata
    if value is None:
        return ""
    s = str(value).strip()
    s = _unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not _unicodedata.combining(ch))
    s = _re.sub(r"\s+", " ", s).strip().lower()
    return s


def _tsiino_re_issue_text_v25(obj):
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


def _tsiino_re_issue_field_v25(obj):
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


def _tsiino_re_dedupe_v25(items):
    out = []
    seen = set()
    for item in items or []:
        text = _tsiino_re_norm_v25(_tsiino_re_issue_text_v25(item))
        field = _tsiino_re_norm_v25(_tsiino_re_issue_field_v25(item))
        # Evita repetir "Longitude é obrigatória" 4-5 vezes na mesma celula.
        key = (field, text)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out

for _tsiino_name_v25 in ("validate_basic_row", "validate_structure", "validate_required_fields", "validate_coordinates"):
    if _tsiino_name_v25 in globals():
        _tsiino_original = globals()[_tsiino_name_v25]
        def _tsiino_make_wrapper_v25(fn):
            def _wrapper(*args, **kwargs):
                return _tsiino_re_dedupe_v25(fn(*args, **kwargs))
            return _wrapper
        globals()[_tsiino_name_v25] = _tsiino_make_wrapper_v25(_tsiino_original)
