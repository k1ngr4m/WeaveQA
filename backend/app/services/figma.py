from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import httpx

from ..config import get_settings


def parse_figma_url(figma_url: str) -> tuple[str, str | None]:
    parsed = urlparse(figma_url)
    match = re.search(r"/(?:file|design)/([^/]+)", parsed.path)
    if not match:
        raise ValueError("Invalid Figma URL: missing file or design key")
    file_key = match.group(1)
    query = parse_qs(parsed.query)
    node_id = query.get("node-id", [None])[0]
    return file_key, node_id


async def fetch_figma_payload(file_key: str, node_id: str | None) -> dict:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            settings.figma_mcp_server_url,
            json={"file_key": file_key, "node_id": node_id, "depth_limit": 5, "include_images": False},
        )
        response.raise_for_status()
        return response.json()


def extract_ui_items(payload: dict) -> tuple[list[dict], list[dict]]:
    root = payload.get("document") or payload.get("root") or payload
    frames: list[dict] = []
    items: list[dict] = []

    def visit(node: dict, path: list[str], depth: int) -> None:
        name = str(node.get("name") or node.get("label") or node.get("id") or "Untitled")
        node_id = str(node.get("id") or node.get("node_id") or name)
        node_type = str(node.get("type") or node.get("role") or "NODE")
        current_path = [*path, name]
        if node_type.upper() in {"FRAME", "PAGE", "CANVAS", "SECTION"} or depth == 0:
            frames.append(
                {
                    "figma_node_id": node_id,
                    "name": name,
                    "node_type": node_type,
                    "depth": depth,
                    "raw_node": node,
                    "sort_order": len(frames),
                }
            )
        category, confidence = categorize(name, node_type, node)
        if category:
            items.append(
                {
                    "figma_node_id": node_id,
                    "category": category,
                    "label": name,
                    "role": node_type,
                    "text": node.get("text") or node.get("characters") or node.get("content"),
                    "constraints": constraints_for(node, name),
                    "interaction_hint": node.get("description") or node.get("helperText"),
                    "source_path": current_path,
                    "confidence": confidence,
                }
            )
        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                visit(child, current_path, depth + 1)

    visit(root, [], 0)
    return frames, items


def categorize(name: str, node_type: str, node: dict) -> tuple[str | None, float]:
    lowered = f"{name} {node_type}".lower()
    if any(word in lowered for word in ["input", "select", "date", "switch", "upload", "输入", "选择", "日期", "开关", "上传"]):
        return "field", 0.82
    if any(word in lowered for word in ["button", "btn", "submit", "save", "按钮", "提交", "保存", "删除", "确认"]):
        return "action", 0.84
    if any(word in lowered for word in ["tab", "breadcrumb", "back", "next", "跳转", "返回", "导航"]):
        return "navigation", 0.72
    if any(word in lowered for word in ["toast", "error", "empty", "loading", "错误", "空态", "加载"]):
        return "feedback", 0.74
    if any(word in lowered for word in ["table", "list", "card", "表格", "列表", "卡片"]):
        return "data_view", 0.66
    if any(word in lowered for word in ["modal", "dialog", "drawer", "弹窗", "抽屉"]):
        return "dialog", 0.76
    return None, 0.5


def constraints_for(node: dict, name: str) -> dict:
    props = node.get("props") or node.get("componentProperties") or {}
    constraints = dict(node.get("constraints") or {})
    lowered = name.lower()
    if "required" in props or "必填" in name:
        constraints["required"] = bool(props.get("required", True))
    if "number" in lowered or "金额" in name or "预算" in name:
        constraints.setdefault("input_type", "number")
    for key in ["placeholder", "disabled", "min", "max", "maxLength"]:
        if key in props:
            constraints[key] = props[key]
    return constraints
