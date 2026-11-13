# Imagem de desenvolvimento local (o deploy de produção usa o Dockerfile do repositório do HF Space).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY app /app/app
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -e ".[dev]"

COPY . /app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
