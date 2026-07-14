from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Tsiino Herbarium Validator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


def _find_router(module, label: str) -> APIRouter | None:
    for name in ("router", "api_router", "validator_router", "converter_router"):
        obj = getattr(module, name, None)
        if isinstance(obj, APIRouter):
            return obj
    for _, obj in vars(module).items():
        if isinstance(obj, APIRouter):
            return obj
    print(f"AVISO: nenhum APIRouter encontrado em {label}; modulo ignorado.")
    return None


def _include_router(router: APIRouter | None, prefix: str) -> None:
    if router is None:
        return
    existing = getattr(router, "prefix", "") or ""
    if existing.startswith(prefix):
        app.include_router(router)
    else:
        app.include_router(router, prefix=prefix)


# Validator e obrigatorio para a API principal. Se falhar, queremos erro explicito.
from app.routes import validator as validator_module

validator_router = _find_router(validator_module, "app.routes.validator")
if validator_router is None:
    raise RuntimeError("app.routes.validator nao expoe APIRouter")
_include_router(validator_router, "/api/validator")

# Converter e opcional no boot: se estiver quebrado, a API ainda sobe para diagnostico.
try:
    from app.routes import converter as converter_module
    converter_router = _find_router(converter_module, "app.routes.converter")
    if converter_router is not None:
        existing = getattr(converter_router, "prefix", "") or ""
        if existing.startswith("/api/validator"):
            app.include_router(converter_router)
        elif existing == "/converter":
            app.include_router(converter_router, prefix="/api/validator")
        else:
            app.include_router(converter_router, prefix="/api/validator/converter")
except Exception as exc:
    print(f"AVISO: rotas do conversor nao carregadas: {exc}")
