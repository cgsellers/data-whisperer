"""Base para conectores (Plugin System)"""
from abc import ABC, abstractmethod
from typing import AsyncIterator
import hashlib
import json


class BaseConnector(ABC):
    """Interface que deben implementar todos los conectores"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Identificador único del conector"""
        pass

    @abstractmethod
    async def fetch(self, config: dict, last_cursor: str | None = None) -> AsyncIterator[dict]:
        """Yield registros raw desde la fuente"""
        pass

    @abstractmethod
    def validate_config(self, config: dict) -> tuple[bool, str]:
        """Validar config del conector. Retorna (valid, error_msg)"""
        pass

    def compute_hash(self, record: dict) -> str:
        """Hash determinístico para dedup"""
        return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


# ─────────────────────────────────────────────
# Registry auto-descubrimiento via entry_points
# ─────────────────────────────────────────────
_connectors: dict[str, BaseConnector] = {}


def register_connector(connector: BaseConnector):
    _connectors[connector.name] = connector


def get_connector(name: str) -> BaseConnector | None:
    return _connectors.get(name)


def list_connectors() -> list[str]:
    return list(_connectors.keys())


async def load_connectors():
    """Cargar conectores desde entry_points + fallback manual"""
    try:
        from importlib.metadata import entry_points
        for ep in entry_points(group="data_platform.connectors"):
            connector_class = ep.load()
            register_connector(connector_class())
    except Exception:
        pass  # Silencioso en demo

    # Fallback: registrar conectores manualmente si no se cargaron por entry_points
    if not _connectors:
        try:
            from data_platform.connectors.http import HTTPConnector
            register_connector(HTTPConnector())
        except Exception:
            pass