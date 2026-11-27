"""Conexión a PostgreSQL async con SQLAlchemy"""
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from data_platform.models import Base

from .config import settings
from .observability import get_logger

logger = get_logger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.LOG_LEVEL == "DEBUG",
    poolclass=NullPool,  # Para simplicidad en demo
)

async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncSession:
    async with async_session_maker() as session:
        yield session


async def init_db(max_retries: int = 10, retry_delay: float = 2.0):
    """Crear tablas si no existen (para demo, en prod usar Alembic)"""

    for attempt in range(max_retries):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("database_initialized")
            return
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning("database_init_retry", attempt=attempt + 1, max_retries=max_retries, error=str(e))
                await asyncio.sleep(retry_delay)
            else:
                logger.error("database_init_failed", error=str(e))
                raise

