# apps/desktop

**Owner: P3 — Desktop UI**

## Purpose

Electron + React + TypeScript + React Flow application. This is the entire
desktop shell: the main window, the node-graph canvas, all configuration panels,
the execution monitor, the trace viewer, and the save/load UI.

## Sub-directories

| Directory | Contents |
| :--- | :--- |
| `src/canvas/` | React Flow canvas, node components, edge renderers, port-type validation |
| `src/panels/` | Right-side config panel, execution monitor panel, post-run trace panel, left-side node palette |
| `src/ipc/` | Electron main ↔ renderer IPC channel definitions and typed bridge helpers |

## Key constraints (from TRD)

- Backend spawned by Electron as a **child process** on a random `127.0.0.1` port.
- A **per-session auth token** is passed to the backend at spawn time.
- Canvas serialises to **pipeline JSON schema v2** (defined in `shared/pipeline.schema.json`).
- Secrets are **never** embedded in saved pipeline JSON — pre-export scrub is mandatory.

## How to develop

```bash
npm install          # install all dependencies
npm run dev          # start Vite dev server + Electron
npm test             # run Vitest unit tests
npm run lint         # ESLint + Prettier check
npm run typecheck    # tsc --noEmit
```

## Phase roadmap (from roadmap.md)

| Phase | P3 deliverable |
| :--- | :--- |
| 1 | Electron shell + blank React Flow canvas (zoom/pan/minimap) |
| 2 | Node palette, typed ports, config panels, schema v2 serialisation |
| 3 | Execution monitor (live WS feed), trace view, save/load with secret-scrub |
| 4 | Template gallery, first-run onboarding flow |
