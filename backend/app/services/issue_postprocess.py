# -*- coding: utf-8 -*-
"""Normalização final das ocorrências: remoção de duplicatas e ordenação estável."""
from __future__ import annotations

from typing import Any

from app.schemas.issues import ValidationIssue

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}

# Quando a regra estrutural já acusou o problema, a mensagem redundante sai.
_SUPERSEDED_BY = {
    # coluna com erro de coordenada => não repetir "fora do Brasil" etc.
    "LAT_INVALID": {"POINT_OUTSIDE_BRAZIL"},
    "LONG_INVALID": {"POINT_OUTSIDE_BRAZIL"},
}


def postprocess_issues(issues: list[ValidationIssue | dict[str, Any]], table: Any = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    codes_by_row: dict[Any, set[str]] = {}
    items = [i.model_dump() if isinstance(i, ValidationIssue) else dict(i) for i in issues]
    for item in items:
        codes_by_row.setdefault(item.get("row_number"), set()).add(item.get("code"))
    for item in items:
        row = item.get("row_number")
        code = item.get("code")
        if any(code in drop and src in codes_by_row.get(row, set()) for src, drop in _SUPERSEDED_BY.items()):
            continue
        key = (row, item.get("column_name"), code, item.get("message"))
        if key in seen:
            continue
        seen.add(key)
        item.pop("payload", None)
        out.append(item)
    out.sort(key=lambda i: (i.get("row_number") is not None, i.get("row_number") or 0,
                            SEVERITY_ORDER.get(i.get("severity"), 3)))
    return out
