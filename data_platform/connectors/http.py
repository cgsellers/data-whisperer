"""Conector HTTP genérico (ejemplo funcional)"""
from collections.abc import AsyncIterator

import httpx

from .base import BaseConnector, register_connector


class HTTPConnector(BaseConnector):
    name = "http_generic"

    def validate_config(self, config: dict) -> tuple[bool, str]:
        required = ["base_url", "endpoint"]
        for field in required:
            if field not in config:
                return False, f"Missing required field: {field}"
        return True, ""

    async def fetch(self, config: dict, last_cursor: str | None = None) -> AsyncIterator[dict]:
        base_url = config["base_url"].rstrip("/")
        endpoint = config["endpoint"]
        method = config.get("method", "GET").upper()
        headers = config.get("headers", {})
        params = config.get("params", {})
        auth = config.get("auth", {})

        # Auth simple
        if auth.get("type") == "bearer":
            headers["Authorization"] = f"Bearer {auth.get('token', '')}"

        # Pagination cursor
        if last_cursor and "pagination" in config:
            pag = config["pagination"]
            if pag.get("type") == "cursor":
                params[pag.get("cursor_param", "cursor")] = last_cursor

        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{base_url}{endpoint}"
            response = await client.request(method, url, headers=headers, params=params)
            response.raise_for_status()

            data = response.json()

            # Soportar array directo o objeto con data/items
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("data") or data.get("items") or [data]
            else:
                items = [data]

            for item in items:
                yield item

            # Cursor para siguiente página
            if isinstance(data, dict):
                next_cursor = data.get("next_cursor") or data.get("pagination", {}).get("next_cursor")
                if next_cursor:
                    yield {"_cursor": next_cursor}


# Auto-register
register_connector(HTTPConnector())
