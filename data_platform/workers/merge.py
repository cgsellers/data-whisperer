"""Worker Merge - Consume merge:pending y agrega resultados de 4 agentes"""
import asyncio
import json
from data_platform.core.database import init_db
from data_platform.core.redis import get_redis, stream_consume_group, stream_ack
from data_platform.orchestrator.nodes import merge_node
from data_platform.orchestrator.state import PipelineState, update_state
from data_platform.core.observability import get_logger

logger = get_logger(__name__)

GROUP = "merge-group"
CONSUMER = "merge-1"
STREAM = "merge:pending"

REQUIRED_AGENTS = ["sql", "python", "viz", "insight"]
RESULTS_TTL = 3600  # 1 hora


async def main():
    await init_db()

    r = await get_redis()
    try:
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except Exception:
        pass

    logger.info("merge_worker_started", group=GROUP)

    while True:
        try:
            messages = await stream_consume_group(STREAM, GROUP, CONSUMER, count=10)

            for stream, msgs in messages:
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

                        # Almacenar resultado parcial en Redis
                        result_key = f"merge:results:{run_id}"
                        await r.hset(result_key, agent, result_json)
                        await r.expire(result_key, RESULTS_TTL)

                        # Verificar si tenemos los 4 agentes
                        all_results = await r.hgetall(result_key)
                        if len(all_results) >= len(REQUIRED_AGENTS):
                            # Reconstruir estado completo
                            state_data = json.loads(data.get("state", "{}"))
                            if not state_data:
                                # Recuperar estado base de la primera vez que se procesó
                                state_data = await r.get(f"merge:state:{run_id}")
                                if state_data:
                                    state_data = json.loads(state_data)

                            if not state_data:
                                logger.warning("merge_no_base_state", run_id=run_id)
                                await stream_ack(STREAM, GROUP, msg_id)
                                continue

                            state = PipelineState(**state_data)

                            # Agregar resultados de agentes al estado
                            for ag in REQUIRED_AGENTS:
                                if ag in all_results:
                                    agent_result = json.loads(all_results[ag])
                                    # Crear objeto AgentOutput-like
                                    from data_platform.agents.base import AgentOutput
                                    output = AgentOutput(
                                        status=agent_result.get("status", "failed"),
                                        result=agent_result.get("result", {}),
                                        execution_time_ms=agent_result.get("execution_time_ms", 0),
                                        tokens_used=agent_result.get("tokens_used", 0),
                                        confidence=agent_result.get("confidence", 0.0),
                                        error=agent_result.get("error"),
                                    )
                                    state[f"{ag}_result"] = output

                            # Ejecutar merge final
                            result_state = await merge_node(state)

                            # Limpiar Redis
                            await r.delete(result_key)
                            await r.delete(f"merge:state:{run_id}")

                            logger.info("pipeline_completed",
                                run_id=run_id,
                                status=result_state.get("status"),
                                agents=list(all_results.keys()))

                        else:
                            # Guardar estado base para cuando lleguen los demás
                            if "state" in data:
                                await r.setex(f"merge:state:{run_id}", RESULTS_TTL, data["state"])

                        await stream_ack(STREAM, GROUP, msg_id)

                    except Exception as e:
                        logger.error("merge_worker_msg_failed", error=str(e))

        except Exception as e:
            logger.error("merge_worker_loop_error", error=str(e))
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())