"""Base para agentes LLM - Con integración LLM unificada"""
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID
from data_platform.core.llm import llm_complete_with_cache, LLMResponse
from data_platform.core.observability import get_logger

logger = get_logger(__name__)


@dataclass
class AgentInput:
    """Input para agentes LLM con pregunta en lenguaje natural"""
    question: str = ""  # Pregunta del usuario en lenguaje natural
    context: dict | None = None  # Contexto compartido (features, columns, etc.)
    features: list[dict] | None = None  # Datos para análisis
    params: dict | None = None  # Parámetros extra
    pipeline_run_id: UUID | None = None


@dataclass
class AgentOutput:
    status: str  # success, partial, failed
    result: dict
    execution_time_ms: int
    tokens_used: int = 0
    confidence: float = 1.0
    error: str | None = None
    llm_model: str = ""
    llm_raw: Any = None


class BaseLLMAgent(ABC):
    """Base para agentes que usan LLM con tool calling"""

    # Cada agente define sus tools (OpenAI function calling format)
    tools: list[dict] = []
    system_prompt: str = ""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    async def run(self, input: AgentInput) -> AgentOutput:
        start = time.time()

        try:
            # Construir mensajes
            messages = self._build_messages(input)

            # Llamar LLM con cache
            response: LLMResponse = await llm_complete_with_cache(
                messages=messages,
                tools=self.tools,
                tool_choice="auto" if self.tools else None,
                temperature=0.1,
            )

            # Ejecutar tool calls si los hay
            result = await self._execute_tool_calls(response.tool_calls, input)

            exec_time = int((time.time() - start) * 1000)
            tokens = response.usage.get("total_tokens", 0) if response.usage else 0

            logger.info("agent_completed",
                agent=self.name, status="success", tokens=tokens, time_ms=exec_time)

            return AgentOutput(
                status="success",
                result=result,
                execution_time_ms=exec_time,
                tokens_used=tokens,
                confidence=0.95,
                llm_model=response.model,
                llm_raw=response.raw,
            )

        except Exception as e:
            exec_time = int((time.time() - start) * 1000)
            logger.error("agent_failed", agent=self.name, error=str(e))
            return AgentOutput(
                status="failed",
                result={},
                execution_time_ms=exec_time,
                tokens_used=0,
                confidence=0.0,
                error=str(e),
            )

    def _build_messages(self, input: AgentInput) -> list[dict]:
        """Construye mensajes para el LLM"""
        messages = [{"role": "system", "content": self.system_prompt}]

        # Contexto como mensaje de usuario
        context_parts = []
        if input.question:
            context_parts.append(f"Pregunta: {input.question}")
        if input.context:
            context_parts.append(f"Contexto: {input.context}")
        if input.features:
            context_parts.append(f"Registros disponibles: {len(input.features)}")

        user_content = "\n\n".join(context_parts) if context_parts else "Analiza los datos disponibles."
        messages.append({"role": "user", "content": user_content})

        return messages

    @abstractmethod
    async def _execute_tool_calls(self, tool_calls: list[dict] | None, input: AgentInput) -> dict:
        """Ejecuta las tool calls devueltas por el LLM"""
        pass


# Registry
_agents: dict[str, BaseLLMAgent] = {}


def register_agent(agent: BaseLLMAgent):
    _agents[agent.name] = agent


def get_agent(name: str) -> BaseLLMAgent | None:
    return _agents.get(name)


def list_agents() -> list[str]:
    return list(_agents.keys())


async def load_agents():
    """Carga agentes built-in + entry_points + fallback manual"""
    # Built-in agents (se registran al importar sus módulos)
    try:
        from importlib.metadata import entry_points
        for ep in entry_points(group="data_platform.agents"):
            agent_class = ep.load()
            register_agent(agent_class())
    except Exception:
        pass

    # Fallback: registrar agentes manualmente si no se cargaron por entry_points
    if not _agents:
        try:
            from data_platform.agents.sql import SQLAgent
            from data_platform.agents.python import PythonAgent
            from data_platform.agents.viz import VizAgent
            from data_platform.agents.insight import InsightAgent
            register_agent(SQLAgent())
            register_agent(PythonAgent())
            register_agent(VizAgent())
            register_agent(InsightAgent())
        except Exception:
            pass