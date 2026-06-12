# NeuralFlow — Technical Requirements Document (TRD v1)

> Companion to **NeuralFlow_PRD_v3.md**. This document defines the technical design, stack, interfaces, and build sequence for **R0 (MVP)**, with forward notes for R1 (EXO) and R2 (Community).

---

## 1. Technology Stack (locked for R0)

| Layer | Choice | Rationale |
| :--- | :--- | :--- |
| Desktop shell | **Electron** | Mature cross-platform desktop; large ecosystem. |
| UI | **React + TypeScript** | Type safety across the canvas/data model. |
| Canvas | **React Flow** | Proven node-editor; avoid custom WebGL until perf demands it. |
| Local backend | **Python 3.11 + FastAPI** | Async, simple, rich AI/SDK ecosystem. |
| Backend ↔ UI | **Local HTTP + WebSocket** (backend bound to `127.0.0.1`) | WS streams tokens/monitor events; HTTP for CRUD. |
| Python packaging | **PyInstaller** (embedded runtime) | Ship Python with the app; no user install. |
| Secrets | **OS keychain** (Keychain / Credential Manager / libsecret) via `keyring` | Keys never touch disk in plaintext. |
| Storage | Local **versioned JSON** files + SQLite (run history) | Portable pipelines; queryable trace history. |
| Tests | **pytest** (backend), **Vitest + Playwright** (frontend/e2e) | CI-runnable without GPUs. |

**Forward notes:** R1 adds an `ExoEndpoint`; R2 adds a cloud service (Node.js + PostgreSQL + S3) for the hub.

---

## 2. High-Level Architecture

```
Electron (React + TS, React Flow canvas)
        │  local HTTP + WebSocket  (127.0.0.1)
Python FastAPI backend
   ├── Pipeline Compiler   : node graph → typed, validated DAG (+ loop subgraphs)
   ├── Scheduler           : topo sort, parallel branches, loop state, budget enforcement
   ├── Node Executors      : model / logic / data / tool
   ├── State Manager       : per-node IO, loop history, checkpoints (SQLite)
   └── ModelEndpoint registry
            ├── CloudEndpoint  (OpenAI / Anthropic / Google / OpenAI-compatible)
            └── OllamaEndpoint (single machine)              [+ ExoEndpoint in R1]
```

The scheduler is **endpoint-agnostic**: it never knows whether a node is cloud, local, or sharded. This is the single most important design constraint.

---

## 3. The Core Abstraction: `ModelEndpoint`

Every model backend implements one interface. This makes EXO swappable and keeps R0 free of any distributed code.

```python
from typing import Protocol, AsyncIterator

class ModelEndpoint(Protocol):
    id: str

    async def generate(self, req: "GenRequest") -> AsyncIterator["Token"]:
        """Stream tokens for a request."""

    async def health(self) -> "Health":
        """Is the endpoint online / loaded / warm?"""

    def capabilities(self) -> "Caps":
        """Context length, JSON/structured mode, tool support, vision."""

    def estimate_cost(self, req: "GenRequest") -> "Cost":
        """Estimated $ and token cost for budget enforcement."""
```

Supporting types (sketch): `GenRequest{messages, params, response_format}`, `Token{text, index}`, `Health{online, loaded, warm}`, `Caps{max_context, json_mode, tools, vision}`, `Cost{usd, tokens_in, tokens_out}`.

---

## 4. Pipeline Data Format (schema v2)

Pipelines are versioned JSON. Loops are **subgraphs**, all ports are **typed**, and **no secrets or device pins** are stored (those resolve at run time, keeping pipelines portable and shareable).

```json
{
  "schema_version": "2.0",
  "id": "uuid-placeholder",
  "name": "DeepSeek-style Solver",
  "version": "1.0.0",
  "nodes": [
    { "id": "in", "type": "input", "outputs": [{ "name": "prompt", "type": "text" }] },
    { "id": "solver", "type": "model", "endpoint_ref": "ollama:llama3.3-70b",
      "role": "solver", "config": { "temperature": 0.7, "max_tokens": 2048 },
      "inputs": [{ "name": "input", "type": "text" }],
      "outputs": [{ "name": "output", "type": "text" }] },
    { "id": "verify", "type": "model", "endpoint_ref": "cloud:gpt-4o",
      "role": "verifier", "config": { "temperature": 0.2, "response_format": "json" },
      "inputs": [{ "name": "input", "type": "text" }],
      "outputs": [{ "name": "output", "type": "json" }] }
  ],
  "loops": [
    { "id": "refine", "body": ["solver", "verify"], "max_iterations": 5,
      "stop_when": { "field": "verify.output.verified", "op": "==", "value": true },
      "on_max": "return_best" }
  ],
  "edges": [
    { "from": "in.prompt", "to": "solver.input" },
    { "from": "solver.output", "to": "verify.input" }
  ],
  "endpoints": {
    "ollama:llama3.3-70b": { "kind": "ollama" },
    "cloud:gpt-4o": { "kind": "openai" }
  }
}
```

**Validation rules (compiler):**
1. Graph (excluding loop subgraphs) must be acyclic.
2. Every edge connects compatible port types.
3. Every `endpoint_ref` resolves in `endpoints`.
4. `stop_when` is a structured condition (no raw code / `eval`); supported ops: `==, !=, >, <, >=, <=, contains`.
5. Every loop has a finite `max_iterations` and an `on_max` policy.

---

## 5. Execution Engine

**Flow:** `Input → Compiler (graph→DAG) → Scheduler (topo + parallel + loops) → Node Executors → State Manager → Output/Trace`.

- **Parallelism:** independent DAG branches run concurrently (asyncio).
- **Loops:** evaluated as bounded subgraphs; each iteration's IO recorded in loop history.
- **Checkpointing:** state persisted *between* nodes (never mid-token), enabling graceful failure/retry.
- **Budget enforcement:** scheduler tracks running cost via `estimate_cost`/actuals; on breach of `$` or wall-clock cap → halt + return partial trace. A UI kill switch issues the same halt.
- **Stop conditions:** confidence score, structured field match, manual approval, or max iterations.

---

## 6. Node Type Specifications (R0)

| Node | Inputs → Outputs | Notes |
| :--- | :--- | :--- |
| Input | — → text | User prompt entry; template variables allowed. |
| Output | text/json → — | Final render + trace anchor. |
| Model | text/json → text/json | Wraps a `ModelEndpoint`; supports `response_format`. |
| Loop | subgraph | Bounded iteration with `stop_when` / `on_max`. |
| Judge | N×text → text + score | Scores/selects best candidate. |
| Router | text + condition → branch | Conditional branching. |
| Transform | any → any | Format conversion / templating (sandboxed, no code-exec). |

---

## 7. Security Requirements

1. **Secrets:** keychain only; never written to pipeline JSON; pre-export scrub + lint.
2. **Local server:** bind to `127.0.0.1` only; per-session auth token between Electron and backend.
3. **Tool/RAG output:** treated as untrusted; clearly flagged in UI; never auto-executed.
4. **Code Executor:** out of R0; when added, sandboxed subprocess, no network by default, CPU/mem/time limits, explicit opt-in.
5. **Shared pipelines:** validated/scrubbed before save and before import.

---

## 8. Build Sequence

| Phase | Weeks | Deliverable / Definition of Done |
| :--- | :--- | :--- |
| **Spike** | 1–2 | Hard-coded Input→Cloud model→Output runs end-to-end through `ModelEndpoint`; token streaming visible in a minimal UI. |
| **R0 Alpha** | 3–8 | Canvas + compiler + scheduler + Cloud & Ollama endpoints; custom DAG with a loop runs; trace view works. |
| **R0 Beta** | 9–12 | 10–20 templates, budget caps, monitor, signed/notarized installers, opt-in telemetry. |
| **R0 Launch** | 13–14 | Onboarding polish + docs; new user → first template run in < 5 min. |
| **R1** | +6–8 | `ExoEndpoint`; device view; Apple-Silicon demo; honest perf UI (live tok/s). |
| **R2** | +8–12 | Cloud hub: template sharing → custom configs → monetization (legal-gated). |

**Efficiency rules:** build `ModelEndpoint` in week 1; ship cloud-only first (CI-testable, no GPU); defer custom WebGL canvas and the R2 cloud service until demand is proven.

---

## 9. Suggested Repo Layout

```
neuralflow/
├── apps/
│   └── desktop/            # Electron + React + React Flow (TypeScript)
│       ├── src/canvas/
│       ├── src/panels/
│       └── src/ipc/
├── backend/
│   ├── neuralflow/
│   │   ├── compiler/       # graph → typed DAG + validation
│   │   ├── scheduler/      # topo, parallel, loops, budget
│   │   ├── executors/      # model/logic/data/tool nodes
│   │   ├── endpoints/      # ModelEndpoint impls (cloud, ollama, [exo])
│   │   ├── state/          # SQLite, checkpoints, trace
│   │   └── api/            # FastAPI routes + WebSocket
│   └── tests/
├── templates/              # first-party pipeline JSON
└── packaging/              # PyInstaller + signing/notarization scripts
```

---

## 10. Open Technical Questions (resolve before Spike)

1. Electron ↔ Python: spawn FastAPI as a child process vs. system service? (Recommend child process bound to a random local port.)
2. Telemetry vendor / self-hosted, and exact opt-in UX.
3. Cost data source for `estimate_cost` (per-provider pricing tables — how kept current?).
4. Minimum confidence-score contract for Judge/Verifier nodes (where does the score come from — model self-report vs. separate scorer?).
