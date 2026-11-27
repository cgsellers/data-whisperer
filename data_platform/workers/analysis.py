"""Worker Analysis - Consume analysis:pending y hace fan-out a 4 agentes LLM"""
import asyncio
import contextlib
import json

from data_platform.core.database import init_db
from data_platform.core.observability import get_logger
from data_platform.core.redis import get_redis, stream_ack, stream_consume_group
from data_platform.orchestrator.state import PipelineState

logger = get_logger(__name__)

GROUP = "analysis-group"
CONSUMER = "analysis-1"
STREAM = "analysis:pending"

AGENT_STREAMS = {
    "sql": "analysis:sql",
    "python": "analysis:python",
    "viz": "analysis:viz",
    "insight": "analysis:insight",
}


async def main():
    await init_db()

    r = await get_redis()
    with contextlib.suppress(Exception):
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)

    logger.info("analysis_worker_started", group=GROUP)

    while True:
        try:
            messages = await stream_consume_group(STREAM, GROUP, CONSUMER, count=3)

            for _stream, msgs in messages:
                for msg_id, data in msgs:
                    try:
                        state_data = json.loads(data.get("state", "{}"))
                        state = PipelineState(**state_data)
                        question = data.get("question", f"Analiza datos de {state['source_id']}")

                        # Fan-out: publicar en 4 streams de agentes
                        for _agent_name, agent_stream in AGENT_STREAMS.items():
                            await r.xadd(agent_stream, {
                                "run_id": state["run_id"],
                                "source_id": state["source_id"],
                                "trace_id": state["trace_id"],
                                "question": question,
                                "state": json.dumps(state, default=str),
                            })

                        logger.info("analysis_fanout_completed",
                            run_id=state["run_id"], agents=list(AGENT_STREAMS.keys()))

                        await stream_ack(STREAM, GROUP, msg_id)

                    except Exception as e:
                        logger.error("analysis_worker_msg_failed", error=str(e))

        except Exception as e:
            logger.error("analysis_worker_loop_error", error=str(e))
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
