"""Cliente LLM unificado: OpenAI, Anthropic, Mock (para demo sin API keys)"""
import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from data_platform.core.config import settings
from data_platform.core.observability import get_logger

logger = get_logger(__name__)


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[dict] | None = None
    usage: dict | None = None
    model: str = ""
    raw: Any = None


class BaseLLMClient(ABC):
    @abstractmethod
    async def complete(  # noqa: PLR0913, PLR0917
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> LLMResponse:
        pass

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        pass


class MockLLMClient(BaseLLMClient):
    """Cliente mock determinista para demo sin API keys"""

    def __init__(self):
        self.call_count = 0

    async def complete(  # noqa: PLR0913, PLR0917
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> LLMResponse:
        self.call_count += 1
        last_msg = messages[-1]["content"].lower() if messages else ""

        # Respuestas deterministas según el contexto
        if "sql" in last_msg or "text-to-sql" in last_msg:
            return LLMResponse(
                content="",
                tool_calls=[{
                    "id": "call_sql_1",
                    "type": "function",
                    "function": {
                        "name": "execute_sql",
                        "arguments": json.dumps({
                            "query": "SELECT channel, date, SUM(total) as total_sales, COUNT(*) as orders FROM feature_records WHERE features->>'_source' = 'orders_api' GROUP BY channel, date ORDER BY date DESC LIMIT 7",
                            "params": {}
                        })
                    }
                }],
                usage={"prompt_tokens": 150, "completion_tokens": 80, "total_tokens": 230},
                model="mock-gpt-4o-mini"
            )

        if "python" in last_msg or "code-gen" in last_msg or "forecast" in last_msg:
            return LLMResponse(
                content="",
                tool_calls=[{
                    "id": "call_python_1",
                    "type": "function",
                    "function": {
                        "name": "execute_python",
                        "arguments": json.dumps({
                            "code": "import pandas as pd\nimport numpy as np\nfrom prophet import Prophet\n\n# Simular forecast\ndf = pd.DataFrame(features)\ndf['date'] = pd.to_datetime(df['features'].apply(lambda x: x.get('date')))\ndf['total'] = df['features'].apply(lambda x: x.get('total', 0))\ndaily = df.groupby('date')['total'].sum().reset_index()\ndaily.columns = ['ds', 'y']\n\nmodel = Prophet()\nmodel.fit(daily)\nfuture = model.make_future_dataframe(periods=7)\nforecast = model.predict(future)\n\nresult = forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].tail(7)\nprint(result.to_json(orient='records'))"
                        })
                    }
                }],
                usage={"prompt_tokens": 200, "completion_tokens": 150, "total_tokens": 350},
                model="mock-gpt-4o-mini"
            )

        if "viz" in last_msg or "plotly" in last_msg or "visualiz" in last_msg:
            return LLMResponse(
                content="",
                tool_calls=[{
                    "id": "call_viz_1",
                    "type": "function",
                    "function": {
                        "name": "generate_viz",
                        "arguments": json.dumps({
                            "spec": {
                                "data": [{
                                    "type": "bar",
                                    "x": ["web", "mobile", "app", "store"],
                                    "y": [45000, 32000, 18000, 12000],
                                    "name": "Ventas por canal"
                                }],
                                "layout": {
                                    "title": "Ventas por Canal - Última Semana",
                                    "xaxis": {"title": "Canal"},
                                    "yaxis": {"title": "Ventas (€)"}
                                }
                            }
                        })
                    }
                }],
                usage={"prompt_tokens": 180, "completion_tokens": 120, "total_tokens": 300},
                model="mock-gpt-4o-mini"
            )

        if "insight" in last_msg or "anomal" in last_msg or "narrativa" in last_msg:
            return LLMResponse(
                content="",
                tool_calls=[{
                    "id": "call_insight_1",
                    "type": "function",
                    "function": {
                        "name": "generate_insight",
                        "arguments": json.dumps({
                            "anomalies": [
                                {
                                    "metric": "mobile_sales",
                                    "expected": 12500,
                                    "actual": 9600,
                                    "deviation_pct": -23.2,
                                    "severity": "high"
                                }
                            ],
                            "narrative": "Las ventas mobile cayeron 23% vs media 7d (9.6K vs 12.5K). Coincide con deploy v2.3.1 que introdujo bug en checkout iOS (error rate 4.2% vs 0.1% baseline). Impacto estimado: -2.9K€/día. Acción: rollback inmediato v2.3.1 → v2.3.0.",
                            "severity": "critical",
                            "recommendations": [
                                "Rollback v2.3.1",
                                "Monitor checkout iOS",
                                "Alertar on-call"
                            ]
                        })
                    }
                }],
                usage={"prompt_tokens": 220, "completion_tokens": 180, "total_tokens": 400},
                model="mock-gpt-4o-mini"
            )

        # Respuesta por defecto
        return LLMResponse(
            content="Análisis completado correctamente.",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            model="mock-gpt-4o-mini"
        )

    async def embed(self, text: str) -> list[float]:
        # Embedding determinista basado en hash (para cache semántico)
        hash_val = hashlib.md5(text.encode()).hexdigest()
        return [float(int(hash_val[i:i+2], 16)) / 255.0 for i in range(0, 32, 2)][:1536]


class OpenAILLMClient(BaseLLMClient):
    def __init__(self):
        try:
            from openai import AsyncOpenAI  # noqa: PLC0415
            self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            self.available = True
        except Exception as e:
            logger.warning("openai_client_unavailable", error=str(e))
            self.client = None
            self.available = False

    async def complete(  # noqa: PLR0913, PLR0917
        self, messages, tools=None, tool_choice=None, temperature=0.1, max_tokens=None, response_format=None
    ):
        if not self.available:
            raise RuntimeError("OpenAI client not available")
        resp = await self.client.chat.completions.create(
            model=settings.LLM_DEFAULT_MODEL,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        msg = resp.choices[0].message
        return LLMResponse(
            content=msg.content or "",
            tool_calls=[tc.model_dump() for tc in msg.tool_calls] if msg.tool_calls else None,
            usage=resp.usage.model_dump() if resp.usage else None,
            model=resp.model,
            raw=resp
        )

    async def embed(self, text: str) -> list[float]:
        if not self.available:
            raise RuntimeError("OpenAI client not available")
        resp = await self.client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return resp.data[0].embedding


class AnthropicLLMClient(BaseLLMClient):
    def __init__(self):
        try:
            from anthropic import AsyncAnthropic  # noqa: PLC0415
            self.client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            self.available = True
        except Exception as e:
            logger.warning("anthropic_client_unavailable", error=str(e))
            self.client = None
            self.available = False

    async def complete(  # noqa: PLR0913, PLR0917
        self, messages, tools=None, tool_choice=None, temperature=0.1, max_tokens=None, response_format=None
    ):
        if not self.available:
            raise RuntimeError("Anthropic client not available")
        # Convertir formato OpenAI -> Anthropic
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] != "system"]
        resp = await self.client.messages.create(
            model=settings.LLM_DEFAULT_MODEL,
            system=system,
            messages=user_msgs,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens or 4096,
        )
        tool_calls = None
        if resp.content and hasattr(resp.content[0], 'name'):
            tool_calls = [{
                "id": "call_1",
                "type": "function",
                "function": {"name": resp.content[0].name, "arguments": json.dumps(resp.content[0].input)}
            }]
        return LLMResponse(
            content=resp.content[0].text if resp.content and hasattr(resp.content[0], 'text') else "",
            tool_calls=tool_calls,
            usage={"prompt_tokens": resp.usage.input_tokens, "completion_tokens": resp.usage.output_tokens, "total_tokens": resp.usage.input_tokens + resp.usage.output_tokens} if resp.usage else None,
            model=resp.model,
            raw=resp
        )

    async def embed(self, text: str) -> list[float]:
        # Anthropic no tiene embeddings, usar fallback
        return MockLLMClient().embed(text)


class LLMCache:
    """Cache semántico en Redis para ahorrar llamadas LLM"""

    def __init__(self):
        self.redis = None
        self.enabled = True

    async def get_redis(self):
        if self.redis is None:
            from data_platform.core.redis import get_redis  # noqa: PLC0415
            self.redis = await get_redis()
        return self.redis

    def _cache_key(self, prompt_hash: str, model: str) -> str:
        return f"llm:cache:{model}:{prompt_hash}"

    async def get(self, messages: list[dict], model: str) -> LLMResponse | None:
        if not self.enabled:
            return None
        try:
            r = await self.get_redis()
            # Hash del último mensaje de usuario + system
            content = "".join(m["content"] for m in messages if m["role"] in ("system", "user"))
            prompt_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
            key = self._cache_key(prompt_hash, model)
            cached = await r.get(key)
            if cached:
                data = json.loads(cached)
                logger.info("llm_cache_hit", model=model, prompt_hash=prompt_hash[:8])
                return LLMResponse(**data)
        except Exception as e:
            logger.warning("llm_cache_error", error=str(e))
        return None

    async def set(self, messages: list[dict], model: str, response: LLMResponse, ttl: int = 86400):
        if not self.enabled:
            return
        try:
            r = await self.get_redis()
            content = "".join(m["content"] for m in messages if m["role"] in ("system", "user"))
            prompt_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
            key = self._cache_key(prompt_hash, model)
            await r.setex(key, ttl, json.dumps({
                "content": response.content,
                "tool_calls": response.tool_calls,
                "usage": response.usage,
                "model": response.model,
            }))
            logger.info("llm_cache_set", model=model, prompt_hash=prompt_hash[:8])
        except Exception as e:
            logger.warning("llm_cache_set_error", error=str(e))


# Factory
_llm_client: BaseLLMClient | None = None
_llm_cache = LLMCache()


def get_llm_client() -> BaseLLMClient:  # noqa: PLW0603
    global _llm_client  # noqa: PLW0603
    if _llm_client is None:
        provider = getattr(settings, "LLM_PROVIDER", "mock").lower()
        if provider == "openai":
            _llm_client = OpenAILLMClient()
            if not _llm_client.available:
                logger.warning("openai_unavailable_falling_back_to_mock")
                _llm_client = MockLLMClient()
        elif provider == "anthropic":
            _llm_client = AnthropicLLMClient()
            if not _llm_client.available:
                logger.warning("anthropic_unavailable_falling_back_to_mock")
                _llm_client = MockLLMClient()
        else:
            _llm_client = MockLLMClient()
        logger.info("llm_client_initialized", provider=provider, type=type(_llm_client).__name__)
    return _llm_client


def get_llm_cache() -> LLMCache:
    return _llm_cache


@dataclass
class LLMCompleteParams:
    messages: list[dict]
    tools: list[dict] | None = None
    tool_choice: str | None = None
    temperature: float = 0.1
    max_tokens: int | None = None
    response_format: dict | None = None
    use_cache: bool = True


async def llm_complete_with_cache(params: LLMCompleteParams) -> LLMResponse:
    client = get_llm_client()
    cache = get_llm_cache()
    model = getattr(settings, "LLM_DEFAULT_MODEL", "mock")

    if params.use_cache:
        cached = await cache.get(params.messages, model)
        if cached:
            return cached

    response = await client.complete(
        params.messages,
        params.tools,
        params.tool_choice,
        params.temperature,
        params.max_tokens,
        params.response_format,
    )

    if params.use_cache:
        await cache.set(params.messages, model, response)

    # Métricas
    from data_platform.core.observability import LLM_TOKENS_TOTAL  # noqa: PLC0415
    if response.usage:
        LLM_TOKENS_TOTAL.labels(model=model, type="prompt").inc(response.usage.get("prompt_tokens", 0))
        LLM_TOKENS_TOTAL.labels(model=model, type="completion").inc(response.usage.get("completion_tokens", 0))
    return response


