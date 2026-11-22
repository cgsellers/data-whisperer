"""Contratos Pydantic para API"""
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Any
from uuid import UUID


class SourceCreate(BaseModel):
    source_id: str = Field(pattern=r"^[a-z_]+$")
    type: str = Field(pattern=r"^(api|csv|db|scrap)$")
    config: dict
    schedule: str | None = None
    enabled: bool = True


class SourceRead(SourceCreate):
    id: UUID
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PipelineRunRead(BaseModel):
    id: UUID
    source_id: str
    status: str
    trace_id: str | None
    started_at: datetime
    completed_at: datetime | None
    stages: dict
    error: str | None

    model_config = ConfigDict(from_attributes=True)


class TriggerIngest(BaseModel):
    config_override: dict | None = None


class FeatureRead(BaseModel):
    entity_id: str
    features: dict
    processing_version: str
    created_at: datetime


# ─────────────────────────────────────────────
# Analysis Layer - Agentes LLM
# ─────────────────────────────────────────────

class AgentInput(BaseModel):
    """Input para agentes LLM - Pregunta en lenguaje natural + contexto"""
    question: str = Field(..., description="Pregunta en lenguaje natural del usuario")
    context: dict | None = Field(None, description="Contexto adicional (opcional)")
    source_id: str | None = Field(None, description="Source específico a consultar")
    run_id: str | None = Field(None, description="Reusar pipeline run existente")


class AgentOutput(BaseModel):
    """Output estandarizado de agente"""
    agent_id: str
    status: str  # success, partial, failed
    result: dict
    execution_time_ms: int
    tokens_used: int = 0
    confidence: float = 1.0
    error: str | None = None
    llm_model: str = ""


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    source_id: str | None = None
    run_id: str | None = None


class AskResponse(BaseModel):
    run_id: str
    status: str
    answer: str | None = None
    sql_result: dict | None = None
    python_result: dict | None = None
    viz_result: dict | None = None
    insight_result: dict | None = None
    tokens_used: int = 0


class PipelineStateResponse(BaseModel):
    run_id: str
    source_id: str
    current_stage: str
    status: str
    stages_completed: list[str]
    stages_failed: list[str]
    error: str | None = None
    tokens_used: int
    started_at: str
    completed_at: str | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str = "1.0.0"