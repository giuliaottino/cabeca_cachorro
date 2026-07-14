from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
validator_path = ROOT / "backend" / "app" / "routes" / "validator.py"
text = validator_path.read_text(encoding="utf-8")

import_line = "from app.services.taxonomy_ffb_sqlite import reference_status as ffb_reference_status, validate_taxonomy_ffb"
if import_line not in text:
    anchor = "from app.services.spreadsheet_reader import parse_xlsx\n"
    if anchor not in text:
        raise SystemExit("Não encontrei o ponto de inserção dos imports em validator.py")
    text = text.replace(anchor, anchor + import_line + "\n", 1)

text = text.replace("all_issues.extend(_local_taxonomy(record))", "all_issues.extend(validate_taxonomy_ffb(record))")
text = text.replace("all_issues.extend(_local_taxonomy(record))", "all_issues.extend(validate_taxonomy_ffb(record))")

status_re = re.compile(
    r"@router\.get\((['\"])\/status\1\)\s*\ndef\s+status\s*\(\)\s*->\s*dict\[str,\s*Any\]\s*:\n(?P<body>(?:    .*\n)+?)(?=\n@router\.)",
    re.MULTILINE,
)
new_status = '''@router.get("/status")
def status() -> dict[str, Any]:
    return {
        "mode": "local_memory_jobs",
        "taxonomy": ffb_reference_status(),
        "geography": {
            "mode": "local_fixture",
            "status": "pending_ibge_phase2",
            "source": "IBGE Malha Municipal será integrada na próxima fase",
        },
        "features": {
            "structure_validation": True,
            "basic_row_validation": True,
            "taxonomy_ffb_sqlite": True,
            "geography_ibge": False,
            "annotated_xlsx_download": True,
            "map_geojson": True,
        },
    }
'''
text2, n = status_re.subn(new_status, text, count=1)
if n == 0:
    print("AVISO: não consegui substituir /status automaticamente. O resto do patch foi aplicado.")
    text2 = text

validator_path.write_text(text2, encoding="utf-8")
print(f"validator.py atualizado: {validator_path}")
