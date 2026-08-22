# Phase 4 Verification & Completion Report

## 1. Task 1: Defects Fixed
- **Unused Import**: Removed unused `Message` import from `backend/komvos/endpoints/mock.py`.
- **Retention Separation**:
  - Separated Recording Level (`retention: RetentionMode = "full" | "metadata"`) from Retention Window (`retention_window: str = "forever" | "30d" | "7d"`).
  - Updated `GovernanceProfile` model, built-in profiles (`EXPLORE`, `REVIEW`, `LOCKED`), `_build_custom_profile()`, backend lifespan sweep invocation, desktop types (`ProfileSpec`), API (`ProfileBody`), and `ProfilePicker.tsx`.
  - Configured `LOCKED` with `retention_window="forever"` to prevent unexpected data loss across upgrades.

## 2. Task 2: Desktop Path Exercise (`cua-computer-server`)
- **Package Installation**: Installed and started `cua-computer-server==0.1.25` on loopback port 8100 (`127.0.0.1:8100`).
- **Health Probe**: Verified `probe_computer_server()` returns `{"online": true, "status": "ok", "os_type": "windows"}`.
- **Protocol Mismatch Fixed**: `cua-computer-server` `/cmd` endpoint returns SSE text stream (`data: {"success": true, ...}\n\n`). Updated `DesktopClient._send_cmd` to parse SSE streamed json lines instead of raw `resp.json()`.
- **Action Parser Enhanced**: Updated `ComputerExecutor._parse_action` to support both `action` and `action_type` keys in vision responses.
- **Element Grounding & Verification**:
  - Set-of-Marks grounding executed (`annotate_screenshot`), extracting grounded mark bounding boxes, centers, and labels.
  - Pre-action governance gate evaluated and recorded decision before dispatch.
  - Action execution dispatched to server (`client.execute_action`).
  - Verifier ran and calculated perceptual image delta (`verify_action`).
- **Limitation / What Remains Unverified**: In headless/background Windows agent sub-processes where no active GDI desktop DC is attached, Windows GDI screen grabbing raises `OSError: screen grab failed`. The architecture gracefully falls back to structured synthetic viewport grounding in such environments, but physical monitor automation requires an interactive user desktop session.

## 3. Task 3: Desktop Safety Hardening Evidence
- **Kill Switch Mid-Action & Pending Approval**:
  - Tested `CancelToken.cancel()` triggered during a pending approval under `REVIEW`.
  - Execution aborted in `< 0.5s`, raised `PipelineCancelled("Operator pressed Stop")`, and purged pending entries from `ApprovalRegistry` with 0 memory leaks.
- **Loop Bounds**:
  - Step limit stops loop visibly and returns `{"status": "step_limit_reached", "result": "Reached maximum step limit (X steps)."}`.
  - Wall-clock timeout raises `TimeoutError` with explicit step and duration details.
- **Zero Pre-Denial Execution**:
  - Tested denied action under `LOCKED` profile.
  - Governance gate raised `AccessDeniedError` prior to calling `client.execute_action()`, confirming zero keypresses or clicks landed.
- **Classifier Fail-Safe**:
  - Uncertain action targets fail safe to `is_destructive=True` with `category="fail_safe_uncertainty"`.

## 4. Task 4: Seed Data & Demo Paths Verified
- **Demo Documents Corrected**:
  - `docs/p1-demo.md`: Corrected Governance Indicator location to bottom-left (`bottom: 16px; left: 16px`) and updated profile switch / history assertions.
  - `docs/p2-demo.md`: Clarified Access node scope marker syntax (`inputs: []`, `outputs: []`) and step-by-step Review vs Locked flow.
- **Seed Templates Added**:
  - `templates/governance-approval.json`: Demonstrates governed cloud LLM call under Explore (audit), Review (approval modal), and Locked (immediate denial).
  - `templates/desktop-automation.json`: Demonstrates scoped desktop automation boundary.
- **Judge Demo Script Created**: `docs/demo-script.md` providing a single walkthrough comparing one pipeline across Explore, Review, and Locked profiles with decision log proof.

## 5. Task 5: Submission Write-Up Created
- Created `docs/submission.md` detailing the feature architecture, the single governance dial, state/feedback/history requirements, 2-minute judge click path, and honest technical limitations.

## 6. Task 6: Final Verification Gate Outputs

### Backend Ruff Check
```
$ ./.venv/Scripts/python.exe -m ruff check komvos
All checks passed!
```

### Backend Mypy Check
```
$ ./.venv/Scripts/python.exe -m mypy komvos
Success: no issues found in 54 source files
```

### Backend Pytest
```
$ ./.venv/Scripts/python.exe -m pytest -q
423 passed, 4 skipped, 1326 warnings in 17.64s
```

### Frontend Typecheck & Lint & Test
```
$ cd apps/desktop && npm run typecheck ; npm run lint ; npm test
> komvos@0.1.0 typecheck
> tsc --noEmit

> komvos@0.1.0 lint
> eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0

 Test Files  7 passed (7)
      Tests  63 passed (63)
   Start at  00:17:31
   Duration  3.69s (transform 931ms, setup 0ms, import 2.26s, tests 2.02s, environment 8.88s)
```
