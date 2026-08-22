# neuralflow/serve

**Owner: Phase 3 — Serve pipelines as an API**

## Purpose

Turns a built pipeline into a callable HTTP endpoint, so it can be used from
OpenClaw, OpenWebUI, Cursor, LangChain, curl, or your own code — without
opening the Komvos UI. The primary surface is **OpenAI-compatible**: point an
existing tool's base URL at Komvos and use the deployment ID as the model
name.

## Module layout

| File            | Owns                                                              |
| ---------------- | ------------------------------------------------------------------ |
| `models.py`      | `Deployment` + request/response models, the I/O mapping rules      |
| `keys.py`        | Deployment key generation, hashing, verification                   |
| `ratelimit.py`   | Per-deployment token bucket (in-memory, not persisted)             |
| `store.py`       | SQLite persistence for deployments                                 |
| `routes.py`      | The FastAPI router, built via `create_serve_router(...)`           |

`routes.py` is a **factory**, not a module that imports `api.main.app`
directly. `api/main.py` mounts the router; if `routes.py` imported `main.py`
back, that would be circular. Everything it needs from the rest of the app —
session-token auth, pipeline compilation, endpoint resolution, run tracking —
is either passed into `create_serve_router(...)` as a callable or imported
from `api/registry.py`, which (like this package) has no dependency on
`api/main.py`.

## No second execution pipeline

A served request drives the exact same `PipelineRunner` + `Scheduler` event
queue as a canvas run (`api/registry.run_pipeline_task`,
`api/registry.run_registry`). `routes.py` only translates the same `WsEvent`
stream the `/ws/run/{id}` WebSocket handler already speaks into HTTP shapes —
buffered JSON for non-streaming calls, SSE deltas for `stream: true`. There is
no separate execution engine for served pipelines.

## Deploying a pipeline

`POST /deployments` compiles the pipeline with `mode="served"`
(`compiler/dag.py`), which refuses a pipeline with no access node — see
`compiler/README.md` for why that boundary exists. It then resolves the
chat-completions I/O mapping (below) **once**, at deploy time; a pipeline
whose mapping is ambiguous is never deployed.

## Request/response mapping (3.3)

### Chat-completions path (primary)

- **Input:** the input node with `config.api_field == "messages"`, or the sole
  input node if there is exactly one. Anything else — multiple input nodes,
  none marked — fails deployment outright, naming every candidate. No
  guessing.
- **Output:** the exposed output node (`api_expose` defaults to `true`) with
  `config.api_field == "content"`, or the sole exposed output node if there is
  exactly one. Same ambiguity rule.
- The incoming `messages` array collapses to the single text value the
  pipeline's input node receives: a single message is passed through as-is
  (the common case); more than one is joined into a `role: content`
  transcript, since a pipeline input node has no native concept of a message
  list.
- Streaming (`stream: true`) sends token-level SSE deltas **only** when the
  designated output node is fed directly by exactly one model node
  (`input -> model -> output`). Any other topology — a transform or router
  between the model and the output — buffers the whole result and sends it as
  one delta chunk, because a transform operates on the finished string, not
  token by token. Both cases end with a `finish_reason: "stop"` chunk and a
  literal `data: [DONE]`.

### Native path

`POST /v1/deployments/{id}/run` — request body is `{ "<field>": value, ... }`
keyed by every input node's `config.api_field`, defaulting to the node's own
id when unset, so this path works without any configuration at all. Response
is the same shape, keyed by every **exposed** output node.

## Auth

Two separate credentials, deliberately never interchangeable:

- **Session token** (`api/auth.py`) — the Electron app talking to its own
  backend. Used for the management routes (`POST/GET/DELETE /deployments`,
  rotate-key).
- **Deployment key** (`serve/keys.py`) — a third party talking to one
  deployed pipeline. `kv_` + 32 bytes of `secrets.token_urlsafe`. Only a
  SHA-256 hash is ever persisted; the plaintext exists only in the single
  response that creates or rotates it. Compared with `hmac.compare_digest`.
  Looked up by an O(n) scan over all deployments (`store.find_by_key`) rather
  than an index, since hashes are one-way and a local install has at most a
  handful of deployments — simple beats clever here.

## Access policy enforcement

Every served request compiles the deployment's stored pipeline fresh (with
`mode="served"`) and runs through the identical `ExecutorContext.policy` /
`AccessDeniedError` path canvas runs use (`compiler/dag.py`,
`executors/model.py`, `endpoints/*.py`). A deployed pipeline can never exceed
the policy shown on the canvas when it was deployed, because it is the same
enforcement code, not a re-implementation of it.

## Rate limiting

A simple token bucket per deployment (`ratelimit.py`), default 60 req/min,
configurable per deployment at creation. In-memory and process-lifetime only
— a restart resetting every bucket to full is correct behavior for a local
desktop tool, not a bug to fix with persistence.

## LAN exposure

`expose_lan` is stored per deployment and defaults to `false`. The backend
process itself is bound to `127.0.0.1` (Phase 1 hardening) — that does not
change here, and nothing in this phase makes the process listen more widely.
`_enforce_lan_policy` in `routes.py` is defense in depth for the case where a
request *does* arrive non-loopback anyway (a manual `--host 0.0.0.0` launch,
or a future packaging change): a deployment that never opted in stays inert
even then, rather than silently trusting the process bind to do the whole
job. The desktop UI's LAN toggle requires an explicit confirmation naming the
risk before it can be turned on (`DeployModal.tsx`).

**Known limitation:** `expose_lan=true` does not, by itself, make the backend
reachable from the LAN — the uvicorn process still only listens on
`127.0.0.1` unless it is launched with `--host 0.0.0.0` some other way.
Wiring that switch into the Electron spawn path is out of scope for this
phase; see `upgrade.md` Phase 3.4.2.

## Trace persistence

Served runs are recorded in the same `runs` / `node_executions` /
`loop_iterations` tables canvas runs use (`state/sqlite.py`), tagged with
`deployment_id`, so the Trace modal shows API traffic alongside canvas runs.
`deployment_id` is `NULL` for ordinary canvas runs.

## Known limitations

- Every served request recompiles the deployment's stored pipeline. Cheap for
  pipelines of the size this tool targets, and it keeps enforcement always
  current rather than trusting a cached `CompiledDAG` to still be valid — but
  it is a real per-request cost, revisit if deployments grow large.
- Served (non-streaming and native) requests get a fixed 5-minute wall-clock
  budget (`SERVED_WALL_CLOCK_BUDGET_SECONDS` in `routes.py`), not yet exposed
  as a per-deployment setting.
- `allow_network` / `allowed_domains` on an access policy are inspected and
  stored but nothing in the executors makes general (non-model) outbound
  calls yet, so there is no call site to enforce them against. They matter
  once a node type that does that exists.
