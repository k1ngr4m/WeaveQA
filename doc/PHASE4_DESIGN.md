# WeaveQA Phase 4 Design: 需求变更 Diff 与人工采纳闭环

| 版本 | 日期 | 状态 |
| --- | --- | --- |
| v0.1 | 2026-05-14 | 设计稿 |

## 1. 阶段目标

Phase 4 的目标是让 WeaveQA 从“生成一批测试用例”升级为“持续维护测试用例”。当 PRD、Bug 知识或 Figma UI 上下文发生变化时，系统生成变更分析，标记已有用例的 `added`、`modified`、`deleted`、`unchanged` 状态，并让 QA 人工采纳、驳回或编辑后采纳。

本阶段只做列表式 Diff 评审与合并闭环，不做 React Flow 脑图联动。脑图视图放入 Phase 5。

## 2. 核心概念

- **Requirement Baseline**：一次需求输入 + 知识库快照 + Figma 上下文快照构成的生成基线。
- **Case Version**：正式用例版本，只有评审采纳后才进入 active 状态。
- **Change Proposal**：AI 根据新旧上下文生成的候选变更，不直接覆盖正式用例。
- **Review Decision**：QA 对每条候选变更的决定：采纳、驳回、编辑后采纳。
- **Merge Run**：一次批量合并操作，产生新的用例版本号。

状态定义：

- `unchanged`：当前上下文下无需调整。
- `added`：AI 建议新增用例。
- `modified`：AI 建议修改已有用例。
- `deleted`：AI 建议作废已有用例。

评审状态：

- `pending`
- `accepted`
- `rejected`
- `edited_accepted`

## 3. 用户流程

1. QA 在一个需求工作区内完成首次生成并保存为 baseline v1。
2. 飞书 PRD 或 Figma context 被重新同步，系统发现 snapshot hash 变化。
3. QA 点击“分析变更”，或系统在同步后提示可创建 Diff run。
4. 后端读取旧 baseline、新文档快照、新 Figma context、当前 active 用例。
5. AI 输出 change proposals，每条 proposal 带 action、target case、变更原因、证据引用。
6. 前端列表展示 Diff：新增、修改、删除、无变化分组。
7. QA 逐条采纳/驳回，也可以修改 proposal 内容后采纳。
8. QA 点击“一键合并已采纳”，系统生成新的 case versions，并记录 merge run。
9. 工作区 baseline 更新到新快照，后续生成和 Diff 均基于最新 active 用例。

## 4. Diff 输入与输出

### 4.1 输入上下文

Diff engine 输入：

```json
{
  "requirement_id": "...",
  "previous_baseline_id": "...",
  "new_document_snapshot_ids": ["..."],
  "new_figma_context_id": "...",
  "active_cases": [],
  "retrieved_rag_context": [],
  "ui_context_items": []
}
```

输入原则：

- 旧 baseline 必须固定，不允许使用“当前数据库最新内容”隐式替代。
- 新上下文必须明确 snapshot id，保证 Diff 可复现。
- active cases 只包含当前有效版本，不包含 rejected proposal。
- RAG 和 Figma 引用要带 source id，供 proposal 追溯。

### 4.2 输出契约

AI 输出必须符合强类型结构：

```json
{
  "run_summary": {
    "change_level": "minor|major|breaking",
    "reason": "需求增加预算精度和重复提交限制",
    "affected_modules": ["金额精度", "异常流"]
  },
  "proposals": [
    {
      "id": "generated-by-server",
      "action": "modified",
      "target_case_id": "case-v1-id",
      "module": "金额精度",
      "title": "预算金额精度与极值校验",
      "before": {
        "steps": ["输入 0、最大允许值和超出上限金额"],
        "expected_result": "非法值被阻止"
      },
      "after": {
        "steps": ["输入 0、0.01、最大允许值和超出上限金额"],
        "expected_result": "0.01 不被四舍五入，非法值被阻止"
      },
      "change_reason": "历史 Bug 指出 0.01 元精度丢失",
      "evidence": [
        {
          "source_type": "bug",
          "source_id": "chunk-id",
          "quote": "预算上限输入 0.01 元时被错误四舍五入为 0"
        }
      ],
      "confidence": 0.86
    }
  ]
}
```

约束：

- `added` 不允许有 `target_case_id`。
- `modified` 和 `deleted` 必须有 `target_case_id`。
- `unchanged` 可不展示为 proposal，但需要计入 run summary。
- 每条非 unchanged proposal 至少有一个 evidence。
- confidence 低于 0.6 的 proposal 默认折叠并标记“需重点复核”。

## 5. 后端能力设计

### 5.1 Diff Engine

步骤：

1. 读取旧 baseline 和新 snapshot。
2. 计算文档层 hash diff，定位 changed parent chunks。
3. 基于 changed chunks 检索相关 active cases。
4. 合并 Figma context 差异，识别 UI item 新增/删除/约束变化。
5. 构建 LLM prompt，要求输出 typed JSON。
6. 使用 Pydantic 校验输出。
7. 做 deterministic post-check：
   - action 与 target case 合法性。
   - evidence 是否存在。
   - `added` 与已有 case 标题相似度过高时标记 duplicate risk。
   - `deleted` confidence 低于 0.75 时要求人工二次确认。
8. 保存 diff run 和 proposals。

### 5.2 合并策略

合并只处理 accepted 和 edited_accepted proposals：

- `added`：创建新 case，version=1，status=`active`。
- `modified`：旧 case version status=`superseded`，创建新 version，version+1，status=`active`。
- `deleted`：旧 case version status=`deprecated`，保留历史版本。
- `rejected`：不影响 active cases，只保留审计记录。

合并必须是事务：

- 任意 proposal 合并失败，整个 merge run 回滚。
- merge run 成功后，更新 requirement baseline 指向新 snapshot。

### 5.3 版本号

用例版本使用单 case 自增版本：

- `case_group_id` 表示同一逻辑用例。
- `version` 从 1 开始递增。
- `id` 表示具体版本。
- 前端展示 `TC-102 v3`。

## 6. 数据库设计

PostgreSQL 增量表：

```sql
CREATE TABLE requirements (
  id UUID PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  current_baseline_id UUID,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE requirement_baselines (
  id UUID PRIMARY KEY,
  requirement_id UUID NOT NULL REFERENCES requirements(id),
  version INTEGER NOT NULL,
  requirement_hash TEXT NOT NULL,
  document_snapshot_ids UUID[] NOT NULL DEFAULT '{}',
  figma_context_id UUID,
  rag_context_hash TEXT,
  created_from_run_id UUID,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE test_case_versions (
  id UUID PRIMARY KEY,
  case_group_id UUID NOT NULL,
  requirement_id UUID NOT NULL REFERENCES requirements(id),
  baseline_id UUID REFERENCES requirement_baselines(id),
  version INTEGER NOT NULL,
  status TEXT NOT NULL,
  module TEXT NOT NULL,
  title TEXT NOT NULL,
  preconditions TEXT,
  steps JSONB NOT NULL DEFAULT '[]',
  expected_result TEXT NOT NULL,
  priority TEXT NOT NULL,
  related_risks JSONB NOT NULL DEFAULT '[]',
  citations JSONB NOT NULL DEFAULT '[]',
  ui_coverage_tags TEXT[] NOT NULL DEFAULT '{}',
  figma_citations JSONB NOT NULL DEFAULT '[]',
  source_mix TEXT NOT NULL DEFAULT 'rag',
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE diff_runs (
  id UUID PRIMARY KEY,
  requirement_id UUID NOT NULL REFERENCES requirements(id),
  previous_baseline_id UUID NOT NULL REFERENCES requirement_baselines(id),
  target_document_snapshot_ids UUID[] NOT NULL DEFAULT '{}',
  target_figma_context_id UUID,
  status TEXT NOT NULL,
  change_level TEXT,
  summary TEXT,
  affected_modules TEXT[] NOT NULL DEFAULT '{}',
  error TEXT,
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ
);

CREATE TABLE case_change_proposals (
  id UUID PRIMARY KEY,
  diff_run_id UUID NOT NULL REFERENCES diff_runs(id),
  action TEXT NOT NULL,
  target_case_id UUID REFERENCES test_case_versions(id),
  review_status TEXT NOT NULL DEFAULT 'pending',
  module TEXT NOT NULL,
  title TEXT NOT NULL,
  before_payload JSONB,
  after_payload JSONB,
  change_reason TEXT NOT NULL,
  evidence JSONB NOT NULL DEFAULT '[]',
  confidence NUMERIC(4, 3) NOT NULL,
  duplicate_risk BOOLEAN NOT NULL DEFAULT FALSE,
  reviewer_note TEXT,
  reviewed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE merge_runs (
  id UUID PRIMARY KEY,
  diff_run_id UUID NOT NULL REFERENCES diff_runs(id),
  requirement_id UUID NOT NULL REFERENCES requirements(id),
  status TEXT NOT NULL,
  merged_proposal_ids UUID[] NOT NULL DEFAULT '{}',
  new_baseline_id UUID,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ
);
```

## 7. 后端 API

新增 API：

- `POST /api/requirements`
- `GET /api/requirements/{requirement_id}`
- `POST /api/requirements/{requirement_id}/baselines`
- `GET /api/requirements/{requirement_id}/cases`
- `POST /api/requirements/{requirement_id}/diff-runs`
- `GET /api/diff-runs/{diff_run_id}`
- `GET /api/diff-runs/{diff_run_id}/proposals`
- `PATCH /api/proposals/{proposal_id}`
- `POST /api/proposals/{proposal_id}/accept`
- `POST /api/proposals/{proposal_id}/reject`
- `POST /api/proposals/{proposal_id}/edit-and-accept`
- `POST /api/diff-runs/{diff_run_id}/merge`

改造 API：

- `POST /api/cases/generate`：可选择保存为 requirement baseline v1。
- `POST /api/reviews`：评审记录关联 requirement、baseline、case version。

## 8. 前端设计

新增“变更评审”视图，仍保持 Claude/Anthropic 风格的工作台气质。

页面结构：

- 左侧：需求 baseline 信息、快照版本、变更摘要。
- 顶部：Diff run 状态、change level、影响模块、合并按钮。
- 主区：proposal 列表，按 added/modified/deleted/low confidence 分组。
- 右侧：证据面板，展示 PRD/Bug/Figma 引用。

列表 Diff 呈现：

- `added`：整行绿色左边框，展示新用例完整内容。
- `modified`：before/after 双行对比，旧内容 muted/red，新内容 green。
- `deleted`：旧用例灰色 + 删除原因，采纳前必须二次确认。
- `unchanged`：默认折叠，只在 summary 显示数量。

操作：

- 单条采纳
- 单条驳回
- 编辑后采纳
- 批量采纳高置信度 proposals
- 合并已采纳

## 9. Prompt 与安全阈值

Prompt 必须强调：

- 不允许直接删除低置信度用例。
- 不能因为措辞不同就生成 modified。
- 只有需求、Bug 或 UI 约束发生可测试行为变化时才生成 proposal。
- 每条 proposal 必须说明测试影响。

安全阈值：

- `deleted` proposal confidence < 0.75：禁止批量采纳。
- `modified` proposal confidence < 0.6：默认折叠，要求人工展开。
- duplicate_risk=true 的 `added` proposal：禁止批量采纳。
- evidence 缺失：proposal 标记 invalid，不进入可采纳列表。

## 10. 错误处理

- 旧 baseline 不存在：禁止创建 diff run。
- 新 snapshot 与旧 baseline 完全一致：创建 completed run，summary 显示无变化，不生成 proposals。
- LLM JSON 校验失败：run 状态 failed，保留原始错误摘要。
- 合并时 active case 已被其他 merge run 更新：返回版本冲突，要求刷新 diff。
- 部分 proposal 被驳回不影响合并其他已采纳 proposal。

## 11. 验收标准

- 首次生成的用例可以保存为 requirement baseline v1。
- 修改 PRD snapshot 或 Figma context 后，可以创建 diff run。
- Diff run 能生成 added、modified、deleted 至少三类 proposal。
- 每条 proposal 都展示 action、原因、confidence 和 evidence。
- QA 可以采纳、驳回、编辑后采纳单条 proposal。
- 合并已采纳 proposals 后，active cases 版本正确更新。
- rejected proposal 不影响 active cases。
- deleted proposal 只把旧 case 标记 deprecated，不物理删除。
- 版本冲突时不会覆盖较新的 active case。

## 12. 实施顺序

1. 新增 requirement、baseline、case version 表。
2. 将当前生成结果支持保存为 baseline v1。
3. 新增 diff run 与 proposal 表。
4. 实现 deterministic 文档 hash diff 和相关 case 定位。
5. 实现 LLM diff prompt、Pydantic 校验和 post-check。
6. 实现 proposal 采纳/驳回/编辑后采纳 API。
7. 实现 merge transaction 和版本更新。
8. 前端新增变更评审列表视图。
9. 增加 baseline 不存在、无变化、JSON 校验失败、版本冲突测试。
