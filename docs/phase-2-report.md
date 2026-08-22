# Phase 2 Report — Prove the packaged app actually starts

Status: **complete, all gates green.** Per instruction, changes are **not
committed/pushed yet** — holding until told to.

## Entry check (before any changes)

| Gate | Result |
|---|---|
| `import komvos_api_entry` | OK (exit 0) |
| `ruff check .` | All checks passed! |
| `mypy komvos` | Success: no issues found in 35 source files |
| `pytest -q` | 352 passed, 4 skipped |
| `npm run typecheck` / `npm run lint` | clean |
| `npm test` | 63 passed |

Hands-off files were not touched (verified via `git status` at the end: only
workflow, e2e, playwright-config, and new smoke-script files changed).

---

## Task 1 — Smoke-test the packaged backend in the build matrix

### What I read first (as instructed)

- `backend/komvos/api/auth.py` — auth is fail-closed: requests authenticate only
  by presenting the exact token from the `NEURALFLOW_SESSION_TOKEN` env var.
  (`KOMVOS_DEV=1` fallback applies only when NO token is configured; the
  packaged spawn path in `apps/desktop/src/main.ts:84-88` strips it.)
- `apps/desktop/src/main.ts` — Electron spawns the binary with
  `--host 127.0.0.1 --port N`, env `NEURALFLOW_SESSION_TOKEN=<token>`.
- `backend/komvos/api/registry.py:211-219` — mock endpoints require
  `NEURALFLOW_ALLOW_MOCK_ENDPOINT=1`; the gate is used as-is, not weakened.

### Files added / changed

1. **`packaging/scripts/smoke_backend.py`** (new) — single cross-platform
   Python script that:
   - picks a free port,
   - spawns `packaging/dist/komvos_backend(.exe)` with
     `--host 127.0.0.1 --port <free port>` and env
     `NEURALFLOW_SESSION_TOKEN=<random>`,
     `NEURALFLOW_ALLOW_MOCK_ENDPOINT=1`, `KOMVOS_DEV` removed (packaged parity),
   - polls `/health` until HTTP 200, hard timeout 60 s,
   - POSTs a 3-node pipeline (input → mock model → output) to
     `/pipelines/run` with the Bearer token,
   - polls `/runs/{run_id}/trace` until a terminal status; asserts it is
     `"completed"` (timeout 120 s),
   - terminates the process; every failure path exits non-zero.

   Full script is in the working tree (`packaging/scripts/smoke_backend.py`);
   key excerpts:

   ```python
   env = os.environ.copy()
   env["NEURALFLOW_SESSION_TOKEN"] = token          # fail-closed auth, same as Electron
   env["NEURALFLOW_ALLOW_MOCK_ENDPOINT"] = "1"      # mock gate opt-in, unchanged
   env.pop("KOMVOS_DEV", None)                      # production parity
   proc = subprocess.Popen(
       [binary, "--host", "127.0.0.1", "--port", str(port)], env=env, ...)
   ```

2. **`.github/workflows/build.yml`** — one step added to the build job,
   identical on all three runners, immediately after "Build backend executable":

   ```yaml
   - name: Smoke-test packaged backend
     run: python packaging/scripts/smoke_backend.py
   ```

   (`python` is on PATH from the existing setup-python step; the script locates
   the binary itself per-OS.)

### Deliberate-failure proof (DoD requirement)

**Outcome A — broken binary (bad import reintroduced):**
Temporarily changed `backend/komvos_api_entry.py:5` back to
`from neuralflow.api.main import app`, rebuilt with
`packaging/build_backend.ps1`, ran the smoke script:

```
Launching C:\Users\anime\Documents\GitHub\Far-Away\packaging\dist\komvos_backend.exe on 127.0.0.1:65252
SMOKE TEST FAILED: /health did not return 200 within 60s
EXITCODE=1
```

(PyInstaller's own analysis confirms why: `warn-komvos_backend.txt` reports
`missing module named 'neuralflow.api.main' - imported by ...komvos_api_entry.py`.)

**Outcome B — healthy binary (bad import reverted, rebuilt):**

```
Launching C:\Users\anime\Documents\GitHub\Far-Away\packaging\dist\komvos_backend.exe on 127.0.0.1:50902
Backend healthy on 127.0.0.1:50902
Started run f716cc37-0bec-4b11-aa1a-24ce11e347fc
Run completed (3 node executions recorded)
Smoke test passed.
EXITCODE=0
```

The source file was restored to `from komvos.api.main import app`.

*Honest note:* the very first broken-binary build appeared to pass once — the
rebuilt exe started fine seconds after the edit. A subsequent rebuild of the
same broken source produced an exe that failed exactly as expected. The
temporary pass was consistent with PyInstaller reusing stale cached analysis
for the just-edited entry file; after any clean rebuild the failure is caught.
CI always checks out fresh sources, so this cannot mask a real breakage there.

## Task 2 — Run the E2E suite in CI

The suite had never been wired up and could not have passed anywhere:

1. **`playwright.config.ts` backend webServer was doubly broken**:
   `-m uvicorn neuralflow.api.main:app` (pre-rename package → ModuleNotFoundError)
   and `.venv\\Scripts\\python.exe` (Windows-only path). Fixed to
   `cd ../../backend && python -m uvicorn komvos.api.main:app --port 8000`.
2. **Auth**: the browser falls back to token `'test-token'` on port 8000
   (`src/hooks/useBackend.ts:32-33`), but the config never set
   `NEURALFLOW_SESSION_TOKEN`, so every authenticated call would 401
   (fail-closed). Added `NEURALFLOW_SESSION_TOKEN: 'test-token'`.
3. **CORS**: with a session token set but no `KOMVOS_DEV`, the Vite dev origin
   is rejected at preflight (`OPTIONS /pipelines/run → 400`, confirmed from
   backend logs), so the browser never reached the API. Added
   `KOMVOS_DEV: '1'` — this mirrors the unpackaged dev spawn path in
   `src/main.ts:116`. Auth remains fail-closed: with a token configured,
   `KOMVOS_DEV` does not widen authentication (`auth.py:65-80`).
4. **`e2e/merge_b.spec.ts` fixes** (suite fixed, nothing deleted/skipped):
   - Dismiss the first-run guided Tour overlay before interacting; its
     full-screen backdrop intercepted the Run click (test timed out clicking).
   - The assertion `getByText('(done)')` is obsolete — the UI has not rendered
     a "(done)" title suffix for a long time; finished nodes now show a ✓
     status icon (`PipelineNode.tsx STATUS_ICONS`). Replaced with a ✓ visibility
     check plus button-label assertions (`toContainText('Run Pipeline')`,
     `not.toContainText('Running')`) — the old exact-match also broke on the
     idle button's ▶ glyph.
5. **`.github/workflows/verify.yml`** — two steps added to the test job so both
   build.yml and release.yml inherit E2E coverage:

   ```yaml
   - name: Install Playwright browsers
     working-directory: apps/desktop
     run: npx playwright install --with-deps chromium

   - name: Test frontend E2E (Playwright)
     working-directory: apps/desktop
     run: npm run test:e2e
   ```

Local proof (backend + vite started by Playwright itself, as CI will):

```
[WebServer] [STDERR] INFO:     Application startup complete.
  1 passed (4.6s)
...
  1 passed (4.5s)     # second run, stable
```

## Definition of Done — verbatim output

### `cd backend && python -c "import komvos_api_entry"`
(no output — exit 0; only the pre-existing pydantic UserWarning about the
`model_name` protected namespace on stderr)

### `cd backend && ruff check .`
```
All checks passed!
```

### `cd backend && mypy komvos`
```
Success: no issues found in 35 source files
```

### `cd backend && pytest -q`
```
352 passed, 4 skipped, 3 warnings in 10.10s
```

### `cd apps/desktop && npm run typecheck && npm run lint`
```
> komvos@0.1.0 typecheck
> tsc --noEmit

> komvos@0.1.0 lint
> eslint src --ext ts,tsx --report-unused-disable-directives --max-warnings 0

(no output — both clean)
```

### `cd apps/desktop && npm test`
```
 Test Files  7 passed (7)
      Tests  63 passed (63)
```

## Incomplete items

- The CI jobs themselves were not executed on GitHub runners (would require a
  push); the smoke step and e2e steps were proven locally on Windows with the
  real PyInstaller binary and the real Playwright suite instead. The smoke
  script is pure-stdlib Python and OS-independent; residual risk is limited to
  runner quirks (e.g. `--with-deps` apt packages on ubuntu-latest).

## Disagreements / notes

1. `KOMVOS_DEV=1` in the Playwright webServer env looks superficially like a
   security weakening, but it matches how the app itself runs unpackaged in dev
   (`main.ts:116`) and does not affect auth while a session token is set. The
   Task-1 smoke test deliberately runs WITHOUT it, exercising the packaged
   fail-closed path.
2. The brief said "fix the suite or the config" for failing E2E — both needed
   fixing (config: package name, python path, credentials/CORS; suite: tour
   dismissal, obsolete `(done)` assertion). No tests deleted or skipped.
3. Not committed/pushed — held per explicit instruction, contrary to the
   original deliverable "push after committing".
