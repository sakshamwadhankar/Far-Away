# P2 — MASTER PROMPT (desktop control as a governed domain)

## P1 verdict — passed

Verified directly, not from the report: both commits landed, `App.tsx` diff is 15
lines (inside budget), no test files added or modified, frontend `typecheck` /
`lint` / `test` all clean at 63 passing. `HUMAN_ORIGINS.has(d.origin)` is genuinely
used in `DecisionHistory.tsx:152`, and `ApprovalPrompt.tsx` really does handle
countdown and expiry. The demo path in `docs/p1-demo.md` is concrete and usable.

**The Round 2 submission is now complete and gradeable.** P2–P4 are upside.

## Key research findings baked into this prompt

- `cua` is **MIT** — compatible. But the optional `ultralytics` extra is
  **AGPL-3.0**; shipping it would attach AGPL obligations to the whole installer.
  It must not be installed.
- `OmniParser` is **CC-BY-4.0** — attribution is legally required.
- `cua-computer-server` defaults to **port 8000**, which **collides with the Komvos
  dev backend**. Must be configured onto a different port.
- Use **thin mode only**: `cua-computer-server` as the action layer. Komvos owns the
  agent loop. Using `cua-agent` would put the loop inside cua, where governance can
  only gate at task level instead of per action — that would destroy the entire
  point of the feature.

---

```
You are working in the Komvos repository (Electron + React + TypeScript desktop app
in apps/desktop, Python 3.11 FastAPI backend in backend/, package name `komvos`).

═══ WORKING STYLE — THIS OVERRIDES YOUR DEFAULTS ═══
DO NOT WRITE TESTS. Not one. No test files, no test functions, no fixtures, no mock
scaffolding, no sample-data harnesses. Do not create any file whose name contains
"test" or "spec". Do not edit any existing test.
DO NOT insert placeholder or dummy data into a source file intending to remove it
later. Write the real implementation once, directly.
Verification is performed by someone else outside this run. Your only job is
working code.
Keep the report SHORT — bullets, not prose. Report what you actually did, not what
the specification asked for.
═══════════════════════════════════════════════════

ENTRY CHECK — only these may HALT you:
  cd backend && ./.venv/Scripts/python.exe -m pytest -q
  cd ../apps/desktop && npm run typecheck
If either fails, STOP, write docs/p2-report.md saying what is red, change nothing.

HANDS OFF — a second operator owns these. Do not create, edit, rename, move,
reformat or delete them:
  .github/workflows/   packaging/
  apps/desktop/src/main.ts
  apps/desktop/src/hooks/useBackend.ts
  apps/desktop/src/hooks/usePipelineActions.ts
  apps/desktop/src/hooks/useRunSocket.ts
  apps/desktop/index.html
  apps/desktop/src/components/SettingsModal.tsx
  backend/komvos/executors/logic.py
  README.md
PARTITIONED — edit only as described:
  apps/desktop/src/App.tsx  - MOUNT POINTS ONLY. Imports and rendering your
    components. Do not restructure existing layout, state or handlers. Keep the
    diff in this file under ~20 lines.
  backend/pyproject.toml    - ONE EXCEPTION, granted for this phase only: you may
    add the single dependency named in TASK 1. Change nothing else in that file —
    no version bumps, no reordering, no formatting.

═══ CONTEXT: what already exists ═══
backend/komvos/governance/ is a working governance engine:
  - GovernanceDecision emitted on ALLOW as well as DENY, with domain, capability,
    outcome, reason, effective policy, governing access nodes, and DecisionOrigin
    (including origins that identify a HUMAN approval or denial).
  - Postures Enforce / Ask / Audit.
  - Three profiles EXPLORE / REVIEW / LOCKED, default LOCKED, bidirectional
    resolution against a pipeline's access policy.
  - Real mid-run suspend and resume for Ask, with an approvals registry and API.
  - Persisted decision log with filtering, keyset pagination, and JSON/CSV export.
  - Live decision events on the run WebSocket.
apps/desktop/src/governance/ has the full UI: active-profile indicator, profile
picker, decision history panel, approval prompt.

FOUR governance domains exist today: providers, egress, spend, retention.
This phase adds a FIFTH: desktop.

Read before writing code, and confirm in the report:
backend/komvos/governance/ (all .py + README.md), backend/komvos/compiler/models.py,
backend/komvos/executors/model.py, backend/komvos/executors/__init__.py,
backend/komvos/endpoints/base.py, backend/komvos/api/registry.py (the health and
detection patterns), shared/pipeline.schema.json, shared/types.ts,
apps/desktop/src/canvas/nodes/AccessNode.tsx, apps/desktop/src/canvas/accessPolicy.ts,
apps/desktop/src/panels/LeftSidebar.tsx.

═══ WHAT THIS PHASE BUILDS ═══
Komvos gains the ability to operate the computer — screenshot, click, type — and
EVERY SINGLE ACTION passes through the governance engine before it happens. A
second agent verifies each action actually did what was intended.

TASK 1 — Dependency, connection, and licence hygiene.
Add `cua-computer-server` to backend/pyproject.toml. Pin it to an exact version,
matching how the other pinned dependencies in that file are written.

THREE HARD CONSTRAINTS, all non-negotiable:

  (a) DO NOT install or depend on the optional `ultralytics` extra. It is AGPL-3.0
      and shipping it inside a PyInstaller installer would attach AGPL obligations
      to this entire product. If any transitive path pulls it in, STOP and report
      it rather than proceeding.

  (b) `cua-computer-server` defaults to port 8000, which is the same port the
      Komvos dev backend uses. This WILL collide. Choose a different default port
      for it, make it configurable, and document the choice.

  (c) Connect over loopback only. The computer-server must never be reachable off
      this machine.

Create a new package backend/komvos/desktop/ with a README.md in the style of the
other package READMEs — explain the why, matching the tone of
backend/komvos/governance/README.md.

Add detection following the existing pattern: the codebase already probes for a
local Ollama and reports availability. Do the same here — is the computer-server
present and reachable? Surface it the same way, so the UI can tell the user the
feature is unavailable instead of failing mid-run.

USE THIN MODE ONLY. You are using cua as an ACTION LAYER: screenshot, click, type,
key, scroll. Komvos owns the agent loop. Do NOT use cua's own agent framework — if
the loop lives inside cua, governance can only gate whole tasks instead of
individual actions, which defeats the entire purpose of this phase.

TASK 2 — The desktop governance domain.
Add `desktop` to the governance domain enumeration. Extend AccessPolicy with the
capabilities this domain needs — at minimum: whether desktop control is permitted
at all, which applications may be touched, and whether destructive actions are
permitted.

Follow the EXISTING semantics precisely. The `allowed_domains` field already
establishes the convention that an empty list means "no restriction", not "nothing
allowed", and the compiler's intersect logic depends on that reading. Your new
list-valued fields must intersect consistently with that convention, and you must
document the semantics in the desktop package README.

Wire the new capabilities into: the policy intersect logic, the compiler's
capability check, and the profile resolution that G2 built. A pipeline containing a
Computer node must be subject to the served-mode rule that already exists — every
node capable of reaching a governed capability must be downstream of an access node.

Extend the three built-in profiles with desktop semantics:
  EXPLORE - Audit. The agent acts freely; every action is recorded.
  REVIEW  - Ask. Destructive actions suspend the run and ask the user.
  LOCKED  - Enforce. Only explicitly allowed applications; destructive actions denied.

TASK 3 — Destructive action classification.
"Destructive" must be a real, defensible classification, not a keyword guess. Decide
what counts — deletion, overwriting, system or security settings, sending or
publishing, anything involving payment, and anything irreversible — and implement it
as an explicit, readable rule set in one place, not scattered through the executor.

When classification is uncertain, treat the action as destructive. Failing safe is
the correct bias and the report must state that you did this.

TASK 4 — The Computer node and its execution loop.
Add a new node type. Its user-facing name is "Computer". No third-party product name
appears in the type name, the UI label, the node config, or any user-visible string.

The node needs a vision-capable model to decide what to do. Reuse the existing
endpoint system — the node references an endpoint the same way a model node does.
Do not build a second model-calling path.

The executor owns this loop:

    observe  -> capture the screen state
    decide   -> the model chooses the next action
    GATE     -> governance decides whether that action may happen
    act      -> execute it via the action layer
    verify   -> confirm it did what was intended
    repeat   -> until the task is done, or a bound is hit

GROUNDING — this is where these systems usually fail. Do NOT ask the model for raw
pixel coordinates; it will hallucinate them confidently. Detect interactive elements
first, overlay numbered marks on them, and have the model choose a MARK NUMBER. You
resolve that number back to an exact target. Keep a coarse grid only as a fallback
for surfaces where no elements can be detected.

THE GATE IS ABSOLUTE. Every single action — every click, every keystroke, every
scroll — produces a GovernanceDecision BEFORE it executes. Not after. Not sampled.
Not batched. Under Ask posture the run suspends at the gate using the existing
approvals machinery from G2; do not build a second approval mechanism.

Bound the loop. A maximum number of steps and a wall-clock limit, both enforced,
both reported when hit. An agent that loops forever on a confusing screen must stop
on its own.

TASK 5 — The verifier.
After each action, a second check confirms the action actually did what was
intended. Compare the observed post-state against what was expected — a state
assertion, supported by a before/after screen comparison. A screen comparison alone
is too weak: an unrelated animation will make it look like something changed when
nothing did.

On mismatch: retry with a bound, then stop and report rather than continuing
blindly. A verifier that always says "looks fine" is worse than no verifier — make
sure it can actually fail, and say in the report how you confirmed it can.

Verifier outcomes belong in the governance log alongside the actions.

TASK 6 — Frontend.
  - The Computer node on the canvas, in the existing visual language, added to the
    node palette. Read LeftSidebar.tsx and the existing node components first.
  - Access node UI extended so a user can grant or withhold the new desktop
    capabilities, matching how the existing capabilities are presented.
  - A live action feed showing what the agent is doing right now — the action, the
    target, the governance outcome. During a desktop run the user must be able to
    watch and understand it. Reuse the existing governance UI components and the
    live decision events rather than building a parallel display.
  - An "Open Source Licences" screen listing third-party components and their
    licences, including the CC-BY-4.0 attribution that is legally required. It does
    NOT go in SettingsModal.tsx — that file is off limits. Build your own component
    and mount it.

BRANDING: no third-party product names or logos anywhere in the interface. The
licences screen is the one and only place third-party names appear. This is a
product with its own identity that happens to use open-source components — which is
normal and legitimate — but attribution belongs in the licences screen, and nowhere
else.

TASK 7 — Safety.
  - The existing kill switch must stop a desktop run immediately, including while
    it is mid-action or awaiting approval.
  - There must be no path that executes an action without passing the gate. Say in
    the report how you assured this — if there is a bypass, say so plainly.
  - Update shared/pipeline.schema.json and shared/types.ts for the new node type and
    the new access-policy capabilities. These three definitions are mirrored on
    purpose and must not drift.

CONSTRAINTS:
- No tests. No edits to existing tests.
- No dependency other than the one named in TASK 1.
- Do not weaken the served-mode access check, the fail-closed defaults, or the
  LOCKED default profile.
- If the computer-server is not installed on this machine, build against its
  documented interface and say clearly in the report that you could not exercise it
  live. Do not fake it, and do not claim you ran something you did not.
- If an instruction looks wrong, implement it anyway and record the disagreement.

DEFINITION OF DONE:
  cd backend
  ./.venv/Scripts/python.exe -m ruff check komvos
  ./.venv/Scripts/python.exe -m mypy komvos
  ./.venv/Scripts/python.exe -m pytest -q
  cd ../apps/desktop && npm run typecheck && npm run lint && npm test
ruff and mypy clean. No NEW failures in either suite.

DELIVERABLES:
1. docs/p2-report.md — SHORT, bullets:
   - Which cua package and version you pinned, and how you confirmed `ultralytics`
     is not pulled in
   - The port you chose and why
   - The new domain's capabilities and their intersect semantics
   - Your destructive-action rule set, listed
   - How grounding works, and what happens when no elements are detected
   - Your evidence that no action can execute without passing the gate
   - How you confirmed the verifier can actually FAIL, not only pass
   - The loop bounds you chose
   - What you could and could not exercise live
   - Full DEFINITION OF DONE output
   - Anything incomplete or that you disagreed with
2. docs/p2-demo.md — the desktop-control demo path, in the same style as
   docs/p1-demo.md: numbered steps with what the user should SEE at each one.
   It must show the same pipeline behaving differently under REVIEW and LOCKED.
3. One commit, prefixed exactly: "p2: "
```
