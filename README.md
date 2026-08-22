<div align="center">

<img src="apps/desktop/src/assets/KomvosLogo.png" alt="Komvos Logo" width="400" />

### A visual desktop platform for building and running multi-model AI pipelines.

Design AI workflows by connecting nodes on a canvas — combining cloud frontier models (OpenAI, Anthropic, Google) with local open-source models (via Ollama) in a single hybrid pipeline.

[![Build](https://github.com/sakshamwadhankar/Far-Away/actions/workflows/build.yml/badge.svg)](https://github.com/sakshamwadhankar/Far-Away/actions/workflows/build.yml)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](#)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

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

Pre-built installers are available on the [**Releases**](../../releases) page. This release includes setup files for **Windows, macOS, and Linux**.

### 🪟 Windows Instructions
We provide two different files for Windows depending on your preference:
* **`Komvos.Setup.0.1.0.exe` (Recommended)**: This is the standard installer. It will install the app on your computer permanently and create a desktop shortcut.
* **`Komvos.0.1.0.exe`**: This is a "Portable" version. It does not install anything; it simply launches the app immediately when you double-click it.

**How to run:**
1. Download either the Setup or Portable `.exe` file.
2. Double-click to run it.
3. *Note: Since the app is currently unsigned, Windows SmartScreen will show a blue "Windows protected your PC" popup. Click **"More info"** and then **"Run anyway"**.*

### 🍎 Mac Instructions (Apple Silicon)
* **`Komvos-0.1.0-arm64.dmg`**: The installer for modern Mac computers (M1, M2, M3 chips).

**How to run:**
1. Download the `.dmg` file.
2. Double click the `.dmg` file to open it.
3. Drag and drop the Komvos app icon into your **Applications** folder.
4. *Note: Since the app is unsigned, macOS might block it from opening the first time. To bypass this, go to your Applications folder, **Right-click** (or Control-click) the Komvos app, and select **Open**.*

### 🐧 Linux Instructions
We provide a few different options for Linux users:
* **`Komvos-0.1.0.AppImage` (Recommended)**: A portable app that works on almost all Linux distributions without installation. Download it, right-click it → Properties → Permissions → Check "Allow executing file as program", and double click to run.
* **`komvos_0.1.0_amd64.deb`**: The standard installer package for Debian/Ubuntu-based systems (like Mint, Pop!_OS). Install it by double-clicking or running `sudo dpkg -i komvos_0.1.0_amd64.deb`.

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

~> Clone this repo

~> Run Start.bat

------------------------------------------------------------------------------
Komvos requires both the backend and frontend to run simultaneously in separate terminals.

**1. Backend (Python 3.11+)**
```bash
cd backend
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate
# Activate (macOS/Linux)
source .venv/bin/activate

pip install -e ".[dev]"

# KOMVOS_DEV=1 is required when running the backend by hand. Auth fails closed:
# without a session token from Electron, requests are rejected unless you opt
# in explicitly. It also allows the Vite dev origin through CORS and enables
# /docs. Never set it for a packaged build.
#   Windows (PowerShell):  $env:KOMVOS_DEV = "1"
#   macOS/Linux:           export KOMVOS_DEV=1
uvicorn komvos.api.main:app --host 127.0.0.1 --port 8000
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

## 🌐 Use your pipeline as an API

Komvos lets you serve any pipeline as an **OpenAI-compatible HTTP endpoint**. This means you can design your architecture visually and immediately use it from LangChain, OpenWebUI, Cursor, or your own code using the standard OpenAI SDK—without opening the UI again.

```python
from openai import OpenAI

# The pipeline behaves exactly like an OpenAI model
client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="kv_...")

resp = client.chat.completions.create(
    model="<deployment_id>",
    messages=[{"role": "user", "content": "hello"}],
)
print(resp.choices[0].message.content)
```

---

## 🛡️ Access Control

Pipelines deployed as an API are secured using an **Access Node**. Dropping an access node onto your canvas explicitly defines what your pipeline is allowed to reach.

- **Capability Discovery:** It shows you exactly which models (OpenAI, Anthropic, Ollama, etc.) the downstream nodes are trying to use.
- **Runtime Enforcement:** It enforces these grants at runtime. If a deployed pipeline is hijacked or altered to make unauthorized outbound calls, the access node blocks the attempt before any network request leaves the machine.

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

- **368 backend tests** (compiler, scheduler, executors, endpoints, API, schema, security; 4 more skip conditionally when a live Ollama instance or stored API keys are absent).
- **71 frontend unit tests** (components, hooks, serialization) and a Playwright E2E suite covering pipeline execution in the UI — all run in CI on every push, and both the build and release jobs are blocked on them.
- **Lint and types enforced in CI**: `ruff` and `mypy --strict` on the backend, ESLint (with `no-explicit-any` as an error) and `tsc --noEmit` on the desktop app.
- **End-to-end verified** against a real local model (`qwen2.5:3b`) when an Ollama instance is available to the test run: full pipeline execution, streaming, loop termination, JSON-repair, cancellation, and partial-trace persistence.
- **Packaged-binary verified in CI** — every build launches the bundled PyInstaller backend on all three OSes, waits for its health endpoint, and executes a real pipeline through it before the Electron app is packaged.
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
│   └── komvos/
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
