"""Routes para Sources"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from data_platform.core.database import get_db
from data_platform.core.security import require_scope
from data_platform.models import Source
from data_platform.schemas import SourceCreate, SourceRead

router = APIRouter(prefix="/sources", tags=["sources"])

_get_db_dep = Depends(get_db)
_require_ingest_write = Depends(require_scope("ingest:write"))
_require_ingest_read = Depends(require_scope("ingest:read"))


@router.post("", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
async def create_source(
    source: SourceCreate,
    db: AsyncSession = _get_db_dep,
    _: dict = _require_ingest_write,
):
    db_source = Source(
        source_id=source.source_id,
        type=source.type,
        config=source.config,
        schedule=source.schedule,
        enabled=source.enabled
    )
    db.add(db_source)
    await db.commit()
    await db.refresh(db_source)
    return db_source


@router.get("", response_model=list[SourceRead])
async def list_sources(
    enabled_only: bool = False,
    db: AsyncSession = _get_db_dep,
    _: dict = _require_ingest_read,
):
    stmt = select(Source)
    if enabled_only:
        stmt = stmt.where(Source.enabled)
    result = await db.execute(stmt.order_by(Source.created_at.desc()))
    return result.scalars().all()


@router.get("/{source_id}", response_model=SourceRead)
async def get_source(
    source_id: str,
    db: AsyncSession = _get_db_dep,
    _: dict = _require_ingest_read,
):
    result = await db.execute(select(Source).where(Source.source_id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source
