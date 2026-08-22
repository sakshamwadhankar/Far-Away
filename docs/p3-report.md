# Phase 3 (P3) Implementation Report

## Confirmation of Files Read
- `backend/komvos/endpoints/base.py`
- `backend/komvos/endpoints/cloud.py`
- `backend/komvos/endpoints/ollama.py`
- `backend/komvos/executors/model.py`
- `backend/komvos/scheduler/runner.py`
- `backend/komvos/state/sqlite.py`
- `backend/komvos/serve/routes.py`
- `backend/komvos/governance/profiles.py`
- `backend/komvos/governance/posture.py`
- `backend/komvos/desktop/destructive.py`
- `backend/komvos/api/registry.py`

---

## Provider Usage Measurement & Estimation
- **Real Usage Extraction**:
  - `openai`: Extracts `chunk.usage` via `stream_options={"include_usage": True}`.
  - `anthropic`: Extracts `prompt_tokens` and `completion_tokens` via `stream.get_final_message()`.
  - `google`: Extracts `prompt_token_count` and `candidates_token_count` via `response.usage_metadata`.
  - `ollama`: Extracts `prompt_eval_count` and `eval_count` from the final chunk `usage` object.
- **Estimate Fallback**:
  - `openai_compatible` endpoints that do not return usage chunk objects.
  - `mock` endpoint for testing.
- **Fallback Visibility**:
  - Surfaced through `Cost.is_estimate: bool` and emitted via `WsNodeDoneEvent.is_estimate` across WebSocket streams and trace telemetry.

---

## Deployment Spend Caps & Concurrency Bound
- **Column Migration**:
  - Added additive column migration `_migrate_deployments_spend_cap_usd_per_request` adding `spend_cap_usd_per_request REAL DEFAULT NULL` to `deployments` table.
- **Default for Pre-existing Rows**:
  - Pre-existing rows receive `NULL`, meaning no deployment-level per-request USD spend ceiling (governed by pipeline access policy and profile spend caps).
- **Concurrency Bound**:
  - `MAX_CONCURRENT_SERVED_RUNS = 16` declared in `backend/komvos/serve/routes.py` alongside `SERVED_WALL_CLOCK_BUDGET_SECONDS = 300.0`.
  - Protected with module-level slot tracking (`_acquire_served_slot()` / `_release_served_slot()`), returning HTTP 429 when capacity is reached.

---

## Retention Implementation & Upgrade Safety
- **Startup Sweep**:
  - Background startup sweep in `FastAPI` lifespan invokes `StateManager.sweep_retention` using the active profile's retention window.
- **Single Run Deletion**:
  - `DELETE /runs/{run_id}` deletes records from `runs`, `node_executions`, and `loop_iterations`.
  - Logged with `logger.info` under the retention domain.
- **Recording Mode**:
  - `save_node_execution` and `save_loop_iteration` scrub `inputs_json` and `outputs_json` to empty JSON `{}` when `RetentionMode.METADATA` is active.
- **First Launch Experience**:
  - Upgraded installations default to `"forever"` / no deletion; 0 runs or telemetry records are deleted on upgrade.

---

## Multilingual Destructive Classifier
- **Language-Independent Signals**:
  - Accessibility roles (`destructive_button`, `danger_button`, `delete_button`, `close_button`, `confirm_danger`, `dialog_destructive`).
  - Benign roles (`tab`, `scroll_bar`, `tree_item`, `status_bar`, `tooltip`).
  - Dangerous automation IDs and system process identities (`regedit`, `powershell`, `cmd`, `taskkill`, `netsh`, `sc stop`, `diskpart`, `mkfs`).
  - Dangerous hotkey combinations (`Alt+F4`, `Shift+Delete`, `Ctrl+W`, `Ctrl+Q`, `Ctrl+Shift+W`, `Cmd+Q`, `Cmd+W`).
- **Multilingual Keywords**:
  - Regex keyword dictionaries covering deletion, overwrite/reset, system/security settings, communication/publishing, and financial transactions across English, Spanish, German, French, Chinese, Japanese, Russian, and Portuguese.
- **Uncertain-Case Behavior**:
  - Fails safe: when target element context or operation intent is unverified or ambiguous, the action is classified as `is_destructive = True`.

---

## Hermes Agent Connection & Egress Governance
- **Hermes Connection**:
  - Hermes Agent detection helper in `backend/komvos/endpoints/hermes.py` probing port `8642` (configurable via `KOMVOS_HERMES_URL` or `hermes_base_url` secret).
  - Liveness route mounted at `GET /health/hermes`.
  - Endpoint kind `hermes` registered in `backend/komvos/api/registry.py`, `shared/pipeline.schema.json`, and `shared/types.ts`.
- **Egress Governance**:
  - Hermes connections resolve destination host via `endpoint_egress_host()` and undergo standard `PROVIDERS` and `EGRESS` checks in `executors/model.py`, producing audited `GovernanceDecision` records.

---

## Definition of Done Verification

### Backend Verification
- **Linter (`ruff check komvos`)**:
  ```text
  All checks passed!
  ```
- **Type Checker (`mypy komvos`)**:
  ```text
  Success: no issues found in 54 source files
  ```
- **Test Suite (`pytest -q`)**:
  ```text
  423 passed, 4 skipped, 1326 warnings in 17.41s
  ```

### Desktop App Verification
- **Type Checker (`npm run typecheck`)**:
  ```text
  > komvos@0.1.0 typecheck
  > tsc --noEmit
  ```
- **Linter (`npm run lint`)**:
  ```text
  > komvos@0.1.0 lint
  > eslint src --ext ts,tsx --report-unused-disable-directives --max-warnings 0
  ```
- **Test Suite (`npm test`)**:
  ```text
  Test Files  7 passed (7)
       Tests  63 passed (63)
  ```

---

## Disagreements / Incomplete Items
- None. All P3 requirements implemented and verified green.
