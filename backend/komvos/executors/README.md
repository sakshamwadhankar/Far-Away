# neuralflow/executors

**Owner: P2 — Endpoints & API**

## Purpose

Per-node-type execution logic. Each executor receives the node's resolved
configuration, its input data from the state layer, and an injected
`ModelEndpoint` (for model nodes) — then drives the node to completion and
writes its output back to the state layer.

## Node executors (R0)

| Executor | Node type | Notes |
| :--- | :--- | :--- |
| `InputExecutor` | `input` | Injects the user prompt / template variables. |
| `OutputExecutor` | `output` | Writes the final result; anchors the trace. |
| `ModelExecutor` | `model` | Calls `endpoint.generate()`, streams tokens via WS, handles `response_format`. |
| `JudgeExecutor` | `judge` | Scores N candidates; selects best. |
| `RouterExecutor` | `router` | Evaluates the condition, selects the output branch. |
| `TransformExecutor` | `transform` | Format conversion / Jinja-style templating; **no `eval`/code exec**. |
| `LoopExecutor` | `loop` | Delegates to scheduler for bounded iteration — see `scheduler/`. |

## Structured-output repair (Phase 3)

When a `model` node requires JSON (`response_format: json`) but the model
returns prose:
1. Prefer **native structured-output mode** (provider `json_object` / `json_schema`).
2. Fallback: **repair-prompt retry** with a hard cap (default 3 attempts).
3. On persistent failure: surface a clear error; store the raw model output in
   the trace — **never silently pass**.

## Phase (roadmap.md)

- **Phase 3:** All executor implementations + structured-output repair path.
