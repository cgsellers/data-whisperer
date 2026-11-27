"""Tests básicos de la plataforma - sin necesidad de BD/Redis reales"""
from datetime import datetime
from uuid import uuid4

import pytest

# Test agents
from data_platform.agents.base import (
    AgentInput,
    AgentOutput,
    BaseLLMAgent,
    _agents,
    get_agent,
    list_agents,
    register_agent,
)
from data_platform.agents.sql import SQLAgent

# Test connectors
from data_platform.connectors.base import BaseConnector, list_connectors
from data_platform.connectors.http import HTTPConnector
from data_platform.core.observability import (
    AGENT_DURATION,
    ETL_DURATION,
    INGESTION_EVENTS,
    INGESTION_LATENCY,
    PIPELINE_DURATION,
    get_logger,
)
from data_platform.core.security import require_scope

# Test models
from data_platform.models import AnalysisResult, FeatureRecord, IngestionEvent, PipelineRun, Source

# Test schemas
from data_platform.schemas import (
    HealthResponse,
    PipelineRunRead,
    SourceCreate,
    TriggerIngest,
)


class TestSchemas:
    """Tests de contratos Pydantic"""

    def test_source_create_valid(self):
        source = SourceCreate(
            source_id="test_api",
            type="api",
            config={"base_url": "https://api.example.com", "endpoint": "/data"},
            schedule=None,
            enabled=True
        )
        assert source.source_id == "test_api"
        assert source.type == "api"

    def test_source_type_validation(self):
        # Valid types
        for t in ["api", "csv", "db", "scrap"]:
            s = SourceCreate(source_id="t", type=t, config={})
            assert s.type == t

        # Invalid type should fail
        with pytest.raises(ValueError):
            SourceCreate(source_id="t", type="invalid", config={})

    def test_pipeline_run_read(self):
        run = PipelineRunRead(
            id=uuid4(),
            source_id="test",
            status="completed",
            trace_id=str(uuid4()),
            started_at=datetime.now(),
            completed_at=datetime.now(),
            stages={"ingest": "ok", "etl": "ok"},
            error=None
        )
        assert run.status == "completed"

    def test_trigger_ingest(self):
        trigger = TriggerIngest(config_override={"method": "POST"})
        assert trigger.config_override == {"method": "POST"}

    def test_health_response(self):
        health = HealthResponse(status="ready", service="api-gateway")
        assert health.status == "ready"
        assert health.version == "1.0.0"


class TestModels:
    """Tests de modelos SQLAlchemy"""

    def test_source_model_fields(self):
        # Verificar que el modelo tiene los campos esperados
        assert hasattr(Source, 'source_id')
        assert hasattr(Source, 'type')
        assert hasattr(Source, 'config')
        assert hasattr(Source, 'schedule')
        assert hasattr(Source, 'enabled')
        assert hasattr(Source, 'created_at')
        assert hasattr(Source, 'updated_at')

    def test_pipeline_run_model_fields(self):
        assert hasattr(PipelineRun, 'id')
        assert hasattr(PipelineRun, 'source_id')
        assert hasattr(PipelineRun, 'status')
        assert hasattr(PipelineRun, 'trace_id')
        assert hasattr(PipelineRun, 'stages')
        assert hasattr(PipelineRun, 'error')

    def test_ingestion_event_model_fields(self):
        assert hasattr(IngestionEvent, 'id')
        assert hasattr(IngestionEvent, 'source_id')
        assert hasattr(IngestionEvent, 'payload')
        assert hasattr(IngestionEvent, 'event_metadata')
        assert hasattr(IngestionEvent, 'pipeline_run_id')
        assert hasattr(IngestionEvent, 'payload_hash')
        assert hasattr(IngestionEvent, 'status')

    def test_feature_record_model_fields(self):
        assert hasattr(FeatureRecord, 'id')
        assert hasattr(FeatureRecord, 'entity_id')
        assert hasattr(FeatureRecord, 'features')
        assert hasattr(FeatureRecord, 'ingestion_event_id')
        assert hasattr(FeatureRecord, 'processing_version')
        assert hasattr(FeatureRecord, 'lineage')

    def test_analysis_result_model_fields(self):
        assert hasattr(AnalysisResult, 'id')
        assert hasattr(AnalysisResult, 'pipeline_run_id')
        assert hasattr(AnalysisResult, 'agent_id')
        assert hasattr(AnalysisResult, 'status')
        assert hasattr(AnalysisResult, 'result')
        assert hasattr(AnalysisResult, 'execution_time_ms')
        assert hasattr(AnalysisResult, 'confidence')
        assert hasattr(AnalysisResult, 'tokens_used')
        assert hasattr(AnalysisResult, 'error')


class TestConnectors:
    """Tests de conectores"""

    def test_base_connector_abstract(self):
        # BaseConnector es ABC, no se puede instanciar directamente (sin implementar métodos abstractos)
        with pytest.raises(TypeError):
            BaseConnector()

    def test_http_connector_creation(self):
        connector = HTTPConnector()
        assert connector.name == "http_generic"
        # validate_config funciona
        valid, msg = connector.validate_config({"base_url": "http://x", "endpoint": "/y"})
        assert valid is True
        valid, msg = connector.validate_config({"base_url": "http://x"})
        assert valid is False

    def test_connector_registry(self):
        # HTTPConnector se registra al importar el módulo (ver import arriba)
        connectors = list_connectors()
        assert "http_generic" in connectors


class TestAgents:
    """Tests de agentes"""

    def test_agent_input_output(self):
        inp = AgentInput(
            question="Test question",
            context={"key": "value"},
            features=[{"col": "val"}],
            params={"query": "SELECT 1"},
            pipeline_run_id=uuid4()
        )
        assert inp.question == "Test question"
        assert inp.features == [{"col": "val"}]

        out = AgentOutput(
            status="success",
            result={"rows": []},
            execution_time_ms=100,
            confidence=0.9
        )
        assert out.status == "success"

    def test_sql_agent_registered(self):
        # SQLAgent se auto-registra al importar el módulo (ver import arriba)
        agents = list_agents()
        assert "sql" in agents

    def test_agent_registry(self):
        # Limpiar registry para test aislado
        _agents.clear()

        class DummyAgent(BaseLLMAgent):
            name = "dummy"
            async def _execute_tool_calls(self, tool_calls, input):
                return {"result": "ok"}

            async def run(self, input):
                return AgentOutput(status="success", result={}, execution_time_ms=0)

        register_agent(DummyAgent())
        assert get_agent("dummy") is not None
        assert "dummy" in list_agents()

        # Restaurar SQLAgent para siguientes tests
        register_agent(SQLAgent())


class TestObservability:
    """Tests de observabilidad básica"""

    def test_structlog_config(self):
        logger = get_logger("test")
        assert logger is not None

    def test_prometheus_metrics_exist(self):
        assert INGESTION_EVENTS is not None
        assert INGESTION_LATENCY is not None
        assert ETL_DURATION is not None
        assert AGENT_DURATION is not None
        assert PIPELINE_DURATION is not None


class TestSecurity:
    """Tests de seguridad básica"""

    def test_require_scope_factory(self):
        checker = require_scope("ingest:write")
        assert callable(checker)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
