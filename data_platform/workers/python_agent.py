"""Worker Python Agent - Consume analysis:python y ejecuta Python Agent"""
import asyncio
import json
from data_platform.core.database import init_db
from data_platform.core.redis import get_redis, stream_consume_group, stream_ack
from data_platform.agents.base import load_agents, get_agent
from data_platform.orchestrator.state import PipelineState
from data_platform.agents.base import AgentInput
from data_platform.core.observability import get_logger

logger = get_logger(__name__)

GROUP = "python-agent-group"
CONSUMER = "python-agent-1"
STREAM = "analysis:python"


async def main():
    await init_db()
    await load_agents()

    r = await get_redis()
    try:
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except Exception:
        pass

    logger.info("python_agent_worker_started", group=GROUP)

    while True:
        try:
            messages = await stream_consume_group(STREAM, GROUP, CONSUMER, count=3)

            for stream, msgs in messages:
                for msg_id, data in msgs:
                    try:
                        state_data = json.loads(data.get("state", "{}"))
                        state = PipelineState(**state_data)
                        question = data.get("question", "")

                        agent = get_agent("python")
                        if not agent:
                            logger.error("python_agent_not_found")
                            await stream_ack(STREAM, GROUP, msg_id)
                            continue

                        features = state.get("feature_records", [])
                        agent_input = AgentInput(
                            question=question,
                            context=state,
                            features=features,
                            params={}
                        )

                        output = await agent.run(agent_input)

                        r = await get_redis()
                        await r.xadd("merge:pending", {
                            "run_id": state["run_id"],
                            "source_id": state["source_id"],
                            "trace_id": state["trace_id"],
                            "agent": "python",
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
                        logger.error("python_agent_worker_msg_failed", error=str(e))

        except Exception as e:
            logger.error("python_agent_worker_loop_error", error=str(e))
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())