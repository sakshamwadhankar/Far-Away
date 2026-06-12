# shared

**Owner: P1 — Backend Core**

## Purpose

Cross-language contracts that both the Python backend and the TypeScript
frontend depend on. This is the **single source of truth** for the pipeline
data format.

> ⚠️ **BREAKING CHANGE protocol**: any modification to files in this directory
> must be announced as a BREAKING CHANGE. P2 and P3 must re-sync their code
> before continuing work (see `roadmap.md` — Coordination rules).

## Contents

| File | Description |
| :--- | :--- |
| `pipeline.schema.json` | JSON Schema v2 — the canonical definition of a NeuralFlow pipeline file. |
| `types.ts` *(Phase 1)* | TypeScript types matching the JSON Schema (Node, Port, Edge, Loop, Pipeline). |

## Who imports what

- **P1 (Python):** generates Pydantic models from the schema in
  `backend/neuralflow/compiler/models.py`.
- **P2 (Python):** imports Pydantic models via P1's `models.py`.
- **P3 (TypeScript):** imports `types.ts` directly into the canvas
  serialisation code.

## Key rules from the schema

1. No secrets or device pins in pipeline JSON (they resolve at run time).
2. Loops are **subgraphs** — not back-edges in the main graph.
3. All ports are **typed**: `text | number | boolean | json | image | audio`.
4. `stop_when` is a structured condition (no raw code).
