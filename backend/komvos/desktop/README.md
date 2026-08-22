# komvos/desktop

**Owner: Desktop workstream — Phase 2**

## Purpose

This package provides governed desktop automation for Komvos. It defines the
desktop action layer, Set-of-Marks visual grounding, destructive action classification,
loopback client communication, and post-action state verification.

## Architecture: Thin Mode Only

Komvos uses the underlying `cua-computer-server` in **thin mode only**:
- The server provides the mechanical action primitives: capturing screenshots, dispatching mouse clicks, key events, text entry, and accessibility tree inspection.
- Komvos **owns the entire agent loop**: `observe -> decide -> GATE -> act -> verify -> repeat`.
- The server never acts autonomously without Komvos prompting, gating, and verifying each individual action.

## Port Isolation & Loopback Security

- **Default Port**: `8100` (configurable via `KOMVOS_DESKTOP_SERVER_PORT` or `KOMVOS_COMPUTER_SERVER_PORT`).
  The standard default port `8000` directly collides with the Komvos development API server. Port `8100` isolates desktop automation from other local services (including Ollama on `11434`).
- **Loopback Enforcement**: All traffic is strictly constrained to `127.0.0.1`. Remote hosts are forbidden and rejected at the client boundary to prevent external command injection.

## Grounding: Set-of-Marks with Grid Fallback

Vision models frequently hallucinate raw (X, Y) pixel coordinates. To ensure deterministic targeting:
1. Interactive UI elements (buttons, inputs, links) are extracted from the accessibility tree.
2. Distinct numbered badges are overlaid directly on the element centers on the screenshot.
3. The model selects an unambiguous **mark number** rather than guessing coordinates.
4. The grounding engine maps the chosen mark back to verified pixel coordinates.
5. If no elements are detected (e.g. custom canvases or games), a coarse numbered grid (cells 1..100) is generated as an automatic fallback.

## The Governance Gate is Absolute

Every single desktop action is subject to governance gating *before* execution:
- **Application Gating**: Checked against `policy.allowed_applications`. If non-empty, interactions with unlisted applications are withheld.
- **Destructive Gating**: Evaluated against the explicit classification rules in `destructive.py`. Destructive operations require `policy.allow_destructive = True`.
- **Posture Consultation**: When an action is withheld by the pipeline policy:
  - Under `ENFORCE`: Denied immediately.
  - Under `ASK`: Suspends the execution loop, emitting an `approval_pending` event to request human confirmation via the governance registry.
  - Under `AUDIT`: Permitted, recording origin as `PROFILE`.
- Every action emits a `GovernanceDecision` record before it can touch the OS.

## Destructive Action Classification

The classification rules in `destructive.py` explicitly cover:
- Deletions & truncations (file removal, drop tables, purge).
- Overwriting & resetting configuration.
- System & security configuration (registry, elevated shells, credential stores).
- Outbound communications & publishing (submitting forms, sending messages, git push).
- Financial transactions (checkout, purchase, payment flows).
- **Fail-Safe Principle**: When target context or intent is ambiguous, the classifier defaults to `is_destructive = True`.

## The Verifier

Verification runs after every mutating action to confirm the action achieved its intended effect:
- Combines active window tracking, accessibility tree inspection, and region-of-interest (ROI) image difference analysis.
- Differentiates between real UI state transitions and ambient animation noise.
- **Can and does fail**: If an action is swallowed or the UI fails to respond, the verifier flags a failure and initiates bounded retries (up to 2 attempts) before aborting cleanly.
