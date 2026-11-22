# Dockerfile for data-whisperer: multi-agent analytics platform
FROM python:3.11-slim

LABEL org.opencontainers.image.title="data-whisperer"
LABEL org.opencontainers.image.description="Multi-agent analytics platform: natural language → SQL, charts, code, narratives"
LABEL org.opencontainers.image.source="https://github.com/yourusername/data-whisperer"

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl && rm -rf /var/lib/apt/lists/*

RUN groupadd -r appuser && useradd -r -g appuser appuser
WORKDIR /app

COPY pyproject.toml ./
# Instalar dependencias directamente (sin editable install para evitar problemas con setuptools.build_meta)
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    "pydantic>=2.0" \
    "pydantic-settings" \
    "sqlalchemy[asyncio]" \
    asyncpg \
    redis \
    "python-jose[cryptography]" \
    "passlib[bcrypt]" \
    "prometheus-client" \
    structlog \
    httpx \
    tenacity \
    python-dotenv \
    pyyaml \
    "langgraph>=0.2.0" \
    "langchain-core>=0.3.0" \
    "psycopg-pool>=3.0" \
    "openai>=1.30.0" \
    "anthropic>=0.25.0" \
    "pandas>=2.0" \
    "numpy>=1.26" \
    "prophet>=1.1" \
    "plotly>=5.20" \
    "scikit-learn>=1.3" \
    "scipy>=1.11"

COPY data_platform/ ./data_platform/
COPY init.sql ./

RUN chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health/live || exit 1

CMD ["uvicorn", "data_platform.api.main:app", "--host", "0.0.0.0", "--port", "8000"]