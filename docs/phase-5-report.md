# Phase 5 Report — Desktop resilience and the unfinished rename

Status: **complete, all gates green.** Per standing instruction: **not
committed or pushed** — waiting for explicit go-ahead.

## Entry check (before changes)

- `ruff check .` → All checks passed! · `mypy komvos` → Success (35 files) ·
  `pytest -q` → 368 passed, 4 skipped
- desktop typecheck/lint clean · `npm test` → 63 passed

---

## Task 1 — Autosave and crash recovery

- **`apps/desktop/src/hooks/useDraftPersistence.ts`** (new)
  - `DRAFT_STORAGE_KEY = 'komvos_autosave_draft_v1'` (line 12);
    `AUTOSAVE_DEBOUNCE_MS = 1500` (line 19).
  - `useAutosaveDraft(getPipeline, deps)` — resets a timer on every dep
    change; when 1.5 s elapse with no change it writes the draft. Unmount
    cancels the write; storage errors are swallowed (best-effort by design).
  - `loadDraft()` tolerates corrupt/missing data; `clearDraft()` removes it.
- **Debounce interval: 1.5 s after the last change.** Canvas edits fire many
  state updates per second; requiring 1.5 s of quiet means one write per
  natural pause, never competing with interaction, while still being ~30×
  faster than any realistic crash-to-loss window.
- **`apps/desktop/src/App.tsx`**
  - Autosave wired at lines 118-129 (`getPipeline` skips mid-run/empty canvas;
    draft is the scrubbed serialized schema). Template origin recorded via
    `lastLoadedTemplateName` (line 90) so drafts are tagged.
  - Restore-on-mount effect (lines 101-116): restores into an **empty canvas
    only** — a template/import loaded earlier can never be clobbered — shows
    banner naming the source template if applicable.
  - Banner (lines 294-305): "Unsaved work from your last session was
    restored…" with **Start clean** (`data-testid="discard-draft"` → clears
    nodes/edges/draft) and **Keep**.
  - Template-load paths (`LeftSidebar`, `OnboardingModal`) now route through
    `handleLoadTemplate` (line 93), which tags the draft AND toasts
    "Autosave note: this template is now your autosaved draft." — satisfying
    the no-silent-overwrite rule.
- **Found & fixed en route:** the pre-run cost-estimate effect refetched and
  replaced the `nodes` array every ~1 s forever (new array identity even when
  estimates were unchanged), which perpetually re-armed autosave. The estimate
  handler now returns the identical array when nothing changed
  (`App.tsx:99-121`), fixing both.

### Verification (full app restart)
`e2e/autosave.spec.ts` (Playwright): injects a 2-node graph, waits for the
localStorage write, **reloads the renderer from scratch**, asserts the restore
banner is visible and both nodes are back on the canvas, then clicks
"Start clean" and asserts empty canvas + draft key removed. **1 passed.**

## Task 2 — Top-level error boundary

- **`apps/desktop/src/components/ErrorBoundary.tsx`** (new): class boundary
  mounted at the very top of the tree in `renderer.tsx`. Fallback keeps the
  shell alive, displays the error message verbatim, and offers recovery:
  **"Export pipeline as JSON"** (downloads the last autosaved draft — the
  durable copy exists precisely for this) when one exists, plus **Reload**.
- Tests `src/components/ErrorBoundary.test.tsx` (4): throwing child does not
  take the app down and shows the message; export action present only when a
  draft exists; children render untouched when nothing throws.

## Task 3 — Finish the rename

Full-repo search performed (64 raw hits triaged). Renamed:

| Surface | Old | New |
|---|---|---|
| Session token env var | `NEURALFLOW_SESSION_TOKEN` | `KOMVOS_SESSION_TOKEN` |
| Mock gate env var | `NEURALFLOW_ALLOW_MOCK_ENDPOINT` | `KOMVOS_ALLOW_MOCK_ENDPOINT` |
| FastAPI title (`api/main.py`, title line ONLY per partition note) | `"NeuralFlow Backend"` | `"Komvos Backend"` |
| Onboarding localStorage key | `neuralflow_first_run` | `komvos_first_run` |
| Tour localStorage key | `neuralflow_tour_completed` | `komvos_tour_completed` |
| Schema `$id` / title (`shared/pipeline.schema.json`) | `neuralflow.app` / NeuralFlow Pipeline | `komvos.app` / Komvos Pipeline |
| `package-lock.json` package name ×2 | `neuralflow-desktop` | `komvos` |
| Onboarding welcome text | "Welcome to NeuralFlow!" | "Welcome to Komvos!" |

Migration concerns handled as required:
- **Env vars:** `auth.py:38-41,54-66` reads the new name first, falls back to
  the legacy name with a deprecation warning; `registry.py:58-72`
  `_mock_gate_enabled()` does the same for the mock gate. Our own spawn/test
  paths were moved to the new names (`src/main.ts:138,164`,
  `playwright.config.ts`, `packaging/scripts/smoke_backend.py`,
  `tests/conftest.py`, `test_api.py`, `test_merge_c.py`,
  `test_provider_resilience.py`).
- **localStorage:** new `src/utils/localStorage.ts::migratedRead()` copies the
  old key's value to the new key on first read and deletes the legacy entry,
  so existing users are NOT shown onboarding/the tour again
  (`OnboardingModal.tsx`, `Tour.tsx`).

Documentation comments/paths updated (18 files): `pyproject.toml` description,
`komvos_api_entry.py` argparse description, `shared/types.ts`,
`shared/README.md`, sub-package README headers (`api/`, `endpoints/`,
`executors/`, `scheduler/`, `state/`), `scheduler/engine.py` docstring,
`api/models.py` docstring, `endpoints/README.md` keyring example,
`benchmark_latency.py`, `packaging/README.md`.

**Deliberately left unchanged (with reasons):**
- `keyring` fallback service `"neuralflow"` (`secrets.py`) and the
  `~/.neuralflow` DB migration path — functional compatibility for existing
  users' keys/data, not cosmetic.
- Hands-off files containing old-name doc references:
  `accessPolicy.ts:13-14`, `DeployModal.tsx:509`, `komvos/compiler/*`
  (models.py docstrings, README), `komvos/serve/README.md`. Owned by the other
  workstream.
- Historical records (`progress.md`, `upgrade.md`, `docs/phase-*-report.md`)
  describe past states; rewriting them would falsify history.
- `api/main.py` module docstring (line 4) and app `description=` (line 146)
  still say NeuralFlow — the phase brief allows editing *only the title line*
  in that file, so they remain (noted as leftover).

## Task 4 — README corrections

`README.md`:
- Test counts corrected against actual runs: "**368 backend tests** … (4 more
  skip conditionally)" and "**71 frontend unit tests** + Playwright E2E";
  also states both build AND release jobs are gated on them (true since
  Phases 2–3).
- Removed the Linux `tar.gz` bullet — no electron-builder target produces one
  (Linux targets are AppImage + deb).
- Reworded the packaged-binary claim to what actually happens now: every CI
  build launches the bundled backend on all three OSes, polls `/health`, and
  executes a real pipeline through it before packaging (Phase 2 smoke step) —
  replacing the stale "was tested standalone" wording.
- Qualified the qwen2.5:3b end-to-end claim with its actual precondition
  (an Ollama instance available to the run); fixed `Komvos/` → `komvos/` in
  the repository structure diagram.

---

## Definition of Done — verbatim output

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
368 passed, 4 skipped, 5 warnings in 11.41s
```

### `cd apps/desktop && npm run typecheck && npm run lint`
```
> tsc --noEmit            (clean)
> eslint src --ext ts,tsx --report-unused-disable-directives --max-warnings 0   (clean)
```

### `cd apps/desktop && npm test`
```
 Test Files  9 passed (9)
      Tests  71 passed (71)
```

### E2E (autosave across full restart + existing suite)
```
npx playwright test e2e/autosave.spec.ts  →  1 passed (6.3s)
npx playwright test                        →  2 passed (merge_b + autosave)
```

### Autosave restores a graph across a full app restart — how verified
Automated: the Playwright spec above reloads the entire renderer and asserts
banner + restored nodes + working discard. Manual: built and launched the real
Electron shell after all changes — backend spawns with the renamed
`KOMVOS_SESSION_TOKEN`, becomes ready, and authenticated renderer calls succeed
(`OPTIONS /models → 200`, `GET /custom-nodes`, `GET /models`,
`GET /pipelines/templates` → all 200 in `komvos_backend_spawn.log`).

## Incomplete items / disagreements

1. **Old-name doc references remain in hands-off files** (`accessPolicy.ts`,
   `DeployModal.tsx`, `komvos/compiler/*`, `komvos/serve/README.md`). Per the
   hands-off protocol I did not touch them; listed here so the other
   workstream can sweep them.
2. **`api/main.py` docstring line 4 and app description line 146** still say
   NeuralFlow — the brief restricts that file to the title line this phase.
   Flagged rather than edited.
3. **Legacy env-var acceptance is permanent-looking code.** The brief says
   accept old names "for one release"; there is no release-versioning hook in
   the repo to auto-expire them, so removal is recorded here as a future task
   rather than implemented on a timer.
