# -*- coding: utf-8 -*-
"""Normalizacao final das ocorrencias de validacao do Tsiino."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

# TSIINO_ISSUE_GEO_V39B

DROP_CODES = {
    "TAXONOMY_LOCAL_FIXTURE",
    "GEOGRAPHY_LOCAL_FIXTURE",
    "TAXON_EMPTY",
}

TAXON_CODES = {
    "TAXONOMY_FAMILY_MISMATCH",
    "TAXON_FAMILY_GENUS_MISMATCH",
    "TAXONOMY_GENUS_NOT_FOUND",
    "TAXON_GENUS_NOT_FOUND",
    "TAXONOMY_SPECIES_NOT_FOUND",
    "TAXON_SPECIES_NOT_FOUND",
}

GEO_CODES = {
    "NS_SIGN_MISMATCH",
    "EW_SIGN_MISMATCH",
    "POINT_OUTSIDE_MUNICIPALITY",
    "POINT_OUTSIDE_STATE",
    "POINT_OUTSIDE_UF",
    "GEOGRAPHY_COORDINATE_MUNICIPALITY_SUGGESTION",
    "INVALID_LATITUDE",
    "INVALID_LONGITUDE",
    "LATITUDE_OUT_OF_RANGE",
    "LONGITUDE_OUT_OF_RANGE",
    "LAT_OUT_OF_RANGE",
    "LONG_OUT_OF_RANGE",
    "MUNICIPALITY_NOT_FOUND",
    "STATE_NOT_FOUND",
    "COUNTRY_NOT_BRAZIL",
}

FIELD_BY_CODE = {
    "TAXONOMY_FAMILY_MISMATCH": "family",
    "TAXON_FAMILY_GENUS_MISMATCH": "family",
    "TAXONOMY_GENUS_NOT_FOUND": "genus",
    "TAXON_GENUS_NOT_FOUND": "genus",
    "TAXONOMY_SPECIES_NOT_FOUND": "sp1",
    "TAXON_SPECIES_NOT_FOUND": "sp1",
    "NS_SIGN_MISMATCH": "lat",
    "EW_SIGN_MISMATCH": "long",
    "POINT_OUTSIDE_MUNICIPALITY": "minorarea",
    "POINT_OUTSIDE_STATE": "majorarea",
    "POINT_OUTSIDE_UF": "majorarea",
    "GEOGRAPHY_COORDINATE_MUNICIPALITY_SUGGESTION": "minorarea",
    "INVALID_LATITUDE": "lat",
    "INVALID_LONGITUDE": "long",
    "LATITUDE_OUT_OF_RANGE": "lat",
    "LONGITUDE_OUT_OF_RANGE": "long",
    "LAT_OUT_OF_RANGE": "lat",
    "LONG_OUT_OF_RANGE": "long",
    "MUNICIPALITY_NOT_FOUND": "minorarea",
    "STATE_NOT_FOUND": "majorarea",
    "COUNTRY_NOT_BRAZIL": "country",
}

CANONICAL_FIELDS = {
    "accession", "collector", "prefix", "number", "suffix", "addcoll",
    "colldd", "collmm", "collyy", "initial", "family", "genus",
    "detstatus", "sp1", "rank1", "sp2", "detby", "detdd", "detmm",
    "detyy", "country", "majorarea", "minorarea", "gazetteer", "locnotes",
    "habitattxt", "lat", "NS", "long", "EW", "llunit", "alt", "alt1",
    "plantdesc", "vernacular", "dups", "project", "genbank",
}

_FIELD_NORM = {f.lower(): f for f in CANONICAL_FIELDS}
_FIELD_NORM.update({"latitude": "lat", "longitude": "long", "municipio": "minorarea", "estado": "majorarea", "uf": "majorarea"})


def _norm_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


def _to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        data = dict(item)
    elif hasattr(item, "model_dump"):
        data = item.model_dump()
    elif hasattr(item, "dict"):
        data = item.dict()
    else:
        data = {
            "row_number": getattr(item, "row_number", None),
            "column_name": getattr(item, "column_name", None),
            "field": getattr(item, "field", None),
            "column": getattr(item, "column", None),
            "severity": getattr(item, "severity", None),
            "code": getattr(item, "code", None),
            "message": getattr(item, "message", None),
            "value": getattr(item, "value", None),
            "suggestion": getattr(item, "suggestion", None),
            "source": getattr(item, "source", None),
        }
    return data


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _row_number(data: dict[str, Any]) -> int | None:
    for key in ("row_number", "row", "linha", "line_number", "_row_number", "_ROW_NUMBER"):
        value = _as_int(data.get(key))
        if value is not None:
            return value
    return None


def _field(data: dict[str, Any]) -> str | None:
    for key in ("column_name", "field", "column", "campo", "col"):
        value = data.get(key)
        if value:
            raw = str(value).strip()
            return _FIELD_NORM.get(raw.lower(), raw)
    code = str(data.get("code") or "").strip()
    if code in FIELD_BY_CODE:
        return FIELD_BY_CODE[code]
    if code.endswith("_REQUIRED"):
        base = code[:-9].lower()
        return _FIELD_NORM.get(base, base if base in CANONICAL_FIELDS else None)
    return None


def _message(data: dict[str, Any]) -> str:
    msg = str(data.get("message") or data.get("detail") or "")
    repl = {
        "Fam├¡lia": "Família", "g├¬nero": "gênero", "determina├º├úo": "determinação",
        "n├úo": "não", "est├í": "está", "munic├¡pio": "município", "geogr├ífico": "geográfico",
        "valida├º├úo": "validação", "taxon├┤mica": "taxonômica",
    }
    for a, b in repl.items():
        msg = msg.replace(a, b)
    return msg


def _is_taxon_or_geo(code: str, msg: str) -> bool:
    if code in TAXON_CODES or code in GEO_CODES:
        return True
    text = _norm_text(msg)
    return any(w in text for w in ("flora", "fung", "genero", "especie", "familia", "coordenad", "latitude", "longitude", "municip", "ibge"))


def _same_municipality_suggestion(msg: str) -> bool:
    text = _norm_text(msg)
    m = re.search(r"cai em\s+(.+?)\s*\([^)]*\),\s*nao em\s+(.+?)\s*\([^)]*\)", text)
    if not m:
        return False
    return _norm_text(m.group(1)) == _norm_text(m.group(2))


def _canonical_duplicate_key(data: dict[str, Any]) -> tuple[Any, ...]:
    row = data.get("row_number")
    col = data.get("column_name")
    code = str(data.get("code") or "")
    msg = _norm_text(data.get("message"))
    if code == "NS_SIGN_MISMATCH":
        msg = "ns_sign_mismatch"
    elif code == "EW_SIGN_MISMATCH":
        msg = "ew_sign_mismatch"
    elif code in {"POINT_OUTSIDE_MUNICIPALITY", "POINT_OUTSIDE_STATE", "POINT_OUTSIDE_UF"}:
        msg = code.lower()
    return (row, col, code, msg)


def _table_index(table: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for idx, row in enumerate(table or [], start=1):
        if not isinstance(row, dict):
            continue
        number = _as_int(row.get("_row_number") or row.get("_ROW_NUMBER") or row.get("row_number") or row.get("LINHA"))
        if number is None:
            number = idx
        out[number] = row
    return out


def _drop_obvious_wrong_taxon(data: dict[str, Any], table_by_row: dict[int, dict[str, Any]]) -> bool:
    code = str(data.get("code") or "")
    row = _as_int(data.get("row_number"))
    if row is None or code not in TAXON_CODES:
        return False
    rec = table_by_row.get(row, {})
    family = str(rec.get("family") or "").strip()
    genus = str(rec.get("genus") or "").strip()
    sp1 = str(rec.get("sp1") or "").strip()
    msg = str(data.get("message") or "")

    if not genus:
        return True
    if code in {"TAXONOMY_SPECIES_NOT_FOUND", "TAXON_SPECIES_NOT_FOUND"} and not sp1:
        return True

    if code in {"TAXONOMY_SPECIES_NOT_FOUND", "TAXON_SPECIES_NOT_FOUND"}:
        sug = str(data.get("suggestion") or "") or msg
        m = re.search(r"Sugest(?:ao|ão):\s*([A-ZÁ-ÚA-Za-zá-ú]+)", sug)
        if m and genus and _norm_text(m.group(1)) != _norm_text(genus):
            return True

    if code in {"TAXONOMY_FAMILY_MISMATCH", "TAXON_FAMILY_GENUS_MISMATCH"} and family and genus:
        text = _norm_text(msg)
        if _norm_text(genus) not in text and _norm_text(family) not in text:
            return True
    return False


def postprocess_issues(issues: list[Any], table: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    table_by_row = _table_index(table or [])
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for item in issues or []:
        data = _to_dict(item)
        code = str(data.get("code") or "").strip()
        msg = _message(data)
        if code in DROP_CODES:
            continue
        if code == "TAXON_EMPTY" or "Família e gênero estão vazios" in msg or "Familia e genero estao vazios" in msg:
            continue
        if code == "GEOGRAPHY_COORDINATE_MUNICIPALITY_SUGGESTION" and _same_municipality_suggestion(msg):
            continue

        row = _row_number(data)
        col = _field(data)

        if _is_taxon_or_geo(code, msg) and row is None:
            continue

        if col is None:
            if _is_taxon_or_geo(code, msg):
                continue
            col = data.get("column_name") or data.get("field") or data.get("column")

        norm = dict(data)
        norm["row_number"] = row
        norm["column_name"] = col
        norm["field"] = col
        norm["column"] = col
        norm["message"] = msg

        if _drop_obvious_wrong_taxon(norm, table_by_row):
            continue

        key = _canonical_duplicate_key(norm)
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)

    return out
