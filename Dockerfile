# syntax=docker/dockerfile:1.7
# ---- frontend build ----
FROM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- python dependencies ----
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY backend/pyproject.toml ./
RUN python -c "import tomllib; print(chr(10).join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > requirements.txt \
    && python -m venv /venv && /venv/bin/pip install -r requirements.txt

# ---- runtime ----
FROM python:3.12-slim
ARG VERSION=0.0.0
ARG REVISION=unknown
LABEL org.opencontainers.image.title="pricewatch" \
      org.opencontainers.image.source="https://github.com/parabyte-ca/pricewatch" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"
ENV PATH="/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    PRICEWATCH_DATA_DIR=/data \
    PRICEWATCH_STATIC_DIR=/app/static
# libatomic1 is needed by the Playwright driver that connects to the browser sidecar
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -g 568 pricewatch && useradd -u 568 -g 568 -d /app -s /usr/sbin/nologin pricewatch \
    && mkdir -p /data /app && chown 568:568 /data
WORKDIR /app
COPY --from=builder /venv /venv
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/pricewatch ./pricewatch
COPY VERSION ./pricewatch/VERSION
COPY --from=frontend /src/dist ./static
USER 568:568
EXPOSE 8086
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,os,sys; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PRICEWATCH_PORT\",\"8086\")}/healthz', timeout=4); sys.exit(0)"
CMD ["sh", "-c", "exec uvicorn pricewatch.main:app --host 0.0.0.0 --port ${PRICEWATCH_PORT:-8086} --proxy-headers --forwarded-allow-ips='*' --no-access-log"]
