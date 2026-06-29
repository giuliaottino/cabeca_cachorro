from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.schemas.issues import ValidationIssue
from app.services.rule_engine import issue

SOURCE = "IBGE Malha Municipal Digital"
DEFAULT_DB = Path(__file__).resolve().parents[2] / "reference" / "ibge_geography.sqlite"


def _norm(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str):
            value = value.strip().replace(",", ".")
        return float(value)
    except Exception:
        return None


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DEFAULT_DB)
    con.row_factory = sqlite3.Row
    return con


def _metadata(con: sqlite3.Connection) -> dict[str, Any]:
    rows = con.execute("SELECT key, value FROM reference_metadata").fetchall()
    meta = {r["key"]: r["value"] for r in rows}
    for key in ("municipality_count", "state_count", "country_count"):
        if key in meta:
            try:
                meta[key] = int(meta[key])
            except Exception:
                pass
    return meta


def reference_status() -> dict[str, Any]:
    if not DEFAULT_DB.exists():
        return {
            "mode": "ibge_sqlite",
            "status": "missing",
            "path": str(DEFAULT_DB),
            "message": "Base geográfica IBGE ainda não foi construída.",
        }
    try:
        with _connect() as con:
            meta = _metadata(con)
        return {
            "mode": "ibge_sqlite",
            "status": "ready",
            "path": str(DEFAULT_DB),
            "source": meta.get("source", SOURCE),
            "source_url": meta.get("source_url"),
            "source_version": meta.get("source_version"),
            "created_at_utc": meta.get("created_at_utc"),
            "municipality_count": meta.get("municipality_count"),
            "state_count": meta.get("state_count"),
            "country_count": meta.get("country_count"),
        }
    except Exception as exc:
        return {
            "mode": "ibge_sqlite",
            "status": "error",
            "path": str(DEFAULT_DB),
            "message": str(exc),
        }


def _point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    n = len(ring)
    if n < 4:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        intersects = ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-15) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _point_in_geom(lon: float, lat: float, geom_json: str) -> bool:
    try:
        rings = json.loads(geom_json)
    except Exception:
        return False
    # Primeiro momento: qualquer anel contendo o ponto conta como dentro.
    # Isso evita dependência de GEOS/PostGIS no Hugging Face gratuito.
    return any(_point_in_ring(lon, lat, ring) for ring in rings)


@lru_cache(maxsize=512)
def _resolve_state(state_norm: str) -> dict[str, Any] | None:
    if not state_norm or not DEFAULT_DB.exists():
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT uf_sigla, uf_name, uf_code FROM ibge_state_alias WHERE alias = ?",
            (state_norm,),
        ).fetchone()
        if row:
            return dict(row)
        row = con.execute(
            "SELECT code AS uf_code, name AS uf_name, uf_sigla FROM ibge_admin WHERE level='state' AND norm_name = ? LIMIT 1",
            (state_norm,),
        ).fetchone()
        return dict(row) if row else None


@lru_cache(maxsize=4096)
def _resolve_municipality(muni_norm: str, uf_sigla: str | None = None) -> list[dict[str, Any]]:
    if not muni_norm or not DEFAULT_DB.exists():
        return []
    with _connect() as con:
        if uf_sigla:
            rows = con.execute(
                """
                SELECT * FROM ibge_admin
                WHERE level='municipality' AND norm_name = ? AND uf_sigla = ?
                ORDER BY name
                """,
                (muni_norm, uf_sigla),
            ).fetchall()
            if rows:
                return [dict(r) for r in rows]
        rows = con.execute(
            """
            SELECT * FROM ibge_admin
            WHERE level='municipality' AND norm_name = ?
            ORDER BY uf_sigla, name
            """,
            (muni_norm,),
        ).fetchall()
        return [dict(r) for r in rows]


def _find_containing(level: str, lat: float, lon: float) -> list[dict[str, Any]]:
    if not DEFAULT_DB.exists():
        return []
    with _connect() as con:
        rows = con.execute(
            """
            SELECT * FROM ibge_admin
            WHERE level = ?
              AND min_lon <= ? AND max_lon >= ?
              AND min_lat <= ? AND max_lat >= ?
            """,
            (level, lon, lon, lat, lat),
        ).fetchall()
    matches = []
    for row in rows:
        d = dict(row)
        if _point_in_geom(lon, lat, d["geom_json"]):
            matches.append(d)
    return matches


def _country_is_brazil(value: Any) -> bool:
    if value is None or value == "":
        return True
    n = _norm(value)
    return n in {"brasil", "brazil", "br"}


def validate_geography_ibge(record: dict[str, Any]) -> list[ValidationIssue]:
    row = record.get("_row_number")
    country = record.get("country")
    majorarea = record.get("majorarea")
    minorarea = record.get("minorarea")
    lat_raw = record.get("lat")
    lon_raw = record.get("long")
    ns = record.get("NS") or record.get("ns")
    ew = record.get("EW") or record.get("ew")
    issues: list[ValidationIssue] = []

    if not DEFAULT_DB.exists():
        return [issue(
            row, "_row", "warning", "IBGE_REFERENCE_MISSING",
            "Base geográfica IBGE ainda não está disponível no servidor.",
            None,
            source=SOURCE,
        )]

    if country and not _country_is_brazil(country):
        issues.append(issue(
            row, "country", "warning", "COUNTRY_NOT_BRAZIL",
            "País informado não é Brasil/Brazil; a validação geográfica atual usa a malha territorial do IBGE para o Brasil.",
            country,
            suggestion="Brasil",
            source=SOURCE,
        ))

    state = _resolve_state(_norm(majorarea)) if majorarea else None
    if majorarea and not state:
        issues.append(issue(
            row, "majorarea", "warning", "STATE_NOT_FOUND_IBGE",
            "Estado/UF não encontrado na base do IBGE.",
            majorarea,
            source=SOURCE,
        ))

    uf_sigla = state.get("uf_sigla") if state else None
    muni_matches = _resolve_municipality(_norm(minorarea), uf_sigla) if minorarea else []
    muni_any_state = _resolve_municipality(_norm(minorarea), None) if minorarea else []

    if minorarea and not muni_any_state:
        issues.append(issue(
            row, "minorarea", "warning", "MUNICIPALITY_NOT_FOUND_IBGE",
            "Município não encontrado na Malha Municipal do IBGE.",
            minorarea,
            source=SOURCE,
        ))
    elif minorarea and state and not muni_matches:
        suggestions = sorted({f"{m['name']} - {m.get('uf_sigla') or ''}" for m in muni_any_state})
        issues.append(issue(
            row, "minorarea", "error", "MUNICIPALITY_STATE_MISMATCH",
            "Município encontrado no IBGE, mas não pertence ao estado/UF informado.",
            minorarea,
            suggestion=", ".join(suggestions[:5]) if suggestions else None,
            source=SOURCE,
        ))

    lat = _as_float(lat_raw)
    lon = _as_float(lon_raw)
    if lat_raw not in (None, "") and lat is None:
        issues.append(issue(row, "lat", "error", "INVALID_LATITUDE", "Latitude não é numérica.", lat_raw, source=SOURCE))
    if lon_raw not in (None, "") and lon is None:
        issues.append(issue(row, "long", "error", "INVALID_LONGITUDE", "Longitude não é numérica.", lon_raw, source=SOURCE))

    if lat is None or lon is None:
        return issues

    if not (-90 <= lat <= 90):
        issues.append(issue(row, "lat", "error", "LATITUDE_OUT_OF_RANGE", "Latitude fora do intervalo -90 a 90.", lat_raw, source=SOURCE))
    if not (-180 <= lon <= 180):
        issues.append(issue(row, "long", "error", "LONGITUDE_OUT_OF_RANGE", "Longitude fora do intervalo -180 a 180.", lon_raw, source=SOURCE))
    if issues and any(i.code in {"LATITUDE_OUT_OF_RANGE", "LONGITUDE_OUT_OF_RANGE"} for i in issues):
        return issues

    if ns and str(ns).strip().upper().startswith("S") and lat > 0:
        issues.append(issue(row, "NS", "warning", "NS_SIGN_MISMATCH", "Campo NS indica Sul, mas latitude está positiva.", ns, suggestion="Latitude negativa ou NS=N", source=SOURCE))
    if ns and str(ns).strip().upper().startswith("N") and lat < 0:
        issues.append(issue(row, "NS", "warning", "NS_SIGN_MISMATCH", "Campo NS indica Norte, mas latitude está negativa.", ns, suggestion="Latitude positiva ou NS=S", source=SOURCE))
    if ew and str(ew).strip().upper().startswith("W") and lon > 0:
        issues.append(issue(row, "EW", "warning", "EW_SIGN_MISMATCH", "Campo EW indica Oeste, mas longitude está positiva.", ew, suggestion="Longitude negativa ou EW=E", source=SOURCE))
    if ew and str(ew).strip().upper().startswith("E") and lon < 0:
        issues.append(issue(row, "EW", "warning", "EW_SIGN_MISMATCH", "Campo EW indica Leste, mas longitude está negativa.", ew, suggestion="Longitude positiva ou EW=W", source=SOURCE))

    containing_munis = _find_containing("municipality", lat, lon)
    containing_states = _find_containing("state", lat, lon)

    if not containing_munis and not containing_states:
        swapped_munis = _find_containing("municipality", lon, lat) if -90 <= lon <= 90 and -180 <= lat <= 180 else []
        if swapped_munis:
            m = swapped_munis[0]
            issues.append(issue(
                row, "lat", "error", "LAT_LONG_POSSIBLY_SWAPPED",
                "A coordenada não cai no Brasil como informada, mas cai se latitude e longitude forem invertidas.",
                f"{lat}, {lon}",
                suggestion=f"lat={lon}, long={lat} ({m['name']} - {m.get('uf_sigla')})",
                source=SOURCE,
            ))
        else:
            issues.append(issue(
                row, "lat", "error", "POINT_OUTSIDE_BRAZIL",
                "Coordenada não cai na Malha Municipal/UF do IBGE para o Brasil.",
                f"{lat}, {lon}",
                source=SOURCE,
            ))
        return issues

    actual_state_siglas = {m.get("uf_sigla") for m in containing_munis if m.get("uf_sigla")}
    actual_state_siglas.update({s.get("uf_sigla") for s in containing_states if s.get("uf_sigla")})

    if state and uf_sigla and actual_state_siglas and uf_sigla not in actual_state_siglas:
        suggestion = ", ".join(sorted(actual_state_siglas))
        issues.append(issue(
            row, "majorarea", "error", "POINT_OUTSIDE_STATE",
            "Coordenada não cai dentro do estado/UF informado segundo a malha do IBGE.",
            f"{lat}, {lon}",
            suggestion=suggestion,
            source=SOURCE,
        ))

    if minorarea and muni_matches:
        expected_codes = {m.get("code") for m in muni_matches}
        actual_codes = {m.get("code") for m in containing_munis}
        if expected_codes and actual_codes and not (expected_codes & actual_codes):
            suggestions = sorted({f"{m['name']} - {m.get('uf_sigla') or ''}" for m in containing_munis})
            issues.append(issue(
                row, "minorarea", "error", "POINT_OUTSIDE_MUNICIPALITY",
                "Coordenada não cai dentro do município informado segundo a malha do IBGE.",
                f"{lat}, {lon}",
                suggestion=", ".join(suggestions[:5]) if suggestions else None,
                source=SOURCE,
            ))

    return issues
