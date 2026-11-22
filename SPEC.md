# Spec Técnica - Plataforma Agéntica de Datos

---

## 1. API REST (OpenAPI 3.0)

### Auth
```
Authorization: Bearer <JWT>
Scopes: ingest:read, ingest:write, analysis:read, analysis:write, admin
```

### Endpoints Core

| Método | Path | Descripción |
|--------|------|-------------|
| `POST` | `/sources` | Registrar source config |
| `GET` | `/sources` | Listar sources |
| `POST` | `/sources/{id}/ingest` | Trigger ingesta manual |
| `GET` | `/pipelines/{run_id}` | Estado pipeline run |
| `GET` | `/pipelines/{run_id}/results` | Resultados análisis |
| `GET` | `/features/{entity_id}` | Consultar features |
| `POST` | `/analysis/sql` | Ejecutar query SQL Agent |
| `POST` | `/analysis/python` | Ejecutar código Python Agent |
| `GET` | `/dashboards/{id}` | Render dashboard HTML |
| `GET` | `/health/live` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe |

### Source Config (POST /sources)
```json
{
  "source_id": "stripe_charges",
  "type": "api",
  "config": {
    "base_url": "https://api.stripe.com/v1",
    "auth": {"type": "bearer", "secret_ref": "stripe_key"},
    "endpoint": "/charges",
    "params": {"limit": 100, "created[gt]": "{{last_run}}"},
    "pagination": "cursor",
    "rate_limit": {"requests": 100, "window_seconds": 60}
  },
  "schedule": "0 */6 * * *",
  "enabled": true
}
```

### Pipeline Run Response
```json
{
  "run_id": "uuid",
  "status": "running|completed|failed|partial",
  "started_at": "ISO8601",
  "completed_at": "ISO8601|null",
  "stages": {
    "ingestion": {"status": "completed", "records": 1500, "duration_ms": 2340},
    "etl": {"status": "completed", "features_created": 45, "duration_ms": 5600},
    "analysis": {"status": "running", "agents": ["sql", "python", "viz"]}
  },
  "trace_id": "abc123"
}
```

---

## 2. Modelos de Datos (SQLAlchemy + Pydantic)

### Source
```python
class Source(Base):
    __tablename__ = "sources"
    id: UUID = Column(UUID, primary_key=True, default=uuid4)
    source_id: str = Column(String, unique=True, index=True)
    type: str = Column(String)  # api, csv, db, scrap
    config: dict = Column(JSONB)
    schedule: str = Column(String)  # cron
    enabled: bool = Column(Boolean, default=True)
    last_run_at: datetime | None = Column(DateTime)
    created_at: datetime = Column(DateTime, default=utcnow)
```

### PipelineRun
```python
class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id: UUID = Column(UUID, primary_key=True, default=uuid4)
    source_id: str = Column(String, ForeignKey("sources.source_id"), index=True)
    status: str = Column(String)  # pending, running, completed, failed, partial
    trace_id: str = Column(String, index=True)
    started_at: datetime = Column(DateTime, default=utcnow)
    completed_at: datetime | None = Column(DateTime)
    stages: dict = Column(JSONB)  # {stage: {status, metrics, error}}
    error: str | None = Column(Text)
```

### FeatureRecord
```python
class FeatureRecord(Base):
    __tablename__ = "feature_records"
    id: UUID = Column(UUID, primary_key=True, default=uuid4)
    entity_id: str = Column(String, index=True)
    features: dict = Column(JSONB)
    ingestion_event_id: UUID = Column(UUID, ForeignKey("ingestion_events.id"))
    processing_version: str = Column(String)  # v1.2.0
    lineage: list[UUID] = Column(ARRAY(UUID))
    created_at: datetime = Column(DateTime, default=utcnow)
    __table_args__ = (Index("ix_entity_created", "entity_id", "created_at"),)
```

### IngestionEvent
```python
class IngestionEvent(Base):
    __tablename__ = "ingestion_events"
    id: UUID = Column(UUID, primary_key=True, default=uuid4)
    source_id: str = Column(String, index=True)
    payload_hash: str = Column(String)  # sha256
    payload: dict = Column(JSONB)
    metadata: dict = Column(JSONB)  # content_type, size, checksum
    status: str = Column(String)  # raw, validated, failed
    created_at: datetime = Column(DateTime, default=utcnow)
```

---

## 3. Plugin System (Entry Points)

### pyproject.toml
```toml
[project.entry-points."data_platform.connectors"]
stripe = "connectors.stripe:StripeConnector"
postgres = "connectors.postgres:PostgresConnector"
csv_file = "connectors.csv:CSVConnector"
http_generic = "connectors.http:HTTPConnector"

[project.entry-points."data_platform.agents"]
sql = "agents.sql:SQLAgent"
python = "agents.python:PythonAgent"
viz = "agents.viz:VizAgent"
insight = "agents.insight:InsightAgent"
```

### Interface Base (abc)
```python
# connectors/base.py
class BaseConnector(ABC):
    @abstractmethod
    def fetch(self, config: dict, last_cursor: str | None) -> AsyncIterator[dict]:
        """Yield raw records"""
    
    @abstractmethod
    def validate_config(self, config: dict) -> ValidationResult:
        pass

# agents/base.py
class BaseAgent(ABC):
    @abstractmethod
    async def run(self, input: AgentInput) -> AgentOutput:
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass
```

---

## 4. Orquestación (LangGraph)

### State Schema
```python
class PipelineState(TypedDict):
    run_id: UUID
    source_id: str
    raw_events: list[RawEvent]
    features: list[FeatureRecord]
    analysis_results: dict[str, AnalysisResult]  # agent_name -> result
    merged_result: dict | None
    errors: list[str]
    current_stage: str
    retry_count: int
```

### Graph Definition
```python
def build_pipeline_graph() -> StateGraph:
    g = StateGraph(PipelineState)
    
    g.add_node("ingest", ingest_node)
    g.add_node("etl", etl_node)
    g.add_node("sql_analysis", sql_agent_node)
    g.add_node("python_analysis", python_agent_node)
    g.add_node("viz_analysis", viz_agent_node)
    g.add_node("insight_analysis", insight_agent_node)
    g.add_node("merge", merge_results_node)
    g.add_node("activate", activation_node)
    
    g.set_entry_point("ingest")
    g.add_edge("ingest", "etl")
    g.add_edge("etl", "sql_analysis")
    g.add_edge("etl", "python_analysis")
    g.add_edge("etl", "viz_analysis")
    g.add_edge("etl", "insight_analysis")
    g.add_edge(["sql_analysis", "python_analysis", "viz_analysis", "insight_analysis"], "merge")
    g.add_edge("merge", "activate")
    g.add_edge("activate", END)
    
    # Checkpointing
    g = g.compile(checkpointer=PostgresSaver(connection_string))
    return g
```

### Nodes (Simplified)
```python
async def ingest_node(state: PipelineState) -> PipelineState:
    connector = get_connector(state["source_id"])
    events = await connector.fetch(state.get("config", {}))
    validated = [validate_event(e) for e in events]
    await redis.xadd("ingestion:raw", [e.model_dump() for e in validated])
    return {**state, "raw_events": validated, "current_stage": "etl"}

async def etl_node(state: PipelineState) -> PipelineState:
    features = await etl_process(state["raw_events"])
    await feature_store.bulk_upsert(features)
    await lineage_tracker.record(features)
    return {**state, "features": features, "current_stage": "analysis"}

async def sql_agent_node(state: PipelineState) -> PipelineState:
    result = await sql_agent.run(features=state["features"])
    return {**state, "analysis_results": {**state["analysis_results"], "sql": result}}

# ... similar for python_agent_node, viz_agent_node, insight_agent_node

async def merge_results_node(state: PipelineState) -> PipelineState:
    merged = merge_with_confidence(state["analysis_results"])
    return {**state, "merged_result": merged}
```

---

## 5. Configuración (Pydantic Settings)

```python
class Settings(BaseSettings):
    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    JWT_SECRET: str
    JWT_ALGORITHM: str = "RS256"
    JWT_PUBLIC_KEY: str
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@postgres:5432/platform"
    DATABASE_POOL_SIZE: int = 20
    
    # Redis
    REDIS_URL: str = "redis://redis:6379/0"
    REDIS_MAX_CONNECTIONS: int = 50
    
    # Rate Limit
    DEFAULT_RATE_LIMIT: int = 100
    DEFAULT_RATE_WINDOW: int = 60
    
    # LangGraph
    LANGGRAPH_CHECKPOINT_TABLE: str = "langgraph_checkpoints"
    
    # Observability
    LOG_LEVEL: str = "INFO"
    JAEGER_ENDPOINT: str = "http://jaeger:14268/api/traces"
    PROMETHEUS_PORT: int = 9090
    
    # Agents
    AGENT_TIMEOUT_SECONDS: int = 300
    MAX_RETRIES: int = 3
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
```

---

## 6. Variables de Entorno (.env.example)

```bash
# Auth
JWT_SECRET=dev-secret-change-in-prod
JWT_PUBLIC_KEY=-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----

# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/platform

# Redis
REDIS_URL=redis://localhost:6379/0

# Observability
LOG_LEVEL=DEBUG
JAEGER_ENDPOINT=http://localhost:14268/api/traces

# External APIs (secrets)
STRIPE_API_KEY=sk_test_...
GITHUB_TOKEN=ghp_...
```

---

## 7. Estructura de Proyecto

```
data_platform/
├── api/
│   ├── routes/
│   │   ├── sources.py
│   │   ├── pipelines.py
│   │   ├── features.py
│   │   ├── analysis.py
│   │   └── health.py
│   ├── middleware/
│   │   ├── auth.py
│   │   ├── rate_limit.py
│   │   └── logging.py
│   └── main.py
├── orchestrator/
│   ├── graph.py
│   ├── nodes/
│   │   ├── ingest.py
│   │   ├── etl.py
│   │   ├── analysis.py
│   │   └── activation.py
│   └── state.py
├── agents/
│   ├── base.py
│   ├── sql/
│   ├── python/
│   ├── viz/
│   └── insight/
├── connectors/
│   ├── base.py
│   ├── stripe.py
│   ├── postgres.py
│   ├── csv.py
│   └── http.py
├── core/
│   ├── config.py
│   ├── database.py
│   ├── redis.py
│   ├── security.py
│   └── observability.py
├── models/
│   ├── source.py
│   ├── pipeline.py
│   ├── feature.py
│   └── event.py
├── schemas/
│   ├── source.py
│   ├── pipeline.py
│   └── analysis.py
└── plugins/
    └── registry.py

tests/
├── unit/
├── integration/
└── fixtures/
```

---

## 8. CI/CD (GitHub Actions - Resumen)

```yaml
# .github/workflows/ci.yml
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
      redis:
        image: redis:7
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e ".[dev]"
      - run: pytest --cov=data_platform --cov-fail-under=80
  
  lint:
    runs-on: ubuntu-latest
    steps:
      - run: ruff check .
      - run: mypy data_platform
  
  build:
    needs: [test, lint]
    runs-on: ubuntu-latest
    steps:
      - run: docker build -t data-platform:${{ github.sha }} .
      - run: docker push ...
```

---

## 9. Checklist de Entregables

- [ ] `docker-compose.yml` funcional (levanta todo con `docker compose up`)
- [ ] API documentada en `/docs` (Swagger UI)
- [ ] Pipeline E2E: source → ingest → etl → analysis → dashboard
- [ ] 3+ conectores: API (Stripe/GitHub), CSV, PostgreSQL
- [ ] 4 agentes: SQL, Python, Viz, Insight
- [ ] Feature Store con lineage
- [ ] Dashboard HTML de ejemplo (artifact)
- [ ] Tests unit + integration (>80% coverage)
- [ ] README con: arquitectura, quickstart, decisiones, troubleshooting