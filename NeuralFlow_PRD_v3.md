# NeuralFlow — Product Requirements Document (v3, Production-Ready)

## 1. Product Positioning

NeuralFlow is a desktop visual editor for building and running multi-model LLM pipelines, with first-class support for local models — including large models distributed across personal machines via EXO — alongside mainstream cloud APIs. It serves as a visual bridge between high-tier cloud reasoning (e.g., DeepSeek, OpenAI) and local, privacy-first validation and execution.

---

## 2. Phased Release Strategy

To ensure a realistic development cycle and immediate user value, the product ships in three strict phases. Each phase is independently useful even if nothing after it ever ships.

| Phase | Core Focus | Hard Exclusions |
| :--- | :--- | :--- |
| **R0: Core Orchestrator** | Visual editor running pipelines against Cloud APIs + single-machine local (Ollama). | NO distributed/EXO, NO marketplace, NO multi-device. |
| **R1: Distributed Local** | Adds EXO backend so users with 2+ machines can shard 70B+ models. | NO marketplace, NO monetization. |
| **R2: Community** | Adds template sharing, custom model configurations, and monetization. | — |

---

## 3. Target Metrics & Success Criteria

All metrics must be measurable via opt-in application telemetry or a scripted test.

| Goal | Measurable Metric |
| :--- | :--- |
| **Visual Speed** | A new user can run a pre-built template in **< 5 minutes**. |
| **Pipeline Creation** | A user can build a custom 3-node pipeline in **< 15 minutes**. |
| **Distributed Local (R1)** | Run a 70B 4-bit model across 2 machines on a **wired** network: first token **< 15 s**, throughput **> 3 tok/s**. |
| **Cloud Latency** | Cloud node execution stays **< 1.3×** raw API latency (app overhead only). |
| **Initial Content** | Launch R0 with **10–20 first-party templates**. |
| **Scalability** | Support up to **8 nodes** and **4 concurrent model endpoints** per pipeline at R0. |

---

## 4. Target Users

| Persona | Need | Primary phase |
| :--- | :--- | :--- |
| **Researcher** | Quick experimentation with multi-model architectures without DevOps. | R0 / R1 |
| **Developer** | Reduce API cost by running some models locally; reproducible pipelines. | R0 |
| **Power User** | Better outputs via verification loops using pre-built templates. | R0 |
| **AI Creator** | Share / monetize pipelines and custom model configs. | R2 |

---

## 5. R0 (MVP) Feature Scope

R0 focuses entirely on establishing core DAG execution and a flawless experience for single-machine + cloud hybrid pipelines.

- **Node Canvas:** React Flow interface with Input, Output, Model, Loop, Judge, Router, and Transform nodes.
- **Model Endpoints:** OpenAI, Anthropic, Google, and any OpenAI-compatible local URL (e.g., Ollama, LM Studio).
- **Execution Modes:** Sequential + parallel execution of independent DAG branches.
- **Execution Monitor:** Live per-node status, token usage, cost, and execution time, plus a post-run trace view.
- **Safety Limits:** Hard per-run budget cap (currency + wall-clock) enforced by the scheduler as a kill switch, with a visible UI stop button.
- **Security:** API keys stored exclusively in the OS keychain, never embedded in pipeline files.
- **Loop Control:** Loop nodes use a strict max-iteration limit plus explicit confidence/stop-conditions modeled as subgraphs (no graph back-edges).
- **Persistence:** Pipelines saved locally as versioned JSON; export scrubs secrets.
- **Templates:** 10–20 first-party templates (Solver→Verifier→Judge, RAG, Ensemble Vote, Cascade, Self-Refine, etc.).
- **Platforms:** macOS + Windows (signed/notarized); Linux best-effort.

**Explicitly OUT of R0:** EXO/multi-device, marketplace, custom-model upload, payments, scheduling, team collaboration, mobile, API export, Code Executor node (deferred for security review).

---

## 6. Built-in Templates (R0)

| Template | Pattern |
| :--- | :--- |
| Solver → Verifier → Judge | DeepSeek-style verification loop (flagship demo) |
| RAG Pipeline | Retriever → Generator → Validator |
| Ensemble Voting | N models answer → aggregator selects best |
| Cascade | Cheap/fast model first → escalate on low confidence |
| Self-Refinement | Model critiques and revises its own output |
| Multi-Perspective | 3 models, 1 aggregator |
| Debate | 2 models argue → 1 adjudicates |

---

## 7. Known Risks & Production Mitigations

| Risk Factor | Root Cause | Required Mitigation |
| :--- | :--- | :--- |
| **Sharded Local Latency (R1)** | EXO swaps tensor data between machines every token; Wi-Fi bandwidth is insufficient. | Reframe R1 as best-effort; strongly recommend wired/Thunderbolt in onboarding; show live tok/s. |
| **Device Drops in EXO (R1)** | If a machine leaves the cluster mid-run, the sharded model loses RAM and crashes. | Checkpoint state *between* nodes; fail the node gracefully on shard loss; offer cloud/smaller-model fallback. |
| **Runaway Logic Loops** | Evaluator nodes that keep rejecting outputs drain local resources or cloud credits. | Global budget cap enforced by the scheduler + visible UI kill switch; show per-iteration cost. |
| **Secret Leakage** | Users accidentally share JSON files containing API keys. | Read keys from OS keychain only; pre-export validation scrubs any secrets. |
| **Malformed Model Output** | A node expects JSON but the model returns prose. | Use native structured-output modes where available; repair-prompt fallback with capped retries; show raw output in trace. |
| **Prompt Injection via Tools/RAG** | External content (web/file) flows untrusted into models. | Treat all tool output as untrusted; warn on external-data nodes; no auto code-exec. |
| **Code Execution Risk** | Code nodes enable remote code execution. | Sandboxed subprocess, no network by default, resource limits — deferred out of R0. |
| **Stale Model Lists** | Hard-coded provider models go out of date. | Fetch model lists dynamically; allow any OpenAI-compatible model/URL. |
| **Packaging/Signing** | Cross-platform Electron + Python bundling is complex. | Embedded Python runtime; CI builds with macOS notarization + Windows code signing. |

---

## 8. Out-of-Scope (Future Phases)

- Marketplace, monetization, KYC/payouts (R2 — requires legal review of model licenses, tax, content moderation).
- Custom/fine-tuned model upload (R2).
- API/code export of pipelines, scheduled runs, team collaboration, mobile companion (post-R2).
