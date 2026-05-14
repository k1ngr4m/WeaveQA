from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from .. import models
from ..schemas import GenerateRequest, GenerationMetrics, GenerationResponse, SearchResult, TestCase
from .text import content_hash
from .vector_store import VectorStore


GENERATIONS: dict[str, GenerationResponse] = {}


def citation_for(result: SearchResult) -> str:
    return f"{result.title}#{result.chunk_id[:6]}"


def generate_cases(db: Session, payload: GenerateRequest) -> GenerationResponse:
    started = datetime.now()
    contexts = VectorStore().search(db, payload.requirement, payload.mode, 6)
    ui_items = _ui_items(db, payload.figma_context_id)
    cases = build_cases(payload.requirement, payload.mode, contexts, ui_items)
    if payload.mode == "no_kb":
        cases = cases[:2]
    metrics = score_generation(payload.mode, cases, contexts, len(ui_items))
    requirement_id = None
    baseline_id = None
    if payload.save_as_requirement:
        requirement, baseline = save_requirement_baseline(
            db,
            payload.requirement_title or cases[0].title if cases else "Untitled Requirement",
            payload.requirement,
            cases,
            payload.figma_context_id,
        )
        requirement_id = requirement.id
        baseline_id = baseline.id
    elapsed_ms = int((datetime.now() - started).total_seconds() * 1000)
    response = GenerationResponse(
        id=str(uuid4()),
        mode=payload.mode,
        cases=cases,
        metrics=metrics,
        retrieved_context=contexts,
        elapsed_ms=elapsed_ms,
        requirement_id=requirement_id,
        baseline_id=baseline_id,
    )
    GENERATIONS[response.id] = response
    return response


def build_cases(
    requirement: str,
    mode: str,
    contexts: list[SearchResult],
    ui_items: list[models.UiContextItem],
) -> list[TestCase]:
    citations = [citation_for(item) for item in contexts[:3]] or ["requirement-only"]
    context_text = " ".join(item.text for item in contexts)
    ui_text = " ".join(item.label for item in ui_items)
    all_text = requirement + context_text + ui_text
    figma_citations = [
        {"node_id": item.figma_node_id, "label": item.label, "category": item.category}
        for item in ui_items[:3]
    ]
    source_mix = "rag_figma" if contexts and ui_items else "figma" if ui_items else "rag" if contexts else "requirement_only"
    cases = [
        TestCase(
            id=str(uuid4()),
            module="主流程",
            title="创建需求对象成功进入目标状态",
            preconditions="测试账号具备目标模块操作权限，基础配置完整。",
            steps=["进入需求描述对应的创建页面。", "按要求填写必填字段并提交。", "刷新列表并查看详情页状态。"],
            expected_result="数据创建成功，状态、详情字段和列表记录保持一致。",
            priority="P1",
            related_risks=["主流程不可用", "状态流转错误"],
            citations=citations[:2],
            ui_coverage_tags=[],
            figma_citations=[],
            source_mix=source_mix,
        )
    ]
    if any(keyword in all_text for keyword in ["时间", "日期", "开始", "结束"]):
        cases.append(_case("边界校验", "时间范围与状态边界校验", ["分别输入早于当前时间、结束早于开始、合法时间范围。", "提交并观察字段校验提示。", "使用合法时间再次提交。"], "非法时间被阻止并提示原因，合法时间可提交并进入待处理状态。", "P1", citations, source_mix))
    if any(keyword in all_text for keyword in ["预算", "金额", "价格", "0.01"]):
        cases.append(_case("金额精度", "预算金额精度与极值校验", ["输入 0、0.01、最大允许值和超出上限金额。", "提交后查看前端提示和接口返回。", "保存成功后查看详情页金额展示。"], "金额精度不丢失，非法值被阻止，详情页展示与提交值一致。", "P0", citations, source_mix))
    if any(keyword in all_text for keyword in ["权限", "角色", "账号", "绕过"]):
        cases.append(_case("权限控制", "无权限账号无法绕过创建接口", ["使用无权限账号访问创建入口。", "直接调用创建接口提交完整参数。", "使用有权限账号提交同一参数作为对照。"], "无权限入口与接口均被拒绝，有权限账号可按规则创建。", "P0", citations, source_mix))
    if any(keyword in all_text for keyword in ["重复", "多次", "提交", "幂等"]):
        cases.append(_case("异常流", "重复提交不会产生重复记录", ["快速连续点击提交按钮。", "在弱网环境下重复提交同一请求。", "检查列表、详情和审计记录。"], "系统只创建一条有效记录，重复请求被拦截或幂等处理。", "P0", citations, source_mix))
    if ui_items:
        fields = [item for item in ui_items if item.category == "field"]
        actions = [item for item in ui_items if item.category == "action"]
        if fields:
            cases.append(
                TestCase(
                    id=str(uuid4()),
                    module="UI 字段校验",
                    title=f"{fields[0].label} 输入约束与错误提示校验",
                    preconditions="已绑定 Figma UI 上下文。",
                    steps=[f"定位 {fields[0].label}。", "输入空值、非法值和合法值。", "观察错误提示与提交按钮状态。"],
                    expected_result="字段约束、错误文案和提交状态与设计稿上下文一致。",
                    priority="P1",
                    related_risks=["UI 约束遗漏"],
                    citations=citations,
                    ui_coverage_tags=["field", "feedback"],
                    figma_citations=figma_citations,
                    source_mix=source_mix,
                )
            )
        if actions:
            cases.append(
                TestCase(
                    id=str(uuid4()),
                    module="UI 交互",
                    title=f"{actions[0].label} 按钮状态与跳转校验",
                    preconditions="页面已加载，表单字段处于不同有效性状态。",
                    steps=[f"查看 {actions[0].label} 初始状态。", "切换必填字段有效性。", "点击按钮并观察反馈或跳转。"],
                    expected_result="按钮可用性、反馈和跳转行为与设计稿上下文一致。",
                    priority="P1",
                    related_risks=["按钮状态错误", "跳转缺失"],
                    citations=citations,
                    ui_coverage_tags=["action", "navigation"],
                    figma_citations=figma_citations,
                    source_mix=source_mix,
                )
            )
    return cases


def _case(module: str, title: str, steps: list[str], expected: str, priority: str, citations: list[str], source_mix: str) -> TestCase:
    return TestCase(
        id=str(uuid4()),
        module=module,
        title=title,
        preconditions="账号具备创建权限，基础数据准备完成。",
        steps=steps,
        expected_result=expected,
        priority=priority,
        related_risks=[title],
        citations=citations,
        source_mix=source_mix,
    )


def score_generation(mode: str, cases: list[TestCase], contexts: list[SearchResult], ui_count: int) -> GenerationMetrics:
    bug_points = sum(1 for item in contexts if item.asset_type in {"bug", "mixed"})
    if mode == "no_kb":
        coverage = 56
        missed = 4
    elif mode == "prd_only":
        coverage = min(78, 58 + len(cases) * 4)
        missed = max(2, 6 - len(cases))
    else:
        coverage = min(96, 64 + len(cases) * 4 + bug_points * 3 + min(ui_count, 5))
        missed = max(0, 5 - len(cases) - bug_points)
    return GenerationMetrics(coverage_score=coverage, missed_risks=missed, bug_regression_points=bug_points, ui_items=ui_count, mode=mode)


def save_requirement_baseline(
    db: Session,
    title: str,
    description: str,
    cases: list[TestCase],
    figma_context_id: str | None,
) -> tuple[models.Requirement, models.RequirementBaseline]:
    requirement = models.Requirement(title=title, description=description)
    db.add(requirement)
    db.flush()
    baseline = models.RequirementBaseline(
        requirement_id=requirement.id,
        version=1,
        requirement_hash=content_hash(description),
        document_snapshot_ids=[row[0] for row in db.query(models.DocumentSnapshot.id).all()],
        figma_context_id=figma_context_id,
        rag_context_hash=content_hash("".join(case.title for case in cases)),
    )
    db.add(baseline)
    db.flush()
    requirement.current_baseline_id = baseline.id
    for case in cases:
        db.add(
            models.TestCaseVersion(
                case_group_id=str(uuid4()),
                requirement_id=requirement.id,
                baseline_id=baseline.id,
                version=1,
                status="active",
                module=case.module,
                title=case.title,
                preconditions=case.preconditions,
                steps=case.steps,
                expected_result=case.expected_result,
                priority=case.priority,
                related_risks=case.related_risks,
                citations=case.citations,
                ui_coverage_tags=case.ui_coverage_tags,
                figma_citations=case.figma_citations,
                source_mix=case.source_mix,
            )
        )
    db.commit()
    return requirement, baseline


def _ui_items(db: Session, context_id: str | None) -> list[models.UiContextItem]:
    if not context_id:
        return []
    return (
        db.query(models.UiContextItem)
        .filter(models.UiContextItem.context_id == context_id, models.UiContextItem.included.is_(True))
        .all()
    )
