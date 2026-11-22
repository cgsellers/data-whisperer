# Mejoras Futuras - Roadmap de Escalabilidad

> **Este documento registra lo que se recortó del MVP para mantenerlo en 1-2h.**
> Cada item está listo para implementarse cuando el proyecto lo requiera.

---

## 1. Observabilidad Avanzada

### 1.1 Distributed Tracing (Jaeger + OpenTelemetry)
**Qué añade:** Seguimiento end-to-end de requests a través de API → Worker → DB → Redis
```python
# Requiere:
# - opentelemetry-instrumentation-fastapi
# - opentelemetry-instrumentation-sqlalchemy
# - opentelemetry-instrumentation-redis
# - opentelemetry-exporter-jaeger
# - Jaeger all-in-one en docker-compose
```
**Valor:** Detectar cuellos de botella (¿dónde se gasta el tiempo?), debug visual de traces.

### 1.2 Log Aggregation (Loki + Promtail)
**Qué añade:** Query de logs estructurados tipo `{service="worker"} |= "error" | json`
```yaml
# docker-compose.yml + loki-config.yml + promtail-config.yml
```
**Valor:** Correlacionar logs + métricas + traces, alertas basadas en logs.

### 1.3 Dashboards Grafana Pre-provisionados
**Qué añade:** Paneles listos para: throughput, latencia p95, error rate, DLQ size, worker lag.

---

## 2. Orquestación Robusta (LangGraph)

### 2.1 StateGraph con Checkpoints Persistentes
```python
# data_platform/orchestrator/graph.py
g = StateGraph(PipelineState)
g.add_node("ingest", ingest_node)
g.add_node("etl", etl_node)
g.add_node("analysis", analysis_node)  # fan-out paralelo
g.add_edge("ingest", "etl")
g.add_edge("etl", "analysis")
g.add_edge("analysis", "merge")
pipeline_graph = g.compile(checkpointer=PostgresSaver(...))
```
**Valor:**
- **Recovery automático:** Si falla en "analysis", reanuda desde ahí (no repite ingest/etl)
- **Human-in-the-loop:** Pausar pipeline para validación manual
- **Visualización DAG:** `graph.get_graph().draw_mermaid()`
- **Fan-out real:** SQL, Python, Viz, Insight agents en paralelo

### 2.2 Workers Especializados (Escalado Horizontal)
```yaml
# docker-compose.yml
services:
  ingestor:     # 3 réplicas - solo ingesta
  etl-worker:   # 2 réplicas - solo transform
  sql-agent:    # 2 réplicas - solo SQL
  python-agent: # 2 réplicas - solo Python/ML
  viz-agent:    # 1 réplica - solo visualización
  insight-agent: # 1 réplica - solo anomalías
```
**Valor:** Escalar independientemente cada etapa según carga.

---

## 3. Agentes Avanzados

### 3.1 Python Agent (Pandas + scikit-learn + statsmodels)
```python
# data_platform/agents/python.py
class PythonAgent(BaseAgent):
    name = "python"
    async def run(self, input: AgentInput) -> AgentOutput:
        df = pd.DataFrame(input.features)
        # Stats descriptivas, forecasting, clustering, etc.
        return AgentOutput(status="success", result=..., confidence=0.9)
```

### 3.2 Viz Agent (Plotly/Altair → HTML Artifacts)
```python
# data_platform/agents/viz.py
class VizAgent(BaseAgent):
    name = "viz"
    async def run(self, input: AgentInput) -> AgentOutput:
        fig = px.line(df, x="timestamp", y="value")
        html = fig.to_html(include_plotlyjs="cdn")
        return AgentOutput(status="success", result={"html": html, "type": "plotly"})
```

### 3.3 Insight Agent (Detección Anomalías + Narrativas)
```python
# data_platform/agents/insight.py
class InsightAgent(BaseAgent):
    name = "insight"
    async def run(self, input: AgentInput) -> AgentOutput:
        # IsolationForest para anomalías
        # Genera resumen en lenguaje natural
        return AgentOutput(status="success", result={"anomalies": ..., "narrative": "..."})
```

---

## 4. Conectores Reales

| Conector | Entry Point | Implementación |
|----------|-------------|----------------|
| **Stripe** | `stripe` | `connectors/stripe.py` - API Stripe con auth, pagination, webhooks |
| **PostgreSQL** | `postgres` | `connectors/postgres.py` - COPY + CDC (wal2json) |
| **CSV/Parquet** | `csv_file` | `connectors/csv.py` - Chunked reading, schema inference |
| **S3/GCS** | `s3` | `connectors/s3.py` - Streaming download, partitioning |
| **Kafka** | `kafka` | `connectors/kafka.py` - Consumer groups, exactly-once |

---

## 5. Resiliencia y Calidad de Datos

### 5.1 Great Expectations (Data Quality)
```python
# En ETL node
import great_expectations as ge
context = ge.get_context()
validation = context.run_checkpoint(
    checkpoint_name="feature_records_checkpoint",
    batch_request={"datasource": "pg", "table": "feature_records"}
)
if not validation.success:
    raise DataQualityError(validation.result)
```

### 5.2 Dead Letter Queue (DLQ) con Reprocesamiento
```python
# Redis Stream separado: "ingestion:dlq"
# UI para inspeccionar, corregir payload y re-enviar
```

### 5.3 Idempotencia Garantizada
- Hash determinístico (SHA256) por record → `ON CONFLICT DO NOTHING` en PG
- `processing_version` para re-procesamiento controlado

---

## 6. Seguridad y Multi-tenancy

### 6.1 Row Level Security (PostgreSQL RLS)
```sql
ALTER TABLE feature_records ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON feature_records
    USING (tenant_id = current_setting('app.current_tenant'));
```

### 6.2 Secrets Management
- HashiCorp Vault / AWS Secrets Manager / Azure Key Vault
- Inyección en runtime via CSI driver o sidecar

### 6.3 Audit Log Inmutable
- Tabla `audit_log` con `pg_audit` extension
- Todas las lecturas/escrituras de datos sensibles

---

## 7. CI/CD y Testing Avanzado

### 7.1 Pipeline GitHub Actions
```yaml
# .github/workflows/ci.yml
jobs:
  test:
    services: [postgres, redis]
    steps: [pytest --cov=80]
  lint: [ruff, mypy]
  contract: [schemathesis run /openapi.json]
  load: [locust -f tests/load/locustfile.py]
  build: [docker build, trivy scan]
  deploy-staging: [kubectl apply]
```

### 7.2 Contract Testing (Pact/Schemathesis)
- Validar que API responses cumplen schemas
- Consumer-driven contracts para agents

### 7.3 Chaos Engineering
- `chaos-mesh`: pod kill, network partition, latency injection
- Verificar recovery automático y DLQ

---

## 8. Feature Store Avanzado

### 8.1 Versionado Semántico de Features
- `processing_version: v1.2.0` (semver)
- Backfill automático al cambiar versión

### 8.2 Online/Offline Store Separation
- **Offline:** PostgreSQL/Parquet (entrenamiento)
- **Online:** Redis/KeyDB (serving baja latencia)

### 8.3 Feature Discovery UI
- Catálogo buscable: `feature_name`, `entity_type`, `owner`, `freshness`

---

## 9. Activación y Serving

### 9.1 Dashboard API (React/Vue + Plotly.js)
- Embeddable iframes, auto-refresh, parametrización

### 9.2 Alert Engine
- Reglas PromQL → Alertmanager → Slack/PagerDuty/Email
- Alertas sobre: frescura datos, anomalías, drift

### 9.3 Report Generator (PDF/Excel)
- Jinja2 + WeasyPrint → reportes programados

### 9.4 REST/gRPC Serving Layer
- Feature vector lookup <10ms para ML inference

---

## 10. Arquitectura de Producción (Kubernetes)

```yaml
# k8s/
├── base/
│   ├── deployment-api.yaml      # HPA: cpu>70% → scale
│   ├── deployment-worker.yaml   # KEDA: redis stream lag >100 → scale
│   ├── statefulset-postgres.yaml
│   ├── statefulset-redis.yaml
│   ├── configmap.yaml
│   └── secret.yaml (sealed-secrets)
├── overlays/
│   ├── staging/
│   └── production/
└── monitoring/
    ├── servicemonitor.yaml      # Prometheus Operator
    ├── prometheusrule.yaml      # Alertas
    └── dashboard.yaml           # Grafana
```

---

## Priorización Sugerida

| Fase | Items | Esfuerzo | Impacto |
|------|-------|----------|---------|
| **Fase 1** (Inmediata) | LangGraph checkpoints, Python Agent, Viz Agent | 2-3 días | Alto |
| **Fase 2** (Corto) | Workers especializados, Great Expectations, DLQ UI | 1 semana | Alto |
| **Fase 3** (Medio) | Jaeger + Loki + Grafana, Conectores reales, RLS | 2 semanas | Medio |
| **Fase 4** (Largo) | K8s, Feature Store online/offline, Serving layer | 1 mes | Estratégico |

---

## Notas de Implementación

- Cada mejora es **independiente** y **incremental**
- No hay breaking changes: la API actual se mantiene compatible
- Los plugins (conectores/agentes) se distribuyen como paquetes separados
- Documentación de cada feature en su propio `docs/` folder