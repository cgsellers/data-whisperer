"""Estado del pipeline para LangGraph - TypedDict para checkpoints persistentes"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, TypedDict


class PipelineState(TypedDict, total=False):
    """Estado completo que fluye por el grafo LangGraph"""
    # Identificadores
    run_id: str
    source_id: str
    trace_id: str

    # Configuración
    source_config: dict[str, Any]
    pipeline_config: dict[str, Any]

    # Datos en flujo
    raw_events: list[dict[str, Any]]
    validated_events: list[dict[str, Any]]
    feature_records: list[dict[str, Any]]

    # Resultados de agentes (Analysis Layer)
    sql_result: dict[str, Any] | None
    python_result: dict[str, Any] | None
    viz_result: dict[str, Any] | None
    insight_result: dict[str, Any] | None

    # Estado de ejecución
    current_stage: Literal["ingest", "etl", "analysis", "merge", "completed", "failed"]
    status: Literal["pending", "running", "completed", "partial", "failed"]
    error: str | None
    errors: list[str]

    # Métricas y metadata
    stages_completed: list[str]
    stages_failed: list[str]
    started_at: str
    completed_at: str | None
    tokens_used: int
    total_cost_usd: float

    # Para retry/resume
    retry_count: int
    last_checkpoint: str | None


@dataclass
class AgentResult:
    """Resultado estandarizado de un agente"""
    agent_id: str
    status: Literal["success", "failed", "partial"]
    result: Any = None
    execution_time_ms: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    confidence: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def create_initial_state(
    run_id: str,
    source_id: str,
    source_config: dict,
    trace_id: str,
) -> PipelineState:
    """Crea estado inicial para nuevo pipeline run"""
    return PipelineState(
        run_id=run_id,
        source_id=source_id,
        trace_id=trace_id,
        source_config=source_config,
        pipeline_config={},
        raw_events=[],
        validated_events=[],
        feature_records=[],
        sql_result=None,
        python_result=None,
        viz_result=None,
        insight_result=None,
        current_stage="ingest",
        status="pending",
        error=None,
        errors=[],
        stages_completed=[],
        stages_failed=[],
        started_at=datetime.utcnow().isoformat(),
        completed_at=None,
        tokens_used=0,
        total_cost_usd=0.0,
        retry_count=0,
        last_checkpoint=None,
    )


def update_state(state: PipelineState, **updates) -> PipelineState:
    """Actualiza estado inmutable (para LangGraph)"""
    new_state = dict(state)
    new_state.update(updates)
    return new_state
