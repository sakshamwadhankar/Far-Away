# src/panels

**Owner: P3 — Desktop UI**

## Purpose

UI panels that surround the React Flow canvas:

| Panel | Description |
| :--- | :--- |
| **Node palette** (left) | Draggable node types (Input, Output, Model, Loop, Judge, Router, Transform). |
| **Config panel** (right) | Per-selected-node configuration: endpoint ref, system prompt, temperature, max_tokens, response_format, role. |
| **Execution monitor** | Live table (node, status, elapsed, tokens, cost) fed by the WebSocket stream; running total cost + loop iteration counter; visible **KILL SWITCH** button. |
| **Trace view** | Post-run: full IO per node, loop history, cost breakdown. Rendered from the run trace returned by the API. |

## Phase (roadmap.md)

- **Phase 1:** Left sidebar placeholder; right panel placeholder.
- **Phase 2:** Full config panel per node type; live port-type validation highlights.
- **Phase 3:** Execution monitor + trace view fully wired to WebSocket events.
- **Phase 4:** Template gallery panel; first-run onboarding overlay.
