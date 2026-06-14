<div align="center">

<img src="apps/desktop/src/assets/KomvosLogo.png" alt="Komvos Logo" width="400" />

### A visual desktop platform for building and running multi-model AI pipelines.

Design AI workflows by connecting nodes on a canvas — combining cloud frontier models (OpenAI, Anthropic, Google) with local open-source models (via Ollama) in a single hybrid pipeline.

[![Build](https://img.shields.io/badge/build-CI-blue)](#)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](#)
[![Backend Tests](https://img.shields.io/badge/backend%20tests-144%20passing-success)](#)
[![License](https://img.shields.io/badge/license-MIT-green)](#)

[Download](#-download) · [Features](#-features) · [How It Works](#-how-it-works) · [Quick Start](#-quick-start) · [Architecture](#-architecture)

</div>

---

## Overview

**Komvos** turns the powerful but code-heavy world of multi-model AI orchestration into a visual, drag-and-drop experience. Inspired by node editors like ComfyUI and Blender's shader graph, it lets developers, researchers, and power users build advanced AI architectures — such as the **Solver → Verifier → Judge** verification loop popularized by frontier reasoning models — without writing orchestration code.

Pipelines run on a **local-first execution engine** that treats every model (cloud API or a locally-hosted Ollama model) as a uniform endpoint, so you can mix paid cloud reasoning with free, private local inference in the same graph.

> **Why it matters:** There is a real gap between "use one chatbot" and "engineer your own multi-model AI system." Komvos closes it with a visual interface, a hybrid cloud/local runtime, and a shareable pipeline format.

---

## ✨ Features

|     | Feature                        | Description                                                                                                                                                         |
| --- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 🎨  | **Visual Pipeline Canvas**     | Drag-and-drop node editor (React Flow) with typed ports, real-time connection validation, and a minimap.                                                            |
| 🔀  | **Hybrid Cloud + Local**       | Run cloud models (OpenAI, Anthropic, Google) and local models (Ollama) side-by-side in one pipeline.                                                                |
| 💬  | **Chat / Use Mode**            | After building a pipeline, switch to a ChatGPT-style interface and _talk to your pipeline_ with streamed responses.                                                 |
| 🔁  | **Logic Nodes**                | Loops (with safe, structured stop conditions), Judge (select best output), Router (conditional branching), Transform (sandboxed templating), Compare (output diff). |
| 📊  | **Live Execution Monitor**     | Watch nodes pulse, tokens stream, and per-node cost/latency update in real time over WebSocket.                                                                     |
| 💰  | **Cost & Budget Controls**     | Pre-run cost/latency estimates, a hard per-run budget cap, and a kill-switch to stop runs mid-execution.                                                            |
| 🧩  | **Template Gallery**           | 10 ready-to-run pipelines (Solver-Verifier-Judge, RAG, Ensemble Voting, Cascade, Debate, and more).                                                                 |
| 🗂️  | **Full Trace & Persistence**   | Every run is recorded to SQLite — full per-node I/O, loop history, tokens, and cost — with checkpoint/resume support.                                               |
| 🔐  | **Security-First**             | API keys stored in the OS keychain (never in files); template export scrubs secrets; sandboxed template rendering.                                                  |
| 🖥️  | **Self-Contained Desktop App** | One installer per OS. The Python backend is bundled and auto-starts — no terminals, no manual setup.                                                                |

---

## 📦 Download

Pre-built installers are available on the [**Releases**](../../releases) page.

| Platform    | File                                                                 |
| ----------- | -------------------------------------------------------------------- |
| **Windows** | `Komvos Setup 0.1.0.exe` (installer) · `Komvos 0.1.0.exe` (portable) |
| **macOS**   | `Komvos-0.1.0.dmg`                                                   |
| **Linux**   | `Komvos-0.1.0.AppImage` · `.deb`                                     |

> The application is currently distributed unsigned. On Windows, click **More info → Run anyway** at the SmartScreen prompt. Code-signing is planned for the public release.

---

## 🚀 Quick Start

### Prerequisites

To run **local** models, install [Ollama](https://ollama.com) (cloud models only require an API key):

```bash
# Install Ollama from https://ollama.com, then pull a model:
ollama pull qwen2.5:3b
```

### Run the installed app

1. Launch **Komvos** — the backend starts automatically.
2. Open the **Template Gallery** → load **Solver → Verifier → Judge**.
3. Switch to **💬 Use** mode → type a prompt → watch the pipeline execute live.

### Run from source (developers)

NeuralFlow requires both the backend and frontend to run simultaneously in separate terminals.

**1. Backend (Python 3.11+)**
```bash
cd backend
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate
# Activate (macOS/Linux)
source .venv/bin/activate

pip install -e ".[dev]"
uvicorn neuralflow.api.main:app --port 8000
```

**2. Frontend (Node 18+)**
*(Open a new terminal window at the project root)*
```bash
cd apps/desktop
npm install
npm run dev
```

---
##  Made By ~ Dead_Pixel
<img width="800" height="600" alt="Dead_PixelIntro-ezgif com-optimize" src="https://github.com/user-attachments/assets/ebfa2537-09f5-4dfa-b9d4-eb2384f3800e" />


## 🧠 How It Works

A flagship pipeline — the DeepSeek-style verification loop — looks like this:

```
        ┌─────────┐     ┌──────────┐     ┌─────────┐     ┌──────────┐
 Prompt │  INPUT  │ ──▶ │  SOLVER  │ ──▶ │ VERIFIER│ ──▶ │  JUDGE   │ ──▶ Output
        └─────────┘     │ (local)  │     │ (cloud) │     │  (best)  │
                        └──────────┘     └──────────┘     └──────────┘
                              ▲                │
                              └──── loop until verified ────┘
```

The **Solver** drafts an answer (local model), the **Verifier** checks it (returns structured JSON), and the loop repeats until the verification condition is met or max iterations is reached — then the **Judge** selects the best result. All of it built by dragging five nodes onto a canvas.

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Desktop App  (Electron + React + TypeScript)            │
│  • React Flow canvas  • Chat mode  • Live monitor        │
└───────────────────────────┬──────────────────────────────┘
                            │  local HTTP + WebSocket (127.0.0.1)
┌───────────────────────────┴──────────────────────────────┐
│  Backend  (Python · FastAPI)                             │
│  • Compiler:  graph → typed, validated DAG               │
│  • Scheduler: parallel branches, loops, budget, cancel   │
│  • Executors: model / judge / router / transform / ...   │
│  • State:     SQLite trace + checkpoints                 │
│  • Endpoints: ModelEndpoint abstraction ↓                │
└───────────────────────────┬──────────────────────────────┘
            ┌───────────────┼────────────────┐
      ┌─────┴─────┐   ┌──────┴──────┐   ┌─────┴──────┐
      │  Cloud    │   │   Ollama    │   │  (EXO —    │
      │ APIs      │   │  (local)    │   │  roadmap)  │
      └───────────┘   └─────────────┘   └────────────┘
```

**The key design decision** is the `ModelEndpoint` abstraction: the scheduler never knows whether a node runs on a cloud API, a local Ollama model, or (in future) a distributed cluster. This keeps the engine simple and makes new backends pluggable.

### Tech Stack

| Layer         | Technology                                            |
| ------------- | ----------------------------------------------------- |
| Desktop shell | Electron                                              |
| UI            | React, TypeScript, React Flow                         |
| Backend       | Python 3.11, FastAPI, Pydantic                        |
| Local models  | Ollama (OpenAI-compatible API)                        |
| Persistence   | SQLite                                                |
| Packaging     | PyInstaller (backend) + electron-builder (installers) |
| CI            | GitHub Actions (Windows / macOS / Linux matrix)       |

---

## ✅ Quality & Testing

- **144 backend tests** (compiler, scheduler, executors, endpoints, API, schema) + frontend unit tests.
- **End-to-end verified** against a real local model (`qwen2.5:3b`): full pipeline execution, streaming, loop termination, JSON-repair, cancellation, and partial-trace persistence.
- **Packaged-binary verified** — the bundled backend was tested standalone (running a real pipeline through the PyInstaller executable, not just in dev).
- Strict contracts: typed pipeline schema mirrored across JSON Schema, Python (Pydantic), and TypeScript.

```bash
# Backend
cd backend && python -m pytest tests/ -v

# Frontend
cd apps/desktop && npm test && npm run typecheck
```

---

## 🗺️ Roadmap

| Stage                      | Status      | Scope                                                                                                                                             |
| -------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| **R0 — Core**              | ✅ Complete | Visual editor, hybrid cloud/local execution, chat mode, templates, packaged desktop app                                                           |
| **R1 — Distributed Local** | 🔜 Planned  | Run 70B+ models across multiple machines via the [EXO](https://github.com/exo-explore/exo) framework, behind the same `ModelEndpoint` abstraction |
| **R2 — Community**         | 🔜 Planned  | Template sharing, custom model integration, marketplace                                                                                           |

---

## 📁 Repository Structure

```
.
├── apps/desktop/        # Electron + React + TypeScript desktop app
│   ├── src/canvas/      # Node editor, serialization
│   └── src/panels/      # Config, monitor, chat, gallery
├── backend/             # FastAPI backend
│   └── neuralflow/
│       ├── compiler/    # graph → validated DAG
│       ├── scheduler/   # execution engine, events, cancellation
│       ├── executors/   # node implementations
│       ├── endpoints/   # cloud / ollama model endpoints
│       └── state/       # SQLite trace + checkpoints
├── shared/              # Pipeline schema (JSON Schema + TS types)
├── templates/           # First-party pipeline templates
├── packaging/           # PyInstaller build scripts
└── .github/workflows/   # CI: multi-OS build + release
```

---

## 📄 License

Released under the [MIT License](LICENSE).

---

<div align="center">

**Komvos** — _Make multi-model AI orchestration as easy as connecting nodes._

</div>
