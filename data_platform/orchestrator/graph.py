"""Grafo LangGraph con checkpoints persistentes en PostgreSQL (con fallback a memoria)"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

# Try to import PostgresSaver, fallback to MemorySaver
try:
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg_pool import AsyncConnectionPool
    POSTGRES_SAVER_AVAILABLE = True
except ImportError:
    POSTGRES_SAVER_AVAILABLE = False
    PostgresSaver = None
    AsyncConnectionPool = None


from data_platform.core.config import settings
from data_platform.core.database import async_session_maker
from data_platform.core.observability import get_logger
from data_platform.models import PipelineRun
from data_platform.orchestrator.nodes import analysis_node, etl_node, ingest_node, merge_node
from data_platform.orchestrator.state import PipelineState, create_initial_state

logger = get_logger(__name__)

# Pool global para checkpoints
_checkpoint_pool = None
_checkpointer = None
_compiled_graph = None
_use_postgres = POSTGRES_SAVER_AVAILABLE


async def get_checkpoint_pool():
    global _checkpoint_pool  # noqa: PLW0603
    if _checkpoint_pool is None and _use_postgres:
        database_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        _checkpoint_pool = AsyncConnectionPool(
            database_url,
            min_size=1,
            max_size=5,
            open=False,
        )
        await _checkpoint_pool.open()
        logger.info("checkpoint_pool_opened")
    return _checkpoint_pool


async def get_checkpointer():
    global _checkpointer, _use_postgres  # noqa: PLW0603
    if _checkpointer is None:
        if _use_postgres:
            try:
                pool = await get_checkpoint_pool()
                _checkpointer = PostgresSaver(pool)
                await _checkpointer.setup()
                logger.info("checkpointer_ready (PostgresSaver)")
            except Exception as e:
                logger.warning("postgres_checkpointer_failed_fallback", error=str(e))
                _use_postgres = False
                _checkpointer = MemorySaver()
                logger.info("checkpointer_ready (MemorySaver fallback)")
        else:
            _checkpointer = MemorySaver()
            logger.info("checkpointer_ready (MemorySaver)")
    return _checkpointer


def build_graph() -> StateGraph:
    """Construye el grafo LangGraph"""
    graph = StateGraph(PipelineState)

    # Nodos
    graph.add_node("ingest", ingest_node)
    graph.add_node("etl", etl_node)
    graph.add_node("analysis", analysis_node)
    graph.add_node("merge", merge_node)

    # Edges - flujo secuencial
    graph.set_entry_point("ingest")
    graph.add_edge("ingest", "etl")
    graph.add_edge("etl", "analysis")
    graph.add_edge("analysis", "merge")
    graph.add_edge("merge", END)

    return graph


async def get_compiled_graph():
    """Obtiene grafo compilado con checkpointer (singleton)"""
    global _compiled_graph  # noqa: PLW0603
    if _compiled_graph is None:
        checkpointer = await get_checkpointer()
        graph = build_graph()
        _compiled_graph = graph.compile(checkpointer=checkpointer)
        logger.info("langgraph_compiled_with_checkpoints", checkpointer_type=type(checkpointer).__name__)
    return _compiled_graph


async def run_pipeline_graph(
    run_id: str,
    source_id: str,
    source_config: dict,
    trace_id: str | None = None,
) -> PipelineState:
    """
    Ejecuta el pipeline completo via LangGraph con checkpoints.
    Permite resume automático si falla a mitad.
    """
    trace_id = trace_id or run_id

    # Crear PipelineRun en BD si no existe (necesario para FK en ingestion_events)
    async with async_session_maker() as db:
        existing = await db.get(PipelineRun, run_id)
        if not existing:
            run = PipelineRun(
                id=run_id,
                source_id=source_id,
                status="running",
                trace_id=trace_id,
                stages={}
            )
            db.add(run)
            await db.commit()

    initial_state = create_initial_state(run_id, source_id, source_config, trace_id)

    graph = await get_compiled_graph()

    # Config para checkpoint
    config = {
        "configurable": {
            "thread_id": run_id,  # Un thread por pipeline run
        }
    }

    logger.info("langgraph_pipeline_started", run_id=run_id, trace_id=trace_id)

    try:
        # Ejecutar - LangGraph maneja checkpoints automáticamente
        final_state = await graph.ainvoke(initial_state, config=config)

        # Actualizar estado final en BD
        async with async_session_maker() as db:
            run = await db.get(PipelineRun, run_id)
            if run:
                run.status = final_state.get("status", "completed")
                run.completed_at = None  # Will be set by DB
                run.stages = final_state.get("stages_completed", {})
                await db.commit()

        logger.info("langgraph_pipeline_completed",
            run_id=run_id, status=final_state.get("status"))
        return final_state

    except Exception as e:
        logger.error("langgraph_pipeline_failed", run_id=run_id, error=str(e))
        # Retornar estado con error
        return update_state(initial_state,
            status="failed",
            current_stage="failed",
            error=str(e),
        )


def update_state(state: PipelineState, **updates) -> PipelineState:
    """Helper para actualizar estado inmutable"""
    new_state = dict(state)
    new_state.update(updates)
    return new_state


async def resume_pipeline(run_id: str) -> PipelineState:
    """Reanuda pipeline desde último checkpoint"""
    graph = await get_compiled_graph()
    config = {"configurable": {"thread_id": run_id}}

    logger.info("langgraph_resume_attempt", run_id=run_id)

    # Obtener estado actual del checkpoint
    state = await graph.aget_state(config)
    if not state or not state.values:
        raise ValueError(f"No checkpoint found for run_id={run_id}")

    logger.info("langgraph_resume_from_checkpoint",
        run_id=run_id, stage=state.values.get("current_stage"))

    # Continuar desde donde quedó
    return await graph.ainvoke(None, config=config)


async def get_pipeline_state(run_id: str) -> PipelineState | None:
    """Obtiene estado actual del pipeline desde checkpoints"""
    graph = await get_compiled_graph()
    config = {"configurable": {"thread_id": run_id}}
    state = await graph.aget_state(config)
    return state.values if state else None


async def close_checkpointer():
    """Cierra conexiones de checkpointer (para shutdown)"""
    global _checkpoint_pool, _checkpointer, _compiled_graph  # noqa: PLW0603
    if _checkpoint_pool:
        await _checkpoint_pool.close()
        _checkpoint_pool = None
    _checkpointer = None
    _compiled_graph = None
    logger.info("checkpointer_closed")
