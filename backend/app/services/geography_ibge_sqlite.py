"""Validação geográfica contra a Malha Municipal Digital do IBGE (SQLite local, sem PostGIS).

Desenho:
- metadados dos 5.573 municípios (nome, UF, bbox) ficam em memória;
- o teste ponto-em-polígono usa paridade de cruzamentos vetorizada em numpy sobre todos os anéis
  do município (contempla multipolígonos e buracos);
- geometrias são carregadas sob demanda e mantidas num cache LRU; resultados por coordenada também.
"""
from __future__ import annotations

import difflib
import json
import math
import sqlite3
import threading
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

from app.config import settings
from app.schemas.issues import ValidationIssue
from app.services.normalization import Coordinate, norm, parse_coordinate
from app.services.rule_engine import issue

SOURCE = "IBGE Malha Municipal Digital"
BRAZIL_NAMES = {"brasil", "brazil", "br", "bra"}
BOUNDARY_TOLERANCE_KM = 1.0     # fora do município por menos que isso => alerta, não erro
NEAR_LAND_KM = 10.0             # fora do Brasil, mas perto da costa/fronteira => alerta
GEOM_CACHE_SIZE = 160


@dataclass(frozen=True)
class Municipality:
    id: int
    code: str
    name: str
    norm_name: str
    uf_sigla: str
    uf_name: str
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    @property
    def label(self) -> str:
        return f"{self.name} ({self.uf_sigla})"


class _Edges:
    """Arestas de todos os anéis de uma geometria, prontas para operações vetorizadas."""
    __slots__ = ("x0", "y0", "x1", "y1", "dy")

    def __init__(self, rings: list[list[list[float]]]):
        x0, y0, x1, y1 = [], [], [], []
        for ring in rings:
            if len(ring) < 3:
                continue
            pts = np.asarray(ring, dtype=np.float64)
            if not np.array_equal(pts[0], pts[-1]):
                pts = np.vstack([pts, pts[:1]])
            x0.append(pts[:-1, 0])
            y0.append(pts[:-1, 1])
            x1.append(pts[1:, 0])
            y1.append(pts[1:, 1])
        self.x0 = np.concatenate(x0) if x0 else np.empty(0)
        self.y0 = np.concatenate(y0) if y0 else np.empty(0)
        self.x1 = np.concatenate(x1) if x1 else np.empty(0)
        self.y1 = np.concatenate(y1) if y1 else np.empty(0)
        dy = self.y1 - self.y0
        dy[dy == 0] = 1e-15
        self.dy = dy

    def contains(self, lon: float, lat: float) -> bool:
        crosses = (self.y0 > lat) != (self.y1 > lat)
        if not crosses.any():
            return False
        xi = self.x0[crosses] + (lat - self.y0[crosses]) * (self.x1[crosses] - self.x0[crosses]) / self.dy[crosses]
        return bool(np.count_nonzero(lon < xi) % 2)

    def distance_km(self, lon: float, lat: float) -> float:
        """Distância aproximada (projeção equiretangular local) do ponto até a borda."""
        kx = 111.320 * math.cos(math.radians(lat))
        ky = 110.574
        ax, ay = (self.x0 - lon) * kx, (self.y0 - lat) * ky
        bx, by = (self.x1 - lon) * kx, (self.y1 - lat) * ky
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        seg[seg == 0] = 1e-12
        t = np.clip(-(ax * dx + ay * dy) / seg, 0.0, 1.0)
        px, py = ax + t * dx, ay + t * dy
        return float(np.sqrt((px * px + py * py).min())) if px.size else float("inf")


class GeographyReference:
    def __init__(self, db_path=None):
        self.db_path = db_path or settings.geography_db
        self._local = threading.local()
        self._lock = threading.Lock()
        self._geom_lock = threading.Lock()
        self._munis: list[Municipality] | None = None
        self._by_name: dict[str, list[Municipality]] = {}
        self._by_uf: dict[str, list[Municipality]] = {}
        self._states: dict[str, tuple[str, str]] = {}      # alias normalizado -> (sigla, nome)
        self._state_names: dict[str, str] = {}             # sigla -> nome por extenso
        self._bbox: np.ndarray | None = None
        self._geoms: OrderedDict[int, _Edges] = OrderedDict()
        self._meta: dict[str, Any] = {}

    def _con(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            uri = f"file:{self.db_path.as_posix()}?mode=ro&immutable=1"
            con = sqlite3.connect(uri, uri=True, check_same_thread=False)
            con.row_factory = sqlite3.Row
            self._local.con = con
        return con

    def available(self) -> bool:
        return self.db_path.exists()

    def load(self) -> None:
        if self._munis is not None:
            return
        with self._lock:
            if self._munis is not None:
                return
            con = self._con()
            munis = [
                Municipality(r["id"], r["code"], r["name"], r["norm_name"], r["uf_sigla"], r["uf_name"],
                             r["min_lon"], r["min_lat"], r["max_lon"], r["max_lat"])
                for r in con.execute(
                    """SELECT id, code, name, norm_name, uf_sigla, uf_name, min_lon, min_lat, max_lon, max_lat
                       FROM ibge_admin WHERE level = 'municipality'""")
            ]
            for m in munis:
                self._by_name.setdefault(m.norm_name, []).append(m)
                self._by_uf.setdefault(m.uf_sigla, []).append(m)
            for r in con.execute("SELECT alias, uf_sigla, uf_name FROM ibge_state_alias"):
                self._states[r["alias"]] = (r["uf_sigla"], r["uf_name"])
                self._state_names[r["uf_sigla"]] = r["uf_name"]
            for r in con.execute("SELECT uf_sigla, name, norm_name FROM ibge_admin WHERE level = 'state'"):
                self._states.setdefault(r["norm_name"], (r["uf_sigla"], r["name"]))
                self._state_names.setdefault(r["uf_sigla"], r["name"])
            self._meta = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM reference_metadata")}
            self._bbox = np.array([[m.min_lon, m.min_lat, m.max_lon, m.max_lat] for m in munis], dtype=np.float64)
            self._munis = munis

    # -- lookups -------------------------------------------------------------
    def state(self, value: Any) -> tuple[str, str] | None:
        self.load()
        return self._states.get(norm(value))

    def state_name(self, sigla: str) -> str | None:
        self.load()
        return self._state_names.get(sigla)

    def municipalities(self, name: Any, uf: str | None = None) -> list[Municipality]:
        self.load()
        found = self._by_name.get(norm(name), [])
        return [m for m in found if m.uf_sigla == uf] if uf else list(found)

    @lru_cache(maxsize=2048)
    def suggest_municipality(self, name_norm: str, uf: str | None) -> tuple[str, ...]:
        self.load()
        pool = self._by_uf.get(uf, []) if uf else self._munis or []
        names = {m.norm_name: m for m in pool}
        hits = difflib.get_close_matches(name_norm, list(names), n=3, cutoff=0.75)
        return tuple(names[h].label if not uf else names[h].name for h in hits)

    def _edges(self, muni: Municipality) -> _Edges:
        with self._geom_lock:
            cached = self._geoms.get(muni.id)
            if cached is not None:
                self._geoms.move_to_end(muni.id)
                return cached
        row = self._con().execute("SELECT geom_json FROM ibge_admin WHERE id = ?", (muni.id,)).fetchone()
        edges = _Edges(json.loads(row["geom_json"]))
        with self._geom_lock:
            self._geoms[muni.id] = edges
            while len(self._geoms) > GEOM_CACHE_SIZE:
                self._geoms.popitem(last=False)
        return edges

    def _bbox_candidates(self, lon: float, lat: float, pad_deg: float = 0.0) -> list[Municipality]:
        self.load()
        b = self._bbox
        assert b is not None and self._munis is not None
        mask = (b[:, 0] - pad_deg <= lon) & (b[:, 2] + pad_deg >= lon) & (b[:, 1] - pad_deg <= lat) & (b[:, 3] + pad_deg >= lat)
        return [self._munis[i] for i in np.flatnonzero(mask)]

    @lru_cache(maxsize=8192)
    def locate(self, lon: float, lat: float) -> Municipality | None:
        for m in self._bbox_candidates(lon, lat):
            if self._edges(m).contains(lon, lat):
                return m
        return None

    @lru_cache(maxsize=4096)
    def nearest(self, lon: float, lat: float, max_km: float = NEAR_LAND_KM) -> tuple[Municipality, float] | None:
        pad = max_km / 100.0
        best: tuple[Municipality, float] | None = None
        for m in self._bbox_candidates(lon, lat, pad):
            d = self._edges(m).distance_km(lon, lat)
            if d <= max_km and (best is None or d < best[1]):
                best = (m, d)
        return best

    def distance_to(self, muni: Municipality, lon: float, lat: float) -> float:
        return self._edges(muni).distance_km(lon, lat)

    def status(self) -> dict[str, Any]:
        base = {"mode": "ibge_sqlite", "path": str(self.db_path)}
        if not self.available():
            return {**base, "status": "missing", "message": "Base geográfica IBGE ainda não foi construída."}
        try:
            self.load()
        except Exception as exc:  # pragma: no cover
            return {**base, "status": "error", "message": str(exc)}
        return {
            **base,
            "status": "ready",
            "source": self._meta.get("source", SOURCE),
            "source_url": self._meta.get("source_url"),
            "source_version": self._meta.get("source_version"),
            "created_at_utc": self._meta.get("created_at_utc"),
            "municipality_count": len(self._munis or []),
            "state_count": len({m.uf_sigla for m in self._munis or []}),
        }


REFERENCE = GeographyReference()


def reference_status() -> dict[str, Any]:
    return REFERENCE.status()


def _country_is_brazil(value: Any) -> bool:
    return not value or norm(value) in BRAZIL_NAMES


def resolve_uf(record: dict[str, Any]) -> str | None:
    """Sigla da UF informada (usada também pela taxonomia para checar distribuição)."""
    found = REFERENCE.state(record.get("majorarea")) if record.get("majorarea") else None
    return found[0] if found else None


def _fmt(lat: float, lon: float) -> str:
    return f"{lat:.6f}, {lon:.6f}".replace(".000000", "")


def validate_geography_ibge(record: dict[str, Any]) -> list[ValidationIssue]:
    ref = REFERENCE
    row = record.get("_row_number")
    issues: list[ValidationIssue] = []
    country, majorarea, minorarea = record.get("country"), record.get("majorarea"), record.get("minorarea")

    if country and not _country_is_brazil(country):
        issues.append(issue(row, "country", "warning", "COUNTRY_NOT_BRAZIL",
                            "País diferente de Brasil: a checagem de estado, município e coordenada usa a malha do IBGE "
                            "e foi ignorada nesta linha.", country, source=SOURCE))
        return issues
    if country and norm(country) != "brasil":
        issues.append(issue(row, "country", "info", "COUNTRY_FORMAT", "Escreva o país por extenso em português.",
                            country, suggestion="Brasil", source=SOURCE))

    state = ref.state(majorarea) if majorarea else None
    uf = state[0] if state else None
    if majorarea and not state:
        issues.append(issue(row, "majorarea", "error", "STATE_NOT_FOUND_IBGE", "Estado não encontrado na base do IBGE.",
                            majorarea, source=SOURCE))
    elif state and norm(majorarea) == state[0].lower():
        issues.append(issue(row, "majorarea", "warning", "STATE_ABBREVIATION",
                            "Use o nome do estado por extenso, não a sigla.", majorarea, suggestion=state[1], source=SOURCE))

    stated: list[Municipality] = []
    if minorarea:
        stated = ref.municipalities(minorarea, uf)
        if not stated:
            elsewhere = ref.municipalities(minorarea)
            if elsewhere and uf:
                issues.append(issue(row, "minorarea", "error", "MUNICIPALITY_STATE_MISMATCH",
                                    f"Município existe no IBGE, mas não em {uf}.", minorarea,
                                    suggestion=", ".join(m.label for m in elsewhere[:5]), source=SOURCE))
            elif elsewhere:
                stated = elsewhere
            else:
                sugg = ref.suggest_municipality(norm(minorarea), uf)
                issues.append(issue(row, "minorarea", "error", "MUNICIPALITY_NOT_FOUND_IBGE",
                                    "Município não encontrado na Malha Municipal do IBGE." + (f" (UF {uf})" if uf else ""),
                                    minorarea, suggestion=", ".join(sugg) or None, source=SOURCE))

    lat_c: Coordinate = record.get("_lat") or parse_coordinate(record.get("lat"))
    lon_c: Coordinate = record.get("_long") or parse_coordinate(record.get("long"))
    lat, lon = lat_c.value, lon_c.value
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return issues  # ausência/formato/intervalo já tratados no rule_engine

    found = ref.locate(round(lon, 6), round(lat, 6))
    if found is None:
        # Tenta correções comuns: sinal trocado e lat/long invertidas.
        candidates = []
        if lon > 0:
            candidates.append(("longitude com sinal invertido", lat, -lon))
        candidates.append(("latitude com sinal invertido", -lat, lon))
        if lon > 0:
            candidates.append(("latitude e longitude com sinais invertidos", -lat, -lon))
        if -90 <= lon <= 90:
            candidates.append(("latitude e longitude invertidas", lon, lat))
            candidates.append(("latitude e longitude invertidas", -lon if lon > 0 else lon, lat))
        fixes = [(why, la, lo, ref.locate(round(lo, 6), round(la, 6))) for why, la, lo in candidates]
        fixes = [f for f in fixes if f[3] is not None]
        preferred = [f for f in fixes if stated and f[3] in stated] or fixes
        if preferred:
            why, la, lo, m = preferred[0]
            issues.append(issue(row, "lat", "error", "COORDINATE_LIKELY_SWAPPED_OR_SIGN",
                                f"A coordenada não cai no Brasil, mas cai em {m.label} se corrigida ({why}).",
                                _fmt(lat, lon), suggestion=f"lat={la:g}, long={lo:g}", source=SOURCE))
            return issues
        near = ref.nearest(round(lon, 4), round(lat, 4))
        if near:
            m, d = near
            issues.append(issue(row, "lat", "warning", "POINT_OUTSIDE_LAND_LIMIT",
                                f"Coordenada fora dos limites municipais do IBGE, a {d:.1f} km de {m.label} "
                                "(possível ponto em rio largo, costa ou fronteira). Confira.",
                                _fmt(lat, lon), suggestion=m.name, source=SOURCE))
        else:
            issues.append(issue(row, "lat", "error", "POINT_OUTSIDE_BRAZIL",
                                "Coordenada fora do território brasileiro segundo a malha do IBGE.",
                                _fmt(lat, lon), source=SOURCE))
        return issues

    if uf and found.uf_sigla != uf:
        issues.append(issue(row, "majorarea", "error", "POINT_OUTSIDE_STATE",
                            f"A coordenada cai em {found.label}, fora do estado informado ({uf}).",
                            _fmt(lat, lon), suggestion=ref.state_name(found.uf_sigla), source=SOURCE))
    if stated and found not in stated:
        target = stated[0]
        dist = ref.distance_to(target, lon, lat)
        near_boundary = dist <= BOUNDARY_TOLERANCE_KM
        issues.append(issue(
            row, "minorarea", "warning" if near_boundary else "error", "POINT_OUTSIDE_MUNICIPALITY",
            f"A coordenada cai em {found.label}, a {dist:.1f} km do limite de {target.label}. "
            + ("Ponto muito próximo da divisa: confira." if near_boundary else "Confira o município ou a coordenada."),
            _fmt(lat, lon), suggestion=found.name, source=SOURCE))
    elif not minorarea:
        issues.append(issue(row, "minorarea", "info", "MUNICIPALITY_FROM_COORDINATE",
                            f"Município vazio; pela coordenada, a coleta está em {found.label}.", None,
                            suggestion=found.name, source=SOURCE))
    if not majorarea:
        issues.append(issue(row, "majorarea", "info", "STATE_FROM_COORDINATE",
                            f"Estado vazio; pela coordenada: {ref.state_name(found.uf_sigla)}.", None,
                            suggestion=ref.state_name(found.uf_sigla), source=SOURCE))
    return issues
