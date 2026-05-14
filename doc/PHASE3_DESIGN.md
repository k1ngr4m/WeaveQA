# WeaveQA Phase 3 Design: Figma MCP 与 UI 上下文融合

| 版本 | 日期 | 状态 |
| --- | --- | --- |
| v0.1 | 2026-05-14 | 设计稿 |

## 1. 阶段目标

Phase 3 的目标是把 Figma 设计稿转化为可追溯的 UI 测试上下文，并与 Phase 2 的 PRD/Bug 知识库一起输入用例生成流程。生成结果要能覆盖 UI 字段校验、按钮状态、页面跳转、组件可见性、空态/错误态和历史 Bug 回归点。

本阶段不做需求变更 Diff、脑图评审、截图视觉回归和复杂设计稿标注协作。Figma MCP 失败时，系统必须允许用户上传 UI 摘要 JSON 或手动描述作为兜底。

## 2. 用户流程

1. QA 在需求输入区绑定 Figma URL，可选择 frame/page。
2. 后端调用 Figma MCP 获取文件、页面、frame、组件树和节点属性。
3. 系统提取 UI 上下文：表单字段、按钮、导航目标、弹窗、表格列、状态文案、输入约束和可交互节点。
4. 前端展示“UI 上下文预览”，QA 可以排除无关 frame 或标记关键节点。
5. 生成用例时，后端同时读取 PRD/Bug RAG 召回结果和 Figma UI 上下文。
6. 用例结果新增 UI 来源引用，例如 `Figma: 创建活动弹窗 / 预算上限输入框`。
7. 质量评审新增 UI 覆盖指标：字段覆盖、交互覆盖、状态覆盖。

## 3. 功能设计

### 3.1 Figma 绑定

支持输入：

- Figma file URL。
- Figma frame URL，包含 `node-id`。
- 手动上传 UI context JSON，作为无 MCP 环境兜底。

绑定字段：

- `id`
- `requirement_id`
- `figma_url`
- `file_key`
- `node_id`
- `selected_frame_ids`
- `status`: `ready`、`fetching`、`parsed`、`failed`
- `last_synced_at`
- `last_error`

URL 解析规则：

- 从 `/file/{file_key}` 或 `/design/{file_key}` 中解析 file key。
- 从 query 的 `node-id` 解析 frame/node id。
- 如果没有 node id，默认拉取文件第一页 frame 列表，让用户选择。

### 3.2 MCP 客户端

后端新增 `figma_mcp_client` 服务，统一封装 MCP 调用。

输入：

- `file_key`
- `node_id`
- `depth_limit`
- `include_images=false`

输出标准化为 `FigmaNode`：

```json
{
  "id": "1:23",
  "name": "预算上限输入框",
  "type": "TEXT_FIELD",
  "visible": true,
  "text": "预算上限",
  "component_name": "Input",
  "props": {
    "placeholder": "请输入预算",
    "disabled": false,
    "required": true
  },
  "constraints": {
    "input_type": "number",
    "min": 0.01,
    "max": 999999
  },
  "children": []
}
```

MCP 返回结构不稳定时，转换层只保留确定字段；不确定字段放入 `raw_node` JSONB，不进入 prompt 主上下文。

### 3.3 UI 上下文提取

从组件树提取以下 context items：

- `field`: 输入框、选择器、日期控件、开关、上传控件。
- `action`: 主按钮、次按钮、危险操作、链接。
- `navigation`: tab、面包屑、跳转按钮、返回入口。
- `feedback`: toast、error text、empty state、loading state。
- `data_view`: 表格、列表、卡片、统计指标。
- `dialog`: 弹窗、抽屉、确认框。

每个 item 字段：

- `id`
- `figma_node_id`
- `frame_name`
- `category`
- `label`
- `role`
- `text`
- `constraints`
- `interaction_hint`
- `source_path`
- `confidence`

提取规则：

- 名称含 input/select/date/switch/upload 或中文“输入/选择/日期/开关/上传”时归为 `field`。
- 名称含 button/btn 或中文“按钮/提交/保存/删除/确认”时归为 `action`。
- 组件含 disabled、required、placeholder、min/max、maxLength 时写入 constraints。
- 相邻错误文案或说明文案合并进同一 field 的 `interaction_hint`。
- 置信度低于 0.55 的 item 在前端标记为“需确认”。

### 3.4 Prompt 融合策略

生成接口保持 `POST /api/cases/generate`，新增可选字段：

```json
{
  "requirement": "...",
  "mode": "prd_bug",
  "figma_context_id": "...",
  "generation_strategy": ["functional", "boundary", "ui_interaction"]
}
```

上下文拼装顺序：

1. 当前需求文本。
2. PRD/Bug RAG 召回结果。
3. Figma UI context items，按 frame 和 category 分组。
4. 生成约束：每条 UI 相关用例必须引用至少一个 Figma item。

生成结果新增字段：

- `ui_coverage_tags`: `field`、`action`、`navigation`、`feedback`、`data_view`、`dialog`
- `figma_citations`: `frame_name / node_label / node_id`
- `source_mix`: `requirement_only`、`rag`、`figma`、`rag_figma`

### 3.5 前端交互

在现有工作台新增“UI 上下文”面板：

- Figma URL 输入框。
- 拉取/刷新按钮。
- frame 选择列表。
- UI context cards，按 field/action/navigation/feedback 分组。
- 每个 item 支持 include/exclude 切换。
- 低置信度 item 显示 amber 状态。
- 生成结果表新增 “UI 覆盖”列，展示 Figma citations 和 coverage tags。

视觉继续沿用 Claude/Anthropic 风格：

- UI context 面板可使用深色工作区，像代码/证据面板。
- 分类标签使用低饱和 teal/amber/coral。
- 不做 Figma 缩略图画廊，避免工作台变成设计资产浏览器。

## 4. 数据库设计

PostgreSQL 增量表：

```sql
CREATE TABLE figma_contexts (
  id UUID PRIMARY KEY,
  requirement_id UUID,
  figma_url TEXT NOT NULL,
  file_key TEXT NOT NULL,
  node_id TEXT,
  status TEXT NOT NULL DEFAULT 'ready',
  selected_frame_ids TEXT[] NOT NULL DEFAULT '{}',
  raw_payload JSONB,
  parsed_summary JSONB,
  last_synced_at TIMESTAMPTZ,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE figma_frames (
  id UUID PRIMARY KEY,
  context_id UUID NOT NULL REFERENCES figma_contexts(id),
  figma_node_id TEXT NOT NULL,
  name TEXT NOT NULL,
  node_type TEXT NOT NULL,
  depth INTEGER NOT NULL DEFAULT 0,
  raw_node JSONB,
  sort_order INTEGER NOT NULL
);

CREATE TABLE ui_context_items (
  id UUID PRIMARY KEY,
  context_id UUID NOT NULL REFERENCES figma_contexts(id),
  frame_id UUID REFERENCES figma_frames(id),
  figma_node_id TEXT NOT NULL,
  category TEXT NOT NULL,
  label TEXT NOT NULL,
  role TEXT,
  text TEXT,
  constraints JSONB NOT NULL DEFAULT '{}',
  interaction_hint TEXT,
  source_path TEXT[] NOT NULL DEFAULT '{}',
  confidence NUMERIC(4, 3) NOT NULL DEFAULT 0.5,
  included BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL
);
```

测试用例结果表在 Phase 3 可先不持久化；若 Phase 2 已实现 generation 持久化，则追加：

```sql
ALTER TABLE generated_cases ADD COLUMN ui_coverage_tags TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE generated_cases ADD COLUMN figma_citations JSONB NOT NULL DEFAULT '[]';
ALTER TABLE generated_cases ADD COLUMN source_mix TEXT NOT NULL DEFAULT 'rag';
```

## 5. 后端 API

新增 API：

- `POST /api/figma/contexts`
- `GET /api/figma/contexts/{context_id}`
- `POST /api/figma/contexts/{context_id}/sync`
- `GET /api/figma/contexts/{context_id}/frames`
- `GET /api/figma/contexts/{context_id}/items`
- `PATCH /api/figma/items/{item_id}`
- `POST /api/figma/contexts/import-json`

改造 API：

- `POST /api/cases/generate`：支持 `figma_context_id` 和 `generation_strategy`。
- `POST /api/reviews`：支持 UI 覆盖指标，可选保存 `field_coverage`、`action_coverage`、`state_coverage`。

## 6. 服务拆分

新增模块：

- `services/figma_url.py`: 解析 file key 与 node id。
- `services/figma_mcp_client.py`: MCP 连接、请求、错误转换。
- `services/ui_context_extractor.py`: 组件树到 UI context items。
- `services/context_fusion.py`: PRD/Bug RAG + Figma context prompt 拼装。
- `api/figma.py`: Figma context routers。

关键原则：

- MCP 原始响应只在数据库保留，不直接塞进 prompt。
- Prompt 只接收压缩后的 context items。
- Figma 同步和 RAG 检索互不阻塞；Figma 失败时允许继续生成非 UI 用例。

## 7. 错误处理与安全

- MCP 服务不可用：context 状态为 `failed`，前端提示可导入 JSON。
- Figma URL 无效：前端即时校验，后端返回结构化错误。
- 文件无权限：保留 MCP 错误码，不记录敏感 token。
- 组件树过大：默认 depth limit 为 5，超过 500 nodes 时要求选择 frame。
- 原始 payload 可能包含内部设计文案，必须只对当前项目可见；Phase 6 再补 RBAC。
- 不在前端暴露 Figma token；MCP server 凭证通过后端环境变量或本地 MCP 配置管理。

## 8. 配置项

```env
FIGMA_MCP_SERVER_URL=http://localhost:3845
FIGMA_MCP_TIMEOUT_SECONDS=20
FIGMA_MAX_NODE_COUNT=500
FIGMA_DEFAULT_DEPTH_LIMIT=5
ENABLE_FIGMA_JSON_IMPORT=true
```

## 9. 验收标准

- 输入合法 Figma frame URL 后，可以解析 file key 与 node id。
- 同步成功后，前端能展示 frames 和分类后的 UI context items。
- 至少能识别输入框、按钮、弹窗、错误文案、表格列五类元素。
- QA 可以排除无关 UI item，生成时不会引用被排除 item。
- 生成用例中出现 UI 字段校验、按钮状态、错误态/空态、导航跳转相关用例。
- 每条 UI 相关用例包含 Figma citation。
- Figma MCP 失败时，PRD/Bug RAG 生成仍可使用。
- 上传 UI context JSON 后，可以走同样的生成流程。

## 10. 实施顺序

1. 新增 Figma URL 解析和数据表。
2. 实现 JSON import 兜底能力，用静态 Figma-like payload 打通 UI context 提取。
3. 接入 Figma MCP client，标准化 `FigmaNode`。
4. 实现 UI context extractor 和 include/exclude 更新。
5. 在生成接口中加入 `figma_context_id` 和 context fusion。
6. 前端新增 UI 上下文面板和生成结果 UI 覆盖列。
7. 增加 MCP 失败、超大组件树、低置信度 item、排除 item 的测试。
8. 用真实设计稿验证字段/按钮/弹窗/错误态覆盖。
