# WeaveQA Phase 5 Design: 列表 Diff + React Flow 脑图联动评审

| 版本 | 日期 | 状态 |
| --- | --- | --- |
| v0.1 | 2026-05-14 | 设计稿 |

## 1. 阶段目标

Phase 5 的目标是把 Phase 4 的列表式变更评审升级为“双视图联动评审”：QA 可以在表格中精确查看 before/after Diff，也可以在脑图中从模块、风险、用户路径维度理解整批用例变化。两个视图共享同一批 proposal、review status 和 selection state。

本阶段不改变 Phase 4 的合并语义：采纳、驳回、编辑后采纳、合并仍然只作用于 `case_change_proposals` 和 `test_case_versions`。脑图只是评审视图和编辑入口，不引入新的业务真相来源。

## 2. 用户流程

1. QA 打开某个 Diff run，默认进入列表视图。
2. 左侧列表显示 proposal 分组：added、modified、deleted、low confidence。
3. QA 切换到脑图视图，看到需求根节点、模块节点、用例节点和证据节点。
4. 点击列表行时，脑图自动聚焦对应节点；点击脑图节点时，列表滚动到对应 proposal。
5. QA 在任一视图执行采纳/驳回/编辑后采纳，另一视图实时更新状态。
6. QA 可拖拽脑图节点调整局部布局；布局仅保存为视图偏好，不改变用例层级。
7. QA 合并已采纳 proposals，系统仍沿用 Phase 4 的 merge transaction。

## 3. 信息架构

### 3.1 视图模式

前端提供三个 tab：

- `table`: 详细 Diff 表格，适合逐条评审。
- `mindmap`: React Flow 脑图，适合理解影响范围。
- `split`: 左表格右脑图，适合联动评审。

默认打开 `split`，若屏幕宽度小于 1100px，默认 `table`。

### 3.2 脑图节点类型

React Flow 节点：

- `requirement`: 需求根节点。
- `module`: 模块/功能域节点。
- `case`: 用例节点。
- `proposal`: 变更 proposal 节点。
- `evidence`: PRD/Bug/Figma 引用证据节点。

节点颜色：

- `added`: 绿色边框。
- `modified`: amber 边框。
- `deleted`: coral/red 边框。
- `unchanged`: muted 边框。
- `accepted`: 节点右上角 check 状态。
- `rejected`: 节点半透明。
- `low confidence`: 节点左侧 amber 标记。

### 3.3 边类型

React Flow edges：

- `contains`: requirement -> module -> case/proposal。
- `changes`: proposal -> target case。
- `evidenced_by`: proposal -> evidence。
- `supersedes`: modified proposal -> old case。

所有 edge 都只表达视图关系，不写回业务状态。

## 4. 数据契约

新增后端聚合接口：

`GET /api/diff-runs/{diff_run_id}/review-graph`

返回：

```json
{
  "diff_run": {
    "id": "...",
    "summary": "...",
    "change_level": "minor",
    "affected_modules": ["金额精度", "UI 字段校验"]
  },
  "table": {
    "groups": [
      {
        "action": "modified",
        "count": 3,
        "proposal_ids": ["..."]
      }
    ],
    "proposals": []
  },
  "graph": {
    "nodes": [
      {
        "id": "proposal:...",
        "type": "proposal",
        "position": {"x": 420, "y": 160},
        "data": {
          "proposal_id": "...",
          "action": "modified",
          "review_status": "pending",
          "title": "预算金额精度与极值校验",
          "confidence": 0.86
        }
      }
    ],
    "edges": [
      {
        "id": "edge:proposal:case",
        "source": "proposal:...",
        "target": "case:...",
        "type": "changes"
      }
    ]
  },
  "selection": {
    "selected_proposal_id": null,
    "focused_node_id": null
  }
}
```

### 4.1 布局持久化

新增轻量表：

```sql
CREATE TABLE review_view_states (
  id UUID PRIMARY KEY,
  diff_run_id UUID NOT NULL REFERENCES diff_runs(id),
  user_key TEXT NOT NULL DEFAULT 'default',
  view_mode TEXT NOT NULL DEFAULT 'split',
  selected_proposal_id UUID,
  focused_node_id TEXT,
  node_positions JSONB NOT NULL DEFAULT '{}',
  collapsed_groups JSONB NOT NULL DEFAULT '[]',
  updated_at TIMESTAMPTZ NOT NULL
);
```

Phase 5 先使用 `user_key='default'`，Phase 6 RBAC 后再替换为真实用户 ID。

新增 API：

- `GET /api/diff-runs/{diff_run_id}/review-graph`
- `GET /api/diff-runs/{diff_run_id}/view-state`
- `PATCH /api/diff-runs/{diff_run_id}/view-state`

## 5. 前端设计

### 5.1 页面布局

新增 `DiffReviewWorkspace`：

- 顶部 toolbar：view mode tabs、proposal counts、批量采纳、合并按钮。
- 左侧 table pane：分组列表、before/after diff、证据摘要。
- 右侧 graph pane：React Flow canvas、mini map、zoom controls。
- 右边 drawer：选中 proposal 的详情编辑面板。

设计风格：

- 延续暖色 canvas 与深色证据面板。
- 脑图画布不放在厚重卡片里，使用全宽工作区面板。
- 节点圆角不超过 8px。
- 图上按钮优先用图标，悬浮 tooltip 显示含义。

### 5.2 列表联动

状态来源：

- `selectedProposalId`
- `focusedNodeId`
- `viewMode`
- `collapsedGroups`

交互规则：

- 点击 proposal row：设置 `selectedProposalId`，脑图执行 fit/center 到 `proposal:{id}`。
- 点击 graph proposal node：设置 `selectedProposalId`，列表滚动到对应 row。
- 点击 evidence node：右侧 drawer 切到 evidence tab。
- 采纳/驳回成功后重新拉取 proposals 和 review graph。

### 5.3 脑图布局算法

第一版使用 deterministic layered layout，不引入复杂自动布局库：

- requirement 节点在 x=0。
- module 节点在 x=260，按模块排序垂直分布。
- case/proposal 节点在 x=560。
- evidence 节点在 x=900。
- 同模块内按 action 优先级排序：deleted、modified、added、unchanged。

用户拖拽节点后：

- 前端更新 `node_positions`。
- 500ms debounce 后 PATCH view-state。
- 后端只保存坐标，不重新计算业务关系。

## 6. 编辑与评审

### 6.1 编辑后采纳

在 drawer 中编辑 `after_payload`：

- 标题
- 前置条件
- 步骤
- 预期结果
- 优先级
- reviewer note

保存调用现有 Phase 4 API：

- `POST /api/proposals/{proposal_id}/edit-and-accept`

### 6.2 批量操作

批量采纳高置信度：

- 仅包含 `confidence >= 0.75`
- 排除 `deleted`
- 排除 `duplicate_risk=true`
- 排除 evidence 为空的 proposal

此规则与 Phase 4 安全阈值保持一致。

## 7. 后端实现

新增服务：

- `services/review_graph.py`

职责：

- 聚合 diff run、proposals、target cases、evidence。
- 生成 React Flow nodes/edges。
- 合并已保存的 node positions。
- 返回 table groups 和 graph payload。

新增模型：

- `ReviewViewState`

不修改：

- `merge_diff_run`
- `accept_proposal`
- `reject_proposal`
- `edit_and_accept`

## 8. 前端依赖

新增依赖：

- `@xyflow/react`

选择原因：

- React Flow 官方包名已迁移到 `@xyflow/react`。
- 支持节点、边、mini map、controls、拖拽与自定义节点。

## 9. 测试计划

后端测试：

- 有 proposals 时 `review-graph` 返回 requirement/module/proposal/evidence 节点。
- accepted/rejected proposal 的 graph data 状态正确。
- PATCH view-state 后再次 GET 能恢复 node positions。
- 没有 proposal 的 diff run 返回空 graph，但不报错。

前端测试/检查：

- `npm run build`。
- 打开 Diff run 后 table 与 graph 都能展示 proposal。
- 点击列表行可选中对应 graph 节点。
- 点击 graph 节点可反向选中列表行。
- 拖拽节点后刷新页面坐标保留。
- 在 drawer 编辑后采纳，列表与脑图状态同步。

## 10. 验收标准

- Diff run 页面支持 table、mindmap、split 三种视图。
- 同一 proposal 在列表和脑图中状态一致。
- 采纳、驳回、编辑后采纳可以从任一视图触发。
- React Flow 脑图能展示 requirement、module、proposal、evidence 的关系。
- 节点拖拽布局可持久化。
- 合并行为与 Phase 4 完全一致，不因视图切换产生额外业务状态。

## 11. 实施顺序

1. 新增 `ReviewViewState` 模型和 API。
2. 实现 `review_graph` 聚合服务。
3. 后端测试覆盖 graph payload 和 view-state。
4. 安装 `@xyflow/react`。
5. 前端新增 `DiffReviewWorkspace`，先实现 split 视图。
6. 增加 table/mindmap tabs、选中联动、节点拖拽保存。
7. 接入编辑 drawer 和批量高置信采纳。
8. 跑后端测试、前端构建和浏览器手测。
