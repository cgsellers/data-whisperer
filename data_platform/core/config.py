"""Configuración centralizada con Pydantic Settings"""
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # Auth
    JWT_SECRET: str = Field(default="dev-secret-change-in-prod-min-32-chars")
    JWT_ALGORITHM: str = "HS256"  # Simplificado para demo

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/platform"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # Observabilidad
    LOG_LEVEL: str = "INFO"
    JAEGER_ENDPOINT: str = "http://jaeger:14268/api/traces"

    # Agents
    AGENT_TIMEOUT_SECONDS: int = 300
    MAX_RETRIES: int = 3

    # ─────────────────────────────────────────────
    # LLM Configuration
    # ─────────────────────────────────────────────
    LLM_PROVIDER: str = Field(default="mock", description="mock | openai | anthropic")
    LLM_DEFAULT_MODEL: str = Field(default="gpt-4o-mini", description="Modelo por defecto")
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API Key")
    ANTHROPIC_API_KEY: str = Field(default="", description="Anthropic API Key")

    # LLM Budget & Cache
    LLM_DAILY_BUDGET_USD: float = Field(default=10.0, description="Presupuesto diario USD")
    LLM_CACHE_ENABLED: bool = Field(default=True, description="Cache semántico en Redis")
    LLM_CACHE_TTL_SECONDS: int = Field(default=86400, description="TTL cache 24h")

    # Sandbox
    SANDBOX_TIMEOUT_SECONDS: int = Field(default=30)
    SANDBOX_MEMORY_MB: int = Field(default=512)
    SANDBOX_CPU_SECONDS: int = Field(default=10)

    # LangGraph
    LANGGRAPH_CHECKPOINT_POOL_SIZE: int = Field(default=5)

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()