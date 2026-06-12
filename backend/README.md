# backend

**Owner: P1 (compiler, scheduler, state) + P2 (endpoints, executors, api)**

## Purpose

Python 3.11 + FastAPI backend. Runs as a child process of Electron, bound
exclusively to `127.0.0.1`. Provides the full pipeline execution engine
(compiler → scheduler → executors → state) and exposes it over HTTP + WebSocket.

## Package layout

```
backend/
├── neuralflow/          Python package
│   ├── compiler/        P1 — graph → typed DAG + validation rules
│   ├── scheduler/       P1 — topological sort, parallel branches, loop state, budget
│   ├── executors/       P2 — per-node-type execution logic
│   ├── endpoints/       P2 — ModelEndpoint implementations (Cloud, Ollama)
│   ├── state/           P1 — SQLite run history, checkpoints, trace
│   └── api/             P2 — FastAPI app, HTTP routes, WebSocket /ws/run/{id}
└── tests/               Shared test suite (pytest)
```

## How to set up

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

## How to run

```bash
uvicorn neuralflow.api.main:app --host 127.0.0.1 --port 8765 --reload
```

## How to test

```bash
pytest                     # all tests
pytest -k "not live"       # skip tests that require real API keys
ruff check neuralflow      # lint
black --check neuralflow   # format check
```

## Security

- Bound to `127.0.0.1` only — never `0.0.0.0`.
- Requires the **per-session auth token** (passed from Electron via env var at
  spawn time) on every request.
- API keys are read from the OS keychain via `keyring` — never from env vars,
  config files, or pipeline JSON.
