# Architecture Decision Records

This document captures the key architectural decisions for **data-whisperer** — a multi-agent analytics platform where natural language questions fan out to 4 specialized LLM agents (SQL, Python, Viz, Insight) via LangGraph orchestration with persistent checkpoints, semantic caching, and full observability.

## ADR-001: Event-Driven Architecture with Redis Streams

**Status**: Accepted

**Context**: Need asynchronous, scalable communication between pipeline stages with exactly-once semantics and horizontal scaling.

**Decision**: Use Redis Streams with consumer groups for inter-stage communication.

**Consequences**:
- ✅ At-least-once delivery with manual acknowledgment
- ✅ Horizontal scaling via consumer groups
- ✅ Built-in replay capability (stream retention)
- ✅ Low latency (~sub-ms)
- ⚠️ Requires Redis 5.0+ (available in Redis 7)
- ⚠️ No native dead-letter queue (implement manually)

**Alternatives Considered**:
- Kafka: Overkill for single-node, higher operational complexity
- RabbitMQ: Less suitable for log-like replay semantics
- In-memory queues: No persistence, no horizontal scaling

## ADR-002: LangGraph for Pipeline Orchestration

**Status**: Accepted

**Context**: Need stateful, resumable pipeline execution with checkpointing for fault tolerance.

**Decision**: Use LangGraph StateGraph with PostgreSQL checkpointer (MemorySaver fallback).

**Consequences**:
- ✅ Persistent checkpoints enable resume after failures
- ✅ Visual debugging via LangGraph Studio
- ✅ Built-in retry and error handling
- ✅ State versioning for schema evolution
- ⚠️ Learning curve for team
- ⚠️ PostgresSaver requires asyncpg + psycopg_pool

**Alternatives Considered**:
- Custom state machine: Reinventing checkpointing
- Temporal/Cadence: Heavy dependency for this scope
- Airflow: Batch-oriented, not streaming-friendly

## ADR-003: Plugin System via Entry Points

**Status**: Accepted

**Context**: Need extensibility for connectors and agents without modifying core code.

**Decision**: Use `importlib.metadata` entry_points with fallback manual registration.

**Consequences**:
- ✅ Zero-config plugin discovery
- ✅ Standard Python packaging mechanism
- ✅ Multiple plugins per entry point group
- ✅ Version isolation via pip
- ⚠️ Requires reinstall on plugin add (`pip install -e .`)

**Alternatives Considered**:
- Dynamic import from config: Less discoverable
- Class registry with decorators: Manual registration needed
- Plugin directory with importlib: Custom implementation

## ADR-004: Four Specialized LLM Agents

**Status**: Accepted

**Context**: Different analytical tasks require different capabilities (SQL, code, viz, narrative).

**Decision**: Implement four specialized agents instead of one general agent.

**Consequences**:
- ✅ Each agent optimized for its domain
- ✅ Parallel execution via fan-out pattern
- ✅ Independent scaling (SQL/Python agents have 2 replicas)
- ✅ Clear separation of concerns
- ⚠️ More infrastructure (4 worker types)
- ⚠️ Merge complexity for combined responses

**Agent Responsibilities**:
| Agent | Input | Output | Tools |
|-------|-------|--------|-------|
| SQL | Question + schema | Parameterized query + results | `execute_sql` |
| Python | Question + data | Code + execution output | `run_python` |
| Viz | Question + data | Plotly JSON spec | `generate_plotly` |
| Insight | Question + data | Narrative + anomalies | `detect_anomalies` |

## ADR-005: Semantic Cache for LLM Cost Optimization

**Status**: Accepted

**Context**: LLM calls are expensive and often repetitive (similar questions).

**Decision**: Implement embedding-based semantic cache with cosine similarity threshold.

**Consequences**:
- ✅ 60-80% cache hit rate for repetitive queries
- ✅ Cost reduction proportional to cache hits
- ✅ Sub-ms cache lookup vs 1-5s LLM latency
- ⚠️ Storage grows with unique queries
- ⚠️ Requires embedding model (or mock for demo)

**Implementation**:
```python
# Cache key: hash(embedding(question + context))
# Lookup: cosine_similarity > 0.85
# TTL: 24 hours (configurable)
```

## ADR-006: Python Sandbox via Subprocess

**Status**: Accepted

**Context**: Python agent generates and executes arbitrary code - must be sandboxed.

**Decision**: Use subprocess with resource limits (RLIMIT_CPU, RLIMIT_AS, RLIMIT_FSIZE).

**Consequences**:
- ✅ Process isolation (no shared memory)
- ✅ CPU time limits (prevent infinite loops)
- ✅ Memory limits (prevent OOM)
- ✅ No network/filesystem access
- ⚠️ macOS RLIMIT_NPROC requires workaround
- ⚠️ Startup overhead (~50ms per execution)

**Security Layers**:
1. Subprocess isolation
2. Resource limits (CPU: 30s, Memory: 256MB)
3. No imports except stdlib + allowlisted (pandas, numpy, plotly)
4. Timeout enforcement (30s wall clock)

## ADR-007: JWT Authentication with Scopes

**Status**: Accepted

**Context**: Need role-based access control for API endpoints.

**Decision**: HS256 JWT with scope claims (`ingest:write`, `analysis:read`, etc.)

**Consequences**:
- ✅ Stateless authentication
- ✅ Fine-grained permissions
- ✅ Easy to validate in middleware
- ⚠️ HS256 requires shared secret (use RS256 in production)
- ⚠️ Token revocation requires blocklist

**Scopes**:
| Scope | Endpoints |
|-------|-----------|
| `ingest:write` | POST /pipelines/{id}/ingest |
| `analysis:read` | POST /analysis/ask, GET /analysis/runs/{id} |
| `analysis:write` | POST /analysis/runs/{id}/resume |
| `sources:read` | GET /sources |
| `sources:write` | POST /sources, DELETE /sources/{id} |
| `admin:*` | All scopes |

## ADR-008: Observability Stack

**Status**: Accepted

**Context**: Production systems need metrics, logs, and traces.

**Decision**: Prometheus metrics + structlog JSON + OpenTelemetry/Jaeger.

**Consequences**:
- ✅ Industry-standard tools
- ✅ Correlated logs/traces via trace_id
- ✅ Custom LLM metrics (tokens, cost, cache)
- ⚠️ Three separate systems to maintain
- ⚠️ Jaeger all-in-one not for production

**Metrics Categories**:
- **Business**: `pipeline_runs_total`, `ingestion_events_total`
- **Performance**: `etl_processing_duration_seconds`, `llm_latency_seconds`
- **LLM-specific**: `llm_tokens_total`, `llm_cost_usd_total`, `llm_cache_hits_total`
- **System**: `process_cpu_seconds`, `process_resident_memory_bytes`

## ADR-009: Database Schema Design

**Status**: Accepted

**Context**: Need flexible schema for heterogeneous data sources with lineage tracking.

**Decision**: PostgreSQL with JSONB for features, UUID PKs, ARRAY for lineage.

**Schema**:
```sql
-- Sources: connector configuration
sources (id UUID, source_id VARCHAR, type VARCHAR, config JSONB, ...)

-- Pipeline runs: orchestration state
pipeline_runs (id UUID, source_id FK, status, trace_id, stages JSONB, ...)

-- Raw ingestion events: immutable log
ingestion_events (id UUID, source_id FK, pipeline_run_id FK, payload JSONB, ...)

-- Feature records: transformed data
feature_records (entity_id VARCHAR, features JSONB, ingestion_event_id FK, lineage INT[], ...)

-- Analysis results: agent outputs
analysis_results (id UUID, pipeline_run_id FK, agent_id, result JSONB, tokens_used, ...)

-- LangGraph checkpoints: for resume capability
langgraph_checkpoints (thread_id, checkpoint JSONB, ...)
```

**Indexes**:
- `feature_records` GIN on `features` for JSONB queries
- `pipeline_runs` on `status`, `started_at`
- `ingestion_events` on `pipeline_run_id`, `source_id`

## ADR-010: Configuration via Pydantic Settings

**Status**: Accepted

**Context**: Need type-safe, environment-based configuration with validation.

**Decision**: Use `pydantic-settings` with `.env` support.

**Consequences**:
- ✅ Type validation at startup
- ✅ Environment variable mapping
- ✅ Nested settings (LLM config, DB config)
- ✅ Documentation via Field descriptions
- ⚠️ No hot reload (requires restart)

**Structure**:
```python
class Settings(BaseSettings):
    database_url: PostgresDsn
    redis_url: RedisDsn
    jwt_secret: str
    llm: LLMSettings  # Nested model
    
class LLMSettings(BaseSettings):
    provider: Literal["mock", "openai", "anthropic"]
    model: str
    api_key: SecretStr
    monthly_budget_usd: float
    cache_enabled: bool
```

## ADR-011: Multi-stage Docker Build

**Status**: Accepted

**Context**: Need small production images with build-time dependencies separated.

**Decision**: Multi-stage Dockerfile (builder → runtime).

**Consequences**:
- ✅ Smaller final image (~200MB vs ~1GB)
- ✅ No build tools in runtime
- ✅ Layer caching for dependencies
- ⚠️ Slightly more complex Dockerfile

**Stages**:
1. `builder`: Install build deps, compile wheels
2. `runtime`: Copy wheels, install runtime deps only

## ADR-012: Health Check Endpoints

**Status**: Accepted

**Context**: Kubernetes/container orchestration needs liveness/readiness probes.

**Decision**: Separate `/health/live` (process alive) and `/health/ready` (dependencies OK).

**Implementation**:
```python
@router.get("/health/live")
async def liveness():
    return {"status": "alive", "service": "api-gateway"}

@router.get("/health/ready")
async def readiness(db=Depends(get_db), redis=Depends(get_redis)):
    await db.execute(text("SELECT 1"))
    await redis.ping()
    return {"status": "ready", "service": "api-gateway"}
```

## Future Considerations

### ADR-XXX: Vector Search for Semantic Cache
**Status**: Proposed

Use pgvector for embedding storage instead of in-memory cache. Enables persistence across restarts and larger cache sizes.

### ADR-XXX: Multi-tenancy
**Status**: Proposed

Add `tenant_id` to all tables, implement row-level security, namespace isolation for sources/pipelines.

### ADR-XXX: GitOps Pipeline Definitions
**Status**: Proposed

Define pipelines as YAML in Git, sync via controller. Enables version control, code review, and audit trail for pipeline changes.