# komvos/state

**Owner: P1 — Backend Core**

## Purpose

Durable storage for everything that happens during a pipeline run:
run history, per-node checkpoints, and the full execution trace.
Uses **SQLite** (via the Python standard library `sqlite3`) — no ORM, no
external DB server required.

## What is stored

| Table (sketch) | Contents |
| :--- | :--- |
| `runs` | Run ID, pipeline ID, start/end timestamps, status, total cost, total tokens |
| `node_checkpoints` | Per-node IO snapshot written *between* nodes (never mid-token) |
| `trace_events` | Ordered log of status changes, token chunks, cost updates, loop iterations |

## Checkpointing rules (TRD §5)

- State is persisted **between** nodes, never mid-token stream.
- On a node failure, the run can be **resumed from the last checkpoint** without
  re-running earlier nodes.
- Loop history (per-iteration IO + `stop_when` evaluation) is recorded in
  `trace_events`.

## Phase (roadmap.md)

- **Phase 3:** SQLite schema, checkpoint writer, trace recorder, resume/retry
  logic.
