"""Viz Agent - Generación de especificaciones Plotly"""
import json
from data_platform.agents.base import BaseLLMAgent, AgentInput, register_agent
from data_platform.core.observability import get_logger

logger = get_logger(__name__)


class VizAgent(BaseLLMAgent):
    name = "viz"

    system_prompt = """Eres un experto en visualización de datos. Generas especificaciones Plotly JSON válidas.

REGLAS:
1. Output: Especificación Plotly completa (data + layout)
2. Tipos soportados: bar, line, scatter, histogram, box, heatmap, pie, sunburst, treemap
3. Usa colores accesibles (plotly default o palette viridis/plasma)
4. Incluye título, ejes con unidades, hover informativo
5. Responsive: autosize=true
6. Para series temporales: xaxis type='date'

FORMATO DE SALIDA:
{
  "data": [{ "type": "bar", "x": [...], "y": [...], "name": "..." }],
  "layout": { "title": "...", "xaxis": {"title": "..."}, "yaxis": {"title": "..."} }
}

DEVUELVE: Llama a generate_viz con la especificación completa."""

    tools = [{
        "type": "function",
        "function": {
            "name": "generate_viz",
            "description": "Genera especificación Plotly JSON",
            "parameters": {
                "type": "object",
                "properties": {
                    "spec": {
                        "type": "object",
                        "description": "Especificación Plotly completa",
                        "properties": {
                            "data": {"type": "array"},
                            "layout": {"type": "object"}
                        },
                        "required": ["data", "layout"]
                    }
                },
                "required": ["spec"]
            }
        }
    }]

    async def _execute_tool_calls(self, tool_calls: list[dict] | None, input: AgentInput) -> dict:
        if not tool_calls:
            return {"error": "No visualization generated"}

        for tc in tool_calls:
            if tc.get("function", {}).get("name") == "generate_viz":
                args = json.loads(tc["function"]["arguments"])
                spec = args["spec"]

                # Validar especificación básica
                if "data" not in spec or "layout" not in spec:
                    return {"error": "Invalid Plotly spec: missing data or layout"}

                logger.info("viz_generated", traces=len(spec.get("data", [])))
                return {
                    "spec": spec,
                    "type": "plotly",
                    "renderable": True,
                }

        return {"error": "No valid generate_viz call"}


register_agent(VizAgent())