FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        gnupg \
        apt-transport-https \
        ca-certificates \
        libpq5 \
        unixodbc \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir \
        "sqlalchemy[asyncio]>=2.0" \
        "alembic>=1.13" \
        "aiosqlite>=0.20" \
        "greenlet>=3.0" \
        "PyJWT>=2.8" \
        "bcrypt>=4.0" \
        "cryptography>=42.0" \
        "structlog>=24.0" \
        "slowapi>=0.1.9" \
        "networkx>=3.0" \
        "aio-pika>=9.4" \
        "psycopg[binary]>=3.1"

COPY alembic.ini pyproject.toml ./
COPY alembic ./alembic
COPY application ./application
COPY apps ./apps
COPY domains ./domains
COPY infrastructure ./infrastructure
COPY shared ./shared
COPY scripts/docker_api_entrypoint.py ./scripts/docker_api_entrypoint.py

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8508

ENTRYPOINT ["python", "/app/scripts/docker_api_entrypoint.py"]
