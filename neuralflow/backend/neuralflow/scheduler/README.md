# neuralflow/scheduler

**Owner: P1 — Backend Core**

## Purpose

Takes the validated DAG produced by the compiler and **executes it**.
The scheduler is **endpoint-agnostic** — it never knows whether a node
targets a cloud model, a local Ollama instance, or (in R1) a sharded EXO
cluster. All model I/O is delegated through the `ModelEndpoint` protocol.

## Responsibilities

- **Topological sort** of the DAG to determine execution order.
- **Parallel branch execution**: independent branches run concurrently via
  `asyncio` (no thread pools — stay on the event loop).
- **Loop subgraph execution**: evaluate bounded iterations, record per-iteration
  IO in the state layer, stop on `stop_when` condition or `max_iterations`.
- **Budget enforcement**: track running cost (via `endpoint.estimate_cost` and
  actuals); on breach of the `$` cap *or* the wall-clock cap → halt the run and
  return a partial trace. A UI kill-switch issues the same halt signal.

## Design constraint (TRD §2)

> "The scheduler is endpoint-agnostic: it never knows whether a node is cloud,
> local, or sharded. This is the single most important design constraint."

## Phase (roadmap.md)

- **Phase 2:** Core scheduler — topo sort, parallel branches, loop iteration, injected
  endpoint registry (MockEndpoint in tests).
- **Phase 3:** Budget enforcement integration; kill-switch signal handling.
