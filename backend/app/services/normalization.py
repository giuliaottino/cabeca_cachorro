import re
import unicodedata
from typing import Any


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize('NFKD', value)
    return ''.join(char for char in normalized if not unicodedata.combining(char))


def normalize_key(value: str) -> str:
    value = strip_accents(str(value or '')).lower().strip()
    value = re.sub(r'[^a-z0-9]+', '_', value)
    value = re.sub(r'_+', '_', value).strip('_')
    return value


def clean_cell(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == '' or text.lower() in {'nan', 'none', 'na'}:
        return None
    return text


def to_float(value: Any) -> float | None:
    text = clean_cell(value)
    if text is None:
        return None
    text = text.replace(',', '.')
    text = re.sub(r'[^0-9+\-.]', '', text)
    if text in {'', '+', '-', '.', '+.', '-.'}:
        return None
    try:
        return float(text)
    except ValueError:
        return None
