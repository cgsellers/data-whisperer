"""Worker único - Ejecuta pipeline completo secuencialmente"""
import asyncio
import hashlib
import json
import time
from uuid import uuid4

from sqlalchemy import select, text
from data_platform.core.config import settings
from data_platform.core.database import async_session_maker, init_db
from data_platform.core.redis import get_redis, stream_consume_group, stream_ack, close_redis
from data_platform.connectors.base import get_connector, load_connectors
from data_platform.agents.base import get_agent, load_agents
from data_platform.models import (
    PipelineRun, IngestionEvent, FeatureRecord, AnalysisResult
)
from data_platform.core.observability import get_logger, INGESTION_EVENTS, ETL_DURATION, AGENT_DURATION, PIPELINE_DURATION

logger = get_logger(__name__)


async def run_pipeline(run_id: str, source_id: str, source_config: dict):
    """Ejecuta pipeline completo: ingest → etl → analysis → merge"""
    pipeline_start = time.time()
    logger.info("pipeline_started", run_id=run_id, source_id=source_id)

    async with async_session_maker() as db:
        # Actualizar estado a running
        run = await db.get(PipelineRun, run_id)
        if not run:
            logger.error("run_not_found", run_id=run_id)
            return
        run.status = "running"
        await db.commit()

    try:
        # ─────────────────────────────────────────────
        # 1. INGESTA
        # ─────────────────────────────────────────────
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

        # ─────────────────────────────────────────────
        # 2. ETL
        # ─────────────────────────────────────────────
        etl_start = time.time()
        features = []
        for i, event in enumerate(events):
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
                # Usar el ingestion_event_id correspondiente (mismo índice)
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

        # ─────────────────────────────────────────────
        # 3. ANÁLISIS (agentes)
        # ─────────────────────────────────────────────
        analysis_results = {}
        for agent_name in ["sql"]:
            agent = get_agent(agent_name)
            if not agent:
                continue

            agent_start = time.time()
            try:
                from data_platform.agents.base import AgentInput
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
                        confidence=output.confidence,  # numeric, not string
                        error=output.error
                    )
                    db.add(ar)
                    await db.commit()

            except Exception as e:
                logger.error("agent_failed", agent=agent_name, error=str(e))
                analysis_results[agent_name] = {"status": "failed", "error": str(e)}

            AGENT_DURATION.labels(agent_id=agent_name).observe(time.time() - agent_start)

        # ─────────────────────────────────────────────
        # 4. MERGE + ACTUALIZAR PIPELINE RUN
        # ─────────────────────────────────────────────
        merged = {
            "pipeline_run_id": run_id,
            "source_id": source_id,
            "records_processed": len(events),
            "features_created": len(features),
            "agents": analysis_results,
            "summary": "Pipeline completed successfully" if all(r.get("status") == "success" for r in analysis_results.values()) else "Pipeline completed with errors"
        }

        async with async_session_maker() as db:
            run = await db.get(PipelineRun, run_id)
            if run:
                run.status = "completed" if all(r.get("status") == "success" for r in analysis_results.values()) else "partial"
                run.stages = merged
                run.completed_at = None  # auto
                await db.commit()

        total_duration = time.time() - pipeline_start
        PIPELINE_DURATION.observe(total_duration)
        logger.info("pipeline_completed", run_id=run_id, status=run.status, duration_ms=int(total_duration*1000))

    except Exception as e:
        logger.error("pipeline_failed", run_id=run_id, error=str(e))
        async with async_session_maker() as db:
            run = await db.get(PipelineRun, run_id)
            if run:
                run.status = "failed"
                run.error = str(e)
                await db.commit()
        INGESTION_EVENTS.labels(source_id=source_id, status="failed").inc()


async def main():
    """Loop principal del worker"""
    await init_db()
    await load_connectors()
    await load_agents()

    r = await get_redis()
    try:
        await r.xgroup_create("ingestion:raw", "worker-group", id="0", mkstream=True)
    except Exception:
        pass

    logger.info("worker_started", group="worker-group")

    while True:
        try:
            messages = await stream_consume_group("ingestion:raw", "worker-group", "worker-1", count=5)

            for stream, msgs in messages:
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