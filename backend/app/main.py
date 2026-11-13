from __future__ import annotations

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.config import settings
from app.routes import converter, validator
from app.services.validation import warm_up


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Pré-carrega as bases em segundo plano: /health responde de imediato no cold start do Space.
    threading.Thread(target=warm_up, name="reference-warmup", daemon=True).start()
    yield


app = FastAPI(title="Tsiino Herbarium Validator API", version="2.0.0", lifespan=lifespan)

app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
    max_age=86400,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(validator.router, prefix="/api/validator")
app.include_router(converter.router, prefix="/api/validator")
