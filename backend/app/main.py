from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.validator import router as validator_router

app = FastAPI(
    title="Tsiino Herbarium Validator",
    version="0.2.0",
    description="API local para validação de planilhas de coleta e herbário.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "Tsiino Herbarium Validator"}


app.include_router(validator_router, prefix="/api/validator", tags=["validator"])
