<div align="center">

# Komvos — Project Documentation

**A visual desktop platform for building and running multi-model AI pipelines.**

Version 0.1.0 · MIT License · Windows / macOS / Linux

</div>

---

## Table of Contents

1. [What is Komvos?](#1-what-is-komvos)
2. [Tech Stack — What Is Used & Why](#2-tech-stack--what-is-used--why)
3. [Architecture](#3-architecture)
4. [Core Design Decisions](#4-core-design-decisions)
5. [Security Model](#5-security-model)
6. [Feature Reference](#6-feature-reference)
7. [What Makes Komvos Different From Competitors](#7-what-makes-komvos-different-from-competitors)
8. [Template Gallery](#8-template-gallery)
9. [Quality, Testing & CI](#9-quality-testing--ci)
10. [Build, Packaging & Distribution](#10-build-packaging--distribution)
11. [Repository Structure](#11-repository-structure)
12. [Running the Project](#12-running-the-project)
13. [Roadmap](#13-roadmap)

---

## 1. What is Komvos?

Komvos turns the powerful but code-heavy world of multi-model AI orchestration into a **visual, drag-and-drop experience**. Inspired by node editors like ComfyUI and Blender's shader graph, it lets developers, researchers, and power users build advanced AI architectures — such as the **Solver → Verifier → Judge** verification loop popularized by frontier reasoning models — without writing orchestration code.

Pipelines run on a **local-first execution engine** that treats every model (a cloud API or a locally-hosted Ollama model) as a uniform endpoint, so you can mix paid cloud reasoning with free, private local inference in the same graph.

> **The gap it fills:** there is a real distance between "use one chatbot" and "engineer your own multi-model AI system." Komvos closes it with a visual interface, a hybrid cloud/local runtime, and a shareable pipeline format.

### Flagship example

```
        ┌─────────┐     ┌──────────┐     ┌─────────┐     ┌──────────┐
 Prompt │  INPUT  │ ──▶ │  SOLVER  │ ──▶ │ VERIFIER│ ──▶ │  JUDGE   │ ──▶ Output
        └─────────┘     │ (local)  │     │ (cloud) │     │  (best)  │
                        └──────────┘     └─────────┘     └──────────┘
                              ▲                │
                              └──── loop until verified ────┘
```

The Solver drafts an answer (local model), the Verifier checks it (structured JSON), the loop repeats until the verification condition is met or max iterations is reached — then the Judge picks the best result. Built by dragging five nodes onto a canvas.

### Pipelines as APIs

Any pipeline can be served as an **OpenAI-compatible HTTP endpoint**, so it can be consumed immediately from LangChain, OpenWebUI, Cursor, or any OpenAI SDK client:

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="kv_...")
resp = client.chat.completions.create(
    model="<deployment_id>",
    messages=[{"role": "user", "content": "hello"}],
)
print(resp.choices[0].message.content)
```

---

## 2. Tech Stack — What Is Used & Why

### 2.1 Summary table

| Layer | Technology | Version |
| --- | --- | --- |
| Desktop shell | Electron | ^42 |
| UI framework | React + ReactDOM | ^18.3 |
| Language (frontend) | TypeScript | ^5.5 |
| Node-graph canvas | React Flow (`reactflow`) | ^11.11 |
| Bundler / dev server | Vite (+ `vite-plugin-electron`) | ^8 |
| Unit testing (frontend) | Vitest + Testing Library + jsdom | ^4 |
| E2E testing | Playwright | ^1.44 |
| Lint/format (frontend) | ESLint + Prettier | ^8 / ^3 |
| Text diffing | `diff` | ^9 |
| Backend language | Python | ≥ 3.11 |
| HTTP API framework | FastAPI | 0.115.12 |
| ASGI server | Uvicorn `[standard]` | 0.34.3 |
| Validation / models | Pydantic v2 | 2.13.4 |
| Secrets storage | keyring (OS keychain) | 25.6.0 |
| Async HTTP client | httpx | 0.28.1 |
| Model SDKs | `openai`, `anthropic`, `google-genai` | latest |
| Templating | Jinja2 | ≥ 3.1 |
| Persistence | SQLite (stdlib `sqlite3`) | built-in |
| Backend bundling | PyInstaller | ≥ 6 |
| Installer packaging | electron-builder | ^26 |
| Backend lint/types | ruff · black · mypy `--strict` | pinned |
| Backend tests | pytest (+ asyncio, cov) | 8.3.x |
| CI/CD | GitHub Actions (3-OS matrix) | — |

### 2.2 Why each choice was made

#### Electron
- **What:** Chromium + Node.js desktop shell wrapping the React UI.
- **Why:** The product must be a *self-contained desktop app* (one installer per OS) that can spawn and supervise a local Python backend process, hold per-session secrets, and talk to `127.0.0.1` without CORS pain. A browser tab cannot spawn child processes or generate session tokens; Electron can. It also gives access to OS keychain integration points and per-platform installers via electron-builder.

#### React + TypeScript
- **What:** Component-based UI with static typing.
- **Why:** The canvas app has heavy interactive state (node graphs, live run events, undo/redo). TypeScript is mandatory project-wide (`tsc --noEmit` in CI; ESLint's `no-explicit-any` is an **error**) because the pipeline data model is mirrored across three languages — loose types would break the contract discipline.

#### React Flow
- **What:** Purpose-built node-graph canvas library for React.
- **Why:** Building a node editor (pan/zoom/minimap/custom nodes/edges/handles) from scratch is months of work. React Flow provides the graph interaction primitives so development effort goes into *domain* features: typed ports, connection validation, run-state overlays.

#### Vite
- **What:** Dev server + production bundler for the renderer.
- **Why:** Instant HMR for canvas/UI iteration, native ESM, and `vite-plugin-electron` to build the main/preload processes in the same toolchain. Replaces the older webpack/electron-forge complexity.

#### Vitest + Testing Library + jsdom
- **What:** Vite-native unit test runner with DOM emulation.
- **Why:** Shares the same transform pipeline as the app (no dual config), fast watch mode, and first-class TSX support. Testing Library enforces behavior-over-implementation assertions. 63 frontend unit tests run on every push.

#### Playwright
- **What:** Real-browser end-to-end testing.
- **Why:** The critical user journey (load template → connect nodes → run → see streamed output) crosses Electron IPC, HTTP, and WebSocket boundaries that unit tests cannot cover.

#### FastAPI + Pydantic v2
- **What:** Async Python API framework with declarative validation models.
- **Why:** The engine is fundamentally async (parallel branches, streaming token deltas, cancellation). FastAPI runs on asyncio natively, auto-validates request bodies against Pydantic models, and serves WebSocket endpoints alongside REST in one app. Pydantic v2 is also used as the *internal* data model for compiled DAGs — one validation story from HTTP boundary to executor.

#### Uvicorn
- **What:** ASGI server hosting FastAPI.
- **Why:** Production-grade async server, spawns cleanly as an Electron child process bound to `127.0.0.1`.

#### SQLite (stdlib `sqlite3`)
- **What:** Embedded file database storing runs, checkpoints, traces, deployments.
- **Why:** Local-first means zero external dependencies: no DB server to install, no daemon to babysit. Stdlib driver keeps the dependency tree small (no ORM by design). Perfect fit for single-user desktop workloads where every run is recorded durably.

#### keyring
- **What:** Cross-platform OS keychain access (Windows Credential Manager, macOS Keychain, Linux secret service).
- **Why:** API keys are the crown jewels. They are never stored in env vars, config files, or pipeline JSON — only the OS keychain, read at runtime, failing loudly if absent (never falling back to a dummy key).

#### Official provider SDKs (`openai`, `anthropic`, `google-genai`) + httpx
- **What:** First-party clients per cloud provider; httpx for generic OpenAI-compatible HTTP (Ollama).
- **Why:** Project rule: *"No hallucinated APIs — use official SDKs."* Each provider gets native support for structured output modes and streaming; httpx covers the uniform OpenAI-compatible surface that Ollama exposes.

#### Jinja2 (sandboxed)
- **What:** Templating engine for Transform nodes.
- **Why:** Users need string formatting/joining between nodes. Raw code execution (`eval`) is banned by design; Jinja templates give deterministic, sandbox-safe transformations instead.

#### PyInstaller + electron-builder
- **What:** PyInstaller freezes the Python backend into a single executable (`komvos_backend.exe`); electron-builder produces NSIS/portable (Windows), DMG (macOS), AppImage/deb (Linux).
- **Why:** End users get "one installer, no terminals" — the backend binary ships as an Electron `extraResource` and auto-starts. The packaged binary itself is tested standalone, not just in dev mode.

#### ruff · black · mypy --strict · ESLint
- **What:** Fast Python linter, formatter, strict type checker; JS linter with strict rules.
- **Why:** All four are hard CI gates. Strict typing on both sides of the IPC boundary is what makes the cross-language schema mirroring trustworthy.

#### GitHub Actions (multi-OS matrix)
- **What:** CI running a reusable verification workflow (`verify.yml`) on every push; builds gated on it; releases additionally gated.
- **Why:** A tag push literally cannot publish installers unless every test/lint/type gate passed. Matrix coverage matches the three shipped platforms.

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Desktop App  (Electron + React + TypeScript)            │
│  • React Flow canvas   • Chat mode   • Live monitor      │
└───────────────────────────┬──────────────────────────────┘
                            │  local HTTP + WebSocket (127.0.0.1)
┌───────────────────────────┴──────────────────────────────┐
│  Backend  (Python · FastAPI)                             │
│  • Compiler:  graph → typed, validated DAG               │
│  • Scheduler: parallel branches, loops, budget, cancel   │
│  • Executors: model / judge / router / transform / ...   │
│  • State:     SQLite trace + checkpoints                 │
│  • Serve:     OpenAI-compatible deployments              │
│  • Endpoints: ModelEndpoint abstraction ↓                │
└───────────────────────────┬──────────────────────────────┘
            ┌───────────────┼────────────────┐
      ┌─────┴─────┐   ┌──────┴──────┐   ┌─────┴──────┐
      │  Cloud    │   │   Ollama    │   │  (EXO —    │
      │  APIs     │   │  (local)    │   │  roadmap)  │
      └───────────┘   └─────────────┘   └────────────┘
```

### 3.1 Process model

1. Electron starts and spawns the bundled Python backend as a **child process**.
2. The backend binds exclusively to **`127.0.0.1`** (never `0.0.0.0`) and generates/exchanges a **per-session auth token** with Electron at spawn time.
3. The renderer talks to the backend over local HTTP (REST) and WebSocket (live run streams).
4. Every request — including the WebSocket handshake — must carry the session token; auth fails closed.

### 3.2 Backend modules

| Module | Responsibility |
| --- | --- |
| `komvos/compiler` | Transforms raw pipeline JSON into a typed, validated DAG. Single gate that rejects invalid pipelines before execution. Enforces acyclicity, port-type compatibility, endpoint-reference resolution, structured stop conditions, finite loops, and access-node rules. Computes per-node effective policies. |
| `komvos/scheduler` | Executes the validated DAG: topological ordering, parallel branches via `asyncio` (no thread pools), loop subgraphs with bounded iterations, budget enforcement (`$` cap or wall-clock cap → halt + partial trace), kill-switch handling. Endpoint-agnostic by design. |
| `komvos/executors` | Per-node logic: Input, Output, Model (streaming + response formats), Judge (score & select best), Router (conditional branch), Transform (Jinja templating), Loop. Includes the structured-output repair path. |
| `komvos/endpoints` | `ModelEndpoint` implementations: `CloudEndpoint` (openai \| anthropic \| google \| openai_compatible) and `OllamaEndpoint`. Reads keys from the OS keychain. Future `ExoEndpoint` slots in with zero scheduler changes. |
| `komvos/state` | SQLite persistence: `runs`, per-node checkpoints (written *between* nodes, never mid-token), ordered trace events (status changes, token chunks, cost updates, loop iterations). Enables resume-from-checkpoint after failures. |
| `komvos/api` | FastAPI app bound to loopback. Routes: `GET /health`, `POST /pipelines/run`, `GET /models` (live provider model lists), `WS /ws/run/{id}` (status/token/cost stream), `POST /runs/{id}/stop` (kill switch). Session-token auth everywhere. |
| `komvos/serve` | Deploys pipelines as **OpenAI-compatible HTTP endpoints**: deployment store, `kv_...` API keys (SHA-256 hashed at rest), per-deployment token-bucket rate limiting, chat-completions mapping, SSE streaming. Uses the exact same runner/scheduler as canvas runs. |

### 3.3 Frontend modules

| Folder | Responsibility |
| --- | --- |
| `src/canvas/` | React Flow surface: node renderers (Input, Output, Model, Loop, Judge, Router, Transform, Access), color-coded typed ports with real-time compatibility validation, custom edges, serializer (schema v2.1 round-trip tested), undo/redo. |
| `src/panels/` | LeftSidebar (draggable node palette), RightPanel (per-node config: endpoint ref, system prompt, temperature, max_tokens, response_format, role), MonitorPanel (live status/tokens/cost table + KILL SWITCH), TraceModal (post-run IO, loop history, cost breakdown), ChatPanel ("talk to your pipeline" mode). |
| `src/state/` | `pipelineStore` (graph document) and `runStore` (live run state). |
| `src/hooks/` | `useRunSocket` (WebSocket event ingestion), `useBackend` (spawn/health supervision), `usePipelineActions` (import/export with schema-version checks). |
| `src/components/` | Modals & tours: Settings, Export (scrubs secrets), Deploy (LAN risk confirmation), Publish, Custom Node, onboarding Tour. |

---

## 4. Core Design Decisions

These are the deliberate architectural commitments that shape everything else.

### 4.1 The `ModelEndpoint` abstraction (the single most important constraint)

> "The scheduler is endpoint-agnostic: it never knows whether a node is cloud, local, or sharded."

All model I/O flows through one protocol. The scheduler, executors, and state layer are written once against that protocol. Consequences:

- Mixing GPT-5-class cloud calls and a free local Qwen in **one graph** is not a special feature — it falls out of the abstraction.
- Adding a new backend (e.g., EXO distributed clusters on the R1 roadmap) requires **zero scheduler changes**.
- Tests inject mock endpoints; production injects cloud/Ollama endpoints.

### 4.2 Typed ports and compile-time validation

Ports carry types (`text | number | boolean | json | image | audio`). The compiler validates every edge connection, acyclicity, endpoint references, and loop structure **before** a run starts — structural errors surface instantly, not mid-run.

Loops are modeled as **subgraphs**, not back-edges in the main graph, which keeps the primary DAG acyclic and analyzable. Every loop must declare a finite `max_iterations` and an `on_max` policy (`return_best | fail | return_last`). `stop_when` accepts only structured comparison operators (`== != > < >= <= contains`) — never raw code or `eval`.

### 4.3 Access Nodes — capability-based security

An Access Node dropped onto the canvas declares what its downstream subgraph is permitted to reach: allowed providers, local-model permission, network permission, allowed domains, `max_cost_usd`, `max_tokens`.

When multiple access nodes govern a node, their policies combine by **intersection — the most restrictive wins, never the union**:

| Field | Combination |
| --- | --- |
| `providers` | set intersection |
| `allow_local_models` | logical AND |
| `allow_network` | logical AND |
| `allowed_domains` | intersection; empty list = "unrestricted" (identity element) |
| `max_cost_usd` | lower wins; `null` = no ceiling loses |
| `max_tokens` | lower wins; `null` = no ceiling loses |

**Rationale:** moving a node further downstream can only ever *take capabilities away, never add them*. If ancestors combined by union, wiring an unrelated permissive gate into the graph could widen a tightly-scoped node's reach — making the permission layer something an edge could accidentally defeat.

Enforcement happens in the endpoint layer **before any outbound request leaves the machine**, raising `AccessDeniedError` with actionable messages surfaced over a dedicated WS event.

Two compile modes encode the trust boundary:
- **`"local"`** (canvas run): a pipeline with no access node is permissive — backwards compatible.
- **`"served"`** (exposed via HTTP): a pipeline with no access node is **refused**, because once a pipeline is reachable by third parties, "what can this thing touch" stops being an inspector and becomes a security boundary.

### 4.4 Structured-output repair path

When a model node requires JSON but receives prose:
1. Prefer the provider's **native structured-output mode**.
2. Fallback: **repair-prompt retry** with a hard cap (default 3 attempts).
3. On persistent failure: clear error; the raw model output is stored in the trace — **never silently passed**.

### 4.5 One execution engine, two front doors

Canvas runs and served API requests drive the **identical** `PipelineRunner` + `Scheduler` event queue. The serve layer merely translates the same WS event stream into HTTP shapes (buffered JSON, or SSE deltas for `stream: true`). There is no second execution pipeline to drift out of sync — and served runs recompile fresh each request, so policy enforcement is always current.

---

## 5. Security Model

Security is treated as layered defense-in-depth rather than a checklist:

| Layer | Mechanism |
| --- | --- |
| **Secrets at rest** | API keys live only in the OS keychain via `keyring`. Never hardcoded, never in env vars, never in files. Missing keys raise explicit named errors — no dummy-key fallback. |
| **Secrets in transit/artifacts** | Template export scrubs secrets; pipeline JSON forbids secrets/device pins by schema rule. |
| **Network exposure** | Backend binds to `127.0.0.1` only. LAN exposure is opt-in per deployment, defaults off, and demands explicit confirmation naming the risk in the UI; a runtime guard (`_enforce_lan_policy`) keeps non-opted deployments inert even if the process somehow listens more widely. |
| **Process auth** | Per-session token generated by Electron at spawn, required on every request and WS handshake. Dev mode (`KOMVOS_DEV=1`) fails closed and must be opted into explicitly; never set for packaged builds. |
| **Deployment credentials** | Two deliberately non-interchangeable credential classes: session tokens (management plane) vs deployment keys (`kv_` + 32 bytes entropy, only SHA-256 hash persisted, compared with `hmac.compare_digest`). |
| **Abuse containment** | Per-deployment token-bucket rate limiting (default 60 req/min); per-run hard budget caps (`$` and wall-clock); global kill switch; Access-Node runtime enforcement blocks unauthorized outbound calls before they happen. |
| **Code safety** | No `eval` anywhere in the execution path; transforms are sandboxed templating; stop conditions are structured data. |
| **Supply chain hygiene** | Pinned dependency versions; official SDKs only; CI verifies lint/type/test gates before any artifact ships. |

---

## 6. Feature Reference

| Feature | Description |
| --- | --- |
| 🎨 Visual Pipeline Canvas | Drag-and-drop node editor (React Flow) with typed, color-coded ports, real-time connection validation, minimap, undo/redo. |
| 🔀 Hybrid Cloud + Local | Cloud (OpenAI, Anthropic, Google) and local (Ollama) models side-by-side in one pipeline. |
| 💬 Chat / Use Mode | After building, switch to a ChatGPT-style interface and talk to your pipeline with streamed responses. |
| 🔁 Logic Nodes | Loops (safe structured stop conditions), Judge (select best output), Router (conditional branching), Transform (sandboxed templating), Compare (output diff). |
| 📊 Live Execution Monitor | Nodes pulse, tokens stream, per-node cost/latency update in real time over WebSocket. |
| 💰 Cost & Budget Controls | Pre-run cost/latency estimates, hard per-run budget cap, wall-clock cap, kill switch. |
| 🧩 Template Gallery | 10 ready-to-run pipelines covering the most useful multi-model patterns. |
| 🗂️ Full Trace & Persistence | Every run recorded to SQLite — per-node I/O, loop history, tokens, cost — with checkpoint/resume. |
| 🔐 Security-First | Keychain-stored keys, scrubbed exports, sandboxed transforms, access enforcement. |
| 🖥️ Self-Contained Desktop App | One installer per OS; bundled backend auto-starts — no terminals, no manual setup. |
| 🌐 Serve as API | Any pipeline becomes an OpenAI-compatible endpoint usable from LangChain/OpenWebUI/Cursor/raw SDKs. |
| 🔌 Access Control | Access Nodes discover requested capabilities and enforce grants at runtime. |

---

## 7. What Makes Komvos Different From Competitors

### 7.1 Landscape

| Tool | Category | Where it falls short for multi-model orchestration |
| --- | --- | --- |
| **LangChain / LlamaIndex** | Code-first frameworks | Powerful but steep learning curve; orchestration lives in code; no visual debugging; every architecture change is a refactor. |
| **Flowise / Langflow / Dify** | Web-hosted visual builders | Run as server apps in the browser/Docker; typically organize around *one* LLM plus helpers; weaker secret handling (env vars/config); limited true hybrid cloud+local mixing; security is permissive-by-default. |
| **ComfyUI** | Image-generation node editor | Excellent for Stable Diffusion graphs, but not designed for text/reasoning pipelines, cost governance, or serving LLM workflows as APIs. |
| **n8n / Zapier / Make** | General automation | Integration-first, AI-second: no native concepts for tokens, cost caps, model routing, judges, or verification loops. |

### 7.2 Komvos' differentiators

1. **True hybrid cloud + local in one graph.** The uniform `ModelEndpoint` abstraction makes "GPT-4o verifies the local model's draft" a first-class pattern, not a workaround. Competitors treat local models as an afterthought bolted onto a cloud-centric design.

2. **Desktop-native, privacy-first.** Everything runs on your machine, bound to loopback. Your prompts never pass through a vendor's orchestration cloud. Web-based competitors require hosting a server (often exposing more than intended).

3. **Access Nodes — a real capability system.** No competitor offers graph-scoped permission boundaries with intersection semantics enforced *before* outbound calls. This turns "what is this pipeline allowed to do?" into a visible, enforceable part of the diagram — and served pipelines are refused outright without one.

4. **Cost governance inside the engine.** Pre-flight estimates, hard dollar/token/wall-clock caps, and a kill switch are engine semantics, not UI sugar. Automation platforms bill you after the fact; Komvos stops you *during*.

5. **Your pipeline is an OpenAI-compatible API.** Build visually, then point Cursor/LangChain/OpenWebUI at `localhost/v1` and use your deployment like any model name. Visual builders generally stop at "export JSON"; code frameworks require you to write the serving layer.

6. **Full forensic observability.** Every run persists complete per-node I/O, loop iterations, token counts, and costs to SQLite, with checkpoint/resume. You can answer "why did this output change?" weeks later — impossible in most chat wrappers and rare even in frameworks.

7. **Three-language contract discipline.** One pipeline schema mirrored across JSON Schema, Python (Pydantic, `mypy --strict`), and TypeScript (with `no-explicit-any` as an error), kept in lockstep and round-trip tested. Most visual builders serialize loosely and pay for it in import/export bugs.

8. **Zero-terminal UX.** The Python engine ships frozen inside the installer and self-starts under an authenticated channel. Comparable stacks routinely ask users to run Docker + pip + npm simultaneously.

### 7.3 Positioning summary

> Komvos is not trying to be another LangChain wrapper or a hosted workflow SaaS. It is the missing **desktop workstation for multi-model AI engineering** — where security boundaries, budgets, observability, and hybrid inference are core engine features rather than plugins.

---

## 8. Template Gallery

Ten first-party templates ship with the app (all validate against `shared/pipeline.schema.json`):

| Template | Pattern |
| --- | --- |
| `solver-verifier-judge.json` | DeepSeek-style Solver → Verifier → Judge loop (flagship demo). |
| `simple-chat.json` | Minimal single-model chat pipeline. |
| `rag-pipeline.json` | Retriever → Generator → Validator. |
| `ensemble-voting.json` | N models answer; aggregator selects best. |
| `cascade.json` | Cheap/fast model first; escalate on low confidence. |
| `debate.json` | Two models argue; one adjudicates. |
| `self-refine.json` | Model critiques and revises its own output. |
| `multi-perspective.json` | Three independent views fused by one aggregator. |
| `language-translator.json` | Dedicated translation flow. |
| `json-extractor.json` | Structured-data extraction with repair fallback. |

---

## 9. Quality, Testing & CI

### Test suites
- **Backend:** ~352 pytest tests (compiler, scheduler, executors, endpoints, API, serve, schema, fuzz tests) — all green in CI.
- **Frontend:** 63 unit tests (Vitest + Testing Library) plus Playwright e2e specs.
- **Real-world verification:** executed end-to-end against a genuine local model (`qwen2.5:3b`): full pipeline execution, streaming, loop termination, JSON-repair, cancellation, partial-trace persistence.
- **Packaged-binary verification:** the PyInstaller-frozen backend was tested standalone — running real pipelines through the executable, not just dev mode.

### Hard gates on every push (reusable `verify.yml`)
| Gate | Command-level standard |
| --- | --- |
| Backend lint | `ruff check .` — zero findings |
| Backend types | `mypy komvos` with `strict = true` — zero errors, no baseline file |
| Backend tests | `pytest -q --cov` — must pass |
| Frontend types | `tsc --noEmit` — clean |
| Frontend lint | ESLint `--max-warnings 0`, `no-explicit-any` as error |
| Frontend tests | `vitest run` — all green |

Build jobs declare `needs: verify`; release workflows call the same verifier, so **a tag push cannot publish installers without passing everything**.

### Engineering ground rules (from `AGENT.md`)
1. No dummy/fake/mock data in app code — real APIs only; fakes confined to clearly-named test files.
2. No silent placeholders — raise explicit errors instead of stubbed returns.
3. No secrets in code or files — keychain only.
4. No hallucinated APIs — official SDKs, always.
5. Honor contracts — shared schema changes are BREAKING CHANGE events requiring re-sync.
6. Types + tests mandatory — full type hints, every feature ships with a test.

---

## 10. Build, Packaging & Distribution

```
Python backend ──PyInstaller──▶ komvos_backend(.exe)
                                     │  (electron-builder extraResource)
React/Electron app ──vite build──▶  ▼
                          electron-builder targets
        ┌─────────────────────┼──────────────────────┐
   Windows: NSIS installer   macOS: DMG          Linux: AppImage + deb
   + portable exe           (arm64)              + tar.gz
```

- Output versioned installers land in `apps/dist/`; release artifacts attach to GitHub Releases.
- Windows SmartScreen/macOS Gatekeeper notes for unsigned builds are documented in the README download section.

---

## 11. Repository Structure

```
.
├── apps/desktop/            # Electron + React + TypeScript desktop app
│   └── src/
│       ├── canvas/          # Node editor, typed ports, serialization, undo/redo
│       ├── panels/          # Palette, config, monitor, trace, chat panels
│       ├── state/           # pipelineStore, runStore
│       ├── hooks/           # useRunSocket, useBackend, usePipelineActions
│       ├── components/      # Modals (settings/export/deploy/publish), tour
│       ├── contexts/        # Toast notifications
│       └── ipc/, preload    # Electron main ↔ renderer bridge
├── backend/                 # FastAPI execution engine (Python package: komvos)
│   └── komvos/
│       ├── compiler/        # graph → validated DAG + access-policy computation
│       ├── scheduler/       # topo sort, parallel branches, loops, budget, cancel
│       ├── executors/       # per-node-type implementations
│       ├── endpoints/       # ModelEndpoint impls (cloud, ollama)
│       ├── serve/           # OpenAI-compatible deployments, keys, rate limits
│       ├── state/           # SQLite runs/checkpoints/traces
│       └── api/             # FastAPI routes + WebSocket streaming
├── shared/                  # Single source of truth contracts
│   ├── pipeline.schema.json # JSON Schema v2.1 (canonical pipeline format)
│   └── types.ts             # Mirrored TypeScript types
├── templates/               # 10 first-party pipeline templates
├── packaging/               # PyInstaller build scripts
├── docs/                    # Reports & documentation (this file)
└── .github/workflows/       # CI: verify (reusable) + build + release
```

Every module folder carries its own README documenting ownership, purpose, rules, and phase history — deeper detail lives there.

---

## 12. Running the Project

### End users
Download an installer from Releases and launch — the backend starts automatically. For local models, install [Ollama](https://ollama.com) and pull e.g. `ollama pull qwen2.5:3b`.

### Developers
Backend (Python 3.11+):
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate   # or source .venv/bin/activate
pip install -e ".[dev]"
$env:KOMVOS_DEV = "1"                             # dev-only opt-in; fails closed otherwise
uvicorn komvos.api.main:app --host 127.0.0.1 --port 8000
```

Frontend (Node 18+):
```bash
cd apps/desktop
npm install
npm run dev
```

Tests:
```bash
cd backend && python -m pytest tests/ -v          # backend suite
cd apps/desktop && npm test                       # frontend suite
cd apps/desktop && npm run typecheck && npm run lint
```

---

## 13. Roadmap

| Stage | Status | Scope |
| --- | --- | --- |
| **R0 — Core** | ✅ Complete | Visual editor, hybrid cloud/local execution, chat mode, templates, packaged desktop app, serving layer, access-control system. |
| **R1 — Distributed Local** | 🔜 Planned | Run 70B+ models across multiple machines via the [EXO](https://github.com/exo-explore/exo) framework behind the same `ModelEndpoint` abstraction — scheduler unchanged. |
| **R2 — Community** | 🔜 Planned | Template sharing, custom model integrations, marketplace. |

---

<div align="center">

**Komvos** — _Make multi-model AI orchestration as easy as connecting nodes._

</div>
