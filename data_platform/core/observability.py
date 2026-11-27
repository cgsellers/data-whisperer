"""Logging estructurado, métricas Prometheus y OpenTelemetry tracing"""
import logging
import os
import sys

import structlog
from fastapi import Response
from prometheus_client import Counter, Histogram, generate_latest

from .config import settings

# ─────────────────────────────────────────────
# Configurar stdlib logging para que structlog salga a stdout
# ─────────────────────────────────────────────
logging.basicConfig(
    format="%(message)s",
    stream=sys.stdout,
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
)

# ─────────────────────────────────────────────
# Structlog configuración
# ─────────────────────────────────────────────
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
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.BoundLogger,
    cache_logger_on_first_use=True,
)


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)


# ─────────────────────────────────────────────
# OpenTelemetry Setup (auto-instrumentation)
# ─────────────────────────────────────────────
_otel_initialized = False

def init_telemetry():  # noqa: PLW0603
    """Inicializa OpenTelemetry con Jaeger exporter"""
    global _otel_initialized  # noqa: PLW0603
    if _otel_initialized:
        return

    try:
        from opentelemetry import trace  # noqa: PLC0415
        from opentelemetry.exporter.jaeger.thrift import JaegerExporter  # noqa: PLC0415
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # noqa: PLC0415
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor  # noqa: PLC0415
        from opentelemetry.instrumentation.redis import RedisInstrumentor  # noqa: PLC0415
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor  # noqa: PLC0415
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource  # noqa: PLC0415
        from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: PLC0415

        resource = Resource.create({SERVICE_NAME: "data-platform"})
        provider = TracerProvider(resource=resource)

        jaeger_endpoint = os.getenv("JAEGER_ENDPOINT", "http://jaeger:14268/api/traces")
        jaeger_exporter = JaegerExporter(
            agent_host_name="jaeger",
            agent_port=6831,
            collector_endpoint=jaeger_endpoint,
        )

        provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
        trace.set_tracer_provider(provider)

        # Auto-instrumentation
        FastAPIInstrumentor.instrument()
        RedisInstrumentor.instrument()
        SQLAlchemyInstrumentor.instrument()
        HTTPXClientInstrumentor.instrument()

        _otel_initialized = True
        get_logger("observability").info("OpenTelemetry initialized with Jaeger")
    except Exception as e:
        get_logger("observability").warning("OpenTelemetry init failed", error=str(e))


def get_tracer(name: str):
    """Obtiene tracer para spans manuales"""
    from opentelemetry import trace  # noqa: PLC0415
    return trace.get_tracer(name)


# ─────────────────────────────────────────────
# Métricas Prometheus
# ─────────────────────────────────────────────
INGESTION_EVENTS = Counter(
    "ingestion_events_total",
    "Total events ingested",
    ["source_id", "status"]
)

INGESTION_LATENCY = Histogram(
    "ingestion_latency_seconds",
    "Ingestion latency",
    ["source_id"]
)

ETL_DURATION = Histogram(
    "etl_processing_duration_seconds",
    "ETL processing time"
)

AGENT_DURATION = Histogram(
    "agent_execution_duration_seconds",
    "Agent execution time",
    ["agent_id"]
)

PIPELINE_DURATION = Histogram(
    "pipeline_dag_duration_seconds",
    "Full pipeline duration"
)

# LLM Metrics
LLM_TOKENS_TOTAL = Counter(
    "llm_tokens_total",
    "Total LLM tokens used",
    ["model", "type"]  # type: prompt, completion
)

LLM_LATENCY_SECONDS = Histogram(
    "llm_latency_seconds",
    "LLM request latency",
    ["model"]
)

LLM_CACHE_HITS = Counter(
    "llm_cache_hits_total",
    "LLM semantic cache hits",
    ["model"]
)

LLM_COST_USD = Counter(
    "llm_cost_usd_total",
    "Estimated LLM cost in USD",
    ["model"]
)

# Budget metrics
LLM_BUDGET_EXCEEDED = Counter(
    "llm_budget_exceeded_total",
    "Times LLM budget was exceeded",
    ["client_id", "budget_type"]
)


async def metrics_endpoint() -> Response:
    return Response(content=generate_latest(), media_type="text/plain")

