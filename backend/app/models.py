from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def new_id() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(180))
    source_type: Mapped[str] = mapped_column(String(32))
    source_url: Mapped[str] = mapped_column(Text)
    lark_node_token: Mapped[str | None] = mapped_column(String(256), nullable=True)
    sync_mode: Mapped[str] = mapped_column(String(32), default="manual")
    status: Mapped[str] = mapped_column(String(32), default="ready")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    documents: Mapped[list["KnowledgeDocument"]] = relationship(back_populates="source")


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_sources.id"), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    asset_type: Mapped[str] = mapped_column(String(32))
    current_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    source: Mapped[KnowledgeSource | None] = relationship(back_populates="documents")
    snapshots: Mapped[list["DocumentSnapshot"]] = relationship(back_populates="document")
    parents: Mapped[list["KnowledgeParent"]] = relationship(back_populates="document")
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(back_populates="document")


class DocumentSnapshot(Base):
    __tablename__ = "document_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id"))
    sync_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    markdown: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    document: Mapped[KnowledgeDocument] = relationship(back_populates="snapshots")


class KnowledgeParent(Base):
    __tablename__ = "knowledge_parents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id"))
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("document_snapshots.id"))
    heading_path: Mapped[list[str]] = mapped_column(JSON, default=list)
    text: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer)

    document: Mapped[KnowledgeDocument] = relationship(back_populates="parents")
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(back_populates="parent")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    parent_id: Mapped[str] = mapped_column(ForeignKey("knowledge_parents.id"))
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id"))
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("document_snapshots.id"))
    asset_type: Mapped[str] = mapped_column(String(32))
    heading_path: Mapped[list[str]] = mapped_column(JSON, default=list)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    token_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    vector_status: Mapped[str] = mapped_column(String(32), default="pending")
    sort_order: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")
    parent: Mapped[KnowledgeParent] = relationship(back_populates="chunks")


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_sources.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    stage: Mapped[str] = mapped_column(String(32))
    documents_found: Mapped[int] = mapped_column(Integer, default=0)
    documents_changed: Mapped[int] = mapped_column(Integer, default=0)
    chunks_indexed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FigmaContext(Base):
    __tablename__ = "figma_contexts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    requirement_id: Mapped[str | None] = mapped_column(String, nullable=True)
    figma_url: Mapped[str] = mapped_column(Text)
    file_key: Mapped[str] = mapped_column(String(256))
    node_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ready")
    selected_frame_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parsed_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    items: Mapped[list["UiContextItem"]] = relationship(back_populates="context")
    frames: Mapped[list["FigmaFrame"]] = relationship(back_populates="context")


class FigmaFrame(Base):
    __tablename__ = "figma_frames"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    context_id: Mapped[str] = mapped_column(ForeignKey("figma_contexts.id"))
    figma_node_id: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(240))
    node_type: Mapped[str] = mapped_column(String(80))
    depth: Mapped[int] = mapped_column(Integer, default=0)
    raw_node: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer)

    context: Mapped[FigmaContext] = relationship(back_populates="frames")


class UiContextItem(Base):
    __tablename__ = "ui_context_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    context_id: Mapped[str] = mapped_column(ForeignKey("figma_contexts.id"))
    frame_id: Mapped[str | None] = mapped_column(ForeignKey("figma_frames.id"), nullable=True)
    figma_node_id: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(240))
    role: Mapped[str | None] = mapped_column(String(80), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    constraints: Mapped[dict] = mapped_column(JSON, default=dict)
    interaction_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_path: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    included: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    context: Mapped[FigmaContext] = relationship(back_populates="items")


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text)
    current_baseline_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RequirementBaseline(Base):
    __tablename__ = "requirement_baselines"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id"))
    version: Mapped[int] = mapped_column(Integer)
    requirement_hash: Mapped[str] = mapped_column(String(64))
    document_snapshot_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    figma_context_id: Mapped[str | None] = mapped_column(String, nullable=True)
    rag_context_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_from_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TestCaseVersion(Base):
    __tablename__ = "test_case_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    case_group_id: Mapped[str] = mapped_column(String)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id"))
    baseline_id: Mapped[str | None] = mapped_column(ForeignKey("requirement_baselines.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    module: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(240))
    preconditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[list[str]] = mapped_column(JSON, default=list)
    expected_result: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(16))
    related_risks: Mapped[list[str]] = mapped_column(JSON, default=list)
    citations: Mapped[list[str]] = mapped_column(JSON, default=list)
    ui_coverage_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    figma_citations: Mapped[list[dict]] = mapped_column(JSON, default=list)
    source_mix: Mapped[str] = mapped_column(String(32), default="rag")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DiffRun(Base):
    __tablename__ = "diff_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id"))
    previous_baseline_id: Mapped[str] = mapped_column(ForeignKey("requirement_baselines.id"))
    target_document_snapshot_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_figma_context_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    change_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    affected_modules: Mapped[list[str]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CaseChangeProposal(Base):
    __tablename__ = "case_change_proposals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    diff_run_id: Mapped[str] = mapped_column(ForeignKey("diff_runs.id"))
    action: Mapped[str] = mapped_column(String(32))
    target_case_id: Mapped[str | None] = mapped_column(ForeignKey("test_case_versions.id"), nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    module: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(240))
    before_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    change_reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[dict]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float)
    duplicate_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MergeRun(Base):
    __tablename__ = "merge_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    diff_run_id: Mapped[str] = mapped_column(ForeignKey("diff_runs.id"))
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id"))
    status: Mapped[str] = mapped_column(String(32))
    merged_proposal_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    new_baseline_id: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewViewState(Base):
    __tablename__ = "review_view_states"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    diff_run_id: Mapped[str] = mapped_column(ForeignKey("diff_runs.id"))
    user_key: Mapped[str] = mapped_column(String(120), default="default")
    view_mode: Mapped[str] = mapped_column(String(32), default="split")
    selected_proposal_id: Mapped[str | None] = mapped_column(String, nullable=True)
    focused_node_id: Mapped[str | None] = mapped_column(String, nullable=True)
    node_positions: Mapped[dict] = mapped_column(JSON, default=dict)
    collapsed_groups: Mapped[list[str]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
