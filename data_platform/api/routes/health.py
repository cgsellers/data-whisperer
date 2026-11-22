"""Health checks + métricas"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from data_platform.core.database import get_db
from data_platform.core.redis import get_redis
from data_platform.core.observability import metrics_endpoint
from data_platform.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health/live", response_model=HealthResponse)
async def liveness():
    return HealthResponse(status="alive", service="api-gateway")


@router.get("/health/ready", response_model=HealthResponse)
async def readiness(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        r = await get_redis()
        await r.ping()
        return HealthResponse(status="ready", service="api-gateway")
    except Exception:
        return HealthResponse(status="not_ready", service="api-gateway")


@router.get("/metrics")
async def metrics():
    return await metrics_endpoint()


@router.get("/connectors")
async def list_connectors():
    from data_platform.connectors.base import list_connectors
    return {"connectors": list_connectors()}


@router.get("/agents")
async def list_agents():
    from data_platform.agents.base import list_agents
    return {"agents": list_agents()}