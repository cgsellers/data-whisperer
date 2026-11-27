"""Python Agent - Generación de código + ejecución en sandbox"""
import json

from data_platform.agents.base import AgentInput, BaseLLMAgent, register_agent
from data_platform.core.observability import get_logger
from data_platform.core.sandbox import SandboxResult, execute_python

logger = get_logger(__name__)


class PythonAgent(BaseLLMAgent):
    name = "python"

    system_prompt = """Eres un data scientist que genera código Python para análisis de datos.

REGLAS:
1. Genera código que use la variable `features` (lista de dicts con clave 'features')
2. El código DEBE definir variable `result` con el output (dict/serializable)
3. Librerías permitidas: pandas, numpy, prophet, scipy, sklearn, matplotlib, plotly, json, math, statistics, datetime, collections, itertools
4. NO uses: os, sys, subprocess, socket, requests, open, eval, exec, imports no permitidos
5. Para forecasting: usa Prophet con columnas 'ds' (fecha) e 'y' (valor)
6. Para ML: usa sklearn (clustering, regression, etc.)

EJEMPLOS:
- Forecast: Agrupa features por fecha, suma 'total', usa Prophet
- Anomaly detection: Calcula z-score o IQR sobre métricas numéricas
- Aggregation: Usa pandas groupby

DEVUELVE: Llama a execute_python con el código."""

    tools = [{
        "type": "function",
        "function": {
            "name": "execute_python",
            "description": "Ejecuta código Python en sandbox seguro",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Código Python que define variable 'result'"}
                },
                "required": ["code"]
            }
        }
    }]

    async def _execute_tool_calls(self, tool_calls: list[dict] | None, input: AgentInput) -> dict:
        if not tool_calls:
            return {"error": "No Python code generated"}

        for tc in tool_calls:
            if tc.get("function", {}).get("name") == "execute_python":
                args = json.loads(tc["function"]["arguments"])
                code = args["code"]

                # Ejecutar en sandbox
                sandbox_result: SandboxResult = await execute_python(
                    code, input.features or []
                )

                if sandbox_result.timed_out:
                    return {"error": "Timeout", "stderr": sandbox_result.stderr}
                if sandbox_result.returncode != 0:
                    return {"error": "Execution failed", "stderr": sandbox_result.stderr}

                # Parsear stdout como JSON
                try:
                    result_data = json.loads(sandbox_result.stdout.strip())
                    return {"code": code, "result": result_data, "stdout": sandbox_result.stdout}
                except json.JSONDecodeError:
                    return {"code": code, "result": sandbox_result.stdout, "stdout": sandbox_result.stdout}

        return {"error": "No valid execute_python call"}


register_agent(PythonAgent())
