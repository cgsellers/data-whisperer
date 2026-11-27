"""API para Orchestrator (LangGraph) - Puerto 8001"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from data_platform.core.database import async_session_maker, init_db
from data_platform.core.redis import close_redis
from data_platform.models import Source
from data_platform.orchestrator.graph import (
    close_checkpointer,
    get_pipeline_state,
    resume_pipeline,
    run_pipeline_graph,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_redis()
    await close_checkpointer()


app = FastAPI(
    title="Orchestrator - LangGraph",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "name": "Orchestrator (LangGraph)",
        "version": "1.0.0",
        "description": "Pipeline orchestration with persistent checkpoints",
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "orchestrator"}


# Endpoints para gestión de pipelines via LangGraph
@app.post("/pipelines/{run_id}/execute")
async def execute_pipeline(run_id: str, payload: dict):
    """Ejecuta un pipeline via LangGraph"""
    source_id = payload.get("source_id")
    source_config = payload.get("config", {})

    if not source_id:
        return {"error": "source_id required"}

    async with async_session_maker() as db:
        result = await db.execute(select(Source).where(Source.source_id == source_id))
        source = result.scalar_one_or_none()
        if not source:
            return {"error": "Source not found"}
        source_config = source.config

    return await run_pipeline_graph(
        run_id=run_id,
        source_id=source_id,
        source_config=source_config,
        trace_id=payload.get("trace_id", run_id),
    )


@app.get("/pipelines/{run_id}/state")
async def get_state(run_id: str):
    """Obtiene estado desde checkpoints"""
    state = await get_pipeline_state(run_id)
    if not state:
        return {"error": "Not found"}
    return state


@app.post("/pipelines/{run_id}/resume")
async def resume(run_id: str):
    """Reanuda desde checkpoint"""
    return await resume_pipeline(run_id)

