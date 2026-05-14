from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

from ..config import get_settings
from .text import blocks_to_markdown, infer_asset_type


class LarkClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def parse_node_token(self, source_url: str) -> str:
        parsed = urlparse(source_url)
        match = re.search(r"/(?:docx|docs|wiki|folder)/([A-Za-z0-9_-]+)", parsed.path)
        if match:
            return match.group(1)
        if parsed.path:
            return parsed.path.rstrip("/").split("/")[-1]
        return source_url

    async def fetch_document(self, source_url: str) -> dict:
        if not self.settings.lark_app_id or not self.settings.lark_app_secret:
            raise RuntimeError("LARK_APP_ID and LARK_APP_SECRET are required for real Feishu sync")
        token = await self._tenant_token()
        node_token = self.parse_node_token(source_url)
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.settings.lark_base_url}/docx/v1/documents/{node_token}/blocks",
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
        markdown = blocks_to_markdown(payload.get("data", payload))
        title = payload.get("data", {}).get("document", {}).get("title") or f"Feishu {node_token}"
        return {
            "external_id": node_token,
            "title": title,
            "asset_type": infer_asset_type(title, markdown),
            "markdown": markdown,
            "raw_payload": payload,
        }

    async def _tenant_token(self) -> str:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{self.settings.lark_base_url}/auth/v3/tenant_access_token/internal",
                json={"app_id": self.settings.lark_app_id, "app_secret": self.settings.lark_app_secret},
            )
            response.raise_for_status()
            payload = response.json()
        token = payload.get("tenant_access_token")
        if not token:
            raise RuntimeError(f"Feishu token response missing tenant_access_token: {payload}")
        return token
