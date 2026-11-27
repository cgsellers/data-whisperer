"""Worker único - Ejecuta pipeline completo secuencialmente"""
import asyncio
import contextlib
import hashlib
import json
import time
from uuid import uuid4

from sqlalchemy import select

from data_platform.agents.base import AgentInput, get_agent, load_agents
from data_platform.connectors.base import get_connector, load_connectors
from data_platform.core.database import async_session_maker, init_db
from data_platform.core.observability import (
    AGENT_DURATION,
    ETL_DURATION,
    INGESTION_EVENTS,
    PIPELINE_DURATION,
    get_logger,
)
from data_platform.core.redis import get_redis, stream_ack, stream_consume_group
from data_platform.models import AnalysisResult, FeatureRecord, IngestionEvent, PipelineRun

logger = get_logger(__name__)


async def _update_run_status(run_id: str, status: str, stages: dict | None = None, error: str | None = None):
    """Actualiza el estado del pipeline run en BD"""
    async with async_session_maker() as db:
        run = await db.get(PipelineRun, run_id)
        if run:
            run.status = status
            if stages:
                run.stages = stages
            if error:
                run.error = error
            await db.commit()


async def _run_ingestion(run_id: str, source_id: str, source_config: dict) -> tuple[list, list]:
    """Ejecuta etapa de ingesta. Retorna (events, ingestion_event_ids)"""
    ingest_start = time.time()
    connector = get_connector("http_generic")
    if not connector:
        raise Exception("No connector available")

    events = []
    async for record in connector.fetch(source_config):
        if "_cursor" in record:
            continue
        events.append(record)

    # Guardar en BD
    ingestion_event_ids = []
    async with async_session_maker() as db:
        for event in events:
            payload_hash = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
            ie = IngestionEvent(
                source_id=source_id,
                pipeline_run_id=run_id,
                payload_hash=payload_hash,
                payload=event,
                event_metadata={"content_type": "application/json", "size_bytes": len(json.dumps(event))},
                status="validated"
            )
            db.add(ie)
        await db.commit()
        # Obtener IDs de los eventos creados
        result = await db.execute(
            select(IngestionEvent.id).where(IngestionEvent.pipeline_run_id == run_id)
        )
        ingestion_event_ids = [row[0] for row in result.fetchall()]

    INGESTION_EVENTS.labels(source_id=source_id, status="success").inc(len(events))
    logger.info("ingestion_completed", run_id=run_id, count=len(events), duration_ms=int((time.time()-ingest_start)*1000))
    return events, ingestion_event_ids


async def _run_etl(events: list, ingestion_event_ids: list, source_id: str, run_id: str) -> list:
    """Ejecuta etapa ETL. Retorna features"""
    etl_start = time.time()
    features = []
    for _i, event in enumerate(events):
        entity_id = event.get("id") or event.get("entity_id") or str(uuid4())
        feature = {
            "entity_id": entity_id,
            "features": {**event, "_processed_at": time.time(), "_source": source_id},
            "processing_version": "v1.0.0",
            "lineage": []
        }
        features.append(feature)

    async with async_session_maker() as db:
        for i, f in enumerate(features):
            ie_id = ingestion_event_ids[i] if i < len(ingestion_event_ids) else ingestion_event_ids[0]
            fr = FeatureRecord(
                entity_id=f["entity_id"],
                features=f["features"],
                ingestion_event_id=ie_id,
                processing_version=f["processing_version"],
                lineage=f["lineage"]
            )
            db.add(fr)
        await db.commit()

    ETL_DURATION.observe(time.time() - etl_start)
    logger.info("etl_completed", run_id=run_id, features=len(features), duration_ms=int((time.time()-etl_start)*1000))
    return features


async def _run_analysis(features: list, run_id: str) -> dict:
    """Ejecuta etapa de análisis con agentes. Retorna analysis_results"""
    analysis_results = {}
    for agent_name in ["sql"]:
        agent = get_agent(agent_name)
        if not agent:
            continue

        agent_start = time.time()
        try:
            output = await agent.run(AgentInput(
                features=features,
                params={"query": "SELECT count(*) as total FROM feature_records"}
            ))
            analysis_results[agent_name] = {
                "status": output.status,
                "result": output.result,
                "execution_time_ms": output.execution_time_ms,
                "confidence": output.confidence
            }

            # Guardar en BD
            async with async_session_maker() as db:
                ar = AnalysisResult(
                    pipeline_run_id=run_id,
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

        except Exception as e:
            logger.error("agent_failed", agent=agent_name, error=str(e))
            analysis_results[agent_name] = {"status": "failed", "error": str(e)}

        AGENT_DURATION.labels(agent_id=agent_name).observe(time.time() - agent_start)
    return analysis_results


async def run_pipeline(run_id: str, source_id: str, source_config: dict):
    """Ejecuta pipeline completo: ingest → etl → analysis → merge"""
    pipeline_start = time.time()
    logger.info("pipeline_started", run_id=run_id, source_id=source_id)

    # Actualizar estado a running
    await _update_run_status(run_id, "running")

    try:
        # 1. INGESTA
        events, ingestion_event_ids = await _run_ingestion(run_id, source_id, source_config)

        # 2. ETL
        features = await _run_etl(events, ingestion_event_ids, source_id, run_id)

        # 3. ANÁLISIS (agentes)
        analysis_results = await _run_analysis(features, run_id)

        # 4. MERGE + ACTUALIZAR PIPELINE RUN
        success = all(r.get("status") == "success" for r in analysis_results.values())
        merged = {
            "pipeline_run_id": run_id,
            "source_id": source_id,
            "records_processed": len(events),
            "features_created": len(features),
            "agents": analysis_results,
            "summary": "Pipeline completed successfully" if success else "Pipeline completed with errors"
        }

        await _update_run_status(run_id, "completed" if success else "partial", stages=merged)

        total_duration = time.time() - pipeline_start
        PIPELINE_DURATION.observe(total_duration)
        logger.info("pipeline_completed", run_id=run_id, status="completed" if success else "partial", duration_ms=int(total_duration*1000))

    except Exception as e:
        logger.error("pipeline_failed", run_id=run_id, error=str(e))
        await _update_run_status(run_id, "failed", error=str(e))
        INGESTION_EVENTS.labels(source_id=source_id, status="failed").inc()


async def main():
    """Loop principal del worker"""
    await init_db()
    await load_connectors()
    await load_agents()

    r = await get_redis()
    with contextlib.suppress(Exception):
        await r.xgroup_create("ingestion:raw", "worker-group", id="0", mkstream=True)

    logger.info("worker_started", group="worker-group")

    while True:
        try:
            messages = await stream_consume_group("ingestion:raw", "worker-group", "worker-1", count=5)

            for _stream, msgs in messages:
                for msg_id, data in msgs:
                    try:
                        run_id = data.get("run_id")
                        source_id = data.get("source_id")
                        config = json.loads(data.get("config", "{}"))

                        if run_id and source_id:
                            await run_pipeline(run_id, source_id, config)

                        await stream_ack("ingestion:raw", "worker-group", msg_id)
                    except Exception as e:
                        logger.error("message_processing_failed", error=str(e))
                        # No ack -> reintentar

        except Exception as e:
            logger.error("worker_loop_error", error=str(e))
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
