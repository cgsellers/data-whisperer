"""Routes para Pipeline Runs - Versión simplificada"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID, uuid4
import json

from data_platform.core.database import get_db
from data_platform.core.security import verify_token, require_scope
from data_platform.core.redis import stream_add
from data_platform.models import PipelineRun, Source, AnalysisResult
from data_platform.schemas import PipelineRunRead, TriggerIngest

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


@router.post("/{source_id}/ingest", response_model=PipelineRunRead, status_code=status.HTTP_202_ACCEPTED)
async def trigger_ingest(
    source_id: str,
    trigger: TriggerIngest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_scope("ingest:write"))
):
    # Verificar source existe
    result = await db.execute(select(Source).where(Source.source_id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    # Crear pipeline run
    run_id = uuid4()
    run = PipelineRun(
        id=run_id,
        source_id=source_id,
        status="pending",
        trace_id=str(uuid4()),
        stages={}
    )
    db.add(run)
    await db.commit()

    # Publicar en Redis Stream para que el worker lo procese
    config = {**source.config, **(trigger.config_override or {})}
    await stream_add("ingestion:raw", {
        "run_id": str(run_id),
        "source_id": source_id,
        "config": json.dumps(config)
    })

    return run


@router.get("/{run_id}", response_model=PipelineRunRead)
async def get_pipeline(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_scope("ingest:read"))
):
    run = await db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return run


@router.get("/{run_id}/results")
async def get_pipeline_results(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_scope("analysis:read"))
):
    run = await db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    result = await db.execute(
        select(AnalysisResult).where(AnalysisResult.pipeline_run_id == run_id)
    )
    analyses = result.scalars().all()

    return {
        "pipeline_run": run,
        "analyses": [{"agent_id": a.agent_id, "result": a.result, "status": a.status} for a in analyses]
    }