# roadmap.md — NeuralFlow R0 (MVP) — 3-Person Vibecoding Plan

> Read `AGENT.md` first. Run the **VERY FIRST prompt** in AGENT.md §5 once (P1) before anything below.
> This plan covers **R0 (MVP) only**. Stack is locked (see TRD). Each task includes: the exact AI prompt, who owns it, when work merges, tests per person, integration tests after merge, and an **effort/heaviness rating** so you know when to switch to a stronger model.

---

## Team & ownership

| Person | Domain | Folders they own |
| :--- | :--- | :--- |
| **P1 — Backend Core** | Contracts, compiler, scheduler, state | `shared/`, `backend/neuralflow/compiler`, `backend/neuralflow/scheduler`, `backend/neuralflow/state` |
| **P2 — Endpoints & API** | Model endpoints, FastAPI, WebSocket streaming, budget | `backend/neuralflow/endpoints`, `backend/neuralflow/executors`, `backend/neuralflow/api` |
| **P3 — Desktop UI** | Electron shell, React Flow canvas, panels, monitor | `apps/desktop/**` |

**Why this split:** P1 owns the data model everyone depends on, P2 owns everything that talks to models, P3 owns everything the user sees. The only tightly-shared contracts are: **pipeline JSON schema v2** (P1 owns), **`ModelEndpoint` interface** (P1 defines, P2 implements), and **API/WebSocket routes** (P2 owns, P3 consumes).

---

## How to read the heaviness rating (model switching)

| Rating | Meaning | Recommended model tier |
| :--- | :--- | :--- |
| 🟢 **Light** | Boilerplate, wiring, simple CRUD/UI. | Fast/cheap model is fine. |
| 🟡 **Medium** | Real logic, edge cases, async, API integration. | Mid/strong model. |
| 🔴 **Heavy** | Core algorithms, concurrency, schema design, tricky bugs. | Use your strongest model; review carefully. |

> Rule of thumb: start a task on a cheaper model; if it produces wrong/looping/hallucinated output twice, **switch up a tier** for that task.

---

## Phase map (overview)

| Phase | P1 | P2 | P3 | Merge & Integration |
| :--- | :--- | :--- | :--- | :--- |
| **0 Setup** | run first prompt | env setup | env setup | repo skeleton exists |
| **1 Foundations** | schema v2 + `ModelEndpoint` types | `MockEndpoint` + `CloudEndpoint` | Electron+React Flow blank canvas | **Merge A:** contracts shared |
| **2 Core engine** | compiler + scheduler | API + WebSocket + budget | node UI + side panels | **Merge B:** UI ↔ API ↔ engine |
| **3 Features** | loops + checkpoints + trace store | executors + structured-output repair | monitor + trace view + save/load | **Merge C:** end-to-end run |
| **4 Polish** | validation hardening | provider list + Ollama | templates UI + onboarding | **Merge D:** release candidate |

After **each phase**: every person runs their own tests, THEN the team runs the integration test for that phase's merge.

---

# PHASE 1 — Foundations

### P1 — Pipeline schema v2 + shared types  🔴 Heavy
**Prompt:**
```
TASK (P1, Phase 1): Define the pipeline schema v2 and shared contracts.
1. In shared/pipeline.schema.json write the FULL JSON Schema for pipeline schema v2 exactly as described in NeuralFlow_TRD_v1.md section 4 (nodes with typed inputs/outputs, loops as subgraphs, edges, endpoints map, validation rules). No secrets, no device pins in schema.
2. In shared/types.ts (TypeScript) and backend/neuralflow/compiler/models.py (pydantic) define matching types for: Node, Port(type: text|number|boolean|json|image|audio), Edge, Loop(stop_when structured condition, max_iterations, on_max), Pipeline.
3. In backend/neuralflow/endpoints/base.py define the ModelEndpoint Protocol + GenRequest, Token, Health, Caps, Cost exactly as in TRD section 3.
RULES: TS and Python types MUST match the JSON Schema. No app logic. Write unit tests that load a valid sample pipeline JSON and assert it validates, and an invalid one (cyclic edge) and assert it fails.
```
**Tests (P1):** `pytest backend/tests/test_schema.py` — valid loads, cyclic graph rejected, type-mismatch edge rejected.

### P2 — MockEndpoint + CloudEndpoint  🟡 Medium
**Prompt:**
```
TASK (P2, Phase 1): Implement model endpoints against the ModelEndpoint Protocol from backend/neuralflow/endpoints/base.py.
1. MockEndpoint (TEST-ONLY, in tests or clearly named): deterministic streamed tokens for tests. This is the ONLY allowed fake.
2. CloudEndpoint: real implementation for OpenAI + Anthropic + Google + generic OpenAI-compatible base_url. Use official SDKs / httpx. Read API keys from OS keychain via keyring (never hardcode). Implement generate() (streaming), health(), capabilities(), estimate_cost() using a real per-provider pricing table in a config file.
RULES: NO fake responses in CloudEndpoint — it must hit the real API. NO secrets in code. End with how to run a real test (requires a key in keychain) AND a mocked unit test.
```
**Tests (P2):** unit test with `MockEndpoint`; one live smoke test (skipped if no key) hitting a real provider.

### P3 — Electron shell + blank React Flow canvas  🟡 Medium
**Prompt:**
```
TASK (P3, Phase 1): Build the desktop shell.
1. Electron + Vite + React + TS app in apps/desktop that launches a window.
2. A blank React Flow canvas with zoom/pan/minimap and an empty left sidebar (node palette placeholder) and right panel (config placeholder).
3. On startup, Electron spawns the FastAPI backend as a child process on a random 127.0.0.1 port and passes a per-session auth token (stub the backend call for now — just prove the process spawns and a /health ping works once P2's API exists; until then ping a local stub).
RULES: No dummy pipeline data on the canvas. Real React Flow. End with `npm run dev` instructions.
```
**Tests (P3):** `vitest` component render test; manual: app launches, canvas pans/zooms.

### 🔗 MERGE A (after Phase 1)
Combine: P1's `shared/` contracts are imported by P2 (Python) and P3 (TS).
**Integration test:** P2 implements `MockEndpoint` against P1's `base.py` and a test runs a `GenRequest` through it; P3's TS types import `shared/types.ts` and compile with no errors. ✅ Pass = contracts line up across all three.

---

# PHASE 2 — Core engine

### P1 — Compiler + Scheduler  🔴 Heavy
**Prompt:**
```
TASK (P1, Phase 2): Build the pipeline compiler and scheduler.
1. compiler/: turn a pipeline JSON (schema v2) into a typed, validated DAG. Enforce ALL validation rules from TRD section 4 (acyclic excluding loop subgraphs, type-compatible edges, endpoint_ref resolves, structured stop_when only — NO eval/code, finite max_iterations).
2. scheduler/: topological sort, run independent branches in parallel (asyncio), execute loop subgraphs as bounded iterations recording per-iteration IO. Accept an injected endpoint registry (use MockEndpoint in tests).
RULES: Heavy concurrency logic — be careful with parallel + loop interaction. No dummy outputs; use injected endpoints. Full unit tests including a parallel-branch test and a loop-stops-on-condition test and a loop-hits-max test.
```
**Tests (P1):** parallel branches both run; loop stops on `stop_when`; loop respects `max_iterations`; invalid graphs rejected.

### P2 — FastAPI + WebSocket + budget enforcement  🔴 Heavy
**Prompt:**
```
TASK (P2, Phase 2): Build the API layer.
1. FastAPI routes: POST /pipelines/run (accepts pipeline JSON), GET /health, GET /models (fetch real model lists from configured providers).
2. WebSocket /ws/run/{run_id}: stream per-node status, tokens, token counts, cost, timing as the scheduler executes.
3. Budget enforcement: scheduler-level guard that halts the run when $ cap OR wall-clock cap is exceeded, plus a /runs/{id}/stop kill-switch endpoint. Use real estimate_cost from endpoints.
RULES: Bind to 127.0.0.1 only; require the per-session auth token. No fake cost/token numbers — pull from real endpoint responses. Tests with MockEndpoint covering: streaming events emitted, budget breach halts run, stop endpoint halts run.
```
**Tests (P2):** WS emits events in order; over-budget run halts; stop endpoint works.

### P3 — Node UI + config panels  🟡 Medium
**Prompt:**
```
TASK (P3, Phase 2): Build the node editing experience.
1. Node palette sidebar (Input, Output, Model, Loop, Judge, Router, Transform) — drag to canvas.
2. Color-coded typed ports (text/number/boolean/json/image/audio); only compatible ports connect (real-time validation, highlight broken edges).
3. Right-side config panel per node (model node: endpoint, system prompt, temperature, max_tokens, response_format, role).
4. Serialize the canvas to pipeline JSON schema v2 (import shared/types.ts) and back.
RULES: Real serialization to schema v2 — no dummy node data saved. Tests: building a 3-node graph serializes to valid schema v2 JSON.
```
**Tests (P3):** drag/connect works; incompatible ports rejected; canvas ↔ schema v2 round-trips.

### 🔗 MERGE B (after Phase 2)
Combine: P3 UI → P2 API → P1 engine.
**Integration test:** P3 serializes a 3-node pipeline → POST `/pipelines/run` → P2 streams events over WS while P1's scheduler runs it through `MockEndpoint` → UI shows live status. ✅ Pass = a pipeline built in the UI executes end-to-end with mock models and live updates.

---

# PHASE 3 — Features

### P1 — Loops, checkpoints, trace store  🔴 Heavy
**Prompt:**
```
TASK (P1, Phase 3): Add durability + trace.
1. state/: SQLite store for run history; checkpoint state BETWEEN nodes (never mid-token); record full per-node input/output, loop history, tokens, cost, timing.
2. Resume/retry: on a node failure, allow retry from last checkpoint.
RULES: Real persisted data, no fake rows. Tests: a failed node can resume; trace rows match what ran.
```
**Tests (P1):** checkpoint resume works; trace persisted correctly.

### P2 — Executors + structured-output repair  🟡 Medium
**Prompt:**
```
TASK (P2, Phase 3): Implement node executors and robust parsing.
1. executors/: model node (calls endpoint), Judge, Router, Transform, Input, Output.
2. When a node requires JSON but the model returns prose: use native structured-output mode if the provider supports it; else a repair-prompt retry with a hard cap; always store raw output in the trace.
RULES: Real model calls (MockEndpoint in tests). No silently-passing parsers. Tests: malformed JSON triggers repair then succeeds/fails cleanly.
```
**Tests (P2):** each executor type runs; JSON repair path covered.

### P3 — Execution monitor + trace view + save/load  🟡 Medium
**Prompt:**
```
TASK (P3, Phase 3): Build run visibility + persistence UI.
1. Execution monitor: live table (node, status, time, tokens, device, cost) fed by the WebSocket; running cost + elapsed + loop iteration counter; a visible KILL SWITCH button calling /runs/{id}/stop.
2. Post-run trace view: full IO per node, loop history, cost breakdown.
3. Save/load pipelines as versioned JSON files (export scrubs secrets).
RULES: Real data from WS/trace — no fabricated numbers. Tests: monitor renders live events; save/load round-trips; export contains no secrets.
```
**Tests (P3):** monitor updates live; kill switch stops run; save/load + secret-scrub verified.

### 🔗 MERGE C (after Phase 3)
Combine: full stack with real cloud models.
**Integration test (uses a REAL provider key in keychain):** Load the Solver→Verifier→Judge template, run it against a real cloud model, watch live monitor, hit kill switch mid-run (verify it stops), let a clean run finish, open trace, save + reload pipeline. ✅ Pass = a real multi-model pipeline runs end-to-end with real data, killable, traceable, persistable.

---

# PHASE 4 — Polish & Release Candidate

### P1 — Validation hardening + error messages  🟡 Medium
**Prompt:** `Harden the compiler: friendly, specific validation errors for every rule; fuzz-test with malformed pipelines; ensure no crash, always a clear error. Tests for each rule's error message.`
**Tests:** every invalid-pipeline case returns a specific, non-crashing error.

### P2 — Provider model lists + Ollama (single machine)  🟡 Medium
**Prompt:** `Add OllamaEndpoint (single machine, OpenAI-compatible local URL) implementing ModelEndpoint. Make /models fetch live lists from each configured provider AND local Ollama. No hardcoded model lists. Tests with a running Ollama (skip if absent) + mocked unit tests.`
**Tests:** model list is dynamic; Ollama endpoint streams a real local generation (skippable).

### P3 — Templates + onboarding  🟢 Light → 🟡 Medium
**Prompt:** `Add a template gallery loading the 10–20 JSON files from templates/ (one-click import to canvas). Add first-run onboarding: detect keychain keys, prompt to add one, run first template in <5 min. No dummy templates — each is a real, runnable pipeline JSON. Tests: each template validates against schema v2 and imports cleanly.`
**Tests:** every template validates + imports; onboarding completes.

### 🔗 MERGE D (Release Candidate)
**Full integration / acceptance test (the PRD metrics):**
1. Fresh install → new user runs a template in **< 5 min**.
2. Build a custom 3-node pipeline in **< 15 min**.
3. Cloud node overhead **< 1.3×** raw API latency.
4. Budget cap + kill switch verified.
5. Signed/notarized installers build in CI (packaging/).
✅ Pass = R0 is shippable.

---

## Test summary (who tests what, when)

| When | P1 | P2 | P3 | Team integration |
| :--- | :--- | :--- | :--- | :--- |
| End of each phase | unit tests on own modules | unit tests (MockEndpoint) | vitest + manual UI | the phase's MERGE integration test |
| Phase 1 | schema valid/invalid | endpoint via Mock + live smoke | canvas render | **Merge A:** contracts align |
| Phase 2 | scheduler concurrency/loops | WS + budget + stop | canvas↔schema | **Merge B:** UI→API→engine with mocks |
| Phase 3 | checkpoint/trace | executors + JSON repair | monitor/trace/save | **Merge C:** real-model end-to-end |
| Phase 4 | validation fuzz | dynamic models + Ollama | templates + onboarding | **Merge D:** PRD acceptance |

---

## Heaviness map (for model switching at a glance)

| Task | Rating |
| :--- | :--- |
| Schema v2 + contracts (P1.1) | 🔴 |
| Compiler + Scheduler (P1.2) | 🔴 |
| Loops/checkpoints/trace (P1.3) | 🔴 |
| Validation hardening (P1.4) | 🟡 |
| Cloud endpoints (P2.1) | 🟡 |
| API + WS + budget (P2.2) | 🔴 |
| Executors + JSON repair (P2.3) | 🟡 |
| Provider lists + Ollama (P2.4) | 🟡 |
| Electron + canvas shell (P3.1) | 🟡 |
| Node UI + panels (P3.2) | 🟡 |
| Monitor + trace + save (P3.3) | 🟡 |
| Templates + onboarding (P3.4) | 🟢→🟡 |

**Switch to your strongest model for every 🔴 task** (the compiler, scheduler, concurrency, schema, and API/WS/budget are where bugs are silent and expensive). Cheaper models are fine for 🟢 and most 🟡 UI wiring.

---

## Coordination rules

- Anyone changing a **shared contract** (schema v2, `ModelEndpoint`, API routes) announces a **BREAKING CHANGE** and the other two re-sync before continuing.
- Do not start a phase's MERGE until all three have green tests on their own branches.
- If two people's work must combine mid-phase, do it at the nearest MERGE point, not ad hoc.
