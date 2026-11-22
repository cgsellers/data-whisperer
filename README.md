# Plataforma Agéntica de Datos

**Stack:** Python 3.11, FastAPI, PostgreSQL 16, Redis 7, Docker Compose

---

## Quickstart

```bash
# 1. Configurar entorno
cp .env.example .env

# 2. Levantar todo (API + Worker + PostgreSQL + Redis)
docker compose up -d

# 3. Verificar
curl http://localhost:8000/health/ready
# → {"status":"ready"}

# 4. Documentación API
open http://localhost:8000/docs
```

---

## Arquitectura (4 Capas, 1 Worker)

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  INGESTA    │──▶│   ETL       │──▶│  ANÁLISIS   │──▶│  ACTIVACIÓN │
│  (Sources)  │   │  (Transform)│   │  (Agents)   │   │  (Outputs)  │
└─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘
       │                │                │                │
       ▼                ▼                ▼                ▼
  HTTP Connector   ETL Simple      SQL Agent          Pipeline Results
  Rate Limiter     Feature Store   (PostgreSQL)       REST API
  Redis Stream     (PostgreSQL)                     Structured Logs
```

**Orquestación:** Worker único secuencial (ingest → etl → analysis → merge) consumiendo de Redis Stream.

---

## Estructura del Proyecto

```
data_platform/
├── api/
│   ├── main.py              # FastAPI + lifespan + middleware
│   └── routes/
│       ├── health.py        # /health/live, /health/ready, /metrics, /connectors, /agents
│       ├── sources.py       # CRUD sources
│       └── pipelines.py     # Trigger + status + results
├── connectors/
│   ├── base.py              # BaseConnector + registry + entry_points
│   └── http.py              # HTTPConnector genérico
├── agents/
│   ├── base.py              # BaseAgent + registry
│   └── sql.py               # SQLAgent (ejemplo funcional)
├── core/
│   ├── config.py            # Pydantic Settings
│   ├── database.py          # SQLAlchemy async + init_db
│   ├── redis.py             # Client + rate limiter (Lua) + stream helpers
│   ├── observability.py     # Structlog + Prometheus metrics
│   └── security.py          # JWT + rate limit middleware + scopes
├── models/__init__.py       # SQLAlchemy models (5 tablas)
├── schemas/__init__.py      # Pydantic contracts
└── worker.py                # Worker único: ingest → etl → analysis → merge
```

---

## Endpoints Principales

| Método | Path | Descripción |
|--------|------|-------------|
| `POST` | `/sources` | Registrar source (API, CSV, DB, Scrap) |
| `POST` | `/sources/{id}/ingest` | Trigger ingesta manual (async, 202) |
| `GET` | `/pipelines/{run_id}` | Estado + métricas del run |
| `GET` | `/pipelines/{run_id}/results` | Resultados análisis consolidados |
| `GET` | `/health/live` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe (verifica DB + Redis) |
| `GET` | `/metrics` | Métricas Prometheus |
| `GET` | `/connectors` | Conectores registrados |
| `GET` | `/agents` | Agentes registrados |

---

## Configuración de Source (Ejemplo)

```json
POST /sources
{
  "source_id": "httpbin_test",
  "type": "api",
  "config": {
    "base_url": "https://httpbin.org",
    "endpoint": "/get",
    "method": "GET"
  },
  "schedule": null,
  "enabled": true
}
```

---

## Agentes Implementados

| Agente | Capacidad | Output |
|--------|-----------|--------|
| **SQL Agent** | Queries parametrizadas sobre feature_records | Tabla + plan |

---

## Observabilidad (Mínima)

| Pilar | Implementación |
|-------|----------------|
| **Logs** | JSON estructurado via structlog (service, trace_id, event, metrics) |
| **Métricas** | `/metrics` Prometheus (counters, histograms por etapa) |
| **Health** | `/health/live` + `/health/ready` por servicio |

---

## Testing

```bash
# Unit tests
pytest tests/unit -v

# Ver cobertura
pytest --cov=data_platform --cov-fail-under=80
```

---

## Decisiones Clave (Para Defensa)

| Decisión | Justificación |
|----------|---------------|
| **FastAPI** | Async nativo, validación Pydantic auto, OpenAPI gratis |
| **PostgreSQL + JSONB** | ACID + flexibilidad schemas, una sola BD operacional |
| **Redis Streams** | Colas persistentes + consumer groups sin Kafka |
| **Worker único secuencial** | Simple, debuggeable, suficiente para MVP |
| **Plugin system (entry_points)** | Extensible sin tocar core: nuevo conector = nuevo paquete |
| **Rate limiter Lua** | Atómico, sin race conditions, sliding window |
| **Structlog JSON** | Parsable por Loki/ELK sin regex, correlation via trace_id |

---

## Variables de Entorno Requeridas

```bash
# .env
JWT_SECRET=your-secret-min-32-chars
JWT_ALGORITHM=HS256
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/platform
REDIS_URL=redis://redis:6379/0
LOG_LEVEL=INFO
```

---

## Documentación Detallada

- [ARQUITECTURA.md](./ARQUITECTURA.md) - Decisiones, flujos, contratos, observabilidad
- [SPEC.md](./SPEC.md) - API OpenAPI, modelos DB, plugin system, orquestación
- [MEJORAS_FUTURAS.md](./MEJORAS_FUTURAS.md) - Roadmap de escalabilidad y features

---

## Licencia

MIT