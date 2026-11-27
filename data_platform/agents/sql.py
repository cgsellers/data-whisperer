"""SQL Agent - Text-to-SQL con validación y ejecución segura"""
import json

from sqlalchemy import text

from data_platform.agents.base import AgentInput, BaseLLMAgent, register_agent
from data_platform.core.database import async_session_maker
from data_platform.core.observability import get_logger

logger = get_logger(__name__)


class SQLAgent(BaseLLMAgent):
    name = "sql"

    system_prompt = """Eres un experto en SQL para PostgreSQL. Generas consultas SELECT seguras y parametrizadas.

REGLAS ESTRICTAS:
1. SOLO consultas SELECT (nunca INSERT/UPDATE/DELETE/DROP)
2. Usa SIEMPRE parámetros con :nombre (ej: WHERE source_id = :source_id)
3. Limita resultados a 1000 filas máximo
4. Usa tabla feature_records con columna JSONB 'features'
5. Para acceder a JSONB: features->>'campo' (texto) o features->'campo' (JSON)
6. Agrupa por campos categóricos, agrega numéricos

TABLAS DISPONIBLES:
- feature_records: entity_id, features (JSONB), ingestion_event_id, processing_version, created_at
- ingestion_events: id, source_id, payload (JSONB), created_at
- sources: source_id, type, config (JSONB)

DEVUELVE: Llama a la tool execute_sql con query y params."""

    tools = [{
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": "Ejecuta query SQL parametrizada en PostgreSQL",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "SQL SELECT con parámetros :name"},
                    "params": {"type": "object", "description": "Valores para parámetros"}
                },
                "required": ["query"]
            }
        }
    }]

    async def _execute_tool_calls(self, tool_calls: list[dict] | None, input: AgentInput) -> dict:
        if not tool_calls:
            return {"error": "No SQL query generated"}

        for tc in tool_calls:
            if tc.get("function", {}).get("name") == "execute_sql":
                args = json.loads(tc["function"]["arguments"])
                return await self._execute_query(args["query"], args.get("params", {}))

        return {"error": "No valid execute_sql call"}

    async def _execute_query(self, query: str, params: dict) -> dict:
        """Ejecuta query validada"""
        # Validaciones de seguridad
        query_lower = query.lower().strip()
        if not query_lower.startswith("select"):
            return {"error": "Solo se permiten consultas SELECT"}

        forbidden = ["insert", "update", "delete", "drop", "alter", "create", "truncate", "grant", "revoke"]
        for word in forbidden:
            if f" {word} " in f" {query_lower} ":
                return {"error": f"Palabra prohibida: {word}"}

        if "limit" not in query_lower:
            query += " LIMIT 1000"

        try:
            async with async_session_maker() as db:
                result = await db.execute(text(query), params)
                rows = [dict(row._mapping) for row in result.fetchall()]
                columns = list(result.keys()) if result.keys() else []

            logger.info("sql_executed", rows=len(rows), query=query[:100])
            return {
                "query": query,
                "params": params,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
            }

        except Exception as e:
            logger.error("sql_execution_failed", error=str(e), query=query[:200])
            return {"error": str(e), "query": query, "params": params}


register_agent(SQLAgent())
