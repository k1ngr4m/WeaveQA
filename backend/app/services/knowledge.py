from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models
from ..schemas import DocumentCreate, DocumentRead
from .text import content_hash, infer_asset_type, split_parent_child, tokenize
from .vector_store import VectorStore


def create_document(db: Session, payload: DocumentCreate, sync_run_id: str | None = None) -> models.KnowledgeDocument:
    markdown = payload.content
    digest = content_hash(markdown)
    document = models.KnowledgeDocument(
        title=payload.title,
        asset_type=payload.asset_type or infer_asset_type(payload.title, markdown),
        content_hash=digest,
        last_seen_at=models.now(),
    )
    db.add(document)
    db.flush()
    snapshot = models.DocumentSnapshot(
        document_id=document.id,
        sync_run_id=sync_run_id,
        raw_payload={"manual": True},
        markdown=markdown,
        content_hash=digest,
    )
    db.add(snapshot)
    db.flush()
    document.current_snapshot_id = snapshot.id
    index_snapshot(db, document, snapshot)
    db.commit()
    db.refresh(document)
    return document


def upsert_external_document(
    db: Session,
    title: str,
    asset_type: str,
    markdown: str,
    external_id: str,
    source_id: str | None,
    raw_payload: dict,
    sync_run_id: str | None,
) -> tuple[models.KnowledgeDocument, int, bool]:
    digest = content_hash(markdown)
    document = (
        db.query(models.KnowledgeDocument)
        .filter(models.KnowledgeDocument.external_id == external_id)
        .one_or_none()
    )
    if document and document.content_hash == digest:
        document.last_seen_at = models.now()
        db.commit()
        return document, 0, False
    if not document:
        document = models.KnowledgeDocument(
            source_id=source_id,
            external_id=external_id,
            title=title,
            asset_type=asset_type,
        )
        db.add(document)
        db.flush()
    document.title = title
    document.asset_type = asset_type
    document.content_hash = digest
    document.last_seen_at = models.now()
    snapshot = models.DocumentSnapshot(
        document_id=document.id,
        sync_run_id=sync_run_id,
        raw_payload=raw_payload,
        markdown=markdown,
        content_hash=digest,
    )
    db.add(snapshot)
    db.flush()
    document.current_snapshot_id = snapshot.id
    deleted = db.query(models.KnowledgeChunk).filter(models.KnowledgeChunk.document_id == document.id).delete()
    db.query(models.KnowledgeParent).filter(models.KnowledgeParent.document_id == document.id).delete()
    chunks = index_snapshot(db, document, snapshot)
    db.commit()
    return document, chunks, True


def index_snapshot(db: Session, document: models.KnowledgeDocument, snapshot: models.DocumentSnapshot) -> int:
    vector_store = VectorStore()
    count = 0
    for parent_index, parent_payload in enumerate(split_parent_child(snapshot.markdown)):
        parent = models.KnowledgeParent(
            document_id=document.id,
            snapshot_id=snapshot.id,
            heading_path=parent_payload["heading_path"],
            text=parent_payload["text"],
            sort_order=parent_index,
        )
        db.add(parent)
        db.flush()
        for child_index, child_text in enumerate(parent_payload["children"]):
            tokens = tokenize(child_text)
            chunk = models.KnowledgeChunk(
                parent_id=parent.id,
                document_id=document.id,
                snapshot_id=snapshot.id,
                asset_type=document.asset_type,
                heading_path=parent.heading_path,
                text=child_text,
                token_count=sum(tokens.values()),
                token_counts=dict(tokens),
                sort_order=child_index,
            )
            db.add(chunk)
            db.flush()
            chunk.vector_status = "indexed" if vector_store.upsert_chunk(chunk, document) else "fallback"
            count += 1
    return count


def read_document(document: models.KnowledgeDocument) -> DocumentRead:
    latest = None
    if document.current_snapshot_id:
        latest = next((item for item in document.snapshots if item.id == document.current_snapshot_id), None)
    return DocumentRead(
        id=document.id,
        title=document.title,
        asset_type=document.asset_type,
        content=latest.markdown if latest else "",
        chunk_count=len(document.chunks),
        created_at=document.created_at.isoformat(),
        current_snapshot_id=document.current_snapshot_id,
    )
