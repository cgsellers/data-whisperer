# Arquitectura - Plataforma Agéntica de Datos (Versión MVP)

**Stack:** Python 3.11, FastAPI, PostgreSQL 16, Redis 7, Docker Compose

---

## 1. Arquitectura General (4 Capas, 1 Worker)

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

**Orquestación:** Worker único secuencial consumiendo de Redis Stream `ingestion:raw`.

---

## 2. Componentes Principales

| Componente | Tech | Responsabilidad |
|------------|------|-----------------|
| **API Gateway** | FastAPI | Auth JWT, rate limit Lua, routing, OpenAPI docs |
| **Worker** | Python async | Consume Redis Stream → ingest → etl → analysis → merge |
| **HTTP Connector** | Plugin (entry_point) | Fetch genérico REST APIs, paginación cursor |
| **ETL Simple** | Python | Type coercion, dedup, feature engineering básico |
| **SQL Agent** | Plugin (entry_point) | Queries parametrizadas sobre feature_records |
| **Feature Store** | PostgreSQL + JSONB | Features versionadas + lineage (ARRAY UUID) |
| **Queue/Rate Limit** | Redis Streams + Lua | Async entre API y worker, backpressure, rate limit atómico |

---

## 3. Flujos de Datos

### Ingesta (Async via Redis Stream)
```
POST /sources/{id}/ingest
       │
       ▼
API Gateway: valida auth + rate limit → crea PipelineRun (pending)
       │
       ▼
Publica en Redis Stream "ingestion:raw" {run_id, source_id, config}
       │
       ▼
Worker (consumer group): consume mensaje → ejecuta pipeline completo
```

### Pipeline Completo (Secuencial en Worker)
```
run_pipeline(run_id, source_id, config):
  1. INGEST: HTTPConnector.fetch() → guarda IngestionEvent (PG)
  2. ETL:   transform → guarda FeatureRecord (PG)
  3. ANALYSIS: SQLAgent.run() → guarda AnalysisResult (PG)
  4. MERGE: consolida → actualiza PipelineRun (completed/partial/failed)
```

---

## 4. Contratos Clave (Pydantic)

```python
# Raw Event (Redis Stream)
class RawEvent(BaseModel):
    event_id: UUID
    source_id: str
    timestamp: datetime
    payload: dict
    metadata: EventMeta  # content_type, size_bytes, checksum

# Feature Record (PostgreSQL)
class FeatureRecord(BaseModel):
    feature_id: UUID
    entity_id: str
    features: dict
    ingestion_event_id: UUID
    processing_version: str  # v1.0.0
    lineage: list[UUID]

# Analysis Result
class AnalysisResult(BaseModel):
    analysis_id: UUID
    agent_id: str
    status: Literal["success", "partial", "failed"]
    result: dict
    execution_time_ms: int
    confidence: float
```

---

## 5. Decisiones Clave (Para Defensa)

| Decisión | Por qué |
|----------|---------|
| **FastAPI** | Async nativo, validación Pydantic v2 auto, OpenAPI `/docs` gratis |
| **PostgreSQL + JSONB** | ACID para pipeline runs, schemas flexibles para features, una sola BD |
| **Redis Streams** | Colas persistentes + consumer groups + replay sin Kafka |
| **Worker único secuencial** | Simple, debuggeable, sin estado distribuido complejo |
| **Plugin System (entry_points)** | Extensible: `pip install data-platform-stripe` → auto-registra |
| **Rate Limiter Lua** | Token bucket atómico (ZSET + sliding window), sin race conditions |
| **Structlog JSON** | Logs parseables por Loki/ELK, correlation via trace_id |

---

## 6. Observabilidad (Mínima)

- **Logs:** JSON estructurado (service, trace_id, event, metrics)
- **Métricas:** `/metrics` Prometheus (counter/histogram por etapa)
- **Health:** `/health/live` + `/health/ready` (verifica DB + Redis)
- **Tracing:** *No implementado en MVP* → ver [MEJORAS_FUTURAS.md](./MEJORAS_FUTURAS.md)

---

## 7. Docker Compose (3 Servicios)

```yaml
services:
  api-gateway:    # FastAPI :8000
  worker:         # Pipeline consumer :8000 (same image)
  postgres:       # PG 16 :5432
  redis:          # Redis 7 Streams :6379
```

---

## 8. Testing

| Nivel | Target |
|-------|--------|
| Unit | >80% core/agents (pytest) |
| Integration | E2E pipeline (testcontainers PG/Redis) |
| Contract | Schemas Pydantic |

---

## 9. Referencias

- [FastAPI Tutorial](https://fastapi.tiangolo.com/tutorial/)
- [SQLAlchemy 2.0 Async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Redis Streams](https://redis.io/docs/latest/develop/data-types/streams/)
- [Pydantic v2](https://docs.pydantic.dev/latest/)
- [Structlog](https://www.structlog.org/en/stable/)