# Phase 2 Engineering Report — Governed Desktop Automation & Computer Node

## 1. Summary of Accomplished Work
- Integrated desktop automation primitives and vision-guided actuation directly into the Komvos visual pipeline engine.
- Implemented thin-mode execution model where Komvos owns the entire agent loop (`observe -> decide -> GATE -> act -> verify -> repeat`) while delegating mechanical action calls to a local loopback server.
- Extended the governance framework with a dedicated `desktop` domain, fine-grained application filters, destructive action classification, and fail-safe safety gates.

## 2. Dependency, Connection & Licence Hygiene (Task 1)
- Added single backend dependency `cua-computer-server==0.1.25` in `backend/pyproject.toml`.
- Configured default isolated loopback port 8100 (`KOMVOS_DESKTOP_SERVER_PORT` / `KOMVOS_COMPUTER_SERVER_PORT`) avoiding collision with port 8000.
- Enforced strict loopback-only communication (`127.0.0.1`, `localhost`, `::1`); remote hostnames are explicitly rejected with `ValueError`.
- Avoided YOLO/Ultralytics dependencies entirely; vision grounding operates using accessibility tree elements with coarse grid fallback.
- Implemented loopback health probing endpoint `GET /health/desktop` in `backend/komvos/api/main.py`.
- Created `apps/desktop/src/components/LicensesModal.tsx` displaying all third-party open-source components and legally required CC-BY-4.0 attribution.

## 3. Desktop Governance Domain (Task 2)
- Added `GovernanceDomain.DESKTOP = "desktop"` in `backend/komvos/governance/decisions.py`.
- Extended `AccessPolicy` with `allow_desktop: bool`, `allowed_applications: list[str]`, and `allow_destructive: bool` across `shared/pipeline.schema.json`, `shared/types.ts`, and `backend/komvos/compiler/models.py`.
- Implemented policy intersection rules in `AccessPolicy.intersect`: empty `allowed_applications` acts as the identity element (unrestricted), while non-empty lists compute set intersection.
- Updated compiler checks in `backend/komvos/compiler/dag.py` and `backend/komvos/compiler/validation.py` to gate desktop capabilities and enforce served-mode execution.
- Added `desktop` posture to built-in profiles in `backend/komvos/governance/profiles.py`:
  - **EXPLORE**: `Audit`
  - **REVIEW**: `Ask`
  - **LOCKED**: `Enforce`
- Updated profile resolution in `backend/komvos/governance/resolve.py` so Ask/Audit postures loosen policy restrictions at runtime.

## 4. Destructive Action Classification (Task 3)
- Implemented rule-based classifier in `backend/komvos/desktop/destructive.py` analyzing action types, dangerous hotkeys (`Alt+F4`, `Ctrl+W`, `Shift+Del`), typed text, and target UI element roles/labels.
- Categorizes operations across deletions, overwrites, system/security settings (`regedit`, `powershell`, `cmd`), communication/publishing (`send`, `publish`, `deploy`), and financial transactions (`buy`, `pay`, `checkout`).
- Enforces strict **Fail-Safe Principle**: any ambiguous, unverified, or unrecognized UI action classifies as `is_destructive = True`.

## 5. Computer Node & Execution Loop (Task 4)
- Added `"computer"` node type to schema, frontend palette, and compiler validation.
- Implemented `ComputerExecutor` in `backend/komvos/executors/computer.py` executing the governed cycle.
- Set-of-Marks visual grounding in `backend/komvos/desktop/grounding.py` annotates interactive elements with numbered badges, falling back to a 10×8 grid when accessibility trees are absent.
- Governance gate executes prior to every action invocation; consults active posture, emits `approval_pending` events under `Ask`, and records decisions in the audit log.
- Enforced hard loop bounds: configurable `max_steps` (default 30) and `timeout_seconds` (default 300s).

## 6. Post-Action Verification Engine (Task 5)
- Implemented `backend/komvos/desktop/verifier.py` evaluating state assertions (active window changes, element updates) and visual perceptual difference (ROI and global image deltas).
- Confirmed non-trivial verification: actions producing stagnant screen deltas or failing expected window focus transitions return explicit failure.
- Verification outcomes are recorded as governance decisions (`desktop:verify:<action>`).

## 7. Frontend Integration & Safety (Tasks 6 & 7)
- Extended `apps/desktop/src/canvas/accessPolicy.ts` with `allow_desktop` and `allow_destructive` capability rows and automatic requirement detection for Computer nodes.
- Updated `apps/desktop/src/panels/LeftSidebar.tsx` to add the Computer node with desktop icon (`🖥`) to the node palette.
- Added visual styling and accent colors for `computer` nodes in `apps/desktop/src/canvas/nodes/PipelineNode.tsx`.
- Updated `apps/desktop/src/governance/types.ts` and `ProfilePicker.tsx` with the `desktop` domain.
- Mounted `LicensesModal` in `apps/desktop/src/App.tsx` with a total diff of 4 lines.
- Integrated cooperative cancellation checks (`ctx.check_cancel()`) before every loop step and action dispatch.

## 8. Live Execution Status
- Tested against full internal test suites and local interface contracts.
- The `cua-computer-server` daemon was not running locally on this machine during test execution; execution logic, safety gating, loopback client fallbacks, and Set-of-Marks grounding were built and validated against its documented OpenAPI / HTTP contract and verified clean across all linter and typecheck suites.
