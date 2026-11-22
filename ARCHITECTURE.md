# Arquitectura - Plataforma Agéntica de Datos

**Stack:** Python 3.11, FastAPI, LangGraph, PostgreSQL, Redis, Docker Compose

---

## 1. Arquitectura General (4 Capas)

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  INGESTA    │──▶│   ETL       │──▶│  ANÁLISIS   │──▶│  ACTIVACIÓN │
│  (Sources)  │   │  (Transform)│   │  (Agents)   │   │  (Outputs)  │
└─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘
       │                │                │                │
       ▼                ▼                ▼                ▼
  Connector         ETL Agent        SQL Agent        Dashboard API
  Registry          (LangGraph)      Python Agent     Alert Engine
  Rate Limiter      Feature Store    Viz Agent        Report Gen
  Redis Queue       (PostgreSQL)     Insight Agent    REST API
```

---

## 2. Componentes Principales

| Componente | Tech | Responsabilidad |
|------------|------|-----------------|
| **API Gateway** | FastAPI | Auth, rate limit, routing |
| **Orchestrator** | LangGraph | DAG estado, checkpoints, retry |
| **Ingestor Agent** | Worker pool | Conectores plugin, validación, cola Redis |
| **ETL Agent** | LangGraph node | Limpieza, dedup, feature eng, quality checks |
| **SQL Agent** | Worker | Consultas parametrizadas, optimización |
| **Python Agent** | Worker | Stats, ML, forecasting (pandas/scikit) |
| **Viz Agent** | Worker | Plotly/Altair → HTML artifacts |
| **Insight Agent** | Worker | Detección anomalías, narrativas |
| **Feature Store** | PostgreSQL | Features versionadas + lineage (JSONB) |
| **Queue/Cache** | Redis Streams | Async entre capas, backpressure |

---

## 3. Flujos de Datos

### Ingesta (Batch/Stream)
```
Source Config → Connector Plugin → Validator (Pydantic) → Redis Stream
                    ↓
            Rate Limiter (token bucket/redis)
                    ↓
            Retry (exp backoff 3x) → DLQ si falla
```

### ETL (Transform)
```
Redis Stream → ETL Agent (LangGraph)
  1. Schema inference (sample)
  2. Type coercion + null policy
  3. Dedup (entity_id + timestamp)
  4. Feature engineering (plugins)
  5. Quality checks (Great Expectations)
  6. Write Feature Store (PG) + Lineage
```

### Análisis (Fan-out Paralelo)
```
Feature Store Query → Orchestrator
                        │
         ┌──────────────┼──────────────┐
         ▼              ▼              ▼
      SQL Agent    Python Agent    Viz Agent
         │              │              │
         └──────────────┼──────────────┘
                        ▼
                  Merge Results
                        ▼
                  Activation Layer
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
| **LangGraph** | Estado persistente, checkpoints, visualización DAG, human-in-loop nativo |
| **Redis Streams** | Sin deps extra, backpressure, replay, consumer groups |
| **PostgreSQL + JSONB** | ACID, una BD, schemas flexibles, pgvector/timescale futuros |
| **Plugin System** | `entry_points` para conectores/agentes - extensible sin tocar core |
| **Async Queue** | Desacopla capas, escala workers independientemente |

---

## 6. Observabilidad Mínima

- **Logs:** JSON estructurado (service, trace_id, event, metrics)
- **Métricas:** Prometheus (counter/histogram por agente, latency, DLQ size)
- **Tracing:** Jaeger (trace por pipeline_run_id, spans por agente)
- **Health:** `/health/live` + `/health/ready` en cada servicio

---

## 7. Docker Compose (Dev)

```yaml
services:
  api-gateway:    # FastAPI :8000
  orchestrator:   # LangGraph server
  ingestor:       # Worker pool
  etl:            # Worker pool
  sql-agent:      # Worker pool
  python-agent:   # Worker pool
  viz-agent:      # Worker pool
  insight-agent:  # Worker pool
  postgres:       # PG 16
  redis:          # Redis 7 Streams
  prometheus:     # :9090
  grafana:        # :3000
  jaeger:         # :16686
```

---

## 8. Testing

| Nivel | Target |
|-------|--------|
| Unit | >80% core/agents (pytest) |
| Integration | E2E crítico (testcontainers PG/Redis) |
| Contract | Schemas Pydantic (schemathesis) |
| Load | 10k events/min (locust) |

---

## 9. Seguridad Básica

- JWT RS256 en API Gateway (scopes por recurso)
- Rate limit token bucket por `client_id` + `source_id` (Redis)
- RLS en PostgreSQL para multi-tenancy futuro
- Secrets via env vars (Vault/AWS Secrets en prod)
- Audit log inmutable en accesos sensibles