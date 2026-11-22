-- Esquema mínimo para la plataforma agéntica
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Sources
CREATE TABLE sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id VARCHAR(100) UNIQUE NOT NULL,
    type VARCHAR(20) NOT NULL CHECK (type IN ('api', 'csv', 'db', 'scrap')),
    config JSONB NOT NULL,
    schedule VARCHAR(100),
    enabled BOOLEAN DEFAULT true,
    last_run_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_sources_enabled ON sources(enabled) WHERE enabled = true;

-- Pipeline Runs
CREATE TABLE pipeline_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id VARCHAR(100) NOT NULL REFERENCES sources(source_id),
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed', 'partial')),
    trace_id VARCHAR(100),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    stages JSONB DEFAULT '{}',
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_pipeline_runs_source ON pipeline_runs(source_id);
CREATE INDEX idx_pipeline_runs_status ON pipeline_runs(status);

-- Ingestion Events (Raw)
CREATE TABLE ingestion_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id VARCHAR(100) NOT NULL REFERENCES sources(source_id),
    pipeline_run_id UUID REFERENCES pipeline_runs(id),
    payload_hash VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    event_metadata JSONB NOT NULL,
    status VARCHAR(20) DEFAULT 'raw',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_ingestion_source ON ingestion_events(source_id);
CREATE INDEX idx_ingestion_run ON ingestion_events(pipeline_run_id);

-- Feature Records (Processed)
CREATE TABLE feature_records (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id VARCHAR(200) NOT NULL,
    features JSONB NOT NULL,
    feature_metadata JSONB DEFAULT '{}',  -- metadata extra: schema version, quality scores, etc.
    ingestion_event_id UUID NOT NULL REFERENCES ingestion_events(id),
    processing_version VARCHAR(20) NOT NULL,
    lineage UUID[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_features_entity ON feature_records(entity_id);
CREATE INDEX idx_features_entity_created ON feature_records(entity_id, created_at DESC);

-- Analysis Results
CREATE TABLE analysis_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pipeline_run_id UUID NOT NULL REFERENCES pipeline_runs(id),
    agent_id VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('success', 'partial', 'failed')),
    result JSONB,
    execution_time_ms INTEGER,
    tokens_used INTEGER,
    confidence NUMERIC(3,2),
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_analysis_run ON analysis_results(pipeline_run_id);

-- LangGraph Checkpoints (creada por PostgresSaver.setup() pero incluida para referencia)
CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
    thread_id VARCHAR(255) NOT NULL,
    checkpoint_ns VARCHAR(255) NOT NULL DEFAULT '',
    checkpoint_id VARCHAR(255) NOT NULL,
    parent_checkpoint_id VARCHAR(255),
    type VARCHAR(100),
    checkpoint JSONB NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);
CREATE INDEX IF NOT EXISTS idx_langgraph_thread_ns ON langgraph_checkpoints(thread_id, checkpoint_ns);

-- Trigger para updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_sources_updated_at
    BEFORE UPDATE ON sources
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();