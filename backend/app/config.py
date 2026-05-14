from __future__ import annotations

import os
from functools import lru_cache


class Settings:
    def __init__(self) -> None:
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./weaveqa.db")
        self.qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        self.qdrant_collection = os.getenv("QDRANT_COLLECTION", "weaveqa_knowledge_chunks")
        self.lark_app_id = os.getenv("LARK_APP_ID", "")
        self.lark_app_secret = os.getenv("LARK_APP_SECRET", "")
        self.lark_base_url = os.getenv("LARK_BASE_URL", "https://open.feishu.cn/open-apis")
        self.figma_mcp_server_url = os.getenv("FIGMA_MCP_SERVER_URL", "http://127.0.0.1:3845/sse")
        self.embedding_provider = os.getenv("EMBEDDING_PROVIDER", "lexical")
        self.embedding_base_url = os.getenv("EMBEDDING_BASE_URL", "")
        self.embedding_api_key = os.getenv("EMBEDDING_API_KEY", "")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
