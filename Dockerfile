# One publicly accessible origin for React and FastAPI: no CORS or API keys.
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend/src \
    SPHEREX_DATA_DIR=/data \
    SPHEREX_CACHE_BUDGET_MB=512
WORKDIR /app
COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/src ./backend/src
RUN pip install --no-cache-dir -e ./backend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
RUN useradd -r -m -u 10001 explorer && mkdir -p /data && chown explorer:explorer /data
USER explorer
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn spherex_api.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
