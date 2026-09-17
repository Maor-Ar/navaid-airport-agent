FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NAVAID_OFFLINE=1 \
    PORT=8080

COPY pyproject.toml README.md ./
COPY navaid ./navaid
COPY scripts/build_snapshot.py ./scripts/build_snapshot.py
COPY data/fixtures ./data/fixtures
COPY data/curated ./data/curated
COPY docs ./docs

RUN pip install --no-cache-dir \
        "google-genai>=1.0.0,<3" \
        fastapi \
        "uvicorn[standard]" \
        duckdb \
        "pydantic>=2" \
        httpx \
        pandas \
        openpyxl \
        python-dotenv \
    && pip install --no-cache-dir --no-deps . \
    && python scripts/build_snapshot.py --offline --force-fixtures \
    && useradd --create-home --uid 10001 navaid \
    && chown -R navaid:navaid /app

USER navaid

EXPOSE 8080

CMD ["sh", "-c", "uvicorn navaid.api.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
