"""API Routes para análisis conversacional - /analysis/ask"""
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from data_platform.agents.base import AgentInput, get_agent, load_agents
from data_platform.core.database import async_session_maker
from data_platform.core.observability import get_logger
from data_platform.core.security import require_scope
from data_platform.models import Source
from data_platform.orchestrator.graph import get_pipeline_state, resume_pipeline, run_pipeline_graph
from data_platform.orchestrator.state import create_initial_state, update_state

logger = get_logger(__name__)
router = APIRouter(prefix="/analysis", tags=["analysis"])

_require_analysis_read = Depends(require_scope("analysis:read"))
_require_analysis_write = Depends(require_scope("analysis:write"))


class AskRequest(BaseModel):
    question: str = Field(..., description="Pregunta en lenguaje natural")
    source_id: str | None = Field(None, description="Source específico (opcional)")
    run_id: str | None = Field(None, description="Reusar pipeline run existente")
    agent: Literal["sql", "python", "viz", "insight", "auto"] | None = Field(
        "auto", description="Agente específico a ejecutar (auto = todos en paralelo)"
    )


class AskResponse(BaseModel):
    run_id: str
    status: str
    answer: str | None = None
    sql_result: dict | None = None
    python_result: dict | None = None
    viz_result: dict | None = None
    insight_result: dict | None = None
    tokens_used: int = 0
    agent: str | None = None


@dataclass
class SingleAgentGraphParams:
    run_id: str
    source_id: str
    source_config: dict
    trace_id: str
    agent_name: str
    question: str


@router.post("/ask", response_model=AskResponse)
async def ask_question(
    request: AskRequest,
    background: BackgroundTasks,
    token: dict = _require_analysis_read,
):
    """
    Endpoint principal para preguntas en lenguaje natural.
    Ejecuta pipeline completo con agentes LLM y devuelve respuesta consolidada.
    Si se especifica `agent`, ejecuta solo ese agente.
    """
    # Resolver source_id
    source_id = request.source_id
    if not source_id:
        async with async_session_maker() as db:
            result = await db.execute(
                select(Source.source_id).where(Source.enabled).limit(1)
            )
            source_id = result.scalar_one_or_none()

    if not source_id:
        raise HTTPException(400, "No hay sources configurados. Crea uno en /sources")

    run_id = request.run_id or str(uuid4())
    trace_id = f"ask-{run_id[:8]}"

    logger.info("analysis_ask_received",
        run_id=run_id, question=request.question[:100], agent=request.agent, user=token.get("sub"))

    # Config del source
    async with async_session_maker() as db:
        result = await db.execute(select(Source).where(Source.source_id == source_id))
        source = result.scalar_one_or_none()
        if not source:
            raise HTTPException(404, f"Source {source_id} no encontrado")
        source_config = source.config

    # Ejecutar pipeline via LangGraph (con checkpoints)
    if request.agent and request.agent != "auto":
        # Ejecutar solo agente específico
        params = SingleAgentGraphParams(
            run_id=run_id,
            source_id=source_id,
            source_config=source_config,
            trace_id=trace_id,
            agent_name=request.agent,
            question=request.question,
        )
        final_state = await run_single_agent_graph(params)
    else:
        # Pipeline completo con todos los agentes
        final_state = await run_pipeline_graph(
            run_id=run_id,
            source_id=source_id,
            source_config=source_config,
            trace_id=trace_id,
        )

    # Construir respuesta
    status = final_state.get("status", "unknown")

    # Generar respuesta narrativa combinando insights
    answer = _build_answer(final_state, request.question)

    # Convert AgentOutput objects to dict for response
    def to_dict(obj):
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        return obj

    return AskResponse(
        run_id=run_id,
        status=status,
        answer=answer,
        sql_result=to_dict(final_state.get("sql_result")),
        python_result=to_dict(final_state.get("python_result")),
        viz_result=to_dict(final_state.get("viz_result")),
        insight_result=to_dict(final_state.get("insight_result")),
        tokens_used=final_state.get("tokens_used", 0),
        agent=request.agent,
    )


async def run_single_agent_graph(params: SingleAgentGraphParams) -> dict:
    """Ejecuta solo un agente específico via LangGraph"""
    await load_agents()
    agent = get_agent(params.agent_name)
    if not agent:
        raise HTTPException(400, f"Agente '{params.agent_name}' no disponible")

    # Estado inicial
    state = create_initial_state(
        params.run_id, params.source_id, params.source_config, params.trace_id
    )

    # Necesitamos features - si no hay, disparar ingest+etl primero
    features = state.get("feature_records", [])
    if not features:
        # Usar mock features para demo
        features = [
            {"entity_id": "1", "features": {"channel": "web", "total": 1000, "date": "2024-01-01"}},
            {"entity_id": "2", "features": {"channel": "mobile", "total": 500, "date": "2024-01-01"}},
        ]

    state["feature_records"] = features
    state["source_id"] = params.source_id

    # Ejecutar solo el agente solicitado
    agent_input = AgentInput(
        question=params.question,
        context={"run_id": params.run_id, "source_id": params.source_id, "trace_id": params.trace_id},
        features=features,
        params={}
    )

    output = await agent.run(agent_input)

    # Guardar resultado en estado
    state = update_state(state, current_stage="merge")
    state[f"{params.agent_name}_result"] = output
    state["tokens_used"] = output.tokens_used
    state["status"] = output.status

    return state


def _build_answer(state: dict, question: str) -> str:
    """Construye respuesta en lenguaje natural combinando resultados de agentes"""
    parts = [f"Análisis para: \"{question}\""]

    # Insight narrative (prioridad alta)
    insight = state.get("insight_result")
    if insight and hasattr(insight, 'narrative') and insight.narrative:
        parts.append(f"\n📊 **Insight**: {insight.narrative}")
    elif insight and isinstance(insight, dict) and insight.get("narrative"):
        parts.append(f"\n📊 **Insight**: {insight['narrative']}")

    # SQL result summary
    sql = state.get("sql_result")
    if sql and hasattr(sql, 'result') and sql.result:
        rows = sql.result.get("rows", []) if isinstance(sql.result, dict) else []
        parts.append(f"\n🗄️ **SQL**: {len(rows)} filas retornadas")
    elif sql and isinstance(sql, dict) and sql.get("result"):
        rows = sql["result"].get("rows", [])
        parts.append(f"\n🗄️ **SQL**: {len(rows)} filas retornadas")

    # Python result
    py = state.get("python_result")
    has_py_result = (
        py and hasattr(py, 'result') and py.result
        or py and isinstance(py, dict) and py.get("result")
    )
    if has_py_result:
        parts.append("\n🐍 **Python**: Análisis computacional completado")

    # Viz
    viz = state.get("viz_result")
    if viz and (hasattr(viz, 'result') or isinstance(viz, dict)):
        parts.append("\n📈 **Visualización**: Gráfico generado (Plotly spec)")

    if not any([insight, sql, py, viz]):
        parts.append("\n⚠️ No se generaron resultados. Verifica que hay datos en el source.")

    tokens = state.get("tokens_used", 0)
    parts.append(f"\n---\n*Tokens LLM usados: {tokens} | Pipeline: {state.get('run_id', '')[:8]}*")

    return "\n".join(parts)


@router.get("/runs/{run_id}/state")
async def get_run_state(
    run_id: str,
    token: dict = _require_analysis_read,
):
    """Obtiene estado actual de un pipeline run desde checkpoints"""
    state = await get_pipeline_state(run_id)
    if not state:
        raise HTTPException(404, f"Pipeline run {run_id} no encontrado")
    return state


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: str,
    token: dict = _require_analysis_write,
):
    """Reanuda pipeline desde último checkpoint"""
    final_state = await resume_pipeline(run_id)
    return {"run_id": run_id, "status": final_state.get("status"), "state": final_state}
