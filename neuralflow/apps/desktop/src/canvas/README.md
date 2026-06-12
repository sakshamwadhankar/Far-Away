# src/canvas

**Owner: P3 — Desktop UI**

## Purpose

All React Flow canvas components live here. This folder owns the visual
node-graph surface: node renderers for every node type (Input, Output, Model,
Loop, Judge, Router, Transform), typed port components with colour-coding and
real-time compatibility validation, and custom edge renderers.

The canvas is responsible for serialising its current state to and
deserialising from **pipeline JSON schema v2** (defined in
`shared/pipeline.schema.json`). No dummy data must ever be written to the
serialised format — see AGENT.md rule 1.

## Phase (roadmap.md)

- **Phase 1:** Blank canvas with zoom/pan/minimap; no nodes yet.
- **Phase 2:** Full node palette, typed ports, edge validation, config panel wiring.
- **Phase 3:** Run-state overlays (live status per node fed from WebSocket).
- **Phase 4:** Template import into canvas.
