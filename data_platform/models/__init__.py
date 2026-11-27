"""Modelos SQLAlchemy"""
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(String(100), unique=True, nullable=False, index=True)
    type = Column(String(20), nullable=False)
    config = Column(JSONB, nullable=False)
    schedule = Column(String(100))
    enabled = Column(Boolean, default=True)
    last_run_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(String(100), ForeignKey("sources.source_id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending")
    trace_id = Column(String(100), index=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    stages = Column(JSONB, default={})
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_pipeline_runs_status", "status"),
        Index("ix_pipeline_runs_started", "started_at"),
    )


class IngestionEvent(Base):
    __tablename__ = "ingestion_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(String(100), ForeignKey("sources.source_id"), nullable=False, index=True)
    pipeline_run_id = Column(UUID(as_uuid=True), ForeignKey("pipeline_runs.id"), index=True)
    payload_hash = Column(String(64), nullable=False)
    payload = Column(JSONB, nullable=False)
    event_metadata = Column(JSONB, nullable=False)
    status = Column(String(20), default="raw")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FeatureRecord(Base):
    __tablename__ = "feature_records"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(String(200), nullable=False, index=True)
    features = Column(JSONB, nullable=False)
    feature_metadata = Column(JSONB, default={})  # metadata extra: schema version, quality scores, etc.
    ingestion_event_id = Column(UUID(as_uuid=True), ForeignKey("ingestion_events.id"), nullable=False)
    processing_version = Column(String(20), nullable=False)
    lineage = Column(ARRAY(UUID(as_uuid=True)), default=[])
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_features_entity_created", "entity_id", "created_at"),
    )


class AnalysisResult(Base):
    __tablename__ = "analysis_results"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_run_id = Column(UUID(as_uuid=True), ForeignKey("pipeline_runs.id"), nullable=False, index=True)
    agent_id = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)
    result = Column(JSONB)
    execution_time_ms = Column(Integer)
    tokens_used = Column(Integer)
    confidence = Column(Numeric(3, 2))
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# Tabla para checkpoints de LangGraph (PostgresSaver la crea automáticamente con setup())
# Incluida aquí para referencia y migraciones
class LangGraphCheckpoint(Base):
    __tablename__ = "langgraph_checkpoints"
    thread_id = Column(String(255), primary_key=True)
    checkpoint_ns = Column(String(255), primary_key=True, default="")
    checkpoint_id = Column(String(255), primary_key=True)
    parent_checkpoint_id = Column(String(255))
    type = Column(String(100))
    checkpoint = Column(JSONB, nullable=False)
    checkpoint_metadata = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_langgraph_thread_ns", "thread_id", "checkpoint_ns"),
    )
