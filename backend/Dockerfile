# LAB ERP backend (FastAPI). Build: docker compose build backend
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Europe/Istanbul

# pg_dump/pg_restore 16 must match the postgres:16 server; Debian bookworm only ships 15,
# so take postgresql-client-16 from the PostgreSQL apt repository (build time only).
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg tzdata; \
    install -d /usr/share/postgresql-common/pgdg; \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      | gpg --dearmor -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg; \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-client-16; \
    apt-get purge -y --auto-remove curl gnupg; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
# Sample files for "python -m app.cli seed"
COPY tests/data ./tests/data

RUN useradd --system --uid 1000 --home /app erp \
    && mkdir -p /data /backups \
    && chown -R erp:erp /data /backups /app
USER erp

ENV ERP_DATA_DIR=/data \
    ERP_BACKUP_DIR=/backups

EXPOSE 8000
VOLUME ["/data", "/backups"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# Entrypoint: apply migrations, then serve. A different command (cli, backup) skips both.
ENTRYPOINT ["/bin/sh", "-c", "if [ \"$#\" -gt 0 ]; then exec \"$@\"; fi; alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${ERP_WORKERS:-1} --proxy-headers --forwarded-allow-ips='*' --timeout-keep-alive 75", "entrypoint"]
CMD []
