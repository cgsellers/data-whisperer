# Agentic Data Platform

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue.svg)](https://postgresql.org)
[![Redis](https://img.shields.io/badge/Redis-7-red.svg)](https://redis.io)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.1+-orange.svg)](https://langchain-ai.github.io/langgraph)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue.svg)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Production-ready agentic data platform** with 4 specialized LLM agents (SQL, Python, Viz, Insight) orchestrated via LangGraph with persistent checkpoints, plugin architecture, and full observability.

## Architecture Overview

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Ingest    │────▶│    ETL      │────▶│  Analysis   │────▶│  Activation │
│  (Connectors)│    │ (Transform) │    │ (4 Agents)  │    │ (Dashboards,│
└─────────────┘     └─────────────┘     └─────────────┘     │  Alerts)    │
                                                          └─────────────┘
       │                   │                   │                   │
       ▼                   ▼                   ▼                   ▼
  ┌─────────┐         ┌─────────┐         ┌─────────┐         ┌─────────┐
  │ HTTP    │         │ Feature │         │ SQL     │         │ Grafana │
  │ Generic │         │ Records │         │ Agent   │         │ Dash-   │
  │ Connector        │ (JSONB) │         │ (Text-  │         │ boards  │
  └─────────┘         └─────────┘         │ to-SQL) │         └─────────┘
                                           └─────────┘
                                           ┌─────────┐
                                           │ Python  │
                                           │ Agent   │
                                           │ (Code   │
                                           │  Gen)   │
                                           └─────────┘
                                           ┌─────────┐
                                           │ Viz     │
                                           │ Agent   │
                                           │ (Plotly)│
                                           └─────────┘
                                           ┌─────────┐
                                           │ Insight │
                                           │ Agent   │
                                           │ (Anomaly│
                                           │ +Narr.) │
                                           └─────────┘
```

## Key Features

### Core Platform
- **Multi-source Ingestion** — Plugin-based connectors (HTTP, extensible via entry_points)
- **ETL Pipeline** — JSONB feature store with lineage tracking
- **LangGraph Orchestration** — Persistent checkpoints (PostgreSQL + Memory fallback) with resume capability
- **4 Specialized LLM Agents** — Running in parallel via Redis Streams consumer groups

### Agents
| Agent | Capability | Technology |
|-------|------------|------------|
| **SQL Agent** | Text-to-SQL with parameterized queries | SQLAlchemy + LLM |
| **Python Agent** | Code generation + sandboxed execution | subprocess + resource limits |
| **Viz Agent** | Plotly specification generation | Plotly JSON schema |
| **Insight Agent** | Anomaly detection + narrative generation | Statistical analysis + LLM |

### Observability & Reliability
- **Structured JSON Logging** — structlog with correlation IDs
- **Prometheus Metrics** — Custom counters/histograms + LLM token/cost tracking
- **Distributed Tracing** — OpenTelemetry + Jaeger
- **Rate Limiting** — Lua-based sliding window in Redis (atomic)
- **JWT Authentication** — HS256 with role-based scopes
- **Semantic Cache** — Embedding-based LLM response caching

### Developer Experience
- **Plugin System** — `importlib.metadata` entry_points for connectors/agents
- **Type Safety** — Full Pydantic + SQLAlchemy + TypedDict models
- **OpenAPI Docs** — Auto-generated at `/docs` and `/redoc`
- **Health Checks** — `/health/live` (liveness) + `/health/ready` (readiness)

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.11+ (for local development)

### 1. Clone & Configure
```bash
git clone <your-repo-url>
cd agentic-data-platform
cp .env.example .env
# Edit .env with your API keys (OPENAI_API_KEY, ANTHROPIC_API_KEY)
```

### 2. Start Infrastructure
```bash
docker compose up -d postgres redis jaeger
```

### 3. Run API Gateway
```bash
# Option A: Docker
docker compose up -d api-gateway

# Option B: Local (for development)
pip install -e .
uvicorn data_platform.api.main:app --reload --port 8000
```

### 4. Run Workers (in separate terminals)
```bash
# Terminal 1
python -m data_platform.workers.ingestor

# Terminal 2
python -m data_platform.workers.etl

# Terminal 3
python -m data_platform.workers.analysis

# Terminal 4
python -m data_platform.workers.merge

# Terminal 5-8 (agents - can scale horizontally)
python -m data_platform.workers.sql_agent
python -m data_platform.workers.python_agent
python -m data_platform.workers.viz_agent
python -m data_platform.workers.insight_agent
```

### 5. Test the Platform
```bash
# Generate admin token
python generate_token.py --role admin

# Run E2E test
python test_e2e.py
```

### 6. Access Services
- **API Gateway**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Orchestrator**: http://localhost:8001
- **Jaeger UI**: http://localhost:16686
- **Prometheus**: http://localhost:9090 (if enabled)

## API Usage Examples

### Create a Data Source
```bash
curl -X POST http://localhost:8000/sources \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": "my_api",
    "type": "api",
    "config": {
      "base_url": "https://api.example.com",
      "endpoint": "/data",
      "method": "GET",
      "pagination": {"type": "cursor", "cursor_param": "next"}
    },
    "enabled": true
  }'
```

### Trigger Ingestion
```bash
curl -X POST http://localhost:8000/pipelines/my_api/ingest \
  -H "Authorization: Bearer <TOKEN>"
```

### Ask Questions (Natural Language)
```bash
curl -X POST http://localhost:8000/analysis/ask \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Show me sales by channel for the last 7 days",
    "source_id": "my_api",
    "agent": "auto"
  }'
```

**Response:**
```json
{
  "run_id": "abc-123",
  "status": "completed",
  "answer": "Análisis para: \"Show me sales by channel...\"\n\n📊 **Insight**: Web channel shows 23% growth...\n🗄️ **SQL**: 7 rows returned\n🐍 **Python**: Statistical analysis completed\n📈 **Visualization**: Bar chart generated\n\n--- Tokens: 1,247",
  "sql_result": {"rows": [...], "query": "SELECT ..."},
  "python_result": {"output": "mean: 1234, std: 56"},
  "viz_result": {"spec": {"data": [...], "layout": {...}}},
  "insight_result": {"narrative": "...", "anomalies": [...]},
  "tokens_used": 1247
}
```

### Resume from Checkpoint
```bash
curl -X POST http://localhost:8001/pipelines/abc-123/resume \
  -H "Authorization: Bearer <TOKEN>"
```

## Project Structure

```
agentic-data-platform/
├── data_platform/
│   ├── api/                    # FastAPI application
│   │   ├── main.py            # App factory, lifespan, middleware
│   │   └── routes/            # REST endpoints
│   ├── agents/                # 4 LLM Agents
│   │   ├── base.py           # BaseLLMAgent, registry, I/O models
│   │   ├── sql.py            # Text-to-SQL execution
│   │   ├── python.py         # Code generation + sandbox
│   │   ├── viz.py            # Plotly spec generation
│   │   └── insight.py        # Anomaly detection + narrative
│   ├── connectors/           # Plugin-based ingestion
│   │   ├── base.py          # BaseConnector, registry, entry_points
│   │   └── http.py          # HTTP generic connector
│   ├── core/                 # Shared infrastructure
│   │   ├── config.py        # Pydantic Settings (env-based)
│   │   ├── database.py      # Async SQLAlchemy + retry logic
│   │   ├── redis.py         # Redis client + Lua rate limiter
│   │   ├── llm.py           # Unified LLM client + semantic cache
│   │   ├── sandbox.py       # Python subprocess sandbox
│   │   ├── security.py      # JWT + rate limit middleware
│   │   └── observability.py # structlog + Prometheus metrics
│   ├── models/              # SQLAlchemy ORM models
│   ├── schemas/             # Pydantic request/response contracts
│   ├── orchestrator/        # LangGraph pipeline
│   │   ├── graph.py        # StateGraph + checkpoints
│   │   ├── nodes.py        # ingest, etl, analysis, merge nodes
│   │   ├── state.py        # PipelineState TypedDict
│   │   └── api.py          # Orchestrator REST API (port 8001)
│   └── workers/            # Background workers (Redis Streams)
│       ├── ingestor.py
│       ├── etl.py
│       ├── analysis.py
│       ├── merge.py
│       ├── sql_agent.py
│       ├── python_agent.py
│       ├── viz_agent.py
│       └── insight_agent.py
├── docker-compose.yml       # 10-service stack
├── Dockerfile              # Multi-stage build
├── init.sql                # Database schema
├── pyproject.toml          # Dependencies + entry_points
├── generate_token.py       # JWT token generator
├── test_e2e.py             # End-to-end test
└── README.md               # This file
```

## Extending the Platform

### Add a Custom Connector
```python
# my_connector.py
from data_platform.connectors.base import BaseConnector

class MyConnector(BaseConnector):
    name = "my_custom"

    async def fetch(self, config, last_cursor=None):
        # Your implementation
        yield {"data": "..."}

    def validate_config(self, config):
        return True, ""
```

```toml
# pyproject.toml
[project.entry-points."data_platform.connectors"]
my_custom = "my_connector:MyConnector"
```

### Add a Custom Agent
```python
# my_agent.py
from data_platform.agents.base import BaseLLMAgent, AgentInput, AgentOutput

class MyAgent(BaseLLMAgent):
    name = "my_agent"
    system_prompt = "You are a specialized agent..."
    tools = [...]  # OpenAI function calling format

    async def run(self, input: AgentInput) -> AgentOutput:
        # Your implementation
        return AgentOutput(status="success", result={...})
```

```toml
# pyproject.toml
[project.entry-points."data_platform.agents"]
my_agent = "my_agent:MyAgent"
```

## Configuration

Key environment variables (`.env`):

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection | `postgresql+asyncpg://postgres:postgres@localhost:5432/platform` |
| `REDIS_URL` | Redis connection | `redis://localhost:6379/0` |
| `JWT_SECRET` | HS256 signing key | `dev-secret-change-in-production` |
| `LLM_PROVIDER` | `mock` \| `openai` \| `anthropic` | `mock` |
| `OPENAI_API_KEY` | OpenAI API key | - |
| `ANTHROPIC_API_KEY` | Anthropic API key | - |
| `LLM_MODEL` | Model name | `gpt-4o-mini` |
| `LLM_MONTHLY_BUDGET_USD` | Cost guardrail | `100.0` |

## Monitoring

### Prometheus Metrics
- `ingestion_events_total` — Events ingested by source
- `etl_processing_duration_seconds` — ETL latency histogram
- `llm_tokens_total` — Tokens consumed by model/provider
- `llm_latency_seconds` — LLM call latency
- `llm_cache_hits_total` — Semantic cache hit rate
- `llm_cost_usd_total` — Estimated cost in USD
- `pipeline_runs_total` — Pipeline executions by status

### Jaeger Tracing
All requests propagate `trace_id` across services. View traces at http://localhost:16686

### Health Checks
```bash
curl http://localhost:8000/health/live   # Liveness (k8s probe)
curl http://localhost:8000/health/ready  # Readiness (k8s probe)
```

## Testing

```bash
# Unit tests
pytest tests/ -v

# E2E test (requires running stack)
python test_e2e.py

# Load test
locust -f load_test.py --host=http://localhost:8000
```

## Production Deployment

### Kubernetes (Helm chart recommended)
```yaml
# Key considerations:
# - Use PostgreSQL with pgvector for semantic cache
# - Redis Cluster for HA streams
# - External secrets for JWT/LLM keys
# - HorizontalPodAutoscaler for worker deployments
# - PodDisruptionBudget for stateful components
```

### Docker Swarm / Nomad
```bash
docker stack deploy -c docker-compose.yml platform
```

## Roadmap

- [ ] **Vector Store Integration** — pgvector for semantic search over features
- [ ] **Multi-tenancy** — Namespace isolation for sources/pipelines
- [ ] **Streaming Ingestion** — Kafka/Redpanda connector with exactly-once
- [ ] **Agent Marketplace** — Community-contributed agents via registry
- [ ] **GitOps Pipeline Definitions** — YAML-based pipeline as code
- [ ] **Advanced Scheduling** — Cron + event-driven triggers
- [ ] **RBAC Enhancement** — Fine-grained permissions per resource

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

- [LangGraph](https://github.com/langchain-ai/langgraph) for orchestration
- [FastAPI](https://fastapi.tiangolo.com) for the API framework
- [SQLAlchemy](https://sqlalchemy.org) for async ORM
- [Redis Streams](https://redis.io/docs/latest/develop/data-types/streams/) for message queue
- [structlog](https://www.structlog.org) for structured logging

---

**Built for demonstrating production-grade agentic systems architecture.** 
Perfect for showcasing: distributed systems, LLM integration, event-driven architecture, and observability.