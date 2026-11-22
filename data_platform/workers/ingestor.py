"""Worker Ingestor - Consume ingestion:raw y ejecuta nodo ingest"""
import asyncio
import json
from data_platform.core.database import init_db
from data_platform.core.redis import get_redis, stream_consume_group, stream_ack, close_redis
from data_platform.connectors.base import load_connectors
from data_platform.orchestrator.nodes import ingest_node
from data_platform.orchestrator.state import create_initial_state, update_state
from data_platform.core.observability import get_logger

logger = get_logger(__name__)

GROUP = "ingestor-group"
CONSUMER = "ingestor-1"
STREAM = "ingestion:raw"


async def main():
    await init_db()
    await load_connectors()

    r = await get_redis()
    try:
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except Exception:
        pass

    logger.info("ingestor_started", group=GROUP)

    while True:
        try:
            messages = await stream_consume_group(STREAM, GROUP, CONSUMER, count=5)

            for stream, msgs in messages:
                for msg_id, data in msgs:
                    try:
                        run_id = data.get("run_id")
                        source_id = data.get("source_id")
                        config = json.loads(data.get("config", "{}"))
                        trace_id = data.get("trace_id", run_id)

                        if run_id and source_id:
                            # Crear estado inicial y ejecutar solo ingest_node
                            state = create_initial_state(run_id, source_id, config, trace_id)
                            result_state = await ingest_node(state)

                            # Publicar siguiente etapa si éxito
                            if result_state.get("status") != "failed":
                                await r.xadd("etl:pending", {
                                    "run_id": run_id,
                                    "source_id": source_id,
                                    "config": json.dumps(config),
                                    "trace_id": trace_id,
                                    "state": json.dumps(result_state, default=str),
                                })

                        await stream_ack(STREAM, GROUP, msg_id)

                    except Exception as e:
                        logger.error("ingestor_msg_failed", error=str(e))
                        # No ack -> reintentar

        except Exception as e:
            logger.error("ingestor_loop_error", error=str(e))
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())