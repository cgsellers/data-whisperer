"""Worker SQL Agent - Consume analysis:sql y ejecuta SQL Agent"""
import asyncio
import json
from contextlib import suppress

from data_platform.agents.base import AgentInput, get_agent, load_agents
from data_platform.core.database import init_db
from data_platform.core.observability import get_logger
from data_platform.core.redis import get_redis, stream_ack, stream_consume_group
from data_platform.orchestrator.state import PipelineState

logger = get_logger(__name__)

GROUP = "sql-agent-group"
CONSUMER = "sql-agent-1"
STREAM = "analysis:sql"


async def main():
    await init_db()
    await load_agents()

    r = await get_redis()
    with suppress(Exception):
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)

    logger.info("sql_agent_worker_started", group=GROUP)

    while True:
        try:
            messages = await stream_consume_group(STREAM, GROUP, CONSUMER, count=3)

            for _stream, msgs in messages:
                for msg_id, data in msgs:
                    try:
                        state_data = json.loads(data.get("state", "{}"))
                        state = PipelineState(**state_data)
                        question = data.get("question", "")

                        agent = get_agent("sql")
                        if not agent:
                            logger.error("sql_agent_not_found")
                            await stream_ack(STREAM, GROUP, msg_id)
                            continue

                        # Preparar input
                        features = state.get("feature_records", [])
                        agent_input = AgentInput(
                            question=question,
                            context=state,
                            features=features,
                            params={}
                        )

                        # Ejecutar agente
                        output = await agent.run(agent_input)

                        # Publicar resultado para merge
                        r = await get_redis()
                        await r.xadd("merge:pending", {
                            "run_id": state["run_id"],
                            "source_id": state["source_id"],
                            "trace_id": state["trace_id"],
                            "agent": "sql",
                            "result": json.dumps({
                                "status": output.status,
                                "result": output.result,
                                "execution_time_ms": output.execution_time_ms,
                                "tokens_used": output.tokens_used,
                                "confidence": output.confidence,
                                "error": output.error,
                            }, default=str),
                            "state": json.dumps(state, default=str),
                        })

                        await stream_ack(STREAM, GROUP, msg_id)

                    except Exception as e:
                        logger.error("sql_agent_worker_msg_failed", error=str(e))

        except Exception as e:
            logger.error("sql_agent_worker_loop_error", error=str(e))
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
