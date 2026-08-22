# Komvos Work Progression Log

Running reference of every task completed in this workspace, newest phase at
the bottom. Detailed per-phase evidence lives in `docs/phase-1-report.md` and
`docs/phase-2-report.md`.

> Commit/push status: **phases 1 and 2 are complete and verified locally but
> NOT yet committed** — holding until explicitly told to push.

---

## Phase 0 — Baseline

- Backend: ruff 15 errors, mypy 1 pre-existing error (`serve/models.py:231`),
  pytest 351 passed / 4 skipped.
- Desktop: typecheck + lint clean, vitest 62 passed.
- Note: backend tools must be invoked via `backend/.venv/Scripts/python.exe -m …`
  (ruff/mypy/pytest not on PATH on this machine).

## Phase 1 — Four defects (commit prepared: "phase-1: …")

| # | Defect | Fix |
|---|--------|-----|
| 1 | PyInstaller entry imported dead `neuralflow` package | `komvos_api_entry.py:5` → `komvos.api.main`; regression test `tests/test_api_entry.py` |
| 2 | ruff red (13 E501, 2 UP034) from copy-pasted keyring lookup | new `komvos/secrets.py:get_secret`; 12 call sites replaced across `api/main.py`, `api/registry.py`, `endpoints/cloud.py`, `tests/test_endpoints.py` |
| 3 | release.yml published installers with zero verification | new reusable `.github/workflows/verify.yml` (workflow_call); build.yml + release.yml both call it; release build gated `needs: verify` |
| 4 | exported 2.1 pipelines rejected by importer | `usePipelineActions.ts:69` accepts 2.0 + 2.1; round-trip test in `serializer.test.ts` |

Out-of-scope fix forced by DoD: `serve/models.py:231` no-any-return (one-line
`bool(...)` wrap) — recorded as a disagreement in the phase-1 report.

Final gates phase 1: import OK · ruff clean · mypy clean · pytest 352+4skip ·
desktop typecheck/lint clean · vitest 63 passed.

## Phase 2 — Prove the packaged app starts (uncommitted)

Task 1 — packaged-backend smoke test:
- New `packaging/scripts/smoke_backend.py`: spawns the built binary exactly like
  Electron (127.0.0.1, `NEURALFLOW_SESSION_TOKEN`, mock gate env, no KOMVOS_DEV),
  polls /health ≤60 s, runs a full mock pipeline via `/pipelines/run`, polls
  `/runs/{id}/trace` to `"completed"`, non-zero exit on any failure.
- `build.yml`: one cross-platform step `python packaging/scripts/smoke_backend.py`
  after the PyInstaller build, on all three OSes.
- Proof: broken binary → `SMOKE TEST FAILED: /health did not return 200 within 60s`,
  exit 1; healthy binary → run completed, exit 0.

Task 2 — E2E in CI:
- Fixed `playwright.config.ts`: stale `neuralflow.api.main:app` → `komvos.api.main:app`;
  Windows-only venv path → plain `python`; added `NEURALFLOW_SESSION_TOKEN=test-token`
  and `KOMVOS_DEV=1` (dev-parity CORS; auth still fail-closed with token set).
- Fixed `e2e/merge_b.spec.ts`: dismiss first-run Tour overlay (it blocked clicks);
  replaced obsolete `(done)` text assertion with ✓ status-icon check + button label checks.
- `verify.yml`: added Playwright browser install + `npm run test:e2e` so build.yml
  AND release.yml both inherit E2E coverage.
- Local proof: `npx playwright test` → `1 passed` twice in a row.

Final gates phase 2: identical to phase 1 — all green.

## Phase 3 — Local attack surface and run lifecycle (uncommitted)

Task 1 — hardcoded fallback token removed:
- `useBackend.ts`: 2s port-8000/`test-token` fallback deleted; on IPC timeout the
  app now shows a full-screen actionable error naming the backend spawn log path
  (new `backend-log-path` IPC: `preload.ts` + `main.ts:52`). Dev browser fallback
  kept only behind `import.meta.env.DEV` reading `.env.development`.
- All `'test-token'` literals removed from src/ EXCEPT hands-off
  `DeployModal.tsx:50` (conflict recorded in phase-3 report §1).

Task 2 — CORS hardened via custom protocol:
- Electron registers `komvos://bundle` standard/secure scheme (`main.ts:18-23`),
  serves the built renderer through it (`main.ts:306`), loads packaged UI from it,
  navigation guard updated. Backend allowlist is now `["komvos://bundle"]`;
  `"null"`/`"file://"` gone (`api/main.py:105`). Verified by launching real
  Electron: renderer CORS preflights + authenticated calls all 200 in spawn log.
- `test_security.py` CORS tests updated to the new contract + new null-origin
  rejection regression test added.

Task 3 — abandoned-run leak fixed:
- `run_pipeline_task` owns registry cleanup on every path; bounded producer queue
  (`_DropOnFullQueue`, cap 10 000) prevents unbounded growth without deadlocking;
  5 s grace period preserves late-WS attach (`registry.py:39,44,266,324-338`).
- New test `tests/test_run_lifecycle.py`: abandoned run leaves registry empty.

Final gates phase 3: ruff clean · mypy clean · pytest 354 passed / 4 skipped ·
desktop typecheck/lint/tests 63 passed · grep shows only DeployModal.tsx:50 hit ·
real Electron launch verified against komvos:// origin.

## Phase 4 — Backend durability and provider resilience (uncommitted)

Task 1 — StateManager singleton:
- `api/registry.py:125-181`: `build_default_state_manager()` + memoized
  `ensure_default_state_manager()`; `get_state_manager()` keeps test-override
  priority. Legacy `~/.neuralflow` migration now runs exactly once.
- `api/main.py:127-152`: FastAPI lifespan builds it eagerly at startup; lazy
  fallback covers lifespan-less ASGI transports (tests).

Task 2 — provider resilience (cloud.py / ollama.py, partitioned parts only):
- One SDK/httpx client per (provider, base URL, API key) cached for process
  lifetime; explicit connect=10s / read=120s / write=30s / pool=10s timeouts on
  both endpoints; bounded exponential backoff with ±20% jitter (3 attempts,
  0.5s→8s cap) for 429/5xx and transport errors, applied at stream-open only;
  SDK-native retries disabled (`max_retries=0`) so one policy governs all
  providers. Retries logged, not surfaced as events (runner.py hands-off).
- New `tests/test_provider_resilience.py` (14 tests): classification, backoff
  behaviour, cache identity, ollama timeout assertions, mock-endpoint
  end-to-end regression.

Task 3 — Electron backend log:
- `src/main.ts`: async serialized writes (no blocking appendFileSync);
  size-based rotation at 5 MB keeping 3 generations as `.log.1..3`; no new
  dependency.

Verification: real Electron launch (lifespan startup + renderer API calls 200
via async log path) AND rebuilt PyInstaller binary smoke run — full mock
pipeline completed through the packaged executable (`EXITCODE=0`).
Final gates phase 4: ruff clean / mypy clean / pytest 368 passed, 4 skipped /
desktop typecheck+lint clean / vitest 63 passed (71 after phase-5 additions) /
real Electron launch + rebuilt-binary smoke run both verified.

## Phase 5 — Desktop resilience and the unfinished rename (uncommitted)

Task 1 — autosave & crash recovery:
- New `useDraftPersistence.ts`: debounced (1.5 s) localStorage autosave of the
  scrubbed serialized graph; restore-on-mount into empty canvas only; template
  origin tagged + toast so template loads are never silently overwritten.
- Discard banner ("Start clean" / "Keep") after restore; wired via
  `handleLoadTemplate` in App.tsx.
- Fixed pre-existing estimate refetch loop exposed by autosave (setNodes with
  identical content every ~1 s forever) — now referentially stable.
- Tests: 4 hook unit tests + Playwright `e2e/autosave.spec.ts` proving restore
  across a full renderer restart and clean discard.

Task 2 — error boundary:
- New top-level `ErrorBoundary.tsx` mounted in renderer.tsx: keeps shell alive,
  shows the error, offers "Export pipeline as JSON" (from autosaved draft)
  and Reload. 4 unit tests.

Task 3 — rename finished:
- Env vars → `KOMVOS_SESSION_TOKEN` / `KOMVOS_ALLOW_MOCK_ENDPOINT`, legacy
  names accepted with deprecation warnings (auth.py, registry.py); Electron,
  playwright config, smoke script, and tests moved to new names.
- FastAPI title line → "Komvos Backend" (title line only, per partition).
- localStorage keys migrated on read (`utils/localStorage.ts`):
  komvos_first_run / komvos_tour_completed.
- Schema $id/title, package-lock name, welcome text, pyproject/argparse
  descriptions, sub-package README headers, doc comments updated (18 files).
- Left as-is: functional compat (keyring service, DB migration path), hands-off
  files' comments, historical docs, main.py docstring/description lines.

Task 4 — README corrected: real counts (368 backend / 71 frontend unit / E2E),
tar.gz claim removed, packaged-binary claim reworded to the CI smoke step,
Ollama claim qualified, repo structure dir case fixed.

Final gates phase 5: ruff clean · mypy clean · pytest 368 passed / 4 skipped ·
desktop typecheck/lint clean · vitest 71 passed · e2e 2 passed · real Electron
launch verified with renamed env var.

## Open items / carry-forward

- Commit & push phases 2–5 when the user says go ("phase-1:" committed already;
  phases 2–5 changes staged in working tree, reports written).
- First real CI run should be watched for ubuntu/macOS quirks in the smoke step
  and Playwright `--with-deps`.
- DeployModal.tsx:50 needs the other workstream to drop its `'test-token'`
  fallback (one line) to fully satisfy the phase-3 grep gate.
- Retry visibility in the UI is left to the other workstream (logged only).
- Legacy env-var aliases + old-name comments in hands-off files need eventual
  cleanup by their owners.
