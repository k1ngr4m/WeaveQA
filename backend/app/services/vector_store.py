from __future__ import annotations

from collections import Counter

from sqlalchemy.orm import Session

from ..config import get_settings
from .. import models
from ..schemas import SearchResult
from .embedding import VECTOR_SIZE, cosine_from_tokens, lexical_embedding
from .text import tokenize


class VectorStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = None
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as qmodels

            self.qmodels = qmodels
            self.client = QdrantClient(url=self.settings.qdrant_url, timeout=2)
        except Exception:
            self.client = None
            self.qmodels = None

    def ensure_collection(self) -> None:
        if not self.client or not self.qmodels:
            return
        try:
            collections = self.client.get_collections().collections
            if any(item.name == self.settings.qdrant_collection for item in collections):
                return
            self.client.create_collection(
                collection_name=self.settings.qdrant_collection,
                vectors_config=self.qmodels.VectorParams(size=VECTOR_SIZE, distance=self.qmodels.Distance.COSINE),
            )
        except Exception:
            self.client = None

    def upsert_chunk(self, chunk: models.KnowledgeChunk, document: models.KnowledgeDocument) -> bool:
        if not self.client or not self.qmodels:
            return False
        self.ensure_collection()
        try:
            self.client.upsert(
                collection_name=self.settings.qdrant_collection,
                points=[
                    self.qmodels.PointStruct(
                        id=chunk.id,
                        vector=lexical_embedding(chunk.text),
                        payload={
                            "chunk_id": chunk.id,
                            "parent_id": chunk.parent_id,
                            "document_id": chunk.document_id,
                            "snapshot_id": chunk.snapshot_id,
                            "asset_type": chunk.asset_type,
                            "title": document.title,
                            "heading_path": chunk.heading_path,
                            "text_preview": chunk.text[:240],
                        },
                    )
                ],
            )
            return True
        except Exception:
            self.client = None
            return False

    def search(self, db: Session, query: str, mode: str, top_k: int) -> list[SearchResult]:
        if self.client:
            try:
                return self._qdrant_search(db, query, mode, top_k)
            except Exception:
                self.client = None
        return self._database_search(db, query, mode, top_k)

    def _qdrant_search(self, db: Session, query: str, mode: str, top_k: int) -> list[SearchResult]:
        self.ensure_collection()
        hits = self.client.search(
            collection_name=self.settings.qdrant_collection,
            query_vector=lexical_embedding(query),
            limit=top_k * 2,
        )
        results: list[SearchResult] = []
        for hit in hits:
            payload = hit.payload or {}
            chunk = db.get(models.KnowledgeChunk, payload.get("chunk_id"))
            if not chunk or not _allowed_asset(chunk.asset_type, mode):
                continue
            document = db.get(models.KnowledgeDocument, chunk.document_id)
            parent = db.get(models.KnowledgeParent, chunk.parent_id)
            if document:
                results.append(_result(chunk, document, parent, float(hit.score)))
            if len(results) >= top_k:
                break
        return results

    def _database_search(self, db: Session, query: str, mode: str, top_k: int) -> list[SearchResult]:
        query_tokens = tokenize(query)
        chunks = db.query(models.KnowledgeChunk).all()
        scored: list[tuple[float, models.KnowledgeChunk]] = []
        for chunk in chunks:
            if not _allowed_asset(chunk.asset_type, mode):
                continue
            score = cosine_from_tokens(query_tokens, Counter(chunk.token_counts or {}))
            if score > 0:
                scored.append((score, chunk))
        results: list[SearchResult] = []
        for score, chunk in sorted(scored, key=lambda item: item[0], reverse=True)[:top_k]:
            document = db.get(models.KnowledgeDocument, chunk.document_id)
            parent = db.get(models.KnowledgeParent, chunk.parent_id)
            if document:
                results.append(_result(chunk, document, parent, score))
        return results


def _allowed_asset(asset_type: str, mode: str) -> bool:
    if mode == "no_kb":
        return False
    if mode == "prd_only":
        return asset_type in {"prd", "mixed"}
    return True


def _result(
    chunk: models.KnowledgeChunk,
    document: models.KnowledgeDocument,
    parent: models.KnowledgeParent | None,
    score: float,
) -> SearchResult:
    return SearchResult(
        chunk_id=chunk.id,
        document_id=document.id,
        title=document.title,
        asset_type=chunk.asset_type,
        text=chunk.text,
        parent_text=parent.text if parent else "",
        heading_path=chunk.heading_path or [],
        score=round(score, 4),
    )
