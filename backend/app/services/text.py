from __future__ import annotations

from collections import Counter
import hashlib
import re


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tokenize(text: str) -> Counter[str]:
    lowered = text.lower()
    words = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", lowered)
    bigrams = [f"{words[index]}{words[index + 1]}" for index in range(max(len(words) - 1, 0))]
    return Counter(words + bigrams)


def infer_asset_type(title: str, content: str) -> str:
    haystack = f"{title}\n{content}".lower()
    if any(keyword in haystack for keyword in ["bug", "缺陷", "问题", "回归"]):
        return "bug"
    if any(keyword in haystack for keyword in ["prd", "需求", "产品说明"]):
        return "prd"
    return "mixed"


def split_parent_child(markdown: str) -> list[dict[str, object]]:
    paragraphs = [part.strip() for part in re.split(r"\n{2,}|[。；;]", markdown) if part.strip()]
    if not paragraphs:
        paragraphs = [markdown.strip()]
    parents: list[dict[str, object]] = []
    parent_buffer: list[str] = []
    length = 0
    for paragraph in paragraphs:
        parent_buffer.append(paragraph)
        length += len(paragraph)
        if length >= 500:
            parents.append(_parent_payload(parent_buffer, len(parents)))
            parent_buffer = []
            length = 0
    if parent_buffer:
        parents.append(_parent_payload(parent_buffer, len(parents)))
    return parents


def _parent_payload(paragraphs: list[str], index: int) -> dict[str, object]:
    text = "。".join(paragraphs)
    children: list[str] = []
    child_buffer: list[str] = []
    child_length = 0
    for paragraph in paragraphs:
        child_buffer.append(paragraph)
        child_length += len(paragraph)
        if child_length >= 160:
            children.append("。".join(child_buffer))
            child_buffer = []
            child_length = 0
    if child_buffer:
        children.append("。".join(child_buffer))
    return {"heading_path": [f"Section {index + 1}"], "text": text, "children": children}


def blocks_to_markdown(payload: dict) -> str:
    blocks = payload.get("blocks") or payload.get("items") or []
    lines: list[str] = []
    for block in blocks:
        block_type = str(block.get("type") or block.get("block_type") or "text").lower()
        text = (
            block.get("text")
            or block.get("content")
            or block.get("plain_text")
            or block.get("name")
            or ""
        )
        if isinstance(text, dict):
            text = text.get("text") or text.get("content") or ""
        if not text:
            continue
        if "heading" in block_type or block_type in {"1", "2", "3"}:
            level = 2 if block_type == "2" else 1
            lines.append(f"{'#' * level} {text}")
        elif "table" in block_type:
            lines.append(str(text))
        else:
            lines.append(str(text))
    return "\n\n".join(lines) if lines else str(payload.get("markdown") or payload.get("content") or "")
