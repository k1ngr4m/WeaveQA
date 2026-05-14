from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import models
from .database import get_db, init_db
from .schemas import (
    DiffRunCreate,
    DocumentCreate,
    FigmaContextCreate,
    FigmaJsonImport,
    GenerateRequest,
    ModelConfig,
    ProposalEdit,
    RequirementCreate,
    ReviewCreate,
    ReviewViewStatePatch,
    SearchRequest,
    SourceCreate,
    UiItemPatch,
)
from .services import diff as diff_service
from .services import figma as figma_service
from .services import review_graph as review_graph_service
from .services.generation import GENERATIONS, generate_cases, save_requirement_baseline
from .services.knowledge import create_document, read_document, upsert_external_document
from .services.lark import LarkClient
from .services.vector_store import VectorStore


app = FastAPI(title="WeaveQA API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MODELS: list[ModelConfig] = [
    ModelConfig(id="deepseek-rag", name="DeepSeek Chat", provider="DeepSeek", base_url="https://api.deepseek.com"),
    ModelConfig(id="openai-gpt", name="GPT-5.5", provider="OpenAI Compatible", base_url="https://api.openai.com/v1"),
]
REVIEWS: list[ReviewCreate] = []


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict[str, object]:
    return {
        "status": "ok",
        "documents": db.query(models.KnowledgeDocument).count(),
        "chunks": db.query(models.KnowledgeChunk).count(),
        "sources": db.query(models.KnowledgeSource).count(),
        "requirements": db.query(models.Requirement).count(),
        "generated": len(GENERATIONS),
    }


@app.get("/api/models")
def list_models() -> dict[str, list[ModelConfig]]:
    return {"items": MODELS}


@app.post("/api/models")
def add_model(payload: ModelConfig) -> ModelConfig:
    MODELS.insert(0, payload)
    return payload


@app.get("/api/knowledge/documents")
def list_documents(db: Session = Depends(get_db)) -> dict[str, list[dict]]:
    documents = db.query(models.KnowledgeDocument).order_by(models.KnowledgeDocument.created_at.desc()).all()
    return {"items": [read_document(document).model_dump() for document in documents]}


@app.post("/api/knowledge/documents")
def create_knowledge_document(payload: DocumentCreate, db: Session = Depends(get_db)) -> dict:
    return read_document(create_document(db, payload)).model_dump()


@app.post("/api/knowledge/seed")
def seed_knowledge(db: Session = Depends(get_db)) -> dict[str, object]:
    samples = [
        DocumentCreate(
            title="营销活动 PRD",
            asset_type="prd",
            content="营销活动创建页包含活动名称、时间范围、预算上限、参与门槛、目标人群和提交审核。活动名称不可重复，开始时间必须晚于当前时间，结束时间必须晚于开始时间。提交后状态为待审核，审核通过后才可投放。",
        ),
        DocumentCreate(
            title="营销活动历史 Bug",
            asset_type="bug",
            content="预算上限输入 0.01 元时被错误四舍五入为 0，导致活动无法创建。重复点击提交按钮会产生两条待审核活动。普通运营账号绕过前端入口后仍可调用创建接口。",
        ),
    ]
    for sample in samples:
        create_document(db, sample)
    return {"ok": True, "documents": db.query(models.KnowledgeDocument).count(), "chunks": db.query(models.KnowledgeChunk).count()}


@app.get("/api/knowledge/chunks")
def list_chunks(document_id: str | None = None, db: Session = Depends(get_db)) -> dict[str, list[dict]]:
    query = db.query(models.KnowledgeChunk)
    if document_id:
        query = query.filter(models.KnowledgeChunk.document_id == document_id)
    return {
        "items": [
            {
                "id": chunk.id,
                "document_id": chunk.document_id,
                "asset_type": chunk.asset_type,
                "heading_path": chunk.heading_path,
                "text": chunk.text,
                "vector_status": chunk.vector_status,
            }
            for chunk in query.order_by(models.KnowledgeChunk.created_at.desc()).limit(200).all()
        ]
    }


@app.post("/api/retrieval/search")
def search(payload: SearchRequest, db: Session = Depends(get_db)) -> dict[str, list[dict]]:
    return {"items": [item.model_dump() for item in VectorStore().search(db, payload.query, payload.mode, payload.top_k)]}


@app.post("/api/cases/generate")
def generate(payload: GenerateRequest, db: Session = Depends(get_db)) -> dict:
    return generate_cases(db, payload).model_dump()


@app.post("/api/reviews")
def save_review(payload: ReviewCreate) -> dict[str, object]:
    generation = GENERATIONS.get(payload.generation_id)
    if not generation:
        raise HTTPException(status_code=404, detail="Generation not found")
    REVIEWS.append(payload)
    generation.metrics.saved = True
    return {"ok": True, "metrics": generation.metrics.model_dump(), "reviews": len(REVIEWS)}


@app.get("/api/sources")
def list_sources(db: Session = Depends(get_db)) -> dict[str, list[dict]]:
    sources = db.query(models.KnowledgeSource).order_by(models.KnowledgeSource.created_at.desc()).all()
    return {"items": [_source_payload(source) for source in sources]}


@app.post("/api/sources")
def create_source(payload: SourceCreate, db: Session = Depends(get_db)) -> dict:
    source = models.KnowledgeSource(
        name=payload.name,
        source_type=payload.source_type,
        source_url=payload.source_url,
        lark_node_token=LarkClient().parse_node_token(payload.source_url),
        sync_mode=payload.sync_mode,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return _source_payload(source)


@app.patch("/api/sources/{source_id}")
def update_source(source_id: str, payload: SourceCreate, db: Session = Depends(get_db)) -> dict:
    source = db.get(models.KnowledgeSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    source.name = payload.name
    source.source_type = payload.source_type
    source.source_url = payload.source_url
    source.sync_mode = payload.sync_mode
    source.updated_at = models.now()
    db.commit()
    return _source_payload(source)


@app.post("/api/sources/{source_id}/sync")
async def sync_source(source_id: str, db: Session = Depends(get_db)) -> dict:
    source = db.get(models.KnowledgeSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    run = models.SyncRun(source_id=source.id, status="running", stage="fetching")
    source.status = "syncing"
    db.add(run)
    db.commit()
    try:
        fetched = await LarkClient().fetch_document(source.source_url)
        run.stage = "indexing"
        document, chunks, changed = upsert_external_document(
            db,
            fetched["title"],
            fetched["asset_type"],
            fetched["markdown"],
            fetched["external_id"],
            source.id,
            fetched["raw_payload"],
            run.id,
        )
        run.status = "completed"
        run.stage = "completed"
        run.documents_found = 1
        run.documents_changed = 1 if changed else 0
        run.chunks_indexed = chunks
        run.finished_at = models.now()
        source.status = "ready"
        source.last_synced_at = models.now()
        source.last_error = None
        db.commit()
        return {"ok": True, "run": _sync_payload(run), "document_id": document.id}
    except Exception as exc:
        run.status = "failed"
        run.stage = "failed"
        run.error = str(exc)
        run.finished_at = models.now()
        source.status = "failed"
        source.last_error = str(exc)
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/sync-runs")
def list_sync_runs(db: Session = Depends(get_db)) -> dict[str, list[dict]]:
    runs = db.query(models.SyncRun).order_by(models.SyncRun.started_at.desc()).limit(50).all()
    return {"items": [_sync_payload(run) for run in runs]}


@app.get("/api/sync-runs/{run_id}")
def get_sync_run(run_id: str, db: Session = Depends(get_db)) -> dict:
    run = db.get(models.SyncRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Sync run not found")
    return _sync_payload(run)


@app.post("/api/figma/contexts")
def create_figma_context(payload: FigmaContextCreate, db: Session = Depends(get_db)) -> dict:
    file_key, node_id = figma_service.parse_figma_url(payload.figma_url)
    context = models.FigmaContext(
        requirement_id=payload.requirement_id,
        figma_url=payload.figma_url,
        file_key=file_key,
        node_id=payload.node_id or node_id,
    )
    db.add(context)
    db.commit()
    db.refresh(context)
    return _figma_context_payload(context)


@app.post("/api/figma/contexts/import-json")
def import_figma_json(payload: FigmaJsonImport, db: Session = Depends(get_db)) -> dict:
    file_key, node_id = figma_service.parse_figma_url(payload.figma_url)
    context = models.FigmaContext(
        requirement_id=payload.requirement_id,
        figma_url=payload.figma_url,
        file_key=file_key,
        node_id=node_id,
        status="parsed",
        raw_payload=payload.payload,
    )
    db.add(context)
    db.flush()
    _store_figma_extraction(db, context, payload.payload)
    db.commit()
    db.refresh(context)
    return _figma_context_payload(context)


@app.post("/api/figma/contexts/{context_id}/sync")
async def sync_figma_context(context_id: str, db: Session = Depends(get_db)) -> dict:
    context = db.get(models.FigmaContext, context_id)
    if not context:
        raise HTTPException(status_code=404, detail="Figma context not found")
    context.status = "fetching"
    db.commit()
    try:
        payload = await figma_service.fetch_figma_payload(context.file_key, context.node_id)
        context.raw_payload = payload
        _store_figma_extraction(db, context, payload)
        context.status = "parsed"
        context.last_synced_at = models.now()
        context.last_error = None
        db.commit()
        return _figma_context_payload(context)
    except Exception as exc:
        context.status = "failed"
        context.last_error = str(exc)
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/figma/contexts/{context_id}")
def get_figma_context(context_id: str, db: Session = Depends(get_db)) -> dict:
    context = db.get(models.FigmaContext, context_id)
    if not context:
        raise HTTPException(status_code=404, detail="Figma context not found")
    return _figma_context_payload(context)


@app.get("/api/figma/contexts/{context_id}/frames")
def list_figma_frames(context_id: str, db: Session = Depends(get_db)) -> dict[str, list[dict]]:
    frames = db.query(models.FigmaFrame).filter(models.FigmaFrame.context_id == context_id).all()
    return {"items": [{"id": item.id, "figma_node_id": item.figma_node_id, "name": item.name, "node_type": item.node_type, "depth": item.depth} for item in frames]}


@app.get("/api/figma/contexts/{context_id}/items")
def list_figma_items(context_id: str, db: Session = Depends(get_db)) -> dict[str, list[dict]]:
    items = db.query(models.UiContextItem).filter(models.UiContextItem.context_id == context_id).all()
    return {"items": [_ui_item_payload(item) for item in items]}


@app.patch("/api/figma/items/{item_id}")
def patch_figma_item(item_id: str, payload: UiItemPatch, db: Session = Depends(get_db)) -> dict:
    item = db.get(models.UiContextItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="UI item not found")
    if payload.included is not None:
        item.included = payload.included
    if payload.confidence is not None:
        item.confidence = payload.confidence
    if payload.interaction_hint is not None:
        item.interaction_hint = payload.interaction_hint
    db.commit()
    return _ui_item_payload(item)


@app.post("/api/requirements")
def create_requirement(payload: RequirementCreate, db: Session = Depends(get_db)) -> dict:
    if payload.generation_id:
        generation = GENERATIONS.get(payload.generation_id)
        if not generation:
            raise HTTPException(status_code=404, detail="Generation not found")
        requirement, baseline = save_requirement_baseline(db, payload.title, payload.description, generation.cases, None)
    else:
        requirement = models.Requirement(title=payload.title, description=payload.description)
        db.add(requirement)
        db.flush()
        baseline = models.RequirementBaseline(
            requirement_id=requirement.id,
            version=1,
            requirement_hash=payload.description,
            document_snapshot_ids=[],
        )
        db.add(baseline)
        db.flush()
        requirement.current_baseline_id = baseline.id
        db.commit()
    return _requirement_payload(requirement, baseline)


@app.get("/api/requirements/{requirement_id}")
def get_requirement(requirement_id: str, db: Session = Depends(get_db)) -> dict:
    requirement = db.get(models.Requirement, requirement_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")
    baseline = db.get(models.RequirementBaseline, requirement.current_baseline_id) if requirement.current_baseline_id else None
    return _requirement_payload(requirement, baseline)


@app.get("/api/requirements/{requirement_id}/cases")
def list_requirement_cases(requirement_id: str, db: Session = Depends(get_db)) -> dict[str, list[dict]]:
    cases = (
        db.query(models.TestCaseVersion)
        .filter(models.TestCaseVersion.requirement_id == requirement_id, models.TestCaseVersion.status == "active")
        .all()
    )
    return {"items": [_case_payload(case) for case in cases]}


@app.post("/api/requirements/{requirement_id}/diff-runs")
def create_diff_run(requirement_id: str, payload: DiffRunCreate, db: Session = Depends(get_db)) -> dict:
    try:
        run = diff_service.create_diff_run(db, requirement_id, payload.target_document_snapshot_ids, payload.target_figma_context_id)
        return _diff_run_payload(run)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/diff-runs/{run_id}")
def get_diff_run(run_id: str, db: Session = Depends(get_db)) -> dict:
    run = db.get(models.DiffRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Diff run not found")
    return _diff_run_payload(run)


@app.get("/api/diff-runs/{run_id}/proposals")
def list_proposals(run_id: str, db: Session = Depends(get_db)) -> dict[str, list[dict]]:
    proposals = db.query(models.CaseChangeProposal).filter(models.CaseChangeProposal.diff_run_id == run_id).all()
    return {"items": [_proposal_payload(item) for item in proposals]}


@app.get("/api/diff-runs/{run_id}/review-graph")
def get_review_graph(run_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        return review_graph_service.build_review_graph(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/diff-runs/{run_id}/view-state")
def get_view_state(run_id: str, db: Session = Depends(get_db)) -> dict:
    state = review_graph_service.get_or_create_view_state(db, run_id)
    return _view_state_payload(state)


@app.patch("/api/diff-runs/{run_id}/view-state")
def patch_view_state(run_id: str, payload: ReviewViewStatePatch, db: Session = Depends(get_db)) -> dict:
    state = review_graph_service.patch_view_state(db, run_id, payload)
    return _view_state_payload(state)


@app.post("/api/proposals/{proposal_id}/accept")
def accept_proposal(proposal_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        return _proposal_payload(diff_service.accept_proposal(db, proposal_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        return _proposal_payload(diff_service.reject_proposal(db, proposal_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/proposals/{proposal_id}/edit-and-accept")
def edit_accept_proposal(proposal_id: str, payload: ProposalEdit, db: Session = Depends(get_db)) -> dict:
    try:
        return _proposal_payload(diff_service.accept_proposal(db, proposal_id, "edited_accepted", payload.after_payload, payload.reviewer_note))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/proposals/{proposal_id}")
def patch_proposal(proposal_id: str, payload: ProposalEdit, db: Session = Depends(get_db)) -> dict:
    proposal = db.get(models.CaseChangeProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if payload.after_payload is not None:
        proposal.after_payload = payload.after_payload
    proposal.reviewer_note = payload.reviewer_note
    db.commit()
    return _proposal_payload(proposal)


@app.post("/api/diff-runs/{run_id}/merge")
def merge_diff_run(run_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        merge = diff_service.merge_diff_run(db, run_id)
        return {"id": merge.id, "status": merge.status, "merged_proposal_ids": merge.merged_proposal_ids, "new_baseline_id": merge.new_baseline_id}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/next-phases")
def next_phases() -> dict[str, list[dict[str, str]]]:
    return {
        "items": [
            {"phase": "Phase 2", "goal": "飞书同步、PostgreSQL/Qdrant 持久化、索引诊断。"},
            {"phase": "Phase 3", "goal": "Figma MCP、UI 上下文提取、UI 覆盖用例生成。"},
            {"phase": "Phase 4", "goal": "需求变更 Diff、采纳/驳回、版本化合并。"},
            {"phase": "Phase 5", "goal": "列表 Diff + React Flow 脑图联动。"},
            {"phase": "Phase 6", "goal": "权限、审计、密钥加密、统一代理、测试平台导出。"},
        ]
    }


def _store_figma_extraction(db: Session, context: models.FigmaContext, payload: dict) -> None:
    db.query(models.UiContextItem).filter(models.UiContextItem.context_id == context.id).delete()
    db.query(models.FigmaFrame).filter(models.FigmaFrame.context_id == context.id).delete()
    frames, items = figma_service.extract_ui_items(payload)
    frame_by_node: dict[str, models.FigmaFrame] = {}
    for frame in frames:
        model = models.FigmaFrame(context_id=context.id, **frame)
        db.add(model)
        db.flush()
        frame_by_node[frame["figma_node_id"]] = model
    for item in items:
        frame_id = next(iter(frame_by_node.values())).id if frame_by_node else None
        db.add(models.UiContextItem(context_id=context.id, frame_id=frame_id, **item))
    context.parsed_summary = {"frames": len(frames), "items": len(items)}


def _source_payload(source: models.KnowledgeSource) -> dict:
    return {
        "id": source.id,
        "name": source.name,
        "source_type": source.source_type,
        "source_url": source.source_url,
        "status": source.status,
        "last_synced_at": source.last_synced_at.isoformat() if source.last_synced_at else None,
        "last_error": source.last_error,
    }


def _sync_payload(run: models.SyncRun) -> dict:
    return {
        "id": run.id,
        "source_id": run.source_id,
        "status": run.status,
        "stage": run.stage,
        "documents_found": run.documents_found,
        "documents_changed": run.documents_changed,
        "chunks_indexed": run.chunks_indexed,
        "error": run.error,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def _figma_context_payload(context: models.FigmaContext) -> dict:
    return {
        "id": context.id,
        "requirement_id": context.requirement_id,
        "figma_url": context.figma_url,
        "file_key": context.file_key,
        "node_id": context.node_id,
        "status": context.status,
        "selected_frame_ids": context.selected_frame_ids,
        "parsed_summary": context.parsed_summary,
        "last_synced_at": context.last_synced_at.isoformat() if context.last_synced_at else None,
        "last_error": context.last_error,
    }


def _ui_item_payload(item: models.UiContextItem) -> dict:
    return {
        "id": item.id,
        "context_id": item.context_id,
        "figma_node_id": item.figma_node_id,
        "category": item.category,
        "label": item.label,
        "role": item.role,
        "text": item.text,
        "constraints": item.constraints,
        "interaction_hint": item.interaction_hint,
        "source_path": item.source_path,
        "confidence": item.confidence,
        "included": item.included,
    }


def _requirement_payload(requirement: models.Requirement, baseline: models.RequirementBaseline | None) -> dict:
    return {
        "id": requirement.id,
        "title": requirement.title,
        "description": requirement.description,
        "current_baseline_id": requirement.current_baseline_id,
        "baseline": {
            "id": baseline.id,
            "version": baseline.version,
            "figma_context_id": baseline.figma_context_id,
            "document_snapshot_ids": baseline.document_snapshot_ids,
        }
        if baseline
        else None,
    }


def _case_payload(case: models.TestCaseVersion) -> dict:
    return {
        "id": case.id,
        "case_group_id": case.case_group_id,
        "version": case.version,
        "status": case.status,
        "module": case.module,
        "title": case.title,
        "preconditions": case.preconditions,
        "steps": case.steps,
        "expected_result": case.expected_result,
        "priority": case.priority,
        "citations": case.citations,
        "ui_coverage_tags": case.ui_coverage_tags,
        "figma_citations": case.figma_citations,
        "source_mix": case.source_mix,
    }


def _diff_run_payload(run: models.DiffRun) -> dict:
    return {
        "id": run.id,
        "requirement_id": run.requirement_id,
        "previous_baseline_id": run.previous_baseline_id,
        "target_document_snapshot_ids": run.target_document_snapshot_ids,
        "target_figma_context_id": run.target_figma_context_id,
        "status": run.status,
        "change_level": run.change_level,
        "summary": run.summary,
        "affected_modules": run.affected_modules,
        "error": run.error,
    }


def _proposal_payload(proposal: models.CaseChangeProposal) -> dict:
    return {
        "id": proposal.id,
        "diff_run_id": proposal.diff_run_id,
        "action": proposal.action,
        "target_case_id": proposal.target_case_id,
        "review_status": proposal.review_status,
        "module": proposal.module,
        "title": proposal.title,
        "before_payload": proposal.before_payload,
        "after_payload": proposal.after_payload,
        "change_reason": proposal.change_reason,
        "evidence": proposal.evidence,
        "confidence": proposal.confidence,
        "duplicate_risk": proposal.duplicate_risk,
        "reviewer_note": proposal.reviewer_note,
    }


def _view_state_payload(state: models.ReviewViewState) -> dict:
    return {
        "id": state.id,
        "diff_run_id": state.diff_run_id,
        "user_key": state.user_key,
        "view_mode": state.view_mode,
        "selected_proposal_id": state.selected_proposal_id,
        "focused_node_id": state.focused_node_id,
        "node_positions": state.node_positions,
        "collapsed_groups": state.collapsed_groups,
        "updated_at": state.updated_at.isoformat(),
    }
