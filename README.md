# NeuralFlow

> Desktop visual editor for building and running multi-model LLM pipelines.
> Cloud APIs + local models (Ollama) on a single machine — **R0 (MVP)**.

## Running Locally (Development)

NeuralFlow requires both the FastAPI backend and the React frontend to be running simultaneously during development.

**1. Start the Backend**
```bash
cd backend
.venv\Scripts\python.exe -m uvicorn neuralflow.api.main:app --port 8000
```
*(On macOS/Linux, use `.venv/bin/python`)*

**2. Start the Frontend**
```bash
cd apps/desktop
npm install
npm run dev
```

The frontend will start on port `5173` (or `5174`) and automatically connect to the backend on `127.0.0.1:8000`.

## Architecture (TRD §2)

## What it is

NeuralFlow lets you compose pipelines of AI models visually (React Flow canvas),
execute them against cloud or local endpoints, and inspect every token, cost, and
decision in a live trace view — all without a server, account, or secrets ever
touching disk.

## Stack (locked for R0)

| Layer | Choice |
| :--- | :--- |
| Desktop shell | Electron |
| UI | React + TypeScript + React Flow |
| Local backend | Python 3.11 + FastAPI |
| Transport | Local HTTP + WebSocket on `127.0.0.1` |
| Secrets | OS keychain via `keyring` |
| Storage | Versioned JSON (pipelines) + SQLite (run history) |
| Python packaging | PyInstaller (embedded runtime) |
| Frontend tests | Vitest + Playwright |
| Backend tests | pytest |

## Repository layout

```
neuralflow/
├── AGENT.md                  Development rules (always_on)
├── README.md                 This file
├── roadmap.md                3-person phase plan (P1/P2/P3)
├── NeuralFlow_PRD_v3.md      Product requirements
├── NeuralFlow_TRD_v1.md      Technical requirements
├── .gitignore
├── apps/desktop/             Electron + React + TS + React Flow (P3)
│   └── src/
│       ├── canvas/           Node canvas components
│       ├── panels/           Config / monitor / trace panels
│       └── ipc/              Electron ↔ renderer IPC bridges
├── backend/
│   ├── neuralflow/           Python package (P1 + P2)
│   │   ├── compiler/         Graph → typed DAG + validation (P1)
│   │   ├── scheduler/        Topo sort, parallelism, loops, budget (P1)
│   │   ├── executors/        Node executors: model/logic/data/tool (P2)
│   │   ├── endpoints/        ModelEndpoint implementations (P2)
│   │   ├── state/            SQLite store, checkpoints, trace (P1)
│   │   └── api/              FastAPI routes + WebSocket (P2)
│   └── tests/                Backend test suite
├── shared/                   Shared contracts: JSON Schema v2 + type stubs (P1)
├── templates/                First-party pipeline JSON files (empty for now)
└── packaging/                PyInstaller + signing scripts
```

## How to run (development)

### Backend

```bash
cd neuralflow/backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
uvicorn neuralflow.api.main:app --host 127.0.0.1 --port 8765 --reload
```

### Desktop

```bash
cd neuralflow/apps/desktop
npm install
npm run dev
```

### Tests

```bash
# Backend
cd neuralflow/backend
pytest

# Frontend
cd neuralflow/apps/desktop
npm test
```

## Ownership

| Person | Domain | Folders |
| :--- | :--- | :--- |
| **P1** | Backend core (contracts, compiler, scheduler, state) | `shared/`, `backend/neuralflow/compiler`, `backend/neuralflow/scheduler`, `backend/neuralflow/state` |
| **P2** | Endpoints & API (model endpoints, FastAPI, WebSocket, budget) | `backend/neuralflow/endpoints`, `backend/neuralflow/executors`, `backend/neuralflow/api` |
| **P3** | Desktop UI (Electron shell, React Flow canvas, panels, monitor) | `apps/desktop/**` |

> See `roadmap.md` for the full phase plan and per-task AI prompts.
