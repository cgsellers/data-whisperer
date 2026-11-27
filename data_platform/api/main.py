"""FastAPI Application Entry Point"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from data_platform.agents.base import load_agents
from data_platform.api.routes import analysis, health, pipelines, sources
from data_platform.connectors.base import load_connectors
from data_platform.core.database import init_db
from data_platform.core.redis import close_redis
from data_platform.core.security import rate_limit_middleware
from data_platform.orchestrator.graph import close_checkpointer


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    await load_connectors()
    await load_agents()
    yield
    # Shutdown
    await close_redis()
    await close_checkpointer()


app = FastAPI(
    title="Plataforma Agéntica de Datos",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limit middleware
app.middleware("http")(rate_limit_middleware)

# Routes
app.include_router(health.router)
app.include_router(sources.router)
app.include_router(pipelines.router)
app.include_router(analysis.router)


@app.get("/")
async def root():
    return {
        "name": "Plataforma Agéntica de Datos",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health/ready"
    }
