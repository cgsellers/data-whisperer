"""Insight Agent - Detección de anomalías + narrativa en lenguaje natural"""
import json
from data_platform.agents.base import BaseLLMAgent, AgentInput, register_agent
from data_platform.core.observability import get_logger

logger = get_logger(__name__)


class InsightAgent(BaseLLMAgent):
    name = "insight"

    system_prompt = """Eres un analista de negocio senior. Detectas anomalías y generas narrativas accionables.

TAREA:
1. Analiza los features buscando desviaciones significativas vs baseline (media 7d, 30d)
2. Identifica: caídas/picos en ventas, cambios en conversión, errores, latencia
3. Calcula: desviación %, severidad (low/medium/high/critical)
4. Genera narrativa ejecutiva: QUÉ pasó, POR QUÉ (hipótesis), IMPACTO, ACCIÓN

FORMATO NARRATIVA:
"[Métrica] cayó/subió X% vs media Nd (valor actual vs esperado).
Coincide con [evento/deploy/cambio]. Impacto estimado: $Y/día.
Acción: [recomendación concreta]."

SEVERIDADES:
- low: desviación 5-15%, sin impacto negocio claro
- medium: 15-30%, impacto moderado
- high: 30-50%, impacto significativo
- critical: >50% o impacto directo en revenue

DEVUELVE: Llama a generate_insight con anomalies[] y narrative."""

    tools = [{
        "type": "function",
        "function": {
            "name": "generate_insight",
            "description": "Genera insights con anomalías detectadas y narrativa",
            "parameters": {
                "type": "object",
                "properties": {
                    "anomalies": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "metric": {"type": "string"},
                                "expected": {"type": "number"},
                                "actual": {"type": "number"},
                                "deviation_pct": {"type": "number"},
                                "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]}
                            },
                            "required": ["metric", "expected", "actual", "deviation_pct", "severity"]
                        }
                    },
                    "narrative": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "recommendations": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["anomalies", "narrative", "severity", "recommendations"]
            }
        }
    }]

    async def _execute_tool_calls(self, tool_calls: list[dict] | None, input: AgentInput) -> dict:
        if not tool_calls:
            return {"error": "No insight generated"}

        for tc in tool_calls:
            if tc.get("function", {}).get("name") == "generate_insight":
                args = json.loads(tc["function"]["arguments"])

                logger.info("insight_generated",
                    anomalies=len(args.get("anomalies", [])),
                    severity=args.get("severity"))

                return {
                    "anomalies": args.get("anomalies", []),
                    "narrative": args.get("narrative", ""),
                    "severity": args.get("severity", "low"),
                    "recommendations": args.get("recommendations", []),
                    "generated_at": "auto",
                }

        return {"error": "No valid generate_insight call"}


register_agent(InsightAgent())