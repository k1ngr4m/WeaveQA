# WeaveQA MVP

WeaveQA is an internal QA workbench for validating whether historical PRD and Bug knowledge can improve generated test case coverage.

## What Is Implemented

- React workbench with a warm Claude/Anthropic-inspired visual direction adapted for enterprise QA.
- Modular FastAPI backend with SQLAlchemy models for knowledge sources, snapshots, chunks, Figma UI context, requirements, baselines, case versions, diff runs, proposals, and merge runs.
- Manual knowledge import plus real Feishu source/sync API path. Feishu credentials are read from environment variables.
- Qdrant integration with database lexical fallback, parent-child chunking, retrieval debugger, structured generation, citations, and review metrics.
- Figma MCP integration path plus JSON import fallback for local testing, UI context extraction, UI coverage tags, and Figma citations.
- Diff review workflow with requirement baselines, added/modified/deleted proposals, accept/reject/edit endpoints, and versioned merge.
- Phase 5 review graph workflow with React Flow mindmap, table/mindmap/split view modes, graph payload API, and persisted view state.
- Docker Compose stack for PostgreSQL, Qdrant, backend, and frontend.

## Design Docs

- MVP PRD: [`doc/PRD.md`](doc/PRD.md)
- Phase 2 design: [`doc/PHASE2_DESIGN.md`](doc/PHASE2_DESIGN.md)
- Phase 3 design: [`doc/PHASE3_DESIGN.md`](doc/PHASE3_DESIGN.md)
- Phase 4 design: [`doc/PHASE4_DESIGN.md`](doc/PHASE4_DESIGN.md)
- Phase 5 design: [`doc/PHASE5_DESIGN.md`](doc/PHASE5_DESIGN.md)

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

In another terminal:

```bash
npm install
npm run dev
```

Open `http://localhost:5173`.

If your backend uses another port, start the frontend with:

```bash
VITE_API_BASE=http://localhost:8001 npm run dev
```

Full local stack:

```bash
docker compose up
```

The backend supports real PostgreSQL/Qdrant through `DATABASE_URL` and `QDRANT_URL`. Feishu and Figma MCP require credentials or a running MCP server; JSON/manual import remains available for local testing.

## MVP Success Check

Use the same requirement in three modes:

- `无知识库`
- `仅 PRD`
- `PRD + Bug`

Compare coverage score, missed risks, Bug regression points, retrieved context, and citations attached to generated cases.

## Integrated Flow Check

1. Import or seed knowledge assets.
2. Import Figma context JSON or sync through a running Figma MCP server.
3. Generate cases with `save_as_requirement=true`.
4. Create a diff run for the saved requirement.
5. Accept or reject proposals.
6. Merge accepted proposals and inspect active case versions.
7. Open the split review workspace to inspect proposals as both table rows and graph nodes.

## Test

```bash
python3 -m pytest backend/tests -q
python3 -m py_compile backend/app/*.py backend/app/services/*.py
npm run build
```
