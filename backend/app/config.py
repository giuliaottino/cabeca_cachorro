"""Configuração da API lida de variáveis de ambiente (com padrões seguros para o HF Space)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_ORIGINS = (
    "https://tsiinohiiwiida.net",
    "https://www.tsiinohiiwiida.net",
    "https://api.tsiinohiiwiida.net",
    "http://localhost:7440",
    "http://127.0.0.1:7440",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
)


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _origins() -> list[str]:
    raw = os.environ.get("ALLOWED_ORIGINS", "")
    items = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    return items or list(DEFAULT_ORIGINS)


@dataclass(frozen=True)
class Settings:
    allowed_origins: list[str] = field(default_factory=_origins)
    reference_dir: Path = Path(os.environ.get("REFERENCE_DIR", APP_ROOT / "reference"))
    max_upload_mb: int = _int("MAX_UPLOAD_MB", 20)
    max_rows: int = _int("MAX_ROWS", 5000)
    max_jobs: int = _int("MAX_JOBS", 64)
    job_ttl_hours: int = _int("JOB_TTL_HOURS", 6)

    @property
    def taxonomy_db(self) -> Path:
        return self.reference_dir / "tsiino_reference.sqlite"

    @property
    def geography_db(self) -> Path:
        return self.reference_dir / "ibge_geography.sqlite"


settings = Settings()
