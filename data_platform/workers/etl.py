"""Worker ETL - Consume etl:pending y ejecuta nodo etl"""
import asyncio
import contextlib
import json

from data_platform.core.database import init_db
from data_platform.core.observability import get_logger
from data_platform.core.redis import get_redis, stream_ack, stream_consume_group
from data_platform.orchestrator.nodes import etl_node
from data_platform.orchestrator.state import PipelineState

logger = get_logger(__name__)

GROUP = "etl-group"
CONSUMER = "etl-1"
STREAM = "etl:pending"


async def main():
    await init_db()

    r = await get_redis()
    with contextlib.suppress(Exception):
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)

    logger.info("etl_worker_started", group=GROUP)

    while True:
        try:
            messages = await stream_consume_group(STREAM, GROUP, CONSUMER, count=5)

            for _stream, msgs in messages:
                for msg_id, data in msgs:
                    try:
                        # Reconstruir estado desde mensaje
                        state_data = json.loads(data.get("state", "{}"))
                        state = PipelineState(**state_data)

                        result_state = await etl_node(state)

                        # Publicar siguiente etapa si éxito
                        if result_state.get("status") != "failed":
                            r = await get_redis()
                            await r.xadd("analysis:pending", {
                                "run_id": result_state["run_id"],
                                "source_id": result_state["source_id"],
                                "trace_id": result_state["trace_id"],
                                "state": json.dumps(result_state, default=str),
                            })

                        await stream_ack(STREAM, GROUP, msg_id)

                    except Exception as e:
                        logger.error("etl_worker_msg_failed", error=str(e))

        except Exception as e:
            logger.error("etl_worker_loop_error", error=str(e))
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
