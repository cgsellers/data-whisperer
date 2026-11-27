"""Worker Merge - Consume merge:pending y agrega resultados de 4 agentes"""
import asyncio
import contextlib
import json

from data_platform.agents.base import AgentOutput
from data_platform.core.database import init_db
from data_platform.core.observability import get_logger
from data_platform.core.redis import get_redis, stream_ack, stream_consume_group
from data_platform.orchestrator.nodes import merge_node
from data_platform.orchestrator.state import PipelineState

logger = get_logger(__name__)

GROUP = "merge-group"
CONSUMER = "merge-1"
STREAM = "merge:pending"

REQUIRED_AGENTS = ["sql", "python", "viz", "insight"]
RESULTS_TTL = 3600  # 1 hora


async def _store_partial_result(r, run_id: str, agent: str, result_json: str):
    """Almacena resultado parcial de un agente en Redis"""
    result_key = f"merge:results:{run_id}"
    await r.hset(result_key, agent, result_json)
    await r.expire(result_key, RESULTS_TTL)


async def _check_all_results(r, run_id: str) -> dict | None:
    """Verifica si tenemos todos los resultados requeridos"""
    result_key = f"merge:results:{run_id}"
    all_results = await r.hgetall(result_key)
    if len(all_results) >= len(REQUIRED_AGENTS):
        return all_results
    return None


async def _get_base_state(r, run_id: str, data: dict) -> PipelineState | None:
    """Obtiene el estado base del pipeline"""
    state_data = json.loads(data.get("state", "{}"))
    if not state_data:
        state_data = await r.get(f"merge:state:{run_id}")
        if state_data:
            state_data = json.loads(state_data)

    if not state_data:
        logger.warning("merge_no_base_state", run_id=run_id)
        return None

    return PipelineState(**state_data)


async def _merge_results(state: PipelineState, all_results: dict) -> PipelineState:
    """Agrega resultados de agentes al estado y ejecuta merge_node"""
    for ag in REQUIRED_AGENTS:
        if ag in all_results:
            agent_result = json.loads(all_results[ag])
            output = AgentOutput(
                status=agent_result.get("status", "failed"),
                result=agent_result.get("result", {}),
                execution_time_ms=agent_result.get("execution_time_ms", 0),
                tokens_used=agent_result.get("tokens_used", 0),
                confidence=agent_result.get("confidence", 0.0),
                error=agent_result.get("error"),
            )
            state[f"{ag}_result"] = output

    return await merge_node(state)


async def _cleanup_merge_data(r, run_id: str):
    """Limpia datos temporales de merge en Redis"""
    await r.delete(f"merge:results:{run_id}")
    await r.delete(f"merge:state:{run_id}")


async def main():
    await init_db()

    r = await get_redis()
    with contextlib.suppress(Exception):
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)

    logger.info("merge_worker_started", group=GROUP)

    while True:
        try:
            messages = await stream_consume_group(STREAM, GROUP, CONSUMER, count=10)

            for _stream, msgs in messages:
                for msg_id, data in msgs:
                    try:
                        run_id = data.get("run_id")
                        source_id = data.get("source_id")
                        trace_id = data.get("trace_id")
                        agent = data.get("agent")
                        result_json = data.get("result")

                        if not all([run_id, source_id, trace_id, agent, result_json]):
                            logger.warning("merge_incomplete_data", data=data)
                            await stream_ack(STREAM, GROUP, msg_id)
                            continue

                        await _store_partial_result(r, run_id, agent, result_json)

                        all_results = await _check_all_results(r, run_id)
                        if all_results:
                            state = await _get_base_state(r, run_id, data)
                            if state:
                                result_state = await _merge_results(state, all_results)
                                await _cleanup_merge_data(r, run_id)
                                logger.info("pipeline_completed",
                                    run_id=run_id,
                                    status=result_state.get("status"),
                                    agents=list(all_results.keys()))

                        # Guardar estado base para cuando lleguen los demás
                        elif "state" in data:
                            await r.setex(f"merge:state:{run_id}", RESULTS_TTL, data["state"])

                        await stream_ack(STREAM, GROUP, msg_id)

                    except Exception as e:
                        logger.error("merge_worker_msg_failed", error=str(e))

        except Exception as e:
            logger.error("merge_worker_loop_error", error=str(e))
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
