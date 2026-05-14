from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.figma import extract_ui_items, parse_figma_url
from backend.app.services.text import blocks_to_markdown, split_parent_child


def test_parse_figma_url() -> None:
    file_key, node_id = parse_figma_url("https://www.figma.com/design/ABC123/App?node-id=1-23")
    assert file_key == "ABC123"
    assert node_id == "1-23"


def test_blocks_to_markdown() -> None:
    markdown = blocks_to_markdown({"blocks": [{"type": "heading", "text": "需求"}, {"type": "text", "text": "预算必填"}]})
    assert "需求" in markdown
    assert "预算必填" in markdown


def test_split_parent_child() -> None:
    parents = split_parent_child("预算必填。金额最小 0.01。重复提交需要幂等。")
    assert parents
    assert parents[0]["children"]


def test_extract_ui_items() -> None:
    payload = {
        "document": {
            "id": "1:1",
            "name": "创建活动弹窗",
            "type": "FRAME",
            "children": [
                {"id": "1:2", "name": "预算上限输入框", "type": "Input", "props": {"required": True}},
                {"id": "1:3", "name": "提交按钮", "type": "Button"},
                {"id": "1:4", "name": "错误提示", "type": "Text"},
            ],
        }
    }
    frames, items = extract_ui_items(payload)
    assert frames
    categories = {item["category"] for item in items}
    assert "field" in categories
    assert "action" in categories
    assert "feedback" in categories


def test_api_generation_diff_flow() -> None:
    with TestClient(app) as client:
        client.post("/api/knowledge/seed")
        figma = client.post(
            "/api/figma/contexts/import-json",
            json={
                "figma_url": "https://www.figma.com/design/MOCK/App?node-id=1:1",
                "payload": {
                    "document": {
                        "id": "1:1",
                        "name": "创建活动弹窗",
                        "type": "FRAME",
                        "children": [
                            {"id": "1:2", "name": "预算上限输入框", "type": "Input"},
                            {"id": "1:3", "name": "提交按钮", "type": "Button"},
                        ],
                    }
                },
            },
        )
        assert figma.status_code == 200
        context_id = figma.json()["id"]
        generation = client.post(
            "/api/cases/generate",
            json={
                "requirement": "用户创建营销活动，需要校验预算、时间、权限和重复提交。",
                "mode": "prd_bug",
                "figma_context_id": context_id,
                "save_as_requirement": True,
                "requirement_title": "营销活动创建",
            },
        )
        assert generation.status_code == 200
        requirement_id = generation.json()["requirement_id"]
        assert requirement_id
        diff = client.post(f"/api/requirements/{requirement_id}/diff-runs", json={"target_figma_context_id": context_id})
        assert diff.status_code == 200
        run_id = diff.json()["id"]
        proposals = client.get(f"/api/diff-runs/{run_id}/proposals")
        assert proposals.status_code == 200
        items = proposals.json()["items"]
        assert items
        accepted = client.post(f"/api/proposals/{items[0]['id']}/accept")
        assert accepted.status_code == 200
        merge = client.post(f"/api/diff-runs/{run_id}/merge")
        assert merge.status_code == 200
        assert merge.json()["status"] == "completed"


def test_review_graph_and_view_state() -> None:
    with TestClient(app) as client:
        client.post("/api/knowledge/seed")
        generation = client.post(
            "/api/cases/generate",
            json={
                "requirement": "用户创建营销活动，需要校验预算、时间、权限和重复提交。",
                "mode": "prd_bug",
                "save_as_requirement": True,
                "requirement_title": "营销活动创建",
            },
        )
        requirement_id = generation.json()["requirement_id"]
        diff = client.post(f"/api/requirements/{requirement_id}/diff-runs", json={})
        run_id = diff.json()["id"]
        graph = client.get(f"/api/diff-runs/{run_id}/review-graph")
        assert graph.status_code == 200
        payload = graph.json()
        assert payload["graph"]["nodes"]
        assert any(node["type"] == "proposal" for node in payload["graph"]["nodes"])
        proposal_id = payload["table"]["proposals"][0]["id"]
        node_id = f"proposal:{proposal_id}"
        state = client.patch(
            f"/api/diff-runs/{run_id}/view-state",
            json={
                "view_mode": "mindmap",
                "selected_proposal_id": proposal_id,
                "focused_node_id": node_id,
                "node_positions": {node_id: {"x": 123, "y": 456}},
            },
        )
        assert state.status_code == 200
        restored = client.get(f"/api/diff-runs/{run_id}/view-state")
        assert restored.json()["view_mode"] == "mindmap"
        assert restored.json()["node_positions"][node_id]["x"] == 123
