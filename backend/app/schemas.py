from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


AssetType = Literal["prd", "bug", "mixed"]
GenerationMode = Literal["no_kb", "prd_only", "prd_bug"]


class ModelConfig(BaseModel):
    id: str
    name: str
    provider: str
    base_url: str
    active: bool = True


class DocumentCreate(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    asset_type: AssetType = "mixed"
    content: str = Field(min_length=20)


class DocumentRead(BaseModel):
    id: str
    title: str
    asset_type: str
    content: str
    chunk_count: int
    created_at: str
    current_snapshot_id: str | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=2)
    mode: GenerationMode = "prd_bug"
    top_k: int = Field(default=5, ge=1, le=12)


class SearchResult(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    asset_type: str
    text: str
    parent_text: str = ""
    heading_path: list[str] = []
    score: float


class GenerateRequest(BaseModel):
    requirement: str = Field(min_length=20)
    mode: GenerationMode = "prd_bug"
    figma_context_id: str | None = None
    generation_strategy: list[str] = Field(default_factory=lambda: ["functional", "boundary"])
    save_as_requirement: bool = False
    requirement_title: str | None = None


class TestCase(BaseModel):
    id: str
    module: str
    title: str
    preconditions: str
    steps: list[str]
    expected_result: str
    priority: Literal["P0", "P1", "P2"]
    related_risks: list[str]
    citations: list[str]
    ui_coverage_tags: list[str] = []
    figma_citations: list[dict] = []
    source_mix: str = "rag"


class GenerationMetrics(BaseModel):
    coverage_score: int
    missed_risks: int
    bug_regression_points: int
    mode: GenerationMode
    ui_items: int = 0
    saved: bool = False


class GenerationResponse(BaseModel):
    id: str
    mode: GenerationMode
    cases: list[TestCase]
    metrics: GenerationMetrics
    retrieved_context: list[SearchResult]
    elapsed_ms: int
    requirement_id: str | None = None
    baseline_id: str | None = None


class ReviewCreate(BaseModel):
    generation_id: str
    coverage_score: int = Field(ge=0, le=100)
    missed_risks: int = Field(ge=0)
    bug_regression_points: int = Field(ge=0)
    accepted_cases: int = Field(ge=0)
    notes: str = ""


class SourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    source_type: Literal["lark_doc", "lark_folder"]
    source_url: str
    sync_mode: Literal["manual", "webhook"] = "manual"


class SourceRead(BaseModel):
    id: str
    name: str
    source_type: str
    source_url: str
    status: str
    last_synced_at: str | None
    last_error: str | None


class FigmaContextCreate(BaseModel):
    figma_url: str
    requirement_id: str | None = None
    node_id: str | None = None


class FigmaJsonImport(BaseModel):
    figma_url: str = "https://figma.local/file/mock?node-id=1:1"
    requirement_id: str | None = None
    payload: dict


class UiItemPatch(BaseModel):
    included: bool | None = None
    confidence: float | None = None
    interaction_hint: str | None = None


class RequirementCreate(BaseModel):
    title: str
    description: str
    generation_id: str | None = None


class DiffRunCreate(BaseModel):
    target_document_snapshot_ids: list[str] = []
    target_figma_context_id: str | None = None


class ProposalEdit(BaseModel):
    after_payload: dict | None = None
    reviewer_note: str = ""


class ReviewViewStatePatch(BaseModel):
    view_mode: str | None = None
    selected_proposal_id: str | None = None
    focused_node_id: str | None = None
    node_positions: dict | None = None
    collapsed_groups: list[str] | None = None
