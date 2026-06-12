# neuralflow/compiler

**Owner: P1 — Backend Core**

## Purpose

Transforms a raw pipeline JSON (schema v2) into a **typed, validated DAG** that
the scheduler can execute. This is the single gate that must reject any
structurally or semantically invalid pipeline before execution begins.

## Validation rules enforced (TRD §4)

1. The main graph (excluding loop subgraphs) must be **acyclic**.
2. Every edge must connect **type-compatible** ports
   (`text | number | boolean | json | image | audio`).
3. Every `endpoint_ref` in a model node must resolve in the pipeline's
   `endpoints` map.
4. `stop_when` must be a **structured condition** (no raw code or `eval`);
   supported ops: `==  !=  >  <  >=  <=  contains`.
5. Every loop must have a **finite** `max_iterations` and a defined `on_max`
   policy (`return_best | fail | return_last`).

## Phase (roadmap.md)

- **Phase 2:** Core compiler — DAG construction + all five validation rules.
- **Phase 4:** Validation hardening — friendly error messages per rule; fuzz tests.
