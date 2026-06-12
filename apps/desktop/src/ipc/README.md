# src/ipc

**Owner: P3 — Desktop UI**

## Purpose

Typed Electron IPC (inter-process communication) bridge between the **main
process** and the **renderer process** (React UI).

Responsibilities:

- Expose a typed API surface to the renderer (never expose raw `ipcRenderer`
  directly — use a `contextBridge` preload).
- Manage the lifecycle of the **FastAPI child process**: spawn on app start with a
  random `127.0.0.1` port and a per-session auth token; kill on app quit.
- Surface the backend port + session token to the renderer so it can open
  WebSocket connections and fire HTTP requests.
- Forward file-system operations (save/load pipeline JSON) from the renderer
  through the main process (which has Node.js `fs` access).

## Security note

The per-session auth token is generated in the main process, passed to the
FastAPI backend via an environment variable at spawn time, and forwarded to
the renderer via `contextBridge`. It is **never** stored to disk or included in
pipeline JSON.

## Phase (roadmap.md)

- **Phase 1:** Spawn FastAPI child process; ping `/health`; expose port + token to renderer.
- **Phase 2:** File open/save dialogs; forward pipeline save/load through main.
- **Phase 3:** Kill-switch IPC call (`/runs/{id}/stop`); handle backend crash/restart.
