"""Testes ponta a ponta da API. Usam as bases SQLite reais de reference/ (pulados se ausentes)."""
from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app.config import settings
from app.main import app
from app.services.inpa_schema import CANONICAL_COLUMNS
from app.services.normalization import parse_coordinate

needs_refs = pytest.mark.skipif(
    not (settings.taxonomy_db.exists() and settings.geography_db.exists()),
    reason="bases de referência ausentes",
)
client = TestClient(app)

BASE = {
    "collector": "Lima, J.S.", "number": 1131, "colldd": 3, "collmm": 11, "collyy": 2025,
    "family": "Frullaniaceae", "genus": "Frullania", "sp1": "nodulosa", "country": "Brasil",
    "majorarea": "Amazonas", "minorarea": "São Gabriel da Cachoeira", "lat": -0.153082, "NS": "S",
    "long": -67.005257, "EW": "W", "plantdesc": "Epífita sobre tronco.", "dups": "INPA",
}


def inpa_workbook(rows: list[dict], *, recommendations: bool = True) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Espécimes"
    if recommendations:
        ws.append(["Recomendações no preenchimento"] + ["..."] * (len(CANONICAL_COLUMNS) - 1))
    ws.append(CANONICAL_COLUMNS)
    for row in rows:
        ws.append([row.get(c) for c in CANONICAL_COLUMNS])
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


def upload(content: bytes, name: str = "teste.xlsx", **data):
    form = {"validate_taxonomy": "true", "validate_geography": "true", **data}
    return client.post("/api/validator/upload", files={"file": (name, content)}, data=form)


def codes_for(result: dict, row: int) -> set[str]:
    return {i["code"] for i in result["issues"] if i["row_number"] == row}


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("raw, expected", [
    (-0.153, -0.153), ("-0,153", -0.153), ("0°9'11\" S", -0.153056), ("67 0 19 W", -67.005278),
    ("3.5 S", -3.5), ("abc", None), (None, None),
])
def test_parse_coordinate(raw, expected):
    value = parse_coordinate(raw).value
    assert value == pytest.approx(expected) if expected is not None else value is None


@needs_refs
def test_clean_row_has_no_errors():
    res = upload(inpa_workbook([BASE])).json()
    assert res["summary"]["total_rows"] == 1
    assert res["summary"]["error_count"] == 0, res["issues"]
    assert res["summary"]["is_standard"] is True
    assert res["table"][0]["_row_number"] == 3


@needs_refs
@pytest.mark.parametrize("patch, column, code", [
    ({"genus": "Frulania"}, "genus", "GENUS_NOT_FOUND_FFB"),
    ({"genus": "Xyzzyqwerty"}, "genus", "GENUS_NOT_FOUND_FFB"),
    ({"sp1": "nodulosaa"}, "sp1", "SPECIES_NOT_FOUND_FFB"),
    ({"family": "Fabaceae"}, "family", "FAMILY_GENUS_MISMATCH"),
    ({"sp1": "sp."}, "sp1", "SP1_PLACEHOLDER"),
    ({"lat": None}, "lat", "LAT_REQUIRED"),
    ({"colldd": 31, "collmm": 2}, "colldd", "INVALID_DATE"),
    ({"collyy": 25}, "collyy", "COLLYY_TWO_DIGITS"),
    ({"minorarea": "Barcelos"}, "minorarea", "POINT_OUTSIDE_MUNICIPALITY"),
    ({"minorarea": "Sao Gabriel da Cachoeria"}, "minorarea", "MUNICIPALITY_NOT_FOUND_IBGE"),
    ({"majorarea": "AM"}, "majorarea", "STATE_ABBREVIATION"),
    ({"majorarea": "Pará"}, "majorarea", "POINT_OUTSIDE_STATE"),
    ({"long": 67.005257}, "lat", "COORDINATE_LIKELY_SWAPPED_OR_SIGN"),
    ({"lat": "0°9'11\" S", "long": "67°0'19\" W"}, "lat", "LAT_DMS_FORMAT"),
    ({"plantdesc": None}, "plantdesc", "PLANTDESC_EMPTY"),
    ({"number": "s.n."}, "number", "NUMBER_SN"),
    ({"family": "Leguminosae", "genus": "Inga", "sp1": "edulis"}, "family", "FAMILY_ALTERNATIVE_NAME"),
    ({"family": "Fabaceae", "genus": "Bauhinia", "sp1": "guianensis"}, "sp1", "TAXON_SYNONYM_FFB"),
])
def test_detects_problem(patch, column, code):
    res = upload(inpa_workbook([{**BASE, **patch}])).json()
    hits = [i for i in res["issues"] if i["code"] == code]
    assert hits, f"{code} não detectado; ocorrências: {[(i['code'], i['message']) for i in res['issues']]}"
    assert hits[0]["column_name"] == column


@needs_refs
def test_suggestions():
    res = upload(inpa_workbook([{**BASE, "genus": "Passflora", "family": "Passifloraceae", "sp1": None},
                                {**BASE, "minorarea": "Sao Gabriel da Cachoeria"}])).json()
    by_code = {i["code"]: i for i in res["issues"]}
    assert "Passiflora" in by_code["GENUS_NOT_FOUND_FFB"]["suggestion"]
    assert by_code["MUNICIPALITY_NOT_FOUND_IBGE"]["suggestion"].startswith("São Gabriel da Cachoeira")


@needs_refs
def test_duplicate_collection_number():
    res = upload(inpa_workbook([BASE, BASE])).json()
    dups = [i for i in res["issues"] if i["code"] == "DUPLICATE_COLLECTION_NUMBER"]
    assert {i["row_number"] for i in dups} == {3, 4}


@needs_refs
def test_job_endpoints_and_annotated_download():
    res = upload(inpa_workbook([BASE, {**BASE, "number": 2, "genus": "Frulania"}])).json()
    job = res["job_id"]
    assert client.get(f"/api/validator/jobs/{job}").json()["total_rows"] == 2
    assert client.get(f"/api/validator/jobs/{job}/issues").json() == res["issues"]
    assert len(client.get(f"/api/validator/jobs/{job}/table").json()) == 2
    geo = client.get(f"/api/validator/jobs/{job}/map.geojson").json()
    assert len(geo["features"]) == 2 and geo["features"][1]["properties"]["has_error"] is True

    dl = client.get(f"/api/validator/jobs/{job}/download.xlsx")
    assert dl.status_code == 200
    wb = load_workbook(BytesIO(dl.content))
    ws = wb["Espécimes"]
    genus_col = CANONICAL_COLUMNS.index("genus") + 1
    cell = ws.cell(row=4, column=genus_col)
    assert cell.value == "Frulania"            # valor original preservado
    assert cell.comment and "Gênero" in cell.comment.text
    assert wb.sheetnames[-1] == "Validação Tsiino"

    # A planilha anotada pode ser validada de novo sem ajustes.
    again = upload(dl.content, "anotada.xlsx").json()
    assert again["summary"]["total_rows"] == 2


def non_standard_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Coletor", "Nº coleta", "Dia", "Mês", "Ano", "Família", "Gênero", "Espécie",
               "País", "Estado", "Município", "Latitude", "Longitude", "Observações"])
    ws.append(["Lima, J.S.", 1131, 3, 11, 2025, "Frullaniaceae", "Frullania", "nodulosa",
               "Brasil", "Amazonas", "São Gabriel da Cachoeira", -0.153082, -67.005257, "epífita"])
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


def test_standard_check_and_preview():
    content = non_standard_workbook()
    check = client.post("/api/validator/converter/standard_check", files={"file": ("x.xlsx", content)}).json()
    assert check["detected_standard"] is False
    prev = client.post("/api/validator/converter/preview", files={"file": ("x.xlsx", content)}).json()
    mapping = prev["suggested_mapping"]
    assert mapping["collector"] == "Coletor" and mapping["number"] == "Nº coleta"
    assert mapping["lat"] == "Latitude" and mapping["minorarea"] == "Município"
    assert prev["rows"][0]["Coletor"] == "Lima, J.S."
    # compatibilidade com o mapeador antigo
    old = client.post("/api/validator/converter/preview_rows", files={"file": ("x.xlsx", content)}).json()
    assert old["source_columns"][0] == "Coletor"


@needs_refs
def test_validate_mapped_respects_user_mapping():
    content = non_standard_workbook()
    prev = client.post("/api/validator/converter/preview", files={"file": ("x.xlsx", content)}).json()
    mapping = dict(prev["suggested_mapping"])
    mapping["plantdesc"] = "Observações"
    res = client.post("/api/validator/validate_mapped", files={"file": ("x.xlsx", content)},
                      data={"mapping": __import__("json").dumps(mapping)}).json()
    assert res["summary"]["total_rows"] == 1
    assert res["summary"]["converted_from"] == "x.xlsx"
    assert res["summary"]["error_count"] == 0, res["issues"]
    assert res["table"][0]["plantdesc"] == "epífita"


def test_legacy_convert_endpoint():
    content = non_standard_workbook()
    r = client.post("/api/validator/converter/convert_tolerant_v28", files={"file": ("x.xlsx", content)},
                    data={"mapping": '{"collector": "Coletor", "genus": "Gênero"}'})
    assert r.status_code == 200
    ws = load_workbook(BytesIO(r.content))["Espécimes"]
    header = [c.value for c in ws[1]]
    assert header == CANONICAL_COLUMNS
    row = dict(zip(header, [c.value for c in ws[2]]))
    assert row["collector"] == "Lima, J.S." and row["genus"] == "Frullania" and row["family"] is None


def test_rejects_non_xlsx():
    r = client.post("/api/validator/upload", files={"file": ("x.csv", b"a,b")})
    assert r.status_code == 400


def test_missing_job_is_404():
    assert client.get("/api/validator/jobs/nao-existe").status_code == 404


# ---------------------------------------------------------------- correções e colunas arrastadas
def dragged_workbook(extra_rows: int = 6) -> bytes:
    """3 coletas reais e, abaixo, a coluna 'project' arrastada por mais `extra_rows` linhas."""
    rows = [{**BASE, "number": n, "project": "Tsiino"} for n in (1, 2, 3)]
    rows += [{"project": "Tsiino"} for _ in range(extra_rows)]
    return inpa_workbook(rows)


@needs_refs
def test_detects_column_dragged_beyond_data():
    res = upload(dragged_workbook()).json()
    tf = res["trailing_fill"]
    assert tf and tf["count"] == 6 and tf["first_row"] == 6 and tf["last_data_row"] == 5
    assert [c["field"] for c in tf["columns"]] == ["project"] and tf["columns"][0]["pattern"] == "repeated"
    assert tf["issue_count"] > 6 * 5

    # Mesmo quando as linhas arrastadas são a maioria da planilha.
    many = upload(dragged_workbook(extra_rows=400)).json()["trailing_fill"]
    assert many and many["count"] == 400
    glob = [i for i in res["issues"] if i["code"] == "TRAILING_FILLED_ROWS"]
    assert len(glob) == 1 and glob[0]["row_number"] is None


def test_no_trailing_fill_on_clean_sheet():
    from app.services.corrections import detect_trailing_fill
    recs = [{"_row_number": i, "_raw": {c: BASE.get(c) for c in CANONICAL_COLUMNS}} for i in range(3, 8)]
    assert detect_trailing_fill(recs, CANONICAL_COLUMNS) is None
    # Uma coleta real incompleta no meio não é tratada como arrasto.
    recs.insert(2, {"_row_number": 99, "_raw": {"project": "x"}})
    assert detect_trailing_fill(recs, CANONICAL_COLUMNS) is None


@needs_refs
def test_apply_clears_rows_edits_cells_and_revalidates():
    res = upload(dragged_workbook()).json()
    job = res["job_id"]
    genus_issue_row = 3  # primeira linha de dados (linha 2 = cabeçalho técnico)
    body = {"clear_rows": res["trailing_fill"]["rows"],
            "edits": [{"row": genus_issue_row, "column": "genus", "value": "Frullania"},
                      {"row": genus_issue_row, "column": "lat", "value": "-0.2"}]}
    new = client.post(f"/api/validator/jobs/{job}/apply", json=body)
    assert new.status_code == 200, new.text
    data = new.json()
    assert data["job_id"] != job
    assert data["summary"]["total_rows"] == 3 and data["trailing_fill"] is None
    assert data["summary"]["corrections"] == {**data["summary"]["corrections"], "edits": 2, "cleared_rows": 6, "parent_job": job}
    assert data["summary"]["error_count"] < res["summary"]["error_count"]

    dl = client.get(f"/api/validator/jobs/{data['job_id']}/corrected.xlsx")
    assert dl.status_code == 200 and "corrigida_tsiino" in dl.headers["content-disposition"]
    ws = load_workbook(BytesIO(dl.content))["Espécimes"]
    assert ws.cell(row=3, column=CANONICAL_COLUMNS.index("lat") + 1).value == -0.2   # texto virou número
    assert ws.cell(row=3, column=1).parent is ws and ws.cell(row=2, column=1).value == CANONICAL_COLUMNS[0]
    assert all(ws.cell(row=r, column=CANONICAL_COLUMNS.index("project") + 1).value is None for r in range(6, 12))


def test_apply_rejects_unknown_cells():
    res = upload(inpa_workbook([BASE])).json()
    bad = client.post(f"/api/validator/jobs/{res['job_id']}/apply", json={"edits": [{"row": 999, "column": "genus", "value": "x"}]})
    assert bad.status_code == 400
    empty = client.post(f"/api/validator/jobs/{res['job_id']}/apply", json={})
    assert empty.status_code == 400
