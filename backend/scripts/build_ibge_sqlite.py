"""Constrói uma base SQLite de geografia administrativa a partir da Malha Municipal do IBGE.

Uso local:
    python scripts/build_ibge_sqlite.py --download

Uso com arquivos já baixados:
    python scripts/build_ibge_sqlite.py --municipios reference/downloads/BR_Municipios_2025.zip --ufs reference/downloads/BR_UF_2025.zip --pais reference/downloads/BR_Pais_2025.zip

Saída padrão:
    reference/ibge_geography.sqlite

Dependência: pyshp (pacote PyPI: pyshp; import: shapefile).
A base usa geometria serializada em JSON e índice por bounding box para validação rápida sem PostGIS.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import tempfile
import unicodedata
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import shapefile  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Instale a dependência pyshp: pip install pyshp") from exc

IBGE_YEAR = "2025"
IBGE_BASE = "https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2025/Brasil"
DEFAULT_MUNICIPIOS_URL = f"{IBGE_BASE}/BR_Municipios_{IBGE_YEAR}.zip"
DEFAULT_UFS_URL = f"{IBGE_BASE}/BR_UF_{IBGE_YEAR}.zip"
DEFAULT_PAIS_URL = f"{IBGE_BASE}/BR_Pais_{IBGE_YEAR}.zip"

UF_NAMES = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia",
    "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás",
    "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
    "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco", "PI": "Piauí",
    "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul",
    "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo",
    "SE": "Sergipe", "TO": "Tocantins",
}

UF_CODES = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA",
    "31": "MG", "32": "ES", "33": "RJ", "35": "SP",
    "41": "PR", "42": "SC", "43": "RS",
    "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}

COUNTRY_ALIASES = {"brasil", "brazil", "br", "brasilia?"}


def norm(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def download(url: str, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"Baixando: {url}")
    urllib.request.urlretrieve(url, output)
    return output


def extract_zip(archive: Path, outdir: Path) -> Path:
    print(f"Extraindo: {archive}")
    outdir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(outdir)
    return outdir


def find_shp(path: Path) -> Path:
    shps = sorted(path.rglob("*.shp"))
    if not shps:
        raise FileNotFoundError(f"Nenhum .shp encontrado em {path}")
    # Preferir arquivo principal; evitar xml/auxiliares não se aplica a .shp, mas mantemos determinístico.
    return shps[0]


def fields(reader: Any) -> list[str]:
    return [f[0] for f in reader.fields[1:]]


def rec_get(record: dict[str, Any], candidates: list[str]) -> Any:
    lowered = {k.lower(): k for k in record.keys()}
    for cand in candidates:
        key = lowered.get(cand.lower())
        if key is not None:
            return record.get(key)
    return None


def shape_to_rings(shape: Any) -> list[list[list[float]]]:
    pts = shape.points
    parts = list(shape.parts) + [len(pts)]
    rings: list[list[list[float]]] = []
    for i in range(len(parts) - 1):
        start, end = parts[i], parts[i + 1]
        ring = [[float(x), float(y)] for x, y in pts[start:end]]
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA temp_store=MEMORY")
    con.executescript(
        """
        CREATE TABLE reference_metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE ibge_admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT NOT NULL,
            code TEXT,
            name TEXT NOT NULL,
            norm_name TEXT NOT NULL,
            uf_code TEXT,
            uf_sigla TEXT,
            uf_name TEXT,
            norm_uf_name TEXT,
            min_lon REAL NOT NULL,
            min_lat REAL NOT NULL,
            max_lon REAL NOT NULL,
            max_lat REAL NOT NULL,
            geom_json TEXT NOT NULL
        );

        CREATE INDEX idx_ibge_admin_level_name ON ibge_admin(level, norm_name);
        CREATE INDEX idx_ibge_admin_level_uf ON ibge_admin(level, uf_sigla, norm_name);
        CREATE INDEX idx_ibge_admin_bbox ON ibge_admin(level, min_lon, max_lon, min_lat, max_lat);

        CREATE TABLE ibge_state_alias (
            alias TEXT PRIMARY KEY,
            uf_sigla TEXT NOT NULL,
            uf_name TEXT NOT NULL,
            uf_code TEXT
        );
        """
    )
    return con


def insert_metadata(con: sqlite3.Connection, **items: Any) -> None:
    for key, value in items.items():
        con.execute(
            "INSERT OR REPLACE INTO reference_metadata(key, value) VALUES (?, ?)",
            (key, str(value) if value is not None else None),
        )


def insert_state_aliases(con: sqlite3.Connection) -> None:
    for uf, name in UF_NAMES.items():
        code = next((c for c, sigla in UF_CODES.items() if sigla == uf), None)
        aliases = {uf, uf.lower(), name, norm(name)}
        for alias in aliases:
            con.execute(
                "INSERT OR REPLACE INTO ibge_state_alias(alias, uf_sigla, uf_name, uf_code) VALUES (?, ?, ?, ?)",
                (norm(alias), uf, name, code),
            )


def import_admin(con: sqlite3.Connection, zip_path: Path, level: str) -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        extract_dir = extract_zip(zip_path, Path(tmp) / level)
        shp = find_shp(extract_dir)
        print(f"Lendo {level}: {shp.name}")
        reader = shapefile.Reader(str(shp), encoding="utf-8")
        names = fields(reader)
        total = 0
        for sr in reader.iterShapeRecords():
            record = dict(zip(names, list(sr.record)))
            shape = sr.shape
            rings = shape_to_rings(shape)
            if not rings:
                continue
            min_lon, min_lat, max_lon, max_lat = [float(v) for v in shape.bbox]

            if level == "municipality":
                code = rec_get(record, ["CD_MUN", "CD_GEOCMU", "GEOCODIGO", "CD_GEOCODI"])
                name = rec_get(record, ["NM_MUN", "NM_MUNICIP", "NOME", "NM_NOME"])
                uf_sigla = rec_get(record, ["SIGLA_UF", "UF", "NM_UF_SIGLA"])
                uf_code = rec_get(record, ["CD_UF", "GEOCUF"])
                if not uf_sigla and code:
                    uf_sigla = UF_CODES.get(str(code)[:2])
                if not uf_sigla and uf_code:
                    uf_sigla = UF_CODES.get(str(uf_code).zfill(2))
                uf_sigla = str(uf_sigla).upper() if uf_sigla else None
                uf_name = UF_NAMES.get(uf_sigla or "")
            elif level == "state":
                code = rec_get(record, ["CD_UF", "GEOCODIGO", "CD_GEOCUF"])
                name = rec_get(record, ["NM_UF", "NOME", "NM_NOME"])
                uf_sigla = rec_get(record, ["SIGLA_UF", "UF"])
                if not uf_sigla and code:
                    uf_sigla = UF_CODES.get(str(code).zfill(2))
                uf_sigla = str(uf_sigla).upper() if uf_sigla else None
                uf_name = str(name) if name else UF_NAMES.get(uf_sigla or "")
                code = str(code).zfill(2) if code is not None else None
            else:  # country
                code = rec_get(record, ["CD_PAIS", "CD_GEOCODI", "GEOCODIGO"])
                name = rec_get(record, ["NM_PAIS", "NOME", "NM_NOME"])
                uf_sigla = None
                uf_code = None
                uf_name = None

            if not name:
                continue

            con.execute(
                """
                INSERT INTO ibge_admin(
                    level, code, name, norm_name, uf_code, uf_sigla, uf_name, norm_uf_name,
                    min_lon, min_lat, max_lon, max_lat, geom_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    level,
                    str(code) if code is not None else None,
                    str(name),
                    norm(name),
                    str(locals().get("uf_code")).zfill(2) if locals().get("uf_code") is not None and str(locals().get("uf_code")).strip() else None,
                    uf_sigla,
                    uf_name,
                    norm(uf_name),
                    min_lon,
                    min_lat,
                    max_lon,
                    max_lat,
                    json.dumps(rings, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            total += 1
            if total % 500 == 0:
                con.commit()
                print(f"  {level}: {total}")
        con.commit()
        return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--municipios", type=Path)
    parser.add_argument("--ufs", type=Path)
    parser.add_argument("--pais", type=Path)
    parser.add_argument("--output", type=Path, default=Path("reference/ibge_geography.sqlite"))
    parser.add_argument("--year", default=IBGE_YEAR)
    args = parser.parse_args()

    downloads = Path("reference/downloads")
    if args.download:
        municipios = download(DEFAULT_MUNICIPIOS_URL, downloads / f"BR_Municipios_{IBGE_YEAR}.zip")
        ufs = download(DEFAULT_UFS_URL, downloads / f"BR_UF_{IBGE_YEAR}.zip")
        pais = download(DEFAULT_PAIS_URL, downloads / f"BR_Pais_{IBGE_YEAR}.zip")
    else:
        if not args.municipios or not args.ufs:
            raise SystemExit("Informe --download ou --municipios e --ufs")
        municipios = args.municipios
        ufs = args.ufs
        pais = args.pais

    con = init_db(args.output)
    insert_state_aliases(con)

    muni_total = import_admin(con, municipios, "municipality")
    state_total = import_admin(con, ufs, "state")
    country_total = import_admin(con, pais, "country") if pais and pais.exists() else 0

    insert_metadata(
        con,
        geography_mode="ibge_sqlite",
        source="IBGE Malha Municipal Digital",
        source_url=DEFAULT_MUNICIPIOS_URL,
        source_version=args.year,
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        municipality_count=muni_total,
        state_count=state_total,
        country_count=country_total,
    )
    con.commit()
    con.close()

    print(f"SQLite criado: {args.output}")
    print(f"Municípios/áreas municipais: {muni_total}")
    print(f"UFs: {state_total}")
    print(f"País: {country_total}")


if __name__ == "__main__":
    main()
