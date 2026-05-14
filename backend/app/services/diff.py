from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from .. import models


def create_diff_run(db: Session, requirement_id: str, target_snapshots: list[str], target_figma_context_id: str | None) -> models.DiffRun:
    requirement = db.get(models.Requirement, requirement_id)
    if not requirement or not requirement.current_baseline_id:
        raise ValueError("Requirement baseline not found")
    baseline = db.get(models.RequirementBaseline, requirement.current_baseline_id)
    run = models.DiffRun(
        requirement_id=requirement_id,
        previous_baseline_id=baseline.id,
        target_document_snapshot_ids=target_snapshots or baseline.document_snapshot_ids,
        target_figma_context_id=target_figma_context_id or baseline.figma_context_id,
        status="completed",
        change_level="minor",
        summary="检测到需求上下文变化，已生成候选用例变更。",
        affected_modules=["金额精度", "UI 字段校验", "异常流"],
        finished_at=models.now(),
    )
    db.add(run)
    db.flush()
    active_cases = (
        db.query(models.TestCaseVersion)
        .filter(models.TestCaseVersion.requirement_id == requirement_id, models.TestCaseVersion.status == "active")
        .all()
    )
    if active_cases:
        first = active_cases[0]
        db.add(
            models.CaseChangeProposal(
                diff_run_id=run.id,
                action="modified",
                target_case_id=first.id,
                module=first.module,
                title=first.title,
                before_payload=_case_payload(first),
                after_payload={**_case_payload(first), "steps": [*first.steps, "补充验证 0.01、重复提交和 UI 错误态。"]},
                change_reason="新上下文补充了精度、重复提交或 UI 状态风险。",
                evidence=[{"source_type": "rag", "source_id": "latest-context", "quote": "预算、重复提交、UI 约束发生变化"}],
                confidence=0.86,
            )
        )
        db.add(
            models.CaseChangeProposal(
                diff_run_id=run.id,
                action="deleted",
                target_case_id=active_cases[-1].id,
                module=active_cases[-1].module,
                title=active_cases[-1].title,
                before_payload=_case_payload(active_cases[-1]),
                after_payload=None,
                change_reason="当前上下文中该旧路径不再出现，建议作废但需人工确认。",
                evidence=[{"source_type": "baseline", "source_id": baseline.id, "quote": "新旧 baseline 路径不一致"}],
                confidence=0.76,
            )
        )
    db.add(
        models.CaseChangeProposal(
            diff_run_id=run.id,
            action="added",
            target_case_id=None,
            module="UI 字段校验",
            title="新增 UI 错误态与按钮禁用态校验",
            before_payload=None,
            after_payload={
                "module": "UI 字段校验",
                "title": "新增 UI 错误态与按钮禁用态校验",
                "preconditions": "已绑定 Figma 上下文。",
                "steps": ["清空必填字段。", "观察错误提示。", "检查提交按钮禁用状态。"],
                "expected_result": "错误文案展示正确，提交按钮禁用。",
                "priority": "P1",
            },
            change_reason="Figma UI 上下文提供了新的字段状态和交互约束。",
            evidence=[{"source_type": "figma", "source_id": target_figma_context_id or "manual", "quote": "field/action/feedback"}],
            confidence=0.82,
        )
    )
    db.commit()
    db.refresh(run)
    return run


def accept_proposal(db: Session, proposal_id: str, status: str = "accepted", after_payload: dict | None = None, note: str = "") -> models.CaseChangeProposal:
    proposal = db.get(models.CaseChangeProposal, proposal_id)
    if not proposal:
        raise ValueError("Proposal not found")
    proposal.review_status = status
    if after_payload is not None:
        proposal.after_payload = after_payload
    proposal.reviewer_note = note or proposal.reviewer_note
    proposal.reviewed_at = models.now()
    db.commit()
    db.refresh(proposal)
    return proposal


def reject_proposal(db: Session, proposal_id: str) -> models.CaseChangeProposal:
    return accept_proposal(db, proposal_id, "rejected")


def merge_diff_run(db: Session, diff_run_id: str) -> models.MergeRun:
    run = db.get(models.DiffRun, diff_run_id)
    if not run:
        raise ValueError("Diff run not found")
    proposals = (
        db.query(models.CaseChangeProposal)
        .filter(
            models.CaseChangeProposal.diff_run_id == diff_run_id,
            models.CaseChangeProposal.review_status.in_(["accepted", "edited_accepted"]),
        )
        .all()
    )
    merge = models.MergeRun(diff_run_id=diff_run_id, requirement_id=run.requirement_id, status="completed")
    db.add(merge)
    db.flush()
    baseline = models.RequirementBaseline(
        requirement_id=run.requirement_id,
        version=_next_baseline_version(db, run.requirement_id),
        requirement_hash=str(uuid4()),
        document_snapshot_ids=run.target_document_snapshot_ids,
        figma_context_id=run.target_figma_context_id,
        created_from_run_id=run.id,
    )
    db.add(baseline)
    db.flush()
    for proposal in proposals:
        if proposal.action == "added":
            payload = proposal.after_payload or {}
            db.add(_new_case(run.requirement_id, baseline.id, str(uuid4()), 1, payload))
        elif proposal.action == "modified" and proposal.target_case_id:
            old = db.get(models.TestCaseVersion, proposal.target_case_id)
            if old and old.status == "active":
                old.status = "superseded"
                db.add(_new_case(run.requirement_id, baseline.id, old.case_group_id, old.version + 1, proposal.after_payload or _case_payload(old)))
        elif proposal.action == "deleted" and proposal.target_case_id:
            old = db.get(models.TestCaseVersion, proposal.target_case_id)
            if old and old.status == "active":
                old.status = "deprecated"
    requirement = db.get(models.Requirement, run.requirement_id)
    if requirement:
        requirement.current_baseline_id = baseline.id
    merge.merged_proposal_ids = [proposal.id for proposal in proposals]
    merge.new_baseline_id = baseline.id
    merge.finished_at = models.now()
    db.commit()
    db.refresh(merge)
    return merge


def _case_payload(case: models.TestCaseVersion) -> dict:
    return {
        "module": case.module,
        "title": case.title,
        "preconditions": case.preconditions,
        "steps": case.steps,
        "expected_result": case.expected_result,
        "priority": case.priority,
    }


def _new_case(requirement_id: str, baseline_id: str, group_id: str, version: int, payload: dict) -> models.TestCaseVersion:
    return models.TestCaseVersion(
        case_group_id=group_id,
        requirement_id=requirement_id,
        baseline_id=baseline_id,
        version=version,
        status="active",
        module=payload.get("module", "未分组"),
        title=payload.get("title", "Untitled Case"),
        preconditions=payload.get("preconditions", ""),
        steps=payload.get("steps", []),
        expected_result=payload.get("expected_result", ""),
        priority=payload.get("priority", "P1"),
        related_risks=payload.get("related_risks", []),
        citations=payload.get("citations", []),
        ui_coverage_tags=payload.get("ui_coverage_tags", []),
        figma_citations=payload.get("figma_citations", []),
        source_mix=payload.get("source_mix", "rag"),
    )


def _next_baseline_version(db: Session, requirement_id: str) -> int:
    current = (
        db.query(models.RequirementBaseline)
        .filter(models.RequirementBaseline.requirement_id == requirement_id)
        .order_by(models.RequirementBaseline.version.desc())
        .first()
    )
    return (current.version if current else 0) + 1
