import React, { useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  ArrowRight,
  BookOpen,
  Brain,
  Check,
  ChevronDown,
  Code2,
  Database,
  FilePlus2,
  Gauge,
  GitCompare,
  Layers3,
  Loader2,
  Plus,
  Search,
  Send,
  Settings2,
  Sparkles,
  Target,
  Workflow,
} from "lucide-react";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

const emptyRequirement =
  "";

const emptyFigmaJson = "{\n  \"document\": {\n    \"id\": \"\",\n    \"name\": \"\",\n    \"type\": \"FRAME\",\n    \"children\": []\n  }\n}";

function App() {
  const [health, setHealth] = useState(null);
  const [models, setModels] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [sources, setSources] = useState([]);
  const [syncRuns, setSyncRuns] = useState([]);
  const [figmaContexts, setFigmaContexts] = useState([]);
  const [uiItems, setUiItems] = useState([]);
  const [requirement, setRequirement] = useState(emptyRequirement);
  const [docTitle, setDocTitle] = useState("");
  const [docType, setDocType] = useState("mixed");
  const [docContent, setDocContent] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [figmaUrl, setFigmaUrl] = useState("");
  const [figmaJson, setFigmaJson] = useState(emptyFigmaJson);
  const [query, setQuery] = useState("");
  const [searchResult, setSearchResult] = useState([]);
  const [generation, setGeneration] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [mode, setMode] = useState("prd_bug");
  const [requirements, setRequirements] = useState([]);
  const [activeRequirement, setActiveRequirement] = useState(null);
  const [diffRun, setDiffRun] = useState(null);
  const [proposals, setProposals] = useState([]);
  const [reviewGraph, setReviewGraph] = useState(null);
  const [viewMode, setViewMode] = useState("split");
  const [selectedProposalId, setSelectedProposalId] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const totalChunks = useMemo(() => documents.reduce((sum, doc) => sum + doc.chunk_count, 0), [documents]);
  const latestFigmaContext = figmaContexts[0];

  useEffect(() => {
    bootstrap();
  }, []);

  async function request(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail ?? `Request failed: ${response.status}`);
    }
    return response.json();
  }

  async function bootstrap() {
    setBusy("bootstrap");
    setError("");
    try {
      const [healthPayload, modelPayload, docPayload, sourcePayload, runPayload] = await Promise.all([
        request("/api/health"),
        request("/api/models"),
        request("/api/knowledge/documents"),
        request("/api/sources"),
        request("/api/sync-runs"),
      ]);
      setHealth(healthPayload);
      setModels(modelPayload.items);
      setDocuments(docPayload.items);
      setSources(sourcePayload.items);
      setSyncRuns(runPayload.items);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function importKnowledge() {
    await run("import", async () => {
      const payload = await request("/api/knowledge/documents", {
        method: "POST",
        body: JSON.stringify({ title: docTitle, asset_type: docType, content: docContent }),
      });
      setDocuments((current) => [payload, ...current]);
    });
  }

  async function createSource() {
    await run("source", async () => {
      const payload = await request("/api/sources", {
        method: "POST",
        body: JSON.stringify({ name: sourceName, source_type: "lark_doc", source_url: sourceUrl }),
      });
      setSources((current) => [payload, ...current]);
    });
  }

  async function syncSource(sourceId) {
    await run("sync", async () => {
      await request(`/api/sources/${sourceId}/sync`, { method: "POST", body: "{}" });
      setSources((await request("/api/sources")).items);
      setSyncRuns((await request("/api/sync-runs")).items);
      setDocuments((await request("/api/knowledge/documents")).items);
    });
  }

  async function importFigma() {
    await run("figma", async () => {
      const payload = await request("/api/figma/contexts/import-json", {
        method: "POST",
        body: JSON.stringify({ figma_url: figmaUrl, payload: JSON.parse(figmaJson) }),
      });
      setFigmaContexts((current) => [payload, ...current]);
      setUiItems((await request(`/api/figma/contexts/${payload.id}/items`)).items);
    });
  }

  async function toggleUiItem(item) {
    await run(`ui-${item.id}`, async () => {
      const payload = await request(`/api/figma/items/${item.id}`, {
        method: "PATCH",
        body: JSON.stringify({ included: !item.included }),
      });
      setUiItems((current) => current.map((entry) => (entry.id === item.id ? payload : entry)));
    });
  }

  async function runSearch() {
    await run("search", async () => {
      const payload = await request("/api/retrieval/search", {
        method: "POST",
        body: JSON.stringify({ query, mode, top_k: 5 }),
      });
      setSearchResult(payload.items);
    });
  }

  async function generateCases(nextMode = mode, save = false) {
    setMode(nextMode);
    await run("generate", async () => {
      const payload = await request("/api/cases/generate", {
        method: "POST",
        body: JSON.stringify({
          requirement,
          mode: nextMode,
          figma_context_id: latestFigmaContext?.id,
          generation_strategy: ["functional", "boundary", "ui_interaction"],
          save_as_requirement: save,
          requirement_title: "需求用例集",
        }),
      });
      setGeneration(payload);
      setMetrics(payload.metrics);
      setSearchResult(payload.retrieved_context);
      if (payload.requirement_id) {
        setActiveRequirement({ id: payload.requirement_id, baseline_id: payload.baseline_id });
        setRequirements((current) => [{ id: payload.requirement_id, title: "需求用例集" }, ...current]);
      }
    });
  }

  async function saveReview() {
    if (!generation) return;
    await run("review", async () => {
      const payload = await request("/api/reviews", {
        method: "POST",
        body: JSON.stringify({
          generation_id: generation.id,
          coverage_score: metrics.coverage_score,
          missed_risks: metrics.missed_risks,
          bug_regression_points: metrics.bug_regression_points,
          accepted_cases: generation.cases.length,
          notes: "MVP review saved from workbench",
        }),
      });
      setMetrics(payload.metrics);
    });
  }

  async function createDiffRun() {
    if (!activeRequirement?.id) return;
    await run("diff", async () => {
      const payload = await request(`/api/requirements/${activeRequirement.id}/diff-runs`, {
        method: "POST",
        body: JSON.stringify({ target_figma_context_id: latestFigmaContext?.id }),
      });
      setDiffRun(payload);
      await refreshDiff(payload.id);
    });
  }

  async function reviewProposal(proposal, action) {
    await run(`proposal-${proposal.id}`, async () => {
      await request(`/api/proposals/${proposal.id}/${action}`, { method: "POST", body: "{}" });
      await refreshDiff(proposal.diff_run_id);
    });
  }

  async function mergeDiff() {
    if (!diffRun) return;
    await run("merge", async () => {
      await request(`/api/diff-runs/${diffRun.id}/merge`, { method: "POST", body: "{}" });
      await refreshDiff(diffRun.id);
    });
  }

  async function refreshDiff(runId) {
    const [proposalPayload, graphPayload] = await Promise.all([
      request(`/api/diff-runs/${runId}/proposals`),
      request(`/api/diff-runs/${runId}/review-graph`),
    ]);
    setProposals(proposalPayload.items);
    setReviewGraph(graphPayload);
    setViewMode(graphPayload.selection?.view_mode ?? "split");
    setSelectedProposalId(graphPayload.selection?.selected_proposal_id ?? null);
  }

  async function updateViewState(runId, patch) {
    const payload = await request(`/api/diff-runs/${runId}/view-state`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
    if (patch.view_mode) setViewMode(payload.view_mode);
    if (Object.prototype.hasOwnProperty.call(patch, "selected_proposal_id")) {
      setSelectedProposalId(payload.selected_proposal_id);
    }
    return payload;
  }

  async function run(label, fn) {
    setBusy(label);
    setError("");
    try {
      await fn();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  const modeLabel = { no_kb: "无知识库", prd_only: "仅 PRD", prd_bug: "PRD + Bug" };

  return (
    <div className="app-shell">
      <aside className="side-rail" aria-label="WeaveQA navigation">
        <div className="brand-lockup">
          <div className="brand-mark">WQ</div>
          <div>
            <strong>织策 AI</strong>
            <span>WeaveQA</span>
          </div>
        </div>
        <nav>
          <a className="active" href="#workbench"><Sparkles size={17} /> RAG 工作台</a>
          <a href="#sources"><Database size={17} /> 同步源</a>
          <a href="#figma"><Code2 size={17} /> UI 上下文</a>
          <a href="#diff"><Workflow size={17} /> 变更评审</a>
        </nav>
        <section className="rail-block">
          <p>运行状态</p>
          <strong>{health?.status ?? "checking"}</strong>
          <span>{totalChunks} chunks / {health?.requirements ?? 0} requirements</span>
        </section>
      </aside>

      <main>
        <header className="top-bar">
          <div>
            <p className="eyebrow">Phase 2-4 / Integrated Workbench</p>
            <h1>从知识同步到变更评审的测试用例工作台</h1>
          </div>
          <button className="button secondary" onClick={bootstrap}><Settings2 size={16} /> 刷新</button>
        </header>

        {error ? <div className="error-strip">{error}</div> : null}

        <section className="metric-strip">
          <Metric icon={<BookOpen />} label="知识文档" value={documents.length} />
          <Metric icon={<Brain />} label="模型路由" value={models.length} />
          <Metric icon={<Target />} label="覆盖评分" value={metrics ? `${metrics.coverage_score}%` : "--"} />
          <Metric icon={<GitCompare />} label="Diff Proposals" value={proposals.length} />
        </section>

        <section className="workspace-grid" id="workbench">
          <Panel className="input-panel" title="需求输入" icon={<FilePlus2 size={18} />}>
            <textarea value={requirement} onChange={(event) => setRequirement(event.target.value)} rows={9} />
            <div className="segmented">
              {Object.entries(modeLabel).map(([value, label]) => (
                <button key={value} className={mode === value ? "selected" : ""} onClick={() => generateCases(value)}>
                  {label}
                </button>
              ))}
            </div>
            <div className="action-row">
              <button className="button primary" disabled={busy === "generate"} onClick={() => generateCases(mode)}>
                {busy === "generate" ? <Loader2 className="spin" size={16} /> : <Send size={16} />} 生成
              </button>
              <button className="button secondary" disabled={busy === "generate"} onClick={() => generateCases(mode, true)}>
                <Check size={16} /> 生成并保存 Baseline
              </button>
            </div>
          </Panel>

          <Panel className="dark-panel" title="召回上下文" icon={<Search size={18} />}>
            <div className="search-row">
              <input value={query} onChange={(event) => setQuery(event.target.value)} />
              <button className="icon-button" onClick={runSearch} aria-label="检索">
                {busy === "search" ? <Loader2 className="spin" size={16} /> : <Search size={16} />}
              </button>
            </div>
            <div className="context-list">
              {searchResult.length ? searchResult.map((item) => <ContextItem key={item.chunk_id} item={item} />) : <p className="empty-state">No retrieved context</p>}
            </div>
          </Panel>
        </section>

        <section className="two-column" id="sources">
          <Panel title="知识导入与飞书 Source" icon={<Plus size={18} />}>
            <div className="form-row">
              <input value={docTitle} onChange={(event) => setDocTitle(event.target.value)} />
              <label className="select-wrap">
                <select value={docType} onChange={(event) => setDocType(event.target.value)}>
                  <option value="mixed">PRD + Bug</option>
                  <option value="prd">历史 PRD</option>
                  <option value="bug">历史 Bug</option>
                </select>
                <ChevronDown size={15} />
              </label>
            </div>
            <textarea value={docContent} onChange={(event) => setDocContent(event.target.value)} rows={5} />
            <div className="action-row">
              <button className="button primary" onClick={importKnowledge}><Database size={16} /> 手动导入</button>
            </div>
            <div className="divider" />
            <input value={sourceName} onChange={(event) => setSourceName(event.target.value)} />
            <input value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} />
            <button className="button secondary wide" onClick={createSource}><Plus size={16} /> 新增飞书 Source</button>
          </Panel>

          <Panel title="同步源与任务" icon={<Database size={18} />}>
            <div className="document-list">
              {sources.map((source) => (
                <article key={source.id} className="document-row">
                  <div><strong>{source.name}</strong><span>{source.source_type} / {source.status}</span></div>
                  <button className="mini-button" onClick={() => syncSource(source.id)}>同步</button>
                </article>
              ))}
              {documents.map((doc) => (
                <article key={doc.id} className="document-row">
                  <div><strong>{doc.title}</strong><span>{doc.asset_type} / {doc.chunk_count} chunks</span></div>
                  <code>{doc.id.slice(0, 8)}</code>
                </article>
              ))}
              {syncRuns.slice(0, 3).map((run) => (
                <article key={run.id} className="document-row muted-row">
                  <div><strong>{run.stage}</strong><span>{run.status} / {run.chunks_indexed} chunks</span></div>
                  <code>{run.id.slice(0, 8)}</code>
                </article>
              ))}
            </div>
          </Panel>
        </section>

        <section className="two-column" id="figma">
          <Panel className="dark-panel" title="Figma JSON / MCP 兜底导入" icon={<Code2 size={18} />}>
            <input value={figmaUrl} onChange={(event) => setFigmaUrl(event.target.value)} />
            <textarea value={figmaJson} onChange={(event) => setFigmaJson(event.target.value)} rows={11} />
            <button className="button primary wide" onClick={importFigma}><Code2 size={16} /> 导入 UI 上下文</button>
          </Panel>
          <Panel title="UI Context Items" icon={<Layers3 size={18} />}>
            <div className="tag-cloud">
              {uiItems.map((item) => (
                <button key={item.id} className={`context-chip ${item.included ? "included" : ""}`} onClick={() => toggleUiItem(item)}>
                  <span>{item.category}</span>{item.label}
                </button>
              ))}
            </div>
          </Panel>
        </section>

        <Results generation={generation} metrics={metrics} saveReview={saveReview} />

        <DiffReviewWorkspace
          diffRun={diffRun}
          graph={reviewGraph}
          proposals={proposals}
          viewMode={viewMode}
          selectedProposalId={selectedProposalId}
          disabled={!activeRequirement}
          onAnalyze={createDiffRun}
          onMerge={mergeDiff}
          onReview={reviewProposal}
          onSelect={async (proposalId) => {
            setSelectedProposalId(proposalId);
            if (diffRun) await updateViewState(diffRun.id, { selected_proposal_id: proposalId, focused_node_id: `proposal:${proposalId}` });
          }}
          onViewMode={async (mode) => {
            setViewMode(mode);
            if (diffRun) await updateViewState(diffRun.id, { view_mode: mode });
          }}
          onNodeDrag={async (positions) => {
            if (diffRun) await updateViewState(diffRun.id, { node_positions: positions });
          }}
        />
      </main>
    </div>
  );
}

function Results({ generation, metrics, saveReview }) {
  return (
    <section className="results-panel" id="evaluation">
      <div className="section-heading">
        <div><p className="eyebrow">Generated Cases</p><h2>结构化用例与来源引用</h2></div>
        <button className="button secondary" onClick={saveReview} disabled={!generation}><Check size={16} /> 保存评审</button>
      </div>
      {generation ? (
        <>
          <div className="case-table">
            <div className="table-head"><span>模块</span><span>用例</span><span>优先级</span><span>来源</span></div>
            {generation.cases.map((testCase) => (
              <article key={testCase.id} className="case-row">
                <span>{testCase.module}</span>
                <div>
                  <strong>{testCase.title}</strong>
                  <p>{testCase.preconditions}</p>
                  <ol>{testCase.steps.map((step) => <li key={step}>{step}</li>)}</ol>
                  <p className="expected">{testCase.expected_result}</p>
                  {testCase.ui_coverage_tags?.length ? <p className="ui-tags">{testCase.ui_coverage_tags.join(" / ")}</p> : null}
                </div>
                <span className={`priority ${testCase.priority.toLowerCase()}`}>{testCase.priority}</span>
                <div className="citation-stack">
                  {testCase.citations.map((citation) => <code key={citation}>{citation}</code>)}
                  {testCase.figma_citations?.map((citation) => <code key={citation.node_id}>Figma:{citation.label}</code>)}
                </div>
              </article>
            ))}
          </div>
          <div className="review-band">
            <Metric icon={<Target />} label="覆盖评分" value={`${metrics.coverage_score}%`} />
            <Metric icon={<Gauge />} label="遗漏风险" value={metrics.missed_risks} />
            <Metric icon={<Code2 />} label="UI Items" value={metrics.ui_items ?? 0} />
          </div>
        </>
      ) : <div className="empty-results"><ArrowRight size={20} /><span>Run generation to populate the review table.</span></div>}
    </section>
  );
}

function Metric({ icon, label, value }) {
  return <article className="metric"><div>{icon}</div><span>{label}</span><strong>{value}</strong></article>;
}

function Panel({ title, icon, children, className = "" }) {
  return <section className={`panel ${className}`}><div className="panel-title">{icon}<h2>{title}</h2></div>{children}</section>;
}

function ContextItem({ item }) {
  return <article className="context-item"><div><strong>{item.title}</strong><span>{Math.round(item.score * 100)}%</span></div><p>{item.text}</p><code>{item.asset_type} / {item.chunk_id.slice(0, 8)}</code></article>;
}

const nodeTypes = {
  requirement: ReviewNode,
  module: ReviewNode,
  case: ReviewNode,
  proposal: ReviewNode,
  evidence: ReviewNode,
};

function DiffReviewWorkspace({
  diffRun,
  graph,
  proposals,
  viewMode,
  selectedProposalId,
  disabled,
  onAnalyze,
  onMerge,
  onReview,
  onSelect,
  onViewMode,
  onNodeDrag,
}) {
  const selectedProposal = proposals.find((proposal) => proposal.id === selectedProposalId);
  const nodes = useMemo(() => {
    const graphNodes = graph?.graph?.nodes ?? [];
    return graphNodes.map((node) => ({
      ...node,
      selected: node.data?.proposal_id === selectedProposalId,
      data: {
        ...node.data,
        nodeType: node.type,
        selected: node.data?.proposal_id === selectedProposalId,
      },
    }));
  }, [graph, selectedProposalId]);
  const edges = useMemo(() => (graph?.graph?.edges ?? []).map((edge) => ({ ...edge, animated: edge.type === "changes" })), [graph]);

  function handleNodeClick(_event, node) {
    if (node.data?.proposal_id) onSelect(node.data.proposal_id);
  }

  function handleNodeDragStop(_event, _node, allNodes) {
    const positions = {};
    for (const node of allNodes) positions[node.id] = node.position;
    onNodeDrag(positions);
  }

  return (
    <section className="results-panel diff-workspace" id="diff">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Diff Review</p>
          <h2>列表 Diff + 脑图联动评审</h2>
        </div>
        <div className="action-row">
          <div className="view-tabs" role="tablist">
            {["split", "table", "mindmap"].map((mode) => (
              <button key={mode} className={viewMode === mode ? "selected" : ""} onClick={() => onViewMode(mode)}>
                {mode}
              </button>
            ))}
          </div>
          <button className="button secondary" disabled={disabled} onClick={onAnalyze}><Workflow size={16} /> 分析变更</button>
          <button className="button primary" disabled={!diffRun} onClick={onMerge}><Check size={16} /> 合并已采纳</button>
        </div>
      </div>

      {graph ? (
        <div className={`diff-layout ${viewMode}`}>
          {viewMode !== "mindmap" ? (
            <ProposalTable proposals={proposals} selectedProposalId={selectedProposalId} onSelect={onSelect} onReview={onReview} />
          ) : null}
          {viewMode !== "table" ? (
            <div className="mindmap-pane">
              <ReactFlowProvider>
                <ReactFlow
                  nodes={nodes}
                  edges={edges}
                  nodeTypes={nodeTypes}
                  fitView
                  onNodeClick={handleNodeClick}
                  onNodeDragStop={handleNodeDragStop}
                >
                  <Background color="#ded6c9" gap={22} />
                  <MiniMap pannable zoomable />
                  <Controls />
                </ReactFlow>
              </ReactFlowProvider>
            </div>
          ) : null}
          {selectedProposal ? <ProposalDrawer proposal={selectedProposal} onReview={onReview} /> : null}
        </div>
      ) : (
        <div className="empty-results"><ArrowRight size={20} /><span>保存 baseline 后可创建 Diff run。</span></div>
      )}
    </section>
  );
}

function ProposalTable({ proposals, selectedProposalId, onSelect, onReview }) {
  return (
    <div className="proposal-list table-pane">
      {proposals.map((proposal) => (
        <article
          key={proposal.id}
          className={`proposal-row ${proposal.action} ${selectedProposalId === proposal.id ? "selected" : ""}`}
          onClick={() => onSelect(proposal.id)}
        >
          <div>
            <span className="status-pill">{proposal.action}</span>
            <strong>{proposal.title}</strong>
            <p>{proposal.change_reason}</p>
            <code>{proposal.review_status} / {Math.round(proposal.confidence * 100)}%</code>
          </div>
          <div className="action-row">
            <button className="mini-button" onClick={(event) => { event.stopPropagation(); onReview(proposal, "accept"); }}>采纳</button>
            <button className="mini-button" onClick={(event) => { event.stopPropagation(); onReview(proposal, "reject"); }}>驳回</button>
          </div>
        </article>
      ))}
    </div>
  );
}

function ReviewNode({ data }) {
  const action = data.action || data.nodeType;
  return (
    <div className={`review-node ${data.nodeType} ${action} ${data.review_status ?? ""} ${data.selected ? "selected" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <div className="node-kicker">{data.nodeType}</div>
      <strong>{data.title || data.quote || data.source_type}</strong>
      {data.confidence ? <span>{Math.round(data.confidence * 100)}%</span> : null}
      {data.review_status ? <code>{data.review_status}</code> : null}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function ProposalDrawer({ proposal, onReview }) {
  return (
    <aside className="proposal-drawer">
      <span className="status-pill">{proposal.action}</span>
      <h3>{proposal.title}</h3>
      <p>{proposal.change_reason}</p>
      <div className="drawer-block">
        <strong>Evidence</strong>
        {(proposal.evidence ?? []).map((item) => (
          <code key={`${item.source_type}-${item.source_id}-${item.quote}`}>{item.source_type}: {item.quote}</code>
        ))}
      </div>
      <div className="drawer-block">
        <strong>After</strong>
        <pre>{JSON.stringify(proposal.after_payload, null, 2)}</pre>
      </div>
      <div className="action-row">
        <button className="button primary" onClick={() => onReview(proposal, "accept")}>采纳</button>
        <button className="button secondary" onClick={() => onReview(proposal, "reject")}>驳回</button>
      </div>
    </aside>
  );
}

export default App;
