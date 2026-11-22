# Plataforma Agéntica de Datos - Entrega Técnica

**Versión:** 1.0 (MVP)  
**Fecha:** 2026-11-19  
**Autor:** Carlos Sellers  
**Stack:** Python 3.11, FastAPI, PostgreSQL 16, Redis 7, Docker Compose, LLM (OpenAI/Anthropic)

> **Nota:** Existe repositorio completo con código funcional y despliegue Docker Compose listo para demo en vivo.

---

## 1. Resumen Ejecutivo

Esta plataforma implementa un **pipeline de datos agente** de 4 capas (Ingesta → ETL → Análisis → Activación) donde la capa de **Análisis está potenciada por LLMs** para: generar SQL desde lenguaje natural, escribir código Python de análisis, crear visualizaciones y detectar anomalías con narrativas en lenguaje natural. El MVP demuestra arquitectura plugin, colas asíncronas, autenticación JWT, métricas Prometheus, logging estructurado e integración LLM lista para producción.

**Entregables funcionales:**
- API REST con documentación OpenAPI/Swagger (`/docs`)
- Worker asíncrono consumiendo de Redis Streams
- Conector HTTP genérico (extensible via entry_points)
- **Agentes LLM**: SQL (text-to-SQL), Python (code-gen), Viz (plotly-gen), Insight (anomalías + narrativa)
- PostgreSQL con JSONB para features flexibles + lineage
- Rate limiting atómico en Lua (Redis)
- Health checks, métricas `/metrics`, logs JSON estructurados
- Integración LLM con proveedores configurables (OpenAI, Anthropic, local)

---

## 2. Arquitectura

### 2.1 Visión General (4 Capas, Worker Orquestado)

```
┌─────────────┐   ┌─────────────┐   ┌─────────────────────────────┐   ┌─────────────┐
│  INGESTA    │──▶│   ETL       │──▶│  ANÁLISIS (LLM AGENTS)      │──▶│  ACTIVACIÓN │
│  (Sources)  │   │  (Transform)│   │  • SQL Agent (text→SQL)     │   │  (Outputs)  │
└─────────────┘   └─────────────┘   │  • Python Agent (code-gen)  │   └─────────────┘
       │                │           │  • Viz Agent (plotly-gen)     │        │
       ▼                ▼           │  • Insight Agent (LLM reasoning)│       ▼
  HTTP Connector   ETL Simple      │  • Orchestrator (LangGraph)   │   Pipeline Results
  Rate Limiter     Feature Store   │                               │   REST API
  Redis Stream     (PostgreSQL)    └───────────────────────────────┘   Structured Logs
```

**Orquestación:** LangGraph StateGraph con checkpoints persistentes → permite recovery, human-in-the-loop, paralelismo (fan-out) entre agentes.

### 2.2 Componentes Principales

| Componente | Tech | Responsabilidad |
|------------|------|-----------------|
| **API Gateway** | FastAPI | Auth JWT, rate limit Lua, routing, OpenAPI docs |
| **Orchestrator** | LangGraph | StateGraph: ingest → etl → analysis (fan-out) → merge; checkpoints PG |
| **Worker Pool** | Python async | Consumers especializados por etapa (ingestor, etl, sql-agent, python-agent, viz-agent, insight-agent) |
| **HTTP Connector** | Plugin (entry_point) | Fetch genérico REST APIs, paginación cursor |
| **ETL** | Python + Pandas | Type coercion, dedup, feature engineering, validación Great Expectations |
| **SQL Agent** | LLM (OpenAI/Anthropic) | Text-to-SQL con esquema dinámico, ejecución segura, explicación |
| **Python Agent** | LLM + Sandbox | Genera/ejecuta código Python (pandas, scipy, statsmodels) |
| **Viz Agent** | LLM + Plotly | Genera especificaciones Plotly/Altair → HTML interactivo |
| **Insight Agent** | LLM | Detección anomalías (IsolationForest) + narrativa en lenguaje natural |
| **Feature Store** | PostgreSQL + JSONB | Features versionadas + lineage (ARRAY UUID) + semantic layer para LLM |
| **Queue/Rate Limit** | Redis Streams + Lua | Async entre API y workers, backpressure, rate limit atómico |

### 2.3 Flujo de Datos con LLM Agents

#### Ingesta (Async via Redis Stream)
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
Ingestor Worker: consume → HTTPConnector.fetch() → IngestionEvents (PG)
       │
       ▼
Publica en "etl:transform" → ETL Worker → FeatureRecords (PG)
       │
       ▼
Publica en "analysis:fanout" → LangGraph inicia análisis paralelo
```

#### Análisis Paralelo (LangGraph Fan-Out)
```
analysis_node(state):
  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
  │  SQL Agent  │  │ Python Agent│  │  Viz Agent  │  │ Insight Ag. │
  │  (text→SQL) │  │  (code-gen) │  │ (plotly)    │  │ (anomalies) │
  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
         │                │                │                │
         ▼                ▼                ▼                ▼
  AnalysisResult  AnalysisResult  AnalysisResult  AnalysisResult
         │                │                │                │
         └────────────────┴────────────────┴────────────────┘
                              │
                              ▼
                      merge_node(state)
                              │
                              ▼
                      PipelineRun.completed
```

---

## 3. Agentes LLM (Capa de Análisis)

### 3.1 Arquitectura Común
```python
class BaseLLMAgent(ABC):
    name: str
    system_prompt: str
    model: str = "gpt-4o-mini"  # configurable
    
    @abstractmethod
    async def run(self, input: AgentInput) -> AgentOutput:
        # 1. Construir contexto (esquema, muestras, pregunta)
        # 2. Llamar LLM con tool calling / structured output
        # 3. Validar/ejecutar resultado (SQL sandbox, Python sandbox)
        # 4. Retornar AgentOutput con result, confidence, tokens_used
```

### 3.2 SQL Agent (Text-to-SQL)
| Capacidad | Implementación |
|-----------|----------------|
| **Input** | Pregunta natural + `schema_context` (tablas, columnas, FKs, muestras) |
| **LLM Task** | Genera `SELECT` parametrizado (solo READ, sin DDL/DML) |
| **Validación** | `EXPLAIN` + timeout + row limit + columnas allowlist |
| **Output** | `{rows, columns, sql, explanation, confidence}` |
| **Seguridad** | Solo `SELECT`, sin subqueries destructivas, parameter binding |

### 3.3 Python Agent (Code Generation)
| Capacidad | Implementación |
|-----------|----------------|
| **Input** | Pregunta + `features_schema` + `sample_data` (DataFrame head) |
| **LLM Task** | Genera código Python (pandas, numpy, scipy, statsmodels, sklearn) |
| **Ejecución** | Sandbox aislado (subproceso con timeout, sin red, sin FS) |
| **Output** | `{stdout, stderr, plots_base64, dataframes_json, confidence}` |

### 3.4 Viz Agent (Visualización)
| Capacidad | Implementación |
|-----------|----------------|
| **Input** | Pregunta + `data_sample` + `viz_intent` (línea, barras, scatter, heatmap) |
| **LLM Task** | Genera spec Plotly/Altair (JSON) → renderiza HTML interactivo |
| **Output** | `{html, spec_json, png_base64, confidence}` |

### 3.5 Insight Agent (Anomalías + Narrativa)
| Capacidad | Implementación |
|-----------|----------------|
| **Input** | `feature_records` ventana temporal + `business_context` |
| **Detección** | IsolationForest / Prophet residuals / z-score (Python Agent) |
| **LLM Task** | Genera narrativa: "Qué pasó, por qué, impacto, acción recomendada" |
| **Output** | `{anomalies[], narrative, severity, recommendations, confidence}` |

---

## 4. Contratos de Datos (Pydantic)

### 4.1 Agent Input/Output
```python
class AgentInput(BaseModel):
    entity_ids: list[str] | None = None
    features: list[dict] | None = None
    question: str | None = None          # Para agentes LLM
    context: dict = {}                    # schema, samples, business_rules
    params: dict = {}
    pipeline_run_id: UUID | None = None

class AgentOutput(BaseModel):
    status: Literal["success", "partial", "failed"]
    result: dict
    execution_time_ms: int
    tokens_used: int = 0                  # LLM tokens
    llm_model: str | None = None
    confidence: float = 1.0
    error: str | None = None
    raw_llm_response: dict | None = None  # Para debug/auditoría
```

### 4.2 Feature Record (Semantic Layer para LLM)
```python
class FeatureRecord(BaseModel):
    feature_id: UUID
    entity_id: str
    features: dict
    feature_metadata: dict = {}           # descriptions, units, categories
    ingestion_event_id: UUID
    processing_version: str
    lineage: list[UUID]
```

---

## 5. Modelo de Datos (PostgreSQL)

### 5.1 Tablas Principales

| Tabla | Propósito | Claves |
|-------|-----------|--------|
| `sources` | Catálogo de fuentes | PK `id` (UUID), UK `source_id` |
| `pipeline_runs` | Ejecuciones de pipeline | PK `id`, FK `source_id`, `status`, `trace_id`, `stages` (JSONB) |
| `ingestion_events` | Eventos raw ingeridos | PK `id`, FK `source_id`, `pipeline_run_id`, `payload` (JSONB), `payload_hash` |
| `feature_records` | Features procesadas + metadata semántica | PK `id`, FK `ingestion_event_id`, `features` (JSONB), `feature_metadata` (JSONB), `lineage` (UUID[]) |
| `analysis_results` | Resultados de agentes LLM | PK `id`, FK `pipeline_run_id`, `agent_id`, `result` (JSONB), `tokens_used`, `llm_model`, `confidence` |
| `langgraph_checkpoints` | Estado LangGraph (recovery) | PK `thread_id`, `checkpoint` (JSONB), `metadata` (JSONB) |

### 5.2 Índices Críticos
```sql
CREATE INDEX idx_pipeline_runs_status ON pipeline_runs(status);
CREATE INDEX idx_pipeline_runs_started ON pipeline_runs(started_at);
CREATE INDEX idx_ingestion_source ON ingestion_events(source_id);
CREATE INDEX idx_ingestion_run ON ingestion_events(pipeline_run_id);
CREATE INDEX idx_features_entity_created ON feature_records(entity_id, created_at DESC);
CREATE INDEX idx_analysis_run ON analysis_results(pipeline_run_id);
CREATE INDEX idx_langgraph_thread ON langgraph_checkpoints(thread_id);
```

---

## 6. API REST (Endpoints)

| Método | Path | Descripción | Auth |
|--------|------|-------------|------|
| `POST` | `/sources` | Registrar source (API, CSV, DB, Scrap) | `ingest:write` |
| `GET` | `/sources` | Listar sources | `ingest:read` |
| `POST` | `/pipelines/{source_id}/ingest` | Trigger ingesta manual (async, 202) | `ingest:write` |
| `GET` | `/pipelines/{run_id}` | Estado + métricas del run | `ingest:read` |
| `GET` | `/pipelines/{run_id}/results` | Resultados análisis consolidados | `analysis:read` |
| `POST` | `/analysis/ask` | Pregunta directa a agentes (SQL/Python/Viz/Insight) | `analysis:write` |
| `GET` | `/health/live` | Liveness probe | — |
| `GET` | `/health/ready` | Readiness probe (DB + Redis + LLM) | — |
| `GET` | `/metrics` | Métricas Prometheus | — |
| `GET` | `/connectors` | Conectores registrados | — |
| `GET` | `/agents` | Agentes registrados (incluye modelos LLM) | — |

### 6.1 Endpoint `/analysis/ask` (Interacción Directa)
```bash
POST /analysis/ask
Authorization: Bearer <JWT>
{
  "question": "Ventas por canal última semana",
  "agent": "sql",           # sql | python | viz | insight | auto
  "entity_ids": ["..."],    # opcional
  "context": {"date_range": "last_7d"}
}
# Response: {agent: "sql", result: {...}, sql: "...", confidence: 0.94, tokens: 1234}
```

---

## 7. Sistema de Plugins (Extensibilidad)

### 7.1 Conectores (entry_point: `data_platform.connectors`)
```python
from data_platform.connectors.base import BaseConnector, register_connector

class StripeConnector(BaseConnector):
    name = "stripe"
    async def fetch(self, config, last_cursor=None): ...
    def validate_config(self, config): ...

register_connector(StripeConnector())
```

### 7.2 Agentes LLM (entry_point: `data_platform.agents`)
```python
from data_platform.agents.base import BaseLLMAgent, register_agent

class CustomMLAgent(BaseLLMAgent):
    name = "custom_ml"
    system_prompt = "Eres un experto en..."
    model = "gpt-4o"
    
    async def run(self, input: AgentInput) -> AgentOutput: ...

register_agent(CustomMLAgent())
```

---

## 8. Observabilidad

| Pilar | Implementación |
|-------|----------------|
| **Logs** | JSON estructurado via `structlog` (service, trace_id, event, metrics, llm_tokens) |
| **Métricas** | `/metrics` Prometheus (counters, histograms por etapa + LLM tokens/latencia) |
| **Tracing** | OpenTelemetry → Jaeger (spans: API, worker, LLM call, DB, sandbox) |
| **Health** | `/health/live` + `/health/ready` (verifica DB, Redis, LLM connectivity) |

### 8.1 Métricas Prometheus (incluye LLM)
```prometheus
# LLM específicas
llm_tokens_total{agent, model, type="prompt|completion"}
llm_latency_seconds{agent, model}
llm_cost_usd_total{agent, model}
agent_confidence_histogram{agent}
```

---

## 9. Seguridad y Costos LLM

### 9.1 Autenticación JWT
- **Algoritmo:** HS256 (demo) / RS256 + JWKS (prod)
- **Scopes:** `ingest:write`, `ingest:read`, `analysis:read`, `analysis:write`, `admin`

### 9.2 Rate Limiting (Lua Atómico)
Token bucket sliding window en Redis ZSET — atómico, distribuido.

### 9.3 Control de Costos LLM
| Mecanismo | Descripción |
|-----------|-------------|
| **Budget por pipeline** | `max_tokens_per_run` configurable por source |
| **Model routing** | Preguntas simples → `gpt-4o-mini`; complejas → `gpt-4o` |
| **Cache semántico** | Embedding de pregunta → cache Redis 24h (ahorra 60-80%) |
| **Quotas por tenant** | `daily_token_limit` por `client_id` |
| **Observabilidad** | `/metrics` expone `llm_cost_usd_total` para alertas |

---

## 10. Despliegue (Docker Compose)

### 10.1 Servicios
```yaml
services:
  api-gateway:    # FastAPI :8000
  orchestrator:   # LangGraph API :8001
  ingestor:       # Worker ingesta (x3)
  etl-worker:     # Worker ETL (x2)
  sql-agent:      # Worker SQL Agent (x2)
  python-agent:   # Worker Python Agent (x2)
  viz-agent:      # Worker Viz Agent (x1)
  insight-agent:  # Worker Insight Agent (x1)
  postgres:       # PG 16 :5432
  redis:          # Redis 7 Streams :6379
  jaeger:         # Tracing :16686
```

### 10.2 Variables de Entorno (.env)
```bash
# LLM
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
LLM_DEFAULT_MODEL=gpt-4o-mini
LLM_MAX_TOKENS_PER_RUN=50000

# Auth
JWT_SECRET=dev-secret-change-in-prod-min-32-chars
JWT_ALGORITHM=HS256

# Infra
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/platform
REDIS_URL=redis://redis:6379/0
JAEGER_ENDPOINT=http://jaeger:14268/api/traces
LOG_LEVEL=INFO
```

### 10.3 Quickstart
```bash
cp .env.example .env
# Editar .env con OPENAI_API_KEY / ANTHROPIC_API_KEY
docker compose up -d
curl http://localhost:8000/health/ready
open http://localhost:8000/docs
```

---

## 11. Caso de Uso: Ingesta Diaria + Análisis LLM (E-commerce)

### 11.1 Contexto
**Empresa:** Marketplace online con 50K pedidos/día  
**Objetivo:** Unificar datos de pedidos, catálogo y eventos web → dashboards + alertas automáticas con narrativa.

### 11.2 Flujo Diario (2:00 AM)
```
┌─────────────────────────────────────────────────────────────────┐
│ 02:00  CRON → 3 sources en paralelo (orders_api, catalog, web) │
│ 02:05  Ingesta completada → 15K IngestionEvents                │
│ 02:06  ETL → 15K FeatureRecords v1.0.0 (customer, total, ...)  │
│ 02:07  LangGraph: analysis:fanout (4 agentes en paralelo)      │
│         ├─ SQL Agent: "Ventas por canal/día + top productos"   │
│         ├─ Python Agent: "Forecast 7d con Prophet"             │
│         ├─ Viz Agent: "Dashboard ejecutivo interactivo"        │
│         └─ Insight Agent: "Anomalías + narrativa Slack"        │
│ 02:10  Merge → PipelineRun completed                           │
│ 02:10  GET /pipelines/{id}/results → Dashboards + Alertas      │
└─────────────────────────────────────────────────────────────────┘
```

### 11.3 Ejemplo Pregunta Directa (`/analysis/ask`)
```bash
# Usuario de negocio pregunta:
POST /analysis/ask
{"question": "¿Por qué bajaron ventas mobile ayer?", "agent": "insight"}

# Respuesta Insight Agent:
{
  "agent": "insight",
  "result": {
    "anomalies": [{"metric": "mobile_sales", "expected": 12500, "actual": 9600, "deviation_pct": -23}],
    "narrative": "Las ventas mobile cayeron 23% vs media 7d (9.6K vs 12.5K). "
                 "Coincide con deploy v2.3.1 que introdujo bug en checkout iOS "
                 "(error rate 4.2% vs 0.1% baseline). "
                 "Impacto estimado: -2.9K€/día. "
                 "Acción: rollback inmediato v2.3.1 → v2.3.0.",
    "severity": "critical",
    "recommendations": ["Rollback v2.3.1", "Monitor checkout iOS", "Alertar on-call"]
  },
  "confidence": 0.91,
  "tokens_used": 2341,
  "llm_model": "gpt-4o"
}
```

---

## 12. Decisiones Técnicas Clave

| Decisión | Justificación |
|----------|---------------|
| **LangGraph** | Checkpoints persistentes, recovery, human-in-the-loop, fan-out nativo, visualización DAG |
| **LLM Agents (no hardcoded)** | Flexibilidad: text-to-SQL, code-gen, viz-gen, reasoning — un framework, 4+ agentes |
| **Semantic Layer en PG** | `feature_metadata` (descriptions, units) → LLM entiende datos sin contexto manual |
| **Sandbox Python** | Ejecución segura código LLM (subproceso, timeout, sin red/FS, memory limit) |
| **Cache semántico LLM** | Embedding pregunta → Redis 24h → ahorro 60-80% tokens, latencia <100ms |
| **Budget/Quotas** | Control de costos real: `max_tokens_per_run`, `daily_limit` por tenant |
| **OpenTelemetry + Jaeger** | Trazabilidad end-to-end: API → Worker → LLM → DB → Sandbox |
| **Plugin entry_points** | Extensible sin tocar core: `pip install data-platform-stripe` |

---

## 13. Testing

```bash
# Unit tests (schemas, models, connectors, agents mock, security)
pytest tests/test_core.py -v

# Integration tests (testcontainers PG/Redis + mock LLM)
pytest tests/integration/ -v

# Contract tests (LLM output schemas)
pytest tests/contracts/ -v

# Load test (locust)
locust -f tests/load/locustfile.py
```

---

## 14. Estructura del Proyecto

```
data_platform/
├── api/
│   ├── main.py              # FastAPI + lifespan + middleware
│   └── routes/
│       ├── health.py        # /health/live, /health/ready, /metrics
│       ├── sources.py       # CRUD sources
│       ├── pipelines.py     # Trigger + status + results
│       └── analysis.py      # /analysis/ask (LLM agents directos)
├── orchestrator/
│   ├── graph.py             # LangGraph StateGraph definition
│   ├── nodes.py             # ingest_node, etl_node, analysis_node, merge_node
│   └── state.py             # PipelineState (TypedDict)
├── connectors/
│   ├── base.py              # BaseConnector + registry + entry_points
│   └── http.py              # HTTPConnector genérico
├── agents/
│   ├── base.py              # BaseLLMAgent + AgentInput/Output + registry
│   ├── sql.py               # SQLAgent (text-to-SQL + validación)
│   ├── python.py            # PythonAgent (code-gen + sandbox)
│   ├── viz.py               # VizAgent (plotly-gen)
│   └── insight.py           # InsightAgent (anomalías + narrativa)
├── core/
│   ├── config.py            # Pydantic Settings (incluye LLM)
│   ├── database.py          # SQLAlchemy async + init_db
│   ├── redis.py             # Client + rate limiter (Lua) + Stream helpers
│   ├── observability.py     # Structlog + Prometheus + OpenTelemetry
│   ├── security.py          # JWT + rate limit + scopes
│   ├── llm.py               # Cliente LLM unificado (OpenAI/Anthropic) + cache
│   └── sandbox.py           # Python sandbox (subprocess + resource limits)
├── models/__init__.py       # SQLAlchemy models (6 tablas + checkpoints)
├── schemas/__init__.py      # Pydantic contracts (incluye AgentInput/Output)
└── workers/
    ├── ingestor.py
    ├── etl.py
    ├── sql_agent.py
    ├── python_agent.py
    ├── viz_agent.py
    └── insight_agent.py
```

---

## 15. Limitaciones Conocidas (MVP)

| Área | Limitación | Solución Futura |
|------|------------|-----------------|
| **LLM Costs** | Sin API keys reales en demo | Mock LLM client para demo; config real en prod |
| **Sandbox** | Subproceso básico | gVisor / Firecracker / WASM para aislamiento fuerte |
| **Cache Semántico** | Embedding simple | Vector DB (pgvector / Pinecone) + reranking |
| **Multi-tenancy** | Sin RLS | PostgreSQL RLS + row-level budgets |
| **Eval LLM** | Sin benchmark | Dataset golden + LLM-as-judge (correctness, safety) |
| **Deploy** | Solo Docker Compose | Kubernetes + KEDA (scale by stream lag) |

---

## 16. Referencias Técnicas

- LangGraph: https://langchain-ai.github.io/langgraph/
- OpenAI Function Calling: https://platform.openai.com/docs/guides/function-calling
- Anthropic Tool Use: https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- FastAPI: https://fastapi.tiangolo.com/tutorial/
- SQLAlchemy 2.0 Async: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- Redis Streams: https://redis.io/docs/latest/develop/data-types/streams/
- OpenTelemetry Python: https://opentelemetry.io/docs/instrumentation/python/
- Great Expectations: https://greatexpectations.io/

---

**Fin del Documento**  
*Plataforma Agéntica de Datos - MVP v1.0 (LLM-Powered)*