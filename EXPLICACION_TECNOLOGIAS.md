# Guía de Tecnologías - Para Entender el Scaffold

> **Este archivo NO se entrega**. Es tu guía personal para entender qué hace cada pieza y poder defenderla.

---

## Tabla de Contenidos

1. [Arquitectura General](#arquitectura-general)
2. [FastAPI](#fastapi)
3. [PostgreSQL + SQLAlchemy](#postgresql--sqlalchemy)
4. [Redis + Redis Streams](#redis--redis-streams)
5. [LangGraph](#langgraph)
6. [Prometheus + Grafana](#prometheus--grafana)
7. [Jaeger (Tracing)](#jaeger-tracing)
8. [Loki + Promtail (Logs)](#loki--promtail-logs)
9. [Docker Compose](#docker-compose)
10. [Pydantic + Pydantic Settings](#pydantic--pydantic-settings)
11. [Structlog](#structlog)
12. [Plugin System (Entry Points)](#plugin-system-entry-points)
12. [Recursos para Profundizar](#recursos-para-profundizar)

---

## Arquitectura General

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   API       │     │ Orchestrator│     │  Workers    │     │   Infra     │
│  Gateway    │────▶│  (LangGraph)│────▶│  (Agents)   │     │             │
│  (FastAPI)  │     │             │     │             │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
       │                   │                   │                │
       ▼                   ▼                   ▼                ▼
  ┌─────────┐         ┌─────────┐         ┌─────────┐    ┌──────────┐
  │  Auth   │         │ State   │         │ Redis   │    │PostgreSQL│
  │ Rate Lmt│         │ Checkpt │         │ Streams │    │  (Data)  │
  └─────────┘         └─────────┘         └─────────┘    └──────────┘
                                                        │
                                                ┌───────┴───────┐
                                                ▼               ▼
                                           ┌─────────┐    ┌──────────┐
                                           │Prometheus│    │  Jaeger  │
                                           │ Grafana  │    │  Loki    │
                                           └─────────┘    └──────────┘
```

**Flujo de un request:**
1. **Cliente** → `POST /sources/{id}/ingest` (con JWT)
2. **API Gateway** valida auth + rate limit → crea `PipelineRun` en PG
3. **Background task** invoca `pipeline_graph.ainvoke(state)` (LangGraph)
4. **Nodo ingest** → usa `HTTPConnector` → guarda events en PG + publica en Redis Stream
5. **Nodo etl** → transforma → guarda `FeatureRecord` en PG
6. **Nodo analysis** → ejecuta `SQLAgent` (y otros) → guarda `AnalysisResult` en PG
7. **Nodo merge** → consolida → actualiza `PipelineRun` con resultado final
8. **Cliente** → `GET /pipelines/{run_id}/results` ve todo

---

## FastAPI

### ¿Qué es?
Framework web moderno, rápido (async nativo), con validación automática via Pydantic y docs OpenAPI automáticas (`/docs`, `/redoc`).

### En nuestro código:
```python
# data_platform/api/main.py
app = FastAPI(lifespan=lifespan)  # lifespan = startup/shutdown
app.include_router(sources.router)  # modular: cada router = un archivo
```

### Conceptos clave:

| Concepto | Qué hace | Ejemplo en código |
|----------|----------|-------------------|
| **Dependency Injection** | `Depends(get_db)` inyecta sesión DB automáticamente | `db: AsyncSession = Depends(get_db)` |
| **Pydantic Models** | Validación automática request/response | `SourceCreate`, `SourceRead` |
| **BackgroundTasks** | Ejecuta código tras responder al cliente | `background.add_task(run_pipeline, ...)` |
| **Middleware** | Intercepta request/response global | `rate_limit_middleware` |
| **Lifespan** | Startup/shutdown async | `init_db()`, `load_connectors()`, `close_redis()` |

### Para la defensa:
- "FastAPI nos da validación automática, docs OpenAPI gratis, y async nativo para alto throughput"
- "Usamos Dependency Injection para DB, Redis, Auth - testable y desacoplado"

### Recursos:
- [FastAPI Official Tutorial](https://fastapi.tiangolo.com/tutorial/) - **Empieza aquí**
- [Async SQLAlchemy with FastAPI](https://fastapi.tiangolo.com/async-sql-databases/)
- [Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)

---

## PostgreSQL + SQLAlchemy

### ¿Qué es?
- **PostgreSQL**: BD relacional robusta, ACID, JSONB, arrays, extensiones (pgvector, timescaledb)
- **SQLAlchemy**: ORM + Core. Nosotros usamos **async** (`asyncpg` driver)

### En nuestro código:
```python
# data_platform/core/database.py
engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession)

async def get_db():
    async with async_session_maker() as session:
        yield session  # FastAPI cierra automáticamente
```

### Modelos (data_platform/models/__init__.py):
```python
class Source(Base):
    __tablename__ = "sources"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    source_id = Column(String, unique=True, index=True)
    config = Column(JSONB)           # JSON nativo, indexable
    schedule = Column(String)        # Cron expression
    
class FeatureRecord(Base):
    features = Column(JSONB)         # Features flexibles
    lineage = Column(ARRAY(UUID))    # Array de UUIDs para trazabilidad
```

### Por qué PostgreSQL y no MongoDB:
| Razón | Explicación |
|-------|-------------|
| **ACID** | Transacciones confiables para pipeline runs |
| **JSONB** | Schemas flexibles (features) + índices GIN |
| **Una sola BD** | Menos complejidad operacional |
| **Extensiones futuras** | `pgvector` para embeddings, `timescaledb` para series temporales |

### Para la defensa:
- "PostgreSQL con JSONB nos da lo mejor de los dos mundos: relacional para metadatos/pipeline runs, documento para features"
- "Async SQLAlchemy + asyncpg = no bloquea el event loop bajo carga"

### Recursos:
- [SQLAlchemy 2.0 Tutorial](https://docs.sqlalchemy.org/en/20/tutorial/) - **Imprescindible**
- [Async SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [PostgreSQL JSONB](https://www.postgresql.org/docs/current/datatype-json.html)
- [Indexes on JSONB](https://www.postgresql.org/docs/current/indexes-types.html#INDEXES-GIN)

---

## Redis + Redis Streams

### ¿Qué es Redis?
Key-value store en memoria, sub-milisegundo. Usado para: cache, colas, rate limiting, sessions.

### ¿Qué son Redis Streams?
**Log append-only** con consumer groups (como Kafka pero embebido en Redis).
- **Producer**: `XADD stream * field value`
- **Consumer Group**: `XREADGROUP GROUP group consumer STREAMS stream >`
- **ACK**: `XACK stream group msg_id`

### En nuestro código:

**Rate Limiter (Lua script atómico):**
```python
# data_platform/core/redis.py
RATE_LIMIT_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

redis.call('ZREMRANGEBYSCORE', key, 0, now - window * 1000)
local count = redis.call('ZCARD', key)
if count < limit then
    redis.call('ZADD', key, now, now .. '-' .. math.random())
    redis.call('EXPIRE', key, window)
    return {1, limit - count - 1}
else
    return {0, 0}
end
"""
```
- **Sorted Set** (`ZADD`/`ZCARD`) con timestamp como score
- **Lua** = atómico (race-condition free)
- **Ventana deslizante** (rolling window)

**Streams para colas async:**
```python
# Producer (ingest_node)
await stream_add("ingestion:raw", {"source_id": "...", "payload": "..."})

# Consumer (worker ingestor)
messages = await stream_consume_group("ingestion:raw", "ingestor-workers", "ingestor-1")
for msg_id, data in messages:
    process(data)
    await stream_ack("ingestion:raw", "ingestor-workers", msg_id)
```

### Por qué Redis Streams y no RabbitMQ/Kafka:
| Factor | Redis Streams |
|--------|---------------|
| **Dependencias** | Ya tienes Redis para cache/rate-limit |
| **Consumer Groups** | Nativo, reparto de carga automático |
| **Replay** | `XREAD COUNT 10 STREAMS stream 0` (desde inicio) |
| **Persistencia** | AOF + RDB (configurable) |
| **Simplicidad** | Un solo binario, sin ZooKeeper/KRaft |

### Para la defensa:
- "Redis Streams nos da colas persistentes con consumer groups sin agregar infraestructura extra"
- "Rate limiter en Lua atómico = sin race conditions bajo alta concurrencia"
- "Workers escalables horizontalmente: añades réplicas y se reparten el stream automáticamente"

### Recursos:
- [Redis Streams Intro](https://redis.io/docs/latest/develop/data-types/streams/) - **Oficial, claro**
- [Redis Streams vs Kafka](https://redis.io/blog/redis-streams-vs-kafka/)
- [Rate Limiting Patterns](https://redis.io/docs/latest/develop/use-cases/rate-limiting/)
- [Lua Scripting](https://redis.io/docs/latest/develop/use-cases/scripting/)

---

## LangGraph

### ¿Qué es?
Librería para **grafos de estado** (stateful graphs) construida sobre LangChain. Permite:
- Nodos = funciones (sync/async)
- Edges = transiciones condicionales
- **Checkpointing automático** (persistencia de estado)
- **Human-in-the-loop** (pausar/continuar)
- Visualización del grafo

### En nuestro código:
```python
# data_platform/orchestrator/nodes.py
from langgraph.graph import StateGraph, END

g = StateGraph(PipelineState)  # TypedDict = schema del estado

g.add_node("ingest", ingest_node)
g.add_node("etl", etl_node)
g.add_node("analysis", analysis_node)
g.add_node("merge", merge_node)

g.set_entry_point("ingest")
g.add_edge("ingest", "etl")
g.add_edge("etl", "analysis")
g.add_edge("analysis", "merge")
g.add_edge("merge", END)

pipeline_graph = g.compile()  # Compila a Runnable
```

**Estado (TypedDict):**
```python
# data_platform/orchestrator/state.py
class PipelineState(TypedDict):
    run_id: UUID
    source_id: str
    source_config: dict
    raw_events: list[dict]
    features: list[dict]
    analysis_results: dict[str, Any]
    merged_result: dict | None
    errors: list[str]
    current_stage: str
    retry_count: int
```

**Ejecución:**
```python
# En pipelines.py background task
result = await pipeline_graph.ainvoke(initial_state)
```

### Por qué LangGraph y no código manual:
| Característica | Código Manual | LangGraph |
|----------------|---------------|-----------|
| **Estado persistente** | Tú lo gestionas | Checkpointing automático (PG) |
| **Retry/Recovery** | Try/except manual | Reintentar desde checkpoint |
| **Visualización** | Ninguna | `graph.get_graph().draw_mermaid()` |
| **Human-in-loop** | Difícil | Nativo (`interrupt()`) |
| **Streaming** | Manual | `astream()` nativo |

### Para la defensa:
- "LangGraph nos da orquestación con estado persistente, checkpoints automáticos en PostgreSQL, y visualización del DAG sin código extra"
- "Si un pipeline falla en el nodo 3, podemos reanudar desde ahí sin repetir ingesta/ETL"
- "El estado es un TypedDict tipado = autocompletado y validación en IDE"

### Recursos:
- [LangGraph Official Docs](https://langchain-ai.github.io/langgraph/) - **Empieza aquí**
- [Concepts: State, Nodes, Edges](https://langchain-ai.github.io/langgraph/concepts/)
- [Checkpointing](https://langchain-ai.github.io/langgraph/concepts/checkpointing/)
- [How to: Human in the loop](https://langchain-ai.github.io/langgraph/how-tos/human_in_the_loop/)

---

## Prometheus + Grafana

### ¿Qué es Prometheus?
**Base de datos de series temporales** pull-based (scrapea métricas `/metrics` cada X segundos).
- **Data model**: Métrica + labels (key-value) + timestamp + valor
- **Query language**: PromQL
- **Alerting**: Alertmanager (separado)

### Métricas que exponemos (data_platform/core/observability.py):
```python
# Counter: solo sube (total requests, errors)
INGESTION_EVENTS = Counter("ingestion_events_total", "...", ["source_id", "status"])

# Histogram: latencias (buckets automáticos)
INGESTION_LATENCY = Histogram("ingestion_latency_seconds", "...", ["source_id"])

# Gauge: valor actual (sube/baja)
DLQ_SIZE = Gauge("dead_letter_queue_size", "...", ["stream"])
```

**Endpoint `/metrics`:**
```python
# En health.py
@router.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type="text/plain")
```

### Prometheus Config (prometheus.yml):
```yaml
scrape_configs:
  - job_name: 'api-gateway'
    static_configs:
      - targets: ['api-gateway:8000']  # DNS de Docker Compose
    metrics_path: '/metrics'
```

### Grafana:
Dashboard visual que consulta Prometheus via PromQL.
- Pre-provisionado via `grafana/dashboards/` y `grafana/datasources/`

### Para la defensa:
- "Prometheus pull model = no necesitamos push gateway, cada servicio expone `/metrics`"
- "Labels (source_id, status) = filtrar/agregar en PromQL: `rate(ingestion_events_total[5m])`"
- "Histograms = percentiles (p50, p95, p99) sin almacenar cada request"

### PromQL útiles:
```promql
# Requests por segundo por source
rate(ingestion_events_total[5m])

# Latencia p95
histogram_quantile(0.95, rate(ingestion_latency_seconds_bucket[5m]))

# Error rate
rate(ingestion_events_total{status="failed"}[5m]) / rate(ingestion_events_total[5m])

# Tamaño DLQ actual
dead_letter_queue_size
```

### Recursos:
- [Prometheus Basics](https://prometheus.io/docs/concepts/data_model/) - **Conceptos clave**
- [PromQL Tutorial](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Histogram vs Summary](https://prometheus.io/docs/practices/histograms/)
- [Grafana Dashboard Best Practices](https://grafana.com/docs/grafana/latest/dashboards/best-practices/)

---

## Jaeger (Tracing)

### ¿Qué es?
**Distributed Tracing**: sigue un request a través de múltiples servicios.
- **Trace**: árbol de spans (un request end-to-end)
- **Span**: operación individual (nombre, inicio, fin, tags, logs)
- **Context Propagation**: headers HTTP (`traceparent`, `baggage`)

### En nuestro código:
```python
# data_platform/core/observability.py (implícito via OpenTelemetry)
# Instrumentación automática:
# - FastAPI spans
# - SQLAlchemy spans (queries)
# - Redis spans
# - HTTPX spans (llamadas externas)

# Propagación manual en workers:
# baggage = {"pipeline_run_id": "...", "source_id": "..."}
```

**Docker Compose:**
```yaml
jaeger:
  image: jaegertracing/all-in-one:1.50
  ports:
    - "16686:16686"  # UI
    - "14268:14268"  # Collector (OTLP HTTP)
    - "6831:6831/udp" # Agent (Thrift)
```

### Para la defensa:
- "OpenTelemetry auto-instrumentation = zero code changes para traces básicos"
- "Trace ID propagado via headers = correlacionar logs/métricas/traces"
- "Jaeger UI permite ver cuellos de botella: ¿dónde se gasta el tiempo?"

### Recursos:
- [OpenTelemetry Python](https://opentelemetry.io/docs/instrumentation/python/) - **Setup**
- [Jaeger Architecture](https://www.jaegertracing.io/docs/1.50/architecture/)
- [W3C Trace Context](https://www.w3.org/TR/trace-context/) - **Estándar de propagación**

---

## Loki + Promtail (Logs)

### ¿Qué es Loki?
**"Like Prometheus, but for logs"**. Indexa solo **labels**, no el texto completo = barato y rápido.
- **Promtail**: agent que lee logs de archivos y los envía a Loki
- **LogQL**: query language similar a PromQL

### Configuración (loki-config.yml + promtail-config.yml):
```yaml
# promtail-config.yml
clients:
  - url: http://loki:3100/loki/api/v1/push

positions:
  filename: /tmp/positions.yaml

scrape_configs:
  - job_name: system
    static_configs:
      - targets: [localhost]
        labels:
          job: varlogs
          __path__: /var/log/*log
```

### En nuestro código:
```python
# data_platform/core/observability.py
# structlog → JSON stdout → Docker capture → Promtail → Loki
structlog.configure(processors=[..., JSONRenderer()])
```

### Para la defensa:
- "Structured logging (JSON) + Loki = queries tipo ` {service="api-gateway"} |= \"error\" `| json`"
- "Labels = filtrado rápido, texto completo = búsqueda cuando necesitas"
- "Correlación: trace_id en logs = saltar de Loki a Jaeger"

### Recursos:
- [Grafana Loki Docs](https://grafana.com/docs/loki/latest/)
- [LogQL Tutorial](https://grafana.com/docs/loki/latest/query/logql/)
- [Structlog + Loki](https://www.structlog.org/en/stable/why.html)

---

## Docker Compose

### ¿Qué es?
Orquestación local de contenedores multi-servicio. Un solo archivo define toda la stack.

### Nuestro docker-compose.yml (resumen):
```yaml
services:
  # App
  api-gateway:     # FastAPI :8000
  orchestrator:    # LangGraph server (futuro)
  ingestor:        # Worker (2 replicas)
  etl-worker:      # Worker (2 replicas)
  sql-agent:       # Worker (2 replicas)
  python-agent:    # Worker (2 replicas)
  viz-agent:       # Worker (1 replica)
  insight-agent:   # Worker (1 replica)
  
  # Infra
  postgres:        # :5432, healthcheck pg_isready
  redis:           # :6379, AOF + LRU
  
  # Observabilidad
  prometheus:      # :9090, scrape config
  grafana:         # :3000, dashboards pre-provisionados
  jaeger:          # :16686 UI, :14268 collector
  loki:            # :3100
  promtail:        # Lee /var/log
```

### Puntos clave:
| Feature | Uso |
|---------|-----|
| `depends_on` + `condition: service_healthy` | Orden de arranque real (no solo "started") |
| `healthcheck` | PG: `pg_isready`, Redis: `redis-cli ping`, API: `curl /health/live` |
| `volumes` | Persistencia (pgdata, redisdata) + config montada |
| `deploy.replicas` | Escalado horizontal workers (solo Compose v3+) |
| `networks` implícito | DNS interno: `postgres`, `redis`, `api-gateway` |

### Para la defensa:
- "Un comando (`docker compose up -d`) levanta toda la stack con healthchecks y DNS interno"
- "Workers escalables: `docker compose up -d --scale ingestor=5`"
- "Config externa via `.env` + volúmenes = mismo compose para dev/staging/prod"

### Recursos:
- [Docker Compose Spec](https://docs.docker.com/compose/compose-file/)
- [Healthchecks](https://docs.docker.com/compose/compose-file/compose-file-v3/#healthcheck)
- [Docker Networking](https://docs.docker.com/compose/networking/)

---

## Pydantic + Pydantic Settings

### ¿Qué es Pydantic?
Validación de datos via **type hints**. Rust-backed (v2) = rápido.
- Models = esquemas request/response
- Settings = config desde env vars + `.env` + secrets

### En nuestro código:
```python
# data_platform/schemas/__init__.py
class SourceCreate(BaseModel):
    source_id: str = Field(pattern=r"^[a-z_]+$")
    type: str = Field(pattern=r"^(api|csv|db|scrap)$")
    config: dict
    schedule: str | None = None
    enabled: bool = True

class SourceRead(SourceCreate):
    id: UUID
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)  # ORM mode
```

```python
# data_platform/core/config.py
class Settings(BaseSettings):
    API_HOST: str = "0.0.0.0"
    JWT_SECRET: str = Field(default="dev-secret...")
    DATABASE_URL: str = "postgresql+asyncpg://..."
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()  # Singleton cached
```

### Para la defensa:
- "Pydantic v2 = validación en C/Rust, 10-50x más rápido que v1"
- "Settings = single source of truth para config, type-safe, con `.env` override"
- `from_attributes=True` = convierte ORM models → Pydantic automáticamente

### Recursos:
- [Pydantic v2 Docs](https://docs.pydantic.dev/latest/) - **Migración v1→v2**
- [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [FastAPI + Pydantic](https://fastapi.tiangolo.com/tutorial/body/)

---

## Structlog

### ¿Qué es?
Logging estructurado (key-value) en lugar de strings. Output JSON nativo.
- **Processors pipeline**: cada log pasa por cadena de procesadores
- **Context binding**: `logger.bind(request_id="...")` añade a todos los logs siguientes

### En nuestro código:
```python
# data_platform/core/observability.py
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),  # ← Output JSON
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)
```

**Uso:**
```python
logger = get_logger(__name__)
logger.info("ingestion_completed", source_id="stripe", records=1500, duration_ms=2340)
# {"timestamp":"2026-...","level":"info","event":"ingestion_completed",
#  "source_id":"stripe","records":1500,"duration_ms":2340}
```

### Para la defensa:
- "JSON logs = parsables por Loki/Promtail sin regex frágiles"
- "Context binding = trace_id automático en todos los logs de un request"
- "Structured = queries tipo ` {service="api"} duration_ms>1000` en Loki"

### Recursos:
- [Structlog Docs](https://www.structlog.org/en/stable/)
- [Structlog + OpenTelemetry](https://www.structlog.org/en/stable/integrations.html#opentelemetry)

---

## Plugin System (Entry Points)

### ¿Qué es?
Mecanismo estándar Python (`importlib.metadata`) para **descubrimiento automático** de paquetes que exponen funcionalidad bajo un nombre.

### En nuestro pyproject.toml:
```toml
[project.entry-points."data_platform.connectors"]
http_generic = "data_platform.connectors.http:HTTPConnector"

[project.entry-points."data_platform.agents"]
sql = "data_platform.agents.sql:SQLAgent"
```

### En código (connectors/base.py):
```python
async def load_connectors():
    from importlib.metadata import entry_points
    for ep in entry_points(group="data_platform.connectors"):
        connector_class = ep.load()  # Importa dinámicamente
        register_connector(connector_class())
```

### Ventajas:
| Ventaja | Explicación |
|---------|-------------|
| **Extensibilidad** | Nuevo conector = nuevo paquete, cero cambios en core |
| **Separación** | Conectores pueden vivir en repos/distintos |
| **Testing** | Mockear entry points en tests |
| **Standard** | Usado por pytest, sphinx, flask, etc. |

### Para la defensa:
- "Entry points = plugin system nativo Python, sin dependencias extra"
- "Para añadir Stripe: `pip install data-platform-stripe` y se auto-registra"
- "Cumple requisito 'múltiples fuentes' de forma extensible"

### Recursos:
- [Packaging Python - Entry Points](https://packaging.python.org/en/latest/specifications/entry-points/)
- [importlib.metadata](https://docs.python.org/3/library/importlib.metadata.html)

---

## Recursos para Profundizar

### Libros (gratuitos online):
| Libro | Link |
|-------|------|
| **Designing Data-Intensive Applications** (DDIA) | [Martin Kleppmann](https://dataintensive.github.io/) - **La biblia** |
| **Building Microservices** | [Sam Newman](https://microservices.io/) |
| **Site Reliability Engineering** | [Google SRE Book](https://sre.google/books/) |

### Cursos/Documentación Oficial:
| Tema | Resource |
|------|----------|
| **FastAPI** | [Tutorial Oficial](https://fastapi.tiangolo.com/tutorial/) |
| **SQLAlchemy 2.0** | [Tutorial](https://docs.sqlalchemy.org/en/20/tutorial/) |
| **Redis Streams** | [Redis University RU102](https://university.redis.com/) |
| **Prometheus** | [Prometheus Basics](https://prometheus.io/docs/introduction/overview/) |
| **OpenTelemetry** | [Python Instrumentation](https://opentelemetry.io/docs/instrumentation/python/) |
| **LangGraph** | [LangGraph Concepts](https://langchain-ai.github.io/langgraph/concepts/) |

### Artículos Clave:
| Título | Por qué leerlo |
|--------|----------------|
| [Logs vs Metrics vs Traces](https://www.cncf.io/blog/2020/12/16/logs-metrics-and-traces-whats-the-difference/) | Entender los 3 pilares |
| [Rate Limiting Algorithms](https://blog.figma.com/an-alternative-approach-to-rate-limiting-f8a06cf7c94c) | Token bucket vs sliding window |
| [JSONB in PostgreSQL](https://www.citusdata.com/blog/2016/07/14/choosing-nosql-postgresql-jsonb/) | Cuándo usar JSONB |
| [Distributed Tracing Theory](https://opentelemetry.io/docs/concepts/observability-primer/) | Conceptos base |

### Para Practicar:
1. **Levanta la stack**: `docker compose up -d` → explora Grafana (localhost:3000), Jaeger (localhost:16686)
2. **Haz requests**: `curl http://localhost:8000/health/ready` → mira logs JSON en Loki
3. **Rompe cosas**: Para un worker → mira DLQ crecer en Prometheus
4. **Añade un conector**: Crea `connectors/mock.py` con `BaseConnector` y registra en entry_points

---

## Checklist Mental para la Defensa

- [ ] **¿Por qué FastAPI?** Async, validación auto, OpenAPI gratis
- [ ] **¿Por qué PostgreSQL + JSONB?** ACID + flexibilidad, una sola BD
- [ ] **¿Por qué Redis Streams?** Colas + consumer groups sin Kafka
- [ ] **¿Por qué LangGraph?** Estado persistente, checkpoints, visualización
- [ ] **¿Cómo manejo fallos?** Retry (tenacity), DLQ, checkpoints LangGraph
- [ ] **¿Cómo escalo?** Workers stateless + `docker compose scale`
- [ ] **¿Cómo observo?** Logs (Loki), Métricas (Prometheus), Traces (Jaeger)
- [ ] **¿Cómo configuro?** Pydantic Settings + `.env` + secrets externos
- [ ] **¿Cómo extiendo?** Entry points plugins (conectores/agentes)

---

## Glosario Rápido

| Término | Significado |
|---------|-------------|
| **ACID** | Atomicity, Consistency, Isolation, Durability (propiedades transaccionales) |
| **AOF** | Append-Only File (persistencia Redis) |
| **Backpressure** | Control de flujo: consumidor lento frena al productor |
| **Baggage** | Contexto propagado en traces (W3C) |
| **Checkpoint** | Snapshot de estado para recovery |
| **Consumer Group** | Grupo de consumers que se reparten particiones de un stream |
| **DLQ** | Dead Letter Queue (cola de mensajes fallidos tras retries) |
| **Entry Point** | Plugin discovery estándar Python |
| **GIN Index** | Generalized Inverted Index (para JSONB/arrays en PG) |
| **Idempotency** | Operación repetible sin efectos secundarios |
| **Labels** | Key-value adjuntos a métricas/logs/traces para filtrado |
| **NullPool** | Pool de conexiones que no hace pooling (una por request) |
| **OTLP** | OpenTelemetry Protocol (formato estándar traces/métricas/logs) |
| **PromQL** | Query language de Prometheus |
| **Rolling Window** | Ventana de tiempo deslizante (vs fixed window) |
| **SLA/SLO/SLI** | Service Level Agreement/Objective/Indicator |
| **Span** | Unidad de trabajo en un trace |
| **Token Bucket** | Algoritmo rate limiting (tokens se regeneran) |
| **Trace** | Árbol de spans = un request end-to-end |
| **TypedDict** | Type hint para dicts con claves fijas (Python 3.8+) |
| **WAL** | Write-Ahead Log (PostgreSQL) |

---

> **Tip final**: Si te preguntan "¿por qué X y no Y?", responde con **trade-offs concretos** (ej: "Redis Streams vs Kafka: elegimos Redis porque ya lo teníamos para rate-limit/cache, simplifica ops, y consumer groups cubren nuestra necesidad actual. Kafka lo evaluaríamos si necesitamos replay masivo o retención de años").