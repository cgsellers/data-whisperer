"""Nodos del grafo LangGraph - Cada nodo es una etapa del pipeline"""
import asyncio
import time
import hashlib
import json
import uuid
from typing import Any
from sqlalchemy import select, text
from data_platform.core.config import settings
from data_platform.core.database import async_session_maker
from data_platform.core.redis import get_redis
from data_platform.connectors.base import get_connector
from data_platform.agents.base import get_agent, AgentInput
from data_platform.models import (
    PipelineRun, IngestionEvent, FeatureRecord, AnalysisResult
)
from data_platform.orchestrator.state import (
    PipelineState, create_initial_state, update_state, AgentResult
)
from data_platform.core.observability import (
    get_logger, INGESTION_EVENTS, ETL_DURATION, AGENT_DURATION, PIPELINE_DURATION,
    LLM_TOKENS_TOTAL
)
from data_platform.core.llm import llm_complete_with_cache

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# NODO 1: INGESTA
# ─────────────────────────────────────────────────────────────
async def ingest_node(state: PipelineState) -> PipelineState:
    """Extrae datos del source usando conector"""
    start = time.time()
    logger.info("ingest_node_started", run_id=state["run_id"], source_id=state["source_id"])

    try:
        connector = get_connector("http_generic")
        if not connector:
            raise Exception("Connector 'http_generic' no disponible")

        events = []
        async for record in connector.fetch(state["source_config"]):
            if "_cursor" in record:
                continue
            events.append(record)

        # Guardar en BD
        ingestion_ids = []
        async with async_session_maker() as db:
            for event in events:
                payload_hash = hashlib.sha256(
                    json.dumps(event, sort_keys=True).encode()
                ).hexdigest()
                ie = IngestionEvent(
                    source_id=state["source_id"],
                    pipeline_run_id=state["run_id"],
                    payload_hash=payload_hash,
                    payload=event,
                    event_metadata={
                        "content_type": "application/json",
                        "size_bytes": len(json.dumps(event))
                    },
                    status="validated"
                )
                db.add(ie)
            await db.commit()

            # Obtener IDs
            result = await db.execute(
                select(IngestionEvent.id).where(
                    IngestionEvent.pipeline_run_id == state["run_id"]
                )
            )
            ingestion_ids = [row[0] for row in result.fetchall()]

        INGESTION_EVENTS.labels(
            source_id=state["source_id"], status="success"
        ).inc(len(events))

        logger.info("ingest_node_completed",
            run_id=state["run_id"], count=len(events), duration_ms=int((time.time()-start)*1000))

        return update_state(state,
            raw_events=events,
            validated_events=events,  # Sin validación extra por ahora
            current_stage="etl",
            stages_completed=state.get("stages_completed", []) + ["ingest"],
        )

    except Exception as e:
        logger.error("ingest_node_failed", run_id=state["run_id"], error=str(e))
        return update_state(state,
            current_stage="failed",
            status="failed",
            error=str(e),
            errors=state.get("errors", []) + [f"ingest: {e}"],
            stages_failed=state.get("stages_failed", []) + ["ingest"],
        )


# ─────────────────────────────────────────────────────────────
# NODO 2: ETL
# ─────────────────────────────────────────────────────────────
async def etl_node(state: PipelineState) -> PipelineState:
    """Transforma eventos crudos a feature records"""
    start = time.time()
    logger.info("etl_node_started", run_id=state["run_id"])

    try:
        events = state.get("validated_events", [])
        features = []

        for event in events:
            entity_id = str(event.get("id") or event.get("entity_id") or uuid.uuid4())
            feature = {
                "entity_id": entity_id,
                "features": {**event, "_processed_at": time.time(), "_source": state["source_id"]},
                "processing_version": "v1.0.0",
                "lineage": []
            }
            features.append(feature)

        # Guardar feature records
        async with async_session_maker() as db:
            # Obtener ingestion_event_ids para lineage
            result = await db.execute(
                select(IngestionEvent.id).where(
                    IngestionEvent.pipeline_run_id == state["run_id"]
                )
            )
            ingestion_ids = [row[0] for row in result.fetchall()]

            for i, f in enumerate(features):
                ie_id = ingestion_ids[i] if i < len(ingestion_ids) else ingestion_ids[0]
                fr = FeatureRecord(
                    entity_id=f["entity_id"],
                    features=f["features"],
                    ingestion_event_id=ie_id,
                    processing_version=f["processing_version"],
                    lineage=f["lineage"]
                )
                db.add(fr)
            await db.commit()

        ETL_DURATION.observe(time.time() - start)
        logger.info("etl_node_completed",
            run_id=state["run_id"], features=len(features), duration_ms=int((time.time()-start)*1000))

        return update_state(state,
            feature_records=features,
            current_stage="analysis",
            stages_completed=state.get("stages_completed", []) + ["etl"],
        )

    except Exception as e:
        logger.error("etl_node_failed", run_id=state["run_id"], error=str(e))
        return update_state(state,
            current_stage="failed",
            status="failed",
            error=str(e),
            errors=state.get("errors", []) + [f"etl: {e}"],
            stages_failed=state.get("stages_failed", []) + ["etl"],
        )


# ─────────────────────────────────────────────────────────────
# NODO 3: ANÁLISIS (ejecuta 4 agentes en paralelo)
# ─────────────────────────────────────────────────────────────
async def analysis_node(state: PipelineState) -> PipelineState:
    """Ejecuta los 4 agentes LLM: SQL, Python, Viz, Insight"""
    logger.info("analysis_node_started", run_id=state["run_id"])

    features = state.get("feature_records", [])
    if not features:
        logger.warning("analysis_node_no_features", run_id=state["run_id"])
        return update_state(state, current_stage="merge")

    # Preparar contexto para agentes
    context = _build_agent_context(features, state)

    # Ejecutar agentes en paralelo
    agents_to_run = ["sql", "python", "viz", "insight"]
    results = {}

    async def run_agent(agent_name: str):
        agent = get_agent(agent_name)
        if not agent:
            return agent_name, AgentResult(
                agent_id=agent_name, status="failed", error="Agent not found"
            )

        agent_start = time.time()
        try:
            output = await agent.run(context)
            AGENT_DURATION.labels(agent_id=agent_name).observe(time.time() - agent_start)

            # Guardar en BD
            async with async_session_maker() as db:
                ar = AnalysisResult(
                    pipeline_run_id=state["run_id"],
                    agent_id=agent_name,
                    status=output.status,
                    result=output.result,
                    execution_time_ms=output.execution_time_ms,
                    tokens_used=output.tokens_used,
                    confidence=output.confidence,
                    error=output.error
                )
                db.add(ar)
                await db.commit()

            return agent_name, output

        except Exception as e:
            logger.error("agent_failed", agent=agent_name, error=str(e))
            AGENT_DURATION.labels(agent_id=agent_name).observe(time.time() - agent_start)
            return agent_name, AgentResult(
                agent_id=agent_name, status="failed", error=str(e)
            )

    # Paralelo
    agent_results = await asyncio.gather(*[run_agent(a) for a in agents_to_run])
    results = dict(agent_results)

    # Sumar tokens
    total_tokens = sum(r.tokens_used for r in results.values() if hasattr(r, 'tokens_used'))

    logger.info("analysis_node_completed",
        run_id=state["run_id"],
        agents={k: v.status for k, v in results.items()},
        total_tokens=total_tokens)

    return update_state(state,
        sql_result=results.get("sql"),
        python_result=results.get("python"),
        viz_result=results.get("viz"),
        insight_result=results.get("insight"),
        current_stage="merge",
        stages_completed=state.get("stages_completed", []) + ["analysis"],
        tokens_used=state.get("tokens_used", 0) + total_tokens,
    )


from data_platform.agents.base import AgentInput

def _build_agent_context(features: list[dict], state: PipelineState) -> AgentInput:
    """Construye contexto compartido para todos los agentes"""
    # Extraer sample de features para schema context
    sample_features = features[:10] if len(features) > 10 else features

    # Inferir columnas del primer feature
    columns = []
    if sample_features:
        first = sample_features[0].get("features", {})
        columns = list(first.keys())

    return AgentInput(
        question=f"Analiza los datos del source {state['source_id']} con {len(features)} registros",
        context={
            "run_id": state["run_id"],
            "source_id": state["source_id"],
            "sample_features": sample_features,
            "columns": columns,
            "total_records": len(features),
            "trace_id": state["trace_id"],
        },
        features=features,
        params={}
    )


# ─────────────────────────────────────────────────────────────
# NODO 4: MERGE + FINALIZE
# ─────────────────────────────────────────────────────────────
async def merge_node(state: PipelineState) -> PipelineState:
    """Consolida resultados y actualiza pipeline run"""
    logger.info("merge_node_started", run_id=state["run_id"])

    try:
        results = {
            "sql": state.get("sql_result"),
            "python": state.get("python_result"),
            "viz": state.get("viz_result"),
            "insight": state.get("insight_result"),
        }

        # Determinar estado final
        agent_statuses = {}
        for name, result in results.items():
            if result and hasattr(result, 'status'):
                agent_statuses[name] = result.status
            elif result and isinstance(result, dict):
                agent_statuses[name] = result.get("status", "unknown")
            else:
                agent_statuses[name] = "skipped"

        all_success = all(s == "success" for s in agent_statuses.values())
        any_success = any(s == "success" for s in agent_statuses.values())

        final_status = "completed" if all_success else ("partial" if any_success else "failed")

        merged = {
            "pipeline_run_id": state["run_id"],
            "source_id": state["source_id"],
            "records_processed": len(state.get("raw_events", [])),
            "features_created": len(state.get("feature_records", [])),
            "agents": agent_statuses,
            "summary": f"Pipeline {final_status}. Agents: {agent_statuses}",
            "tokens_used": state.get("tokens_used", 0),
        }

        # Actualizar pipeline run en BD
        async with async_session_maker() as db:
            run = await db.get(PipelineRun, state["run_id"])
            if run:
                run.status = final_status
                run.stages = merged
                run.completed_at = None  # auto timestamp
                await db.commit()

        PIPELINE_DURATION.observe(
            time.time() - time.mktime(time.strptime(state["started_at"][:19], "%Y-%m-%dT%H:%M:%S"))
        )

        logger.info("merge_node_completed",
            run_id=state["run_id"], status=final_status, agents=agent_statuses)

        return update_state(state,
            status=final_status,
            current_stage="completed",
            completed_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            stages_completed=state.get("stages_completed", []) + ["merge"],
        )

    except Exception as e:
        logger.error("merge_node_failed", run_id=state["run_id"], error=str(e))
        return update_state(state,
            current_stage="failed",
            status="failed",
            error=str(e),
            errors=state.get("errors", []) + [f"merge: {e}"],
        )