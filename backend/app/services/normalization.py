"""Funções de normalização compartilhadas por leitura, regras e referências."""
from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from typing import Any

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SPACES = re.compile(r"\s+")
NULL_TOKENS = {"nan", "none", "null", "na", "n/a", "-", "--"}


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def norm(value: Any) -> str:
    """Minúsculas, sem acentos, só [a-z0-9] separados por um espaço."""
    if value is None:
        return ""
    text = strip_accents(str(value).replace("﻿", "").replace("\xa0", " ")).lower()
    return _SPACES.sub(" ", _NON_ALNUM.sub(" ", text)).strip()


def normalize_key(value: Any) -> str:
    return norm(value).replace(" ", "_")


def clean_cell(value: Any) -> Any:
    """Normaliza o valor lido do openpyxl preservando o tipo quando útil.

    - textos: aparados; vazios e marcadores de nulo viram None;
    - floats inteiros (12.0) viram int (12) para não gerar "12.0" em número de coleta e datas;
    - datas são mantidas como date/datetime.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.replace("\xa0", " ").strip()
        if not text or text.lower() in NULL_TOKENS:
            return None
        return text
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        if value.is_integer():
            return int(value)
    return value


def cell_text(value: Any) -> str:
    """Representação textual estável de uma célula (para JSON e comparação)."""
    value = clean_cell(value)
    if value is None:
        return ""
    if isinstance(value, _dt.datetime):
        if value.time() == _dt.time(0, 0):
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, _dt.date):
        return value.isoformat()
    return str(value)


def json_value(value: Any) -> Any:
    """Valor serializável em JSON, sem perder números."""
    value = clean_cell(value)
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    return cell_text(value)


# ---------------------------------------------------------------------------
# Coordenadas
# ---------------------------------------------------------------------------
_DMS_RE = re.compile(
    r"""^\s*(?P<h1>[NSEWLO])?\s*
        (?P<deg>[+-]?\d+(?:[.,]\d+)?)\s*(?:°|º|o|d|deg|\s)\s*
        (?:(?P<min>\d+(?:[.,]\d+)?)\s*(?:'|′|’|m|min|\s)\s*)?
        (?:(?P<sec>\d+(?:[.,]\d+)?)\s*(?:"|″|”|''|s|seg|sec)?\s*)?
        (?P<h2>[NSEWLO])?\s*$""",
    re.IGNORECASE | re.VERBOSE,
)
_DECIMAL_RE = re.compile(r"^\s*(?P<h1>[NSEWLO])?\s*(?P<num>[+-]?\d+(?:[.,]\d+)?)\s*°?\s*(?P<h2>[NSEWLO])?\s*$", re.I)


class Coordinate:
    __slots__ = ("value", "fmt", "hemisphere", "decimals", "raw")

    def __init__(self, value: float | None, fmt: str, hemisphere: str | None, decimals: int | None, raw: Any):
        self.value = value
        self.fmt = fmt  # 'decimal' | 'dms' | 'invalid' | 'empty'
        self.hemisphere = hemisphere
        self.decimals = decimals
        self.raw = raw


def _num(text: str | None) -> float:
    return float(str(text).replace(",", ".")) if text else 0.0


def parse_coordinate(value: Any) -> Coordinate:
    """Interpreta graus decimais (com vírgula ou ponto) e GMS (ex.: 0°9'11" S)."""
    raw = clean_cell(value)
    if raw is None:
        return Coordinate(None, "empty", None, None, value)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        text = repr(float(raw))
        decimals = 0 if isinstance(raw, int) else len(text.split(".")[1].rstrip("0")) if "." in text else 0
        return Coordinate(float(raw), "decimal", None, decimals, value)

    text = str(raw).strip()
    m = _DECIMAL_RE.match(text)
    if m:
        hemi = (m.group("h1") or m.group("h2") or "").upper() or None
        num = m.group("num").replace(",", ".")
        val = float(num)
        if hemi in {"S", "W", "O"} and val > 0:
            val = -val
        decimals = len(num.split(".")[1]) if "." in num else 0
        return Coordinate(val, "decimal", hemi, decimals, value)

    m = _DMS_RE.match(text.replace("''", '"'))
    if m and (m.group("min") or m.group("sec")):
        deg = _num(m.group("deg"))
        minutes = _num(m.group("min"))
        seconds = _num(m.group("sec"))
        if minutes >= 60 or seconds >= 60:
            return Coordinate(None, "invalid", None, None, value)
        val = abs(deg) + minutes / 60 + seconds / 3600
        hemi = (m.group("h1") or m.group("h2") or "").upper() or None
        if deg < 0 or hemi in {"S", "W", "O"}:
            val = -val
        return Coordinate(round(val, 6), "dms", hemi, 6, value)

    return Coordinate(None, "invalid", None, None, value)


def to_float(value: Any) -> float | None:
    return parse_coordinate(value).value
