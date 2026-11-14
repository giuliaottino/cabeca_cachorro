"""Gera data.js para a animação 3D das expedições.

Entradas (todas em _input_data/):
  expedicoes_3d.json             ordem das expedições e trilhas, nomes PT/EN
  kml_expedições/<trilha>.kml    trajetos de GPS (com altitude, se houver)
  expedicoes_fotos/<pasta>/      fotos de cada expedição
  expedicoes_fotos/<pasta>/legendas.csv   (opcional) legendas e posição das fotos

Roda sozinho a cada `quarto render` (pre-render em _quarto.yml).
Para gerar à mão, na raiz do repositório:
    python scripts/build_expedicoes_3d.py
"""
import csv
import json
import math
import re
import statistics
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "_input_data" / "expedicoes_3d.json"
KML_DIR = ROOT / "_input_data" / "kml_expedições"
PHOTO_DIR = ROOT / "_input_data" / "expedicoes_fotos"
OUT = ROOT / "expedicoes" / "3d" / "data.js"
PHOTO_REL = "../../_input_data/expedicoes_fotos"

RIVER_MIN_M = 15000      # trajetos maiores que isso são tratados como rio
CLIMB_MIN_RELIEF = 250   # desnível (m) a partir do qual o trajeto é uma subida
NS = {"k": "http://www.opengis.net/kml/2.2"}


def haversine(a, b):
    r = 6371008.8
    la1, la2 = math.radians(a[1]), math.radians(b[1])
    dla, dlo = la2 - la1, math.radians(b[0] - a[0])
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def parse_coords(text):
    pts = []
    for tok in text.split():
        p = tok.split(",")
        if len(p) >= 2:
            z = float(p[2]) if len(p) > 2 and p[2] else None
            pts.append([float(p[0]), float(p[1]), z])
    return pts


def read_kml(path):
    root = ET.parse(path).getroot()
    doc_name, lines, points = None, [], []
    for pm in root.iter("{%s}Placemark" % NS["k"]):
        name_el = pm.find("k:name", NS)
        name = (name_el.text or "").strip() if name_el is not None else ""
        for ls in pm.iter("{%s}LineString" % NS["k"]):
            c = ls.find("k:coordinates", NS)
            if c is not None and c.text:
                lines.append(parse_coords(c.text))
            if doc_name is None and name:
                doc_name = name
        for pt in pm.iter("{%s}Point" % NS["k"]):
            c = pt.find("k:coordinates", NS)
            if c is not None and c.text and name:
                xy = parse_coords(c.text)
                if xy:
                    points.append({"name": name, "lon": xy[0][0], "lat": xy[0][1]})
    return re.sub(r"\s+", " ", doc_name or path.stem).strip(), lines, points


def dp(pts, tol_m):
    """Douglas-Peucker em projeção local (metros)."""
    if len(pts) < 3:
        return pts
    lat0 = math.radians(pts[0][1])
    xy = [(p[0] * 111320 * math.cos(lat0), p[1] * 110540) for p in pts]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        (ax, ay), (bx, by) = xy[i], xy[j]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy) or 1e-9
        best, idx = 0.0, -1
        for k in range(i + 1, j):
            d = abs(dy * (xy[k][0] - ax) - dx * (xy[k][1] - ay)) / L
            if d > best:
                best, idx = d, k
        if best > tol_m and idx > 0:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    return [p for p, k in zip(pts, keep) if k]


def chain_segments(segs):
    segs = [s for s in segs if len(s) >= 5]
    if not segs:
        return []
    main = max(segs, key=len)
    c = (statistics.mean(p[0] for p in main), statistics.mean(p[1] for p in main))
    segs = [s for s in segs if haversine(c, s[0]) < 60000]  # descarta ruído distante
    out = list(segs[0])
    for s in segs[1:]:
        if haversine(out[-1], s[-1]) < haversine(out[-1], s[0]):
            s = s[::-1]
        out += s
    return out


def clean_z(pts):
    z = [p[2] if (p[2] is not None and p[2] > 5) else None for p in pts]
    idx = [i for i, v in enumerate(z) if v is not None]
    if len(idx) < max(3, len(z) // 10):
        return [None] * len(pts)
    for i in range(len(z)):
        if z[i] is None:
            lo = max((k for k in idx if k < i), default=None)
            hi = min((k for k in idx if k > i), default=None)
            if lo is None:
                z[i] = z[hi]
            elif hi is None:
                z[i] = z[lo]
            else:
                z[i] = z[lo] + (i - lo) / (hi - lo) * (z[hi] - z[lo])
    w = 7
    return [statistics.median(z[max(0, i - w): i + w + 1]) for i in range(len(z))]


def read_captions(folder):
    """legendas.csv opcional: arquivo, legenda_pt, legenda_en, credito, trajeto, lat, lon."""
    f = PHOTO_DIR / folder / "legendas.csv"
    if not f.exists():
        return {}
    text = f.read_text(encoding="utf-8-sig")
    delim = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
    out = {}
    for row in csv.DictReader(text.splitlines(), delimiter=delim):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        if row.get("arquivo"):
            out[row["arquivo"]] = row
    return out


def num(x):
    try:
        return round(float(str(x).replace(",", ".")), 6)
    except ValueError:
        return None


def photos_for(folder):
    d = PHOTO_DIR / folder
    if not d.is_dir():
        return []
    caps = read_captions(folder)
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    out = []
    for name in sorted(f.name for f in d.iterdir() if f.suffix.lower() in exts):
        c = caps.get(name, {})
        p = {"src": f"{PHOTO_REL}/{folder}/{name}"}
        for key, col in (("pt", "legenda_pt"), ("en", "legenda_en"), ("credit", "credito"), ("trail", "trajeto")):
            if c.get(col):
                p[key] = c[col]
        lat, lon = num(c.get("lat", "")), num(c.get("lon", ""))
        if lat is not None and lon is not None:
            p["lat"], p["lon"] = lat, lon
        out.append(p)
    return out


def main():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    data = {"expeditions": []}
    for exp in cfg["expeditions"]:
        prev_end, trails = None, []
        for entry in exp["trails"]:
            entry = {"kml": entry} if isinstance(entry, str) else entry
            path = KML_DIR / f"{entry['kml']}.kml"
            if not path.exists():
                sys.exit(f"KML não encontrado: {path}")
            kml_name, segs, wpts = read_kml(path)
            line = chain_segments(segs)
            if not line:
                print("  (sem linha, ignorado)", entry["kml"])
                continue
            if prev_end and haversine(prev_end, line[-1]) < haversine(prev_end, line[0]):
                line = line[::-1]
            raw_len = sum(haversine(a, b) for a, b in zip(line, line[1:]))
            for p, zz in zip(line, clean_z(line)):
                p[2] = zz
            line = dp(line, 12 if raw_len > RIVER_MIN_M else 3)
            dist = [0.0]
            for a, b in zip(line, line[1:]):
                dist.append(dist[-1] + haversine(a, b))
            prev_end = line[-1]

            zs = [p[2] for p in line if p[2] is not None]
            relief = (max(zs) - min(zs)) if zs else 0
            gain = sum(max(0, b[2] - a[2]) for a, b in zip(line, line[1:]) if a[2] is not None and b[2] is not None)
            mode = entry.get("mode") or (
                "rio" if raw_len > RIVER_MIN_M else "subida" if relief >= CLIMB_MIN_RELIEF else "trilha"
            )
            t = {
                "id": entry["kml"],
                "name": entry.get("name") or kml_name,
                "mode": mode,
                "length_m": round(dist[-1]),
                "gain_m": round(gain),
                "coords": [[round(p[0], 6), round(p[1], 6)] for p in line],
                "dist": [round(d, 1) for d in dist],
                "z": [round(p[2]) if p[2] is not None else None for p in line],
                "waypoints": [
                    {"name": w["name"], "lon": round(w["lon"], 6), "lat": round(w["lat"], 6)}
                    for w in wpts
                    if not re.match(r"(?i)^(wpt\b|minha foto)", w["name"]) and w["name"] != kml_name
                ],
            }
            if entry.get("name_en"):
                t["name_en"] = entry["name_en"]
            if zs:
                top = max(range(len(line)), key=lambda i: line[i][2] if line[i][2] is not None else -1e9)
                t["summit"] = {"i": top, "z": round(line[top][2])}
            trails.append(t)
            print(f"  {mode:7} {entry['kml']:46} {dist[-1]/1000:7.2f} km  +{gain:5.0f} m  wpts={len(t['waypoints'])}")
        photos = photos_for(exp.get("photos", exp["id"]))
        print(f"{exp['id']}: {len(trails)} trajetos, {len(photos)} fotos")
        data["expeditions"].append(
            {k: exp.get(k) for k in ("id", "name", "name_en", "region", "date")} | {"photos": photos, "trails": trails}
        )
    OUT.write_text(
        "// Gerado por scripts/build_expedicoes_3d.py a partir de _input_data/expedicoes_3d.json — não editar à mão.\n"
        "window.TSIINO_EXP = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print("->", OUT.relative_to(ROOT), f"{OUT.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()
