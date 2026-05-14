from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from .. import models


ACTION_ORDER = {"deleted": 0, "modified": 1, "added": 2, "unchanged": 3}


def get_or_create_view_state(db: Session, diff_run_id: str, user_key: str = "default") -> models.ReviewViewState:
    state = (
        db.query(models.ReviewViewState)
        .filter(models.ReviewViewState.diff_run_id == diff_run_id, models.ReviewViewState.user_key == user_key)
        .one_or_none()
    )
    if state:
        return state
    state = models.ReviewViewState(diff_run_id=diff_run_id, user_key=user_key)
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def patch_view_state(db: Session, diff_run_id: str, payload, user_key: str = "default") -> models.ReviewViewState:
    state = get_or_create_view_state(db, diff_run_id, user_key)
    if payload.view_mode is not None:
        state.view_mode = payload.view_mode
    if payload.selected_proposal_id is not None:
        state.selected_proposal_id = payload.selected_proposal_id
    if payload.focused_node_id is not None:
        state.focused_node_id = payload.focused_node_id
    if payload.node_positions is not None:
        state.node_positions = payload.node_positions
    if payload.collapsed_groups is not None:
        state.collapsed_groups = payload.collapsed_groups
    state.updated_at = models.now()
    db.commit()
    db.refresh(state)
    return state


def build_review_graph(db: Session, diff_run_id: str, user_key: str = "default") -> dict:
    run = db.get(models.DiffRun, diff_run_id)
    if not run:
        raise ValueError("Diff run not found")
    requirement = db.get(models.Requirement, run.requirement_id)
    proposals = (
        db.query(models.CaseChangeProposal)
        .filter(models.CaseChangeProposal.diff_run_id == diff_run_id)
        .order_by(models.CaseChangeProposal.module.asc(), models.CaseChangeProposal.action.asc())
        .all()
    )
    state = get_or_create_view_state(db, diff_run_id, user_key)
    nodes, edges = _graph_payload(requirement, run, proposals, state.node_positions or {}, db)
    groups = []
    grouped = defaultdict(list)
    for proposal in proposals:
        grouped[proposal.action].append(proposal.id)
    for action in sorted(grouped, key=lambda value: ACTION_ORDER.get(value, 99)):
        groups.append({"action": action, "count": len(grouped[action]), "proposal_ids": grouped[action]})
    return {
        "diff_run": {
            "id": run.id,
            "summary": run.summary,
            "change_level": run.change_level,
            "affected_modules": run.affected_modules,
        },
        "table": {"groups": groups, "proposals": [_proposal_payload(proposal) for proposal in proposals]},
        "graph": {"nodes": nodes, "edges": edges},
        "selection": {
            "selected_proposal_id": state.selected_proposal_id,
            "focused_node_id": state.focused_node_id,
            "view_mode": state.view_mode,
            "collapsed_groups": state.collapsed_groups,
        },
    }


def _graph_payload(requirement, run, proposals, saved_positions: dict, db: Session) -> tuple[list[dict], list[dict]]:
    nodes: list[dict] = []
    edges: list[dict] = []
    requirement_id = f"requirement:{run.requirement_id}"
    nodes.append(
        _node(
            requirement_id,
            "requirement",
            {"title": requirement.title if requirement else "Requirement", "change_level": run.change_level},
            {"x": 0, "y": 160},
            saved_positions,
        )
    )
    modules = sorted({proposal.module for proposal in proposals})
    module_y = {module: 80 + index * 190 for index, module in enumerate(modules)}
    for module in modules:
        module_id = f"module:{module}"
        nodes.append(_node(module_id, "module", {"title": module}, {"x": 260, "y": module_y[module]}, saved_positions))
        edges.append(_edge(f"edge:{requirement_id}:{module_id}", requirement_id, module_id, "contains"))
    proposal_offsets: dict[str, int] = defaultdict(int)
    evidence_index = 0
    for proposal in sorted(proposals, key=lambda item: (item.module, ACTION_ORDER.get(item.action, 99), item.title)):
        offset = proposal_offsets[proposal.module]
        proposal_offsets[proposal.module] += 1
        proposal_id = f"proposal:{proposal.id}"
        y = module_y.get(proposal.module, 120) + offset * 72
        nodes.append(
            _node(
                proposal_id,
                "proposal",
                {
                    "proposal_id": proposal.id,
                    "action": proposal.action,
                    "review_status": proposal.review_status,
                    "title": proposal.title,
                    "confidence": proposal.confidence,
                    "duplicate_risk": proposal.duplicate_risk,
                },
                {"x": 560, "y": y},
                saved_positions,
            )
        )
        edges.append(_edge(f"edge:module:{proposal.module}:{proposal.id}", f"module:{proposal.module}", proposal_id, "contains"))
        if proposal.target_case_id:
            case = db.get(models.TestCaseVersion, proposal.target_case_id)
            case_id = f"case:{proposal.target_case_id}"
            nodes.append(
                _node(
                    case_id,
                    "case",
                    {
                        "case_id": proposal.target_case_id,
                        "title": case.title if case else proposal.title,
                        "status": case.status if case else "unknown",
                        "version": case.version if case else None,
                    },
                    {"x": 820, "y": y - 36},
                    saved_positions,
                )
            )
            edges.append(_edge(f"edge:proposal:{proposal.id}:case:{proposal.target_case_id}", proposal_id, case_id, "changes"))
        for evidence in proposal.evidence or []:
            evidence_index += 1
            evidence_id = f"evidence:{proposal.id}:{evidence_index}"
            nodes.append(
                _node(
                    evidence_id,
                    "evidence",
                    {
                        "proposal_id": proposal.id,
                        "source_type": evidence.get("source_type"),
                        "source_id": evidence.get("source_id"),
                        "quote": evidence.get("quote"),
                    },
                    {"x": 1060, "y": y + (evidence_index % 2) * 44},
                    saved_positions,
                )
            )
            edges.append(_edge(f"edge:proposal:{proposal.id}:evidence:{evidence_index}", proposal_id, evidence_id, "evidenced_by"))
    return _dedupe_nodes(nodes), edges


def _node(node_id: str, node_type: str, data: dict, position: dict, saved_positions: dict) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "position": saved_positions.get(node_id, position),
        "data": data,
    }


def _edge(edge_id: str, source: str, target: str, edge_type: str) -> dict:
    return {"id": edge_id, "source": source, "target": target, "type": edge_type}


def _dedupe_nodes(nodes: list[dict]) -> list[dict]:
    seen = {}
    for node in nodes:
        seen[node["id"]] = node
    return list(seen.values())


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
