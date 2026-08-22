# Komvos — Master Implementation Prompt

**Repo:** `sakshamwadhankar/Far-Away` · **Branch strategy:** one branch per phase, merged in order.

---

## How to use this prompt

Paste this whole document into your coding agent (Claude Code, Cursor, etc.) as the opening message. Then work **one phase at a time** — do not paste the whole thing and say "do it all." After each phase, run the gate command listed for that phase and confirm it passes before moving on.

---

## Context for the agent

You are working on **Komvos**, an Electron + React desktop app for building and running multi-model LLM pipelines on a visual canvas, backed by a local FastAPI server.

**Read these before writing any code:**

- `AGENT.md` (root) — the project's engineering rules. They are binding. In particular: no mock/fake data in app code, no silent placeholders, no secrets in code, full type hints, every feature ships with a test, and every reply ends with _files changed / how to run / how to test / contracts touched / blockers_.
- `.agents/rules/agentrules.md`
- `NeuralFlow_TRD_v1.md` and `NeuralFlow_PRD_v3.md` — the original technical and product requirement docs.
- `shared/pipeline.schema.json` and `shared/types.ts` — the shared contract between backend and frontend. **Any change here is a BREAKING CHANGE and must be flagged explicitly, with both sides updated in the same commit.**

**Architecture you're working inside:**

```
Electron main (apps/desktop/src/main.ts)
  └─ spawns PyInstaller-bundled FastAPI backend on 127.0.0.1 with a per-session token
       └─ /pipelines/run  →  compiler (DAG + validation)
                          →  scheduler (tiered async engine, loops, CancelToken)
                          →  executors (model / logic / input_output)
                          →  endpoints (cloud / ollama / mock)
                          →  state (SQLite trace persistence)
       └─ /ws/run/{run_id} streams events back to the renderer
```

**Naming note:** the Python package is `neuralflow`, the product is `Komvos`, the repo is `Far-Away`. A rename is half-finished. Do **not** attempt a mass rename in any phase except Phase 5 — it will wreck the PyInstaller specs and the keyring service string, and it will bury the real work in diff noise.

---

# PHASE 0 — Repo hygiene and CI (blocking, do this first)

### 0.1 Fix the `.gitignore` encoding bug

`.gitignore` is currently **UTF-16LE**, not UTF-8. `file .gitignore` reports `data`. Everything after the `.pytest_cache/` line is full of null bytes, so git silently ignores those rules. Verify with `git check-ignore -v scratch/test_backend.py` — it returns nothing.

Rewrite the entire file as **UTF-8, LF line endings**, preserving all intended rules including the currently-broken tail:

```
apps/dist/
apps/desktop/dist-electron/
scratch/
packaging/dist/
packaging/build/
*.dmg
*.exe
*.AppImage
*.deb
*.rpm
```

Then untrack the artifacts that got committed because of the bug:

```bash
git rm -r --cached apps/desktop/dist-electron apps/desktop/playwright-report apps/desktop/test-results scratch
```

Keep `apps/desktop/package-lock.json` tracked — that one belongs in the repo.

**Gate:** `file .gitignore` reports `ASCII text` or `UTF-8 Unicode text`, and `git check-ignore -v scratch/test_backend.py` returns a match.

### 0.2 Add the missing ESLint config

`apps/desktop/package.json` has a `lint` script and the ESLint 8 plugins in devDependencies, but **there is no config file anywhere** — no `.eslintrc*`, no `eslint.config.js`. The script cannot run.

Create `apps/desktop/.eslintrc.cjs` for ESLint 8 with `@typescript-eslint`, `react-hooks`, and `react-refresh`. Set `@typescript-eslint/no-explicit-any` to `error` — `AGENT.md` rule 6 forbids loose `any`. Fix every violation this surfaces; do not add blanket disable comments.

**Gate:** `npm run lint` exits 0.

### 0.3 Make CI actually test

`.github/workflows/build.yml` and `release.yml` currently install dependencies, build the backend executable, build the frontend, and package Electron — **and never run a single test.** The README badge claims "144 passing" and nothing verifies it.

Add a `test` job to `build.yml` that runs **before** `build` (make `build` depend on it via `needs: test`), on `ubuntu-latest` only:

```yaml
- pip install -e ".[dev]"  (in backend/)
- ruff check .
- mypy neuralflow
- pytest -q --cov=neuralflow
- npm ci                   (in apps/desktop/)
- npm run typecheck
- npm run lint
- npm run test
```

If `mypy --strict` (already configured in `pyproject.toml`) produces a large existing error count, do **not** weaken the config. Add a `mypy.ini` baseline or a per-module ignore list, report the count in your summary, and leave a `TODO(typing)` issue list — but the gate must be green and must not silently pass on new errors.

Also fix the badge in `README.md` to reflect the real number, or replace it with a live GitHub Actions status badge pointing at the workflow.

**Gate:** the full `test` job passes locally via `act` or on a pushed branch.

### 0.4 Add `LICENSE`

`README.md` shows an MIT badge and there is no `LICENSE` file, which means the code is legally all-rights-reserved. Add a standard MIT `LICENSE` file with the correct copyright holder name and year.

### 0.5 Fix the broken quick-start command

`README.md` line ~115 says:

```
uvicorn Komvos.api.main:app --port 8000
```

The package is `neuralflow`. Anyone following the README from source hits `ModuleNotFoundError` on the first step. `start.bat` already has it right — make the README match:

```
uvicorn neuralflow.api.main:app --host 127.0.0.1 --port 8000
```

**Commit:** `chore: fix gitignore encoding, add eslint config + LICENSE, run tests in CI`

---

# PHASE 1 — Security hardening

This phase is a **prerequisite for Phase 3.** Do not expose a pipeline over HTTP until these are done.

### 1.1 Lock down CORS

`backend/neuralflow/api/main.py` currently has:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

`allow_origin_regex=".*"` with `allow_credentials=True` means **any webpage the user visits while the backend is running can drive their pipelines and spend their API credits.**

Replace with an explicit allowlist built at startup:

- the Electron renderer origin (`file://` and the custom app scheme, whichever `main.ts` actually loads)
- `http://localhost:5173` and `http://127.0.0.1:5173` **only when `KOMVOS_DEV=1`**

Also gate `docs_url="/docs"` behind `KOMVOS_DEV=1` — it currently exposes the full API surface unconditionally.

### 1.2 Make dev-mode auth fail closed

`backend/neuralflow/api/auth.py` currently accepts **any non-empty bearer token** when `NEURALFLOW_SESSION_TOKEN` is unset, logging a warning. Combined with open CORS this is a full bypass.

Change it so the fallback requires an **explicit** `KOMVOS_DEV=1` environment variable. Without both the token unset _and_ `KOMVOS_DEV=1`, return 401. Update `backend/tests/` fixtures to set `KOMVOS_DEV=1` explicitly rather than relying on the implicit fallback.

Apply the same fix to the WebSocket handler at `/ws/run/{run_id}` — it currently only rejects a mismatched token when `session_token` is set, so an unset token accepts anything.

### 1.3 Harden the Electron BrowserWindow

`apps/desktop/src/main.ts` `createWindow()` sets only `preload` in `webPreferences`. Electron 42's defaults are safe today, but a future upgrade or a stray edit can flip them silently. Set them explicitly:

```ts
webPreferences: {
  preload: path.join(__dirname, 'preload.js'),
  contextIsolation: true,
  nodeIntegration: false,
  sandbox: true,
  webSecurity: true,
}
```

Also add navigation guards, which are currently missing entirely — without them, a link in a model's output can navigate the app window or spawn an unrestricted one:

```ts
win.webContents.setWindowOpenHandler(({ url }) => {
  shell.openExternal(url); // external links go to the real browser
  return { action: "deny" };
});
win.webContents.on("will-navigate", (event, url) => {
  if (!isAllowedOrigin(url)) event.preventDefault();
});
```

### 1.4 Stop blocking the event loop on SQLite

`backend/neuralflow/scheduler/runner.py` calls `save_run`, `save_node_execution`, `save_loop_iteration`, and `update_run_status` **synchronously on the asyncio thread**. Under a fast multi-node streaming run this stalls the WebSocket event pump and makes the live monitor stutter.

- Wrap every `StateManager` call in the async path with `await asyncio.to_thread(...)`, **or** convert `StateManager` to an async facade over a thread pool. Pick one and be consistent.
- Add `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL` to `_init_db` in `backend/neuralflow/state/sqlite.py`. You open a fresh connection per operation with `timeout=5.0`; WAL prevents writer contention from turning into 5-second stalls.

**Tests:** add a test asserting the event loop is not blocked — e.g. a run that emits N events while a slow DB write is in flight still delivers events within a bounded time.

**Commit:** `fix(security): restrict CORS, fail-closed auth, harden electron, unblock event loop`

---

# PHASE 2 — The Access Node

**Goal:** a node on the canvas that shows exactly what capabilities a pipeline can reach, and _enforces_ those limits at runtime. This is the permission layer. It must land before Phase 3, because once a pipeline is reachable over HTTP, "what can this thing touch" stops being an inspector and becomes a security boundary.

### 2.1 The model (BREAKING CHANGE — flag it)

Add to `backend/neuralflow/compiler/models.py`:

```python
NodeType = Literal["input", "output", "model", "loop", "judge",
                   "router", "transform", "compare", "access"]   # ← new

class AccessPolicy(BaseModel):
    providers: list[EndpointKind] = Field(default_factory=list)
    allow_local_models: bool = False
    allow_network: bool = False
    allowed_domains: list[str] = Field(default_factory=list)
    max_cost_usd: float | None = None
    max_tokens: int | None = None
```

Add `access_policy: AccessPolicy | None = None` to `NodeConfig`.

Mirror all of this in `shared/pipeline.schema.json` and `shared/types.ts` **in the same commit**. Bump `schema_version` to `"2.1"` and write a migration in the compiler that treats a `2.0` pipeline as "no access node present" (see 2.3 for what that means).

### 2.2 Compiler: compute the effective policy

In `backend/neuralflow/compiler/dag.py` and `validation.py`:

- An `access` node applies its policy to **every node downstream of it** in the DAG.
- Compute an _effective policy_ per node by walking ancestors. When multiple access nodes are ancestors of the same node, take the **intersection** (most restrictive wins) — never the union. Document this rule in `backend/neuralflow/compiler/README.md`.
- Fail compilation with a clear, actionable error when a node requests something its effective policy doesn't grant. The message must name the node, the capability, and the access node that denied it. Example: `Node 'summarize' (model:anthropic) requires provider 'anthropic', denied by access node 'gate-1' which grants: [openai, ollama].`
- An `access` node has no data ports — it is a scope marker, not a transform. Connections into and out of it carry no payload. Enforce this in validation.

### 2.3 Backward compatibility, made explicit

For pipelines with no access node (all existing `2.0` templates), the effective policy is **permissive** — everything allowed — so nothing breaks today. **But** in Phase 3, a pipeline with no access node is **refused for deployment.** Local canvas runs stay permissive; anything exposed over HTTP requires an explicit policy. Encode this as two distinct compile modes: `compile_pipeline(pipeline, mode="local" | "served")`.

### 2.4 Runtime enforcement

- Add `policy: AccessPolicy` to `ExecutorContext` in `backend/neuralflow/executors/base.py`.
- `CloudEndpoint` (`endpoints/cloud.py`) raises a typed `AccessDeniedError` before making any HTTP call if its provider is not in the effective policy. **Check before the request, not after** — a denied call must never leave the machine.
- `OllamaEndpoint` checks `allow_local_models`.
- `max_cost_usd` and `max_tokens` from the policy feed the existing `CancelToken` budget path in `scheduler/engine.py`. Reuse that machinery; do not build a second budget system.
- Emit a new `access_denied` WebSocket event so the UI can show _which_ node was blocked and why.

### 2.5 The UI

Create `apps/desktop/src/canvas/nodes/AccessNode.tsx`, following the existing `PipelineNode.tsx` conventions.

The node body renders a **live capability list** for everything downstream of it, with three states:

| State                  | Meaning                                                                              |
| ---------------------- | ------------------------------------------------------------------------------------ |
| **Granted & used**     | policy allows it, a downstream node actually calls it                                |
| **Granted & unused**   | policy allows it, nothing downstream uses it → offer a one-click "tighten" to revoke |
| **Requested & denied** | a downstream node needs it, policy blocks it → offer a one-click "grant"             |

That third state is the whole point of the feature: you drop an access node on the canvas, and it tells you what your pipeline is actually reaching for.

Toggling a capability writes back into `config.access_policy` and re-runs client-side validation immediately — no run required to see the effect.

Add the node to the palette in `LeftSidebar.tsx` and wire its inspector into `RightPanel.tsx`.

### 2.6 Tests

- `backend/tests/test_access_policy.py` — intersection semantics for multiple ancestor access nodes, denial error messages, the `local` vs `served` compile modes.
- Extend `test_compiler_fuzz.py` so generated pipelines include access nodes.
- Runtime test: an endpoint denied by policy makes **zero** outbound HTTP calls (assert on a mocked transport, in a clearly-named test file per `AGENT.md` rule 1).
- Frontend: `AccessNode.test.tsx` covering all three capability states.

**Commit:** `feat(access): add access node with compile-time and runtime capability enforcement — BREAKING: schema_version 2.1`

---

# PHASE 3 — Serve pipelines as an API

**Goal:** turn any built pipeline into a callable HTTP endpoint, so it can be used from OpenClaw, OpenWebUI, Cursor, LangChain, curl, or your own code — without opening the Komvos UI.

**Key design decision:** the primary surface is **OpenAI-compatible**. That is what makes it usable everywhere with zero adapter code — the user points an existing tool's base URL at Komvos and uses the deployment ID as the model name.

### 3.1 New module: `backend/neuralflow/serve/`

```
serve/
  __init__.py
  models.py      # Deployment, DeploymentKey pydantic models
  store.py       # SQLite persistence (extends state/sqlite.py schema)
  keys.py        # key generation, hashing, verification
  routes.py      # the FastAPI router
  README.md      # per repo convention — every package has one
```

### 3.2 Endpoints

**Management** (session-token auth, same as existing routes):

| Method   | Path                           | Purpose                                                                    |
| -------- | ------------------------------ | -------------------------------------------------------------------------- |
| `POST`   | `/deployments`                 | Deploy a pipeline. Returns `deployment_id` + **plaintext key, shown once** |
| `GET`    | `/deployments`                 | List deployments (never returns key material)                              |
| `DELETE` | `/deployments/{id}`            | Undeploy                                                                   |
| `POST`   | `/deployments/{id}/rotate-key` | New key, old one dies immediately                                          |

**Public** (deployment-key auth, `Authorization: Bearer kv_...`):

| Method | Path                       | Purpose                                                                         |
| ------ | -------------------------- | ------------------------------------------------------------------------------- |
| `POST` | `/v1/chat/completions`     | **OpenAI-compatible.** `model` = deployment ID. Supports `stream: true` via SSE |
| `GET`  | `/v1/models`               | Lists deployments in OpenAI format, so clients auto-discover them               |
| `POST` | `/v1/deployments/{id}/run` | Native JSON in/out, for pipelines that aren't chat-shaped                       |

### 3.3 Mapping pipeline I/O to the API

Add to `NodeConfig` for `input` and `output` nodes:

```python
api_field: str | None = None       # name of this node in the request/response body
api_expose: bool = True            # include this output in the API response
```

- **Chat-completions path:** the incoming `messages` array maps to the single input node marked `api_field="messages"`, or falls back to the sole input node if there's exactly one. The response `content` comes from the output node with `api_field="content"`, or the sole exposed output node. If the mapping is ambiguous — multiple candidates, none designated — **fail deployment with a clear error listing the candidates.** Do not guess.
- **Native path:** request body is `{ "<api_field>": value, ... }` keyed by input node, response is the same keyed by exposed output nodes.
- **Streaming:** reuse the existing scheduler event queue from `api/registry.py`. Token events from the designated output node become SSE `data:` frames in OpenAI's delta format. Terminal events close the stream. Do not build a second event pipeline.

### 3.4 Auth and binding — non-negotiable rules

1. **Deployment keys are separate from the session token.** Format `kv_` + 32 bytes of `secrets.token_urlsafe`. Store **only** a SHA-256 hash. Show plaintext exactly once, at creation. Compare with `hmac.compare_digest`.
2. **Bind to `127.0.0.1` by default.** LAN exposure (`0.0.0.0`) is opt-in per deployment, requires an explicit confirmation dialog in the UI naming the risk, and is never the default.
3. **A pipeline with no access node cannot be deployed.** Compile with `mode="served"` (Phase 2.3). Return a 422 whose message tells the user to add an access node.
4. **The effective access policy is enforced on every served request**, exactly as on canvas runs. A deployed pipeline can never exceed the policy shown on the canvas.
5. **Rate limiting** per deployment key — simple token bucket, configurable, default something sane like 60 req/min. An exposed endpoint with no limit is one runaway loop away from a large API bill.
6. Every served request is persisted to the existing SQLite trace tables with its `deployment_id`, so the Trace modal shows API traffic alongside canvas runs.

### 3.5 The UI

Create `apps/desktop/src/components/DeployModal.tsx`, modeled on the existing `ExportModal.tsx`/`PublishModal.tsx` patterns.

It shows:

- the endpoint URL and the deployment key (copy button, **plus an explicit "this is shown only once" warning**)
- **a summary of the effective access policy** — this is the moment the user most needs to see what they're about to expose to the network
- ready-to-paste snippets: `curl`, Python (OpenAI SDK, pointing `base_url` at the local server), JavaScript (`fetch`), and a generic "OpenAI-compatible base URL + model name" block for tools like OpenClaw and OpenWebUI
- a live status row: requests served, last call, errors
- rotate-key and undeploy buttons

Add a "Deployments" section to `LeftSidebar.tsx` listing active deployments with their status.

### 3.6 Tests

- `backend/tests/test_serve.py` — key hashing and verification, rejection of wrong/revoked keys, rate limiting, deployment refused without an access node, access policy enforced on served requests.
- OpenAI-compatibility test: a real `openai` Python SDK client pointed at the test server completes a chat call successfully. This is the acceptance criterion for the whole phase.
- Streaming test: SSE frames are well-formed OpenAI deltas and terminate correctly.
- `DeployModal.test.tsx` — key shown once, policy summary rendered, LAN toggle requires confirmation.

**Commit:** `feat(serve): expose pipelines as OpenAI-compatible HTTP endpoints with scoped deployment keys`

---

# PHASE 4 — Refactor `App.tsx`

`apps/desktop/src/App.tsx` is **962 lines** and holds canvas state, run state, token buffers, WebSocket lifecycle, and the build/use mode switch simultaneously. The rest of the frontend is decomposed reasonably; this file is the outlier, and Phases 2 and 3 both add to it.

Extract, in this order:

1. `src/hooks/useRunSocket.ts` — WebSocket lifecycle, reconnection, event buffering (the `tokenStatsBuffer` / `tokenTotalsBuffer` refs move here)
2. `src/hooks/useBackend.ts` — the port/token handshake and readiness state
3. `src/state/pipelineStore.ts` — canvas nodes, edges, undo/redo integration with the existing `useUndoRedo`
4. `src/state/runStore.ts` — per-node status, cost, token totals

**Behavior must not change.** `App.test.tsx` (524 lines) is your safety net — it must pass unmodified before and after. If a test needs changing, that's a behavior change: stop and flag it.

**Gate:** `App.tsx` under 300 lines, `App.test.tsx` green without edits.

**Commit:** `refactor(desktop): extract run socket, backend handshake, and stores from App.tsx`

---

# PHASE 5 — Naming and docs (do this last)

1. **Pick one name.** The Python package is `neuralflow`, the product is `Komvos`, the repo is `Far-Away`, the keyring service string is `"neuralflow"`, and the DB lives at `~/.neuralflow/`. Recommended: keep `Komvos` as the product, rename the Python package to `komvos`, and rename the GitHub repo to `komvos`. If you rename the package you **must** update: `pyproject.toml`, `packaging/pyinstaller.spec`, `packaging/komvos_backend.spec`, `start.bat`, both CI workflows, and every import. **Migrate the keyring service string and the DB path with a fallback that reads the old location** — silently losing users' stored API keys on upgrade is not acceptable.
2. **Fix `package.json` author** — currently `NeuralFlow Team <team@neuralflow.com>`, a placeholder email that ships inside installer metadata.
3. **Delete the duplicate PyInstaller spec** — `packaging/` has both `pyinstaller.spec` and `komvos_backend.spec`. Keep whichever CI actually invokes; delete the other.
4. **Add `CONTRIBUTING.md`** documenting the `AGENT.md` workflow, since this is agent-assisted development.
5. **Update `README.md`** with the two new features: an "Use your pipeline as an API" section with the OpenAI-compatible snippet, and an "Access control" section explaining the access node.

**Commit:** `chore: unify naming, fix package metadata, document access node and API serving`

---

## Global rules for every phase

- **One phase per branch, one PR per phase.** Do not mix phases.
- **Never change `shared/pipeline.schema.json` or `shared/types.ts` without updating both backend and frontend in the same commit, and flagging BREAKING CHANGE in the commit body.**
- **No `TODO` + `return True`.** `AGENT.md` rule 2 — raise an explicit error.
- **No mock data outside clearly-named test files.** `AGENT.md` rule 1. Note that `endpoints/mock.py` is a legitimate named endpoint kind, already gated behind `NEURALFLOW_ALLOW_MOCK_ENDPOINT` — leave that gate in place and extend it to any new mock path.
- **Every phase ends green:** `ruff check . && mypy neuralflow && pytest -q` in `backend/`, and `npm run typecheck && npm run lint && npm run test` in `apps/desktop/`.
- **End every reply with:** files changed · how to run · how to test · contracts touched · blockers.

## Definition of done for the whole effort

1. `git check-ignore` confirms build artifacts are ignored; no `dist-electron/`, `scratch/`, or test output tracked.
2. CI runs lint, typecheck, and the full test suite on every push, and blocks the build job on failure.
3. `LICENSE` exists and matches the README badge.
4. CORS is an allowlist; auth fails closed without `KOMVOS_DEV=1`; Electron has explicit `webPreferences` and navigation guards.
5. Dropping an access node on a canvas shows every capability the downstream pipeline reaches for, distinguishes granted-and-used from granted-and-unused from requested-and-denied, and blocking a capability actually prevents the outbound call.
6. A pipeline can be deployed from the UI, and this works against it unmodified:

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="kv_...")
resp = client.chat.completions.create(
    model="<deployment_id>",
    messages=[{"role": "user", "content": "hello"}],
)
```

7. Deploying a pipeline with no access node is refused with an actionable error.
8. `App.tsx` is under 300 lines with `App.test.tsx` passing unmodified.
