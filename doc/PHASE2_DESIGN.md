# WeaveQA Phase 2 Design: 飞书同步与持久化知识库

| 版本 | 日期 | 状态 |
| --- | --- | --- |
| v0.1 | 2026-05-14 | 设计稿 |

## 1. 阶段目标

Phase 2 的目标是把 MVP 的内存知识库升级为真实可持续运行的知识空间：支持飞书文档同步、手动重建索引、PostgreSQL 持久化、Qdrant 向量检索，并保持现有 RAG 生成体验不变。

本阶段不做 Figma MCP、需求变更 Diff、脑图评审和企业 RBAC。已有手动文本导入继续保留，作为飞书同步失败时的兜底入口。

## 2. 用户流程

1. QA 主管在“知识空间”中新增数据源，选择飞书单篇文档或飞书文件夹。
2. 系统保存数据源配置，状态为 `pending_auth` 或 `ready`。
3. QA 点击“立即同步”，后端拉取飞书文档元信息与正文。
4. 解析器将飞书富文本转为标准 Markdown，保存原文快照和 Markdown 快照。
5. 切分任务生成 Parent/Child chunks，写入 PostgreSQL。
6. 向量任务生成 embedding，写入 Qdrant，payload 保存 chunk、document、source 信息。
7. 前端展示同步状态、文档数、chunk 数、最近错误和重建索引入口。
8. 用例生成继续使用现有三种模式，但召回来源从内存数组切换为 Qdrant + PostgreSQL。

## 3. 功能设计

### 3.1 飞书数据源

支持两类 source：

- `lark_doc`：单篇飞书文档 URL。
- `lark_folder`：飞书文件夹 URL，递归同步第一层文档；MVP 不递归多层文件夹。

数据源字段：

- `id`
- `name`
- `source_type`
- `source_url`
- `lark_node_token`
- `sync_mode`: `manual` 或 `webhook`
- `status`: `ready`、`syncing`、`failed`、`disabled`
- `last_synced_at`
- `last_error`

Phase 2 先实现手动同步。Webhook 只设计接口与验签入口，不默认启用。

### 3.2 文档与快照

每次同步保留文档快照，方便后续 Diff 和回滚：

- `knowledge_documents` 保存飞书文档的稳定身份、标题、类型、当前版本。
- `document_snapshots` 保存每次拉取的 raw payload、Markdown、内容 hash、同步批次 ID。
- 如果内容 hash 未变化，只更新 `last_seen_at`，不重建 chunks。

文档类型自动推断：

- 标题或正文包含“bug / 缺陷 / 问题 / 回归”时标为 `bug`。
- 标题或正文包含“PRD / 需求 / 产品说明”时标为 `prd`。
- 无法判断时标为 `mixed`，允许用户在前端修改。

### 3.3 解析与切分

解析输入：

- 飞书富文本 blocks
- docx/md/xlsx 手动上传在 Phase 2 可作为增强项；若时间紧，保留现有纯文本导入。

输出 Markdown 规则：

- 标题层级保留为 `#` 到 `####`。
- 表格转 Markdown table。
- mention、人员、日期保留为可读文本。
- 图片先保存占位：`[image: title/url]`，多模态解析放到后续阶段。

切分策略：

- Parent chunk：按标题层级或约 900-1200 中文字符聚合。
- Child chunk：按段落/列表项切分，目标 180-320 中文字符。
- Child payload 必须包含 `parent_id`、`document_id`、`snapshot_id`、`asset_type`、`heading_path`。

### 3.4 向量索引

Qdrant collection：`weaveqa_knowledge_chunks`

向量 payload：

- `chunk_id`
- `parent_id`
- `document_id`
- `snapshot_id`
- `source_id`
- `asset_type`
- `title`
- `heading_path`
- `text_preview`
- `content_hash`

Embedding 提供两级实现：

- 默认：本地 lightweight lexical embedding，保证离线可开发。
- 可配置：OpenAI-compatible embedding endpoint，用于真实效果验证。

召回流程：

1. 将 query 转 embedding。
2. Qdrant top_k 检索 child chunks。
3. 从 PostgreSQL 批量读取 child 与 parent 正文。
4. 对同一 parent 下的结果做去重和合并。
5. 返回给前端 `score`、`source`、`heading_path`、`child_text`、`parent_text_preview`。

### 3.5 后端 API

新增 API：

- `GET /api/sources`
- `POST /api/sources`
- `PATCH /api/sources/{source_id}`
- `POST /api/sources/{source_id}/sync`
- `GET /api/sync-runs`
- `GET /api/sync-runs/{run_id}`
- `POST /api/knowledge/documents/{document_id}/reindex`
- `GET /api/knowledge/chunks?document_id=...`
- `POST /api/webhooks/lark`

保留并改造 API：

- `GET /api/knowledge/documents`：从 PostgreSQL 读取。
- `POST /api/knowledge/documents`：继续支持手动导入。
- `POST /api/retrieval/search`：从 Qdrant 检索。
- `POST /api/cases/generate`：接口不变，内部检索实现替换。

### 3.6 前端页面

在现有 Claude/Anthropic 风格基础上扩展，不新增营销页。

新增“同步源”区域：

- 飞书 URL 输入框
- source 类型选择
- 手动同步按钮
- 状态徽标：ready/syncing/failed/disabled
- 最近同步时间和错误提示

新增“同步任务”区域：

- run ID
- 阶段：fetching、parsing、chunking、embedding、completed、failed
- 文档数、chunk 数、耗时、错误

新增“索引诊断”区域：

- 按文档查看 chunks。
- 对选中文档手动重建索引。
- 显示 Qdrant collection 状态和向量数量。

## 4. 数据库设计

PostgreSQL 表：

```sql
CREATE TABLE knowledge_sources (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_url TEXT NOT NULL,
  lark_node_token TEXT,
  sync_mode TEXT NOT NULL DEFAULT 'manual',
  status TEXT NOT NULL DEFAULT 'ready',
  last_synced_at TIMESTAMPTZ,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE knowledge_documents (
  id UUID PRIMARY KEY,
  source_id UUID REFERENCES knowledge_sources(id),
  external_id TEXT,
  title TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  current_snapshot_id UUID,
  content_hash TEXT,
  last_seen_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE document_snapshots (
  id UUID PRIMARY KEY,
  document_id UUID NOT NULL REFERENCES knowledge_documents(id),
  sync_run_id UUID,
  raw_payload JSONB,
  markdown TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE knowledge_parents (
  id UUID PRIMARY KEY,
  document_id UUID NOT NULL REFERENCES knowledge_documents(id),
  snapshot_id UUID NOT NULL REFERENCES document_snapshots(id),
  heading_path TEXT[] NOT NULL DEFAULT '{}',
  text TEXT NOT NULL,
  sort_order INTEGER NOT NULL
);

CREATE TABLE knowledge_chunks (
  id UUID PRIMARY KEY,
  parent_id UUID NOT NULL REFERENCES knowledge_parents(id),
  document_id UUID NOT NULL REFERENCES knowledge_documents(id),
  snapshot_id UUID NOT NULL REFERENCES document_snapshots(id),
  asset_type TEXT NOT NULL,
  heading_path TEXT[] NOT NULL DEFAULT '{}',
  text TEXT NOT NULL,
  token_count INTEGER NOT NULL DEFAULT 0,
  vector_status TEXT NOT NULL DEFAULT 'pending',
  sort_order INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE sync_runs (
  id UUID PRIMARY KEY,
  source_id UUID REFERENCES knowledge_sources(id),
  status TEXT NOT NULL,
  stage TEXT NOT NULL,
  documents_found INTEGER NOT NULL DEFAULT 0,
  documents_changed INTEGER NOT NULL DEFAULT 0,
  chunks_indexed INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ
);
```

## 5. 服务拆分

建议从 `backend/app/main.py` 拆成以下模块：

- `api/`: FastAPI routers。
- `models/`: Pydantic schemas 与 SQLAlchemy models。
- `services/lark_client.py`: 飞书鉴权、URL 解析、文档/文件夹拉取。
- `services/parser.py`: 飞书 block 到 Markdown。
- `services/splitter.py`: Parent/Child 切分。
- `services/vector_store.py`: Qdrant collection、upsert、search。
- `services/embedding.py`: lexical embedding 与 OpenAI-compatible embedding。
- `services/sync_service.py`: 同步编排。
- `repositories/`: PostgreSQL 读写。

Phase 2 可先用同步 HTTP 调用完成任务编排；若同步耗时超过 10 秒，再引入后台任务队列。

## 6. 错误处理与安全

- 飞书 token 缺失：source 状态为 `failed`，提示配置 Lark App ID/Secret。
- 文档无权限：sync run 标记 failed，并保留飞书错误码。
- 内容未变化：跳过解析、切分和向量写入。
- Qdrant 不可用：文档快照仍入库，chunk `vector_status=failed`，前端提示可重建索引。
- API Key、App Secret 不写入前端；通过环境变量注入。
- Webhook 验签必须在保存任何 payload 前完成。

## 7. 配置项

```env
DATABASE_URL=postgresql+psycopg://weaveqa:weaveqa@localhost:5432/weaveqa
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=weaveqa_knowledge_chunks
LARK_APP_ID=
LARK_APP_SECRET=
LARK_WEBHOOK_VERIFY_TOKEN=
EMBEDDING_PROVIDER=lexical
EMBEDDING_BASE_URL=
EMBEDDING_API_KEY=
EMBEDDING_MODEL=
```

## 8. 验收标准

- 可以创建飞书单篇文档 source，并手动同步成功。
- 同步后 PostgreSQL 中存在 source、document、snapshot、parent、chunk、sync_run 记录。
- Qdrant collection 中存在对应 chunk vectors，payload 可追溯到原文档。
- 召回调试页能展示飞书来源、标题路径、相似度和正文片段。
- 现有用例生成接口不变，PRD + Bug 模式仍能生成带引用的用例。
- 关闭 Qdrant 时，系统能保存文档快照并提示索引失败，不丢失原文。
- 同一飞书文档未变化时再次同步不会重复生成 chunks。

## 9. 实施顺序

1. 拆分后端模块，保留现有 API 行为。
2. 引入 PostgreSQL 连接、迁移脚本和 repository。
3. 将手动导入从内存迁到 PostgreSQL。
4. 引入 Qdrant collection 初始化和 lexical embedding。
5. 将检索接口切到 Qdrant + PostgreSQL。
6. 实现飞书 URL 解析和单篇文档同步。
7. 实现 source/sync run 前端面板。
8. 补充文件夹同步和 webhook 验签入口。
9. 增加同步失败、Qdrant 失败、内容未变化的测试。
