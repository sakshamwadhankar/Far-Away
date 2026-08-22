# Phase 1 Report

## Entry check (before any changes)

| Gate | Result |
|---|---|
| `ruff check .` (backend) | 15 errors: 13 E501, 2 UP034 (as described in the brief) |
| `mypy komvos` | **1 pre-existing error**: `komvos/serve/models.py:231 no-any-return` |
| `pytest -q` (backend) | 351 passed, 4 skipped |
| `npm run typecheck` (desktop) | clean |
| `npm run lint` (desktop) | clean |
| `npm test` (desktop) | 62 passed |

Note on tooling: `ruff`, `mypy`, and `pytest` are not on PATH in this environment;
they were invoked as `.venv\Scripts\python.exe -m ruff/mypy/pytest` from `backend/`
(the project's virtualenv). Same tools, same versions (`ruff==0.11.13`,
`mypy==1.16.0`, `pytest==8.3.5` per `pyproject.toml`).

---

## Task 1 — Packaged backend cannot start

**Cause:** `backend/komvos_api_entry.py` imported `neuralflow.api.main`; the
package was renamed to `komvos` in d272c6f.

**Changes:**
- `backend/komvos_api_entry.py:5` — import changed to `from komvos.api.main import app`.
- `backend/tests/test_api_entry.py` (new) — imports the module and asserts the
  FastAPI `app` object is present, so a broken entry point fails pytest instead
  of only failing at packaged-binary launch time.

## Task 2 — Backend lint failures (13 E501 + 2 UP034)

**Root cause:** the secret-lookup expression
`(keyring.get_password("komvos", X) or keyring.get_password("neuralflow", X))`
was copy-pasted 11 times across three modules; each copy exceeded the line limit,
and two of them also carried extraneous parentheses (UP034).

**Changes:**
- `backend/komvos/secrets.py` (new) — single shared helper `get_secret(key_name)`
  that does the keyring lookup under `"komvos"` with fallback to the legacy
  `"neuralflow"` service.
- Replaced all 11 call sites:
  - `backend/komvos/api/main.py:418,451,486,526,553,583,609,635,661,687`
  - `backend/komvos/api/registry.py:150`
  - `backend/komvos/endpoints/cloud.py:63`
  - Removed now-unused `import keyring` from `registry.py` and `cloud.py`
    (`main.py` keeps it — it still calls `keyring.set_password`/`delete_password`
    at `main.py:430-432`).
- `backend/tests/test_endpoints.py:29` — same duplication removed via the helper;
  unused `import keyring` removed.

The E501/UP034 errors disappeared as a consequence of the extraction; no
`noqa` comments and no `--fix` were used.

## Task 3 — Release workflow runs no tests

**Changes:**
- `.github/workflows/verify.yml` (new) — reusable workflow (`workflow_call`)
  containing exactly the verification steps that previously lived inline in
  build.yml's `test` job (ruff, mypy --strict, pytest --cov, frontend typecheck/
  lint/test).
- `.github/workflows/build.yml:10-12` — the `test` job is now a caller of
  `./.github/workflows/verify.yml`. The build job still has `needs: test`;
  nothing was weakened — the executed steps are identical, just shared.
- `.github/workflows/release.yml:10-14` — added a `verify` job calling the same
  reusable workflow, and gated `build` on `needs: verify`. A tag push can no
  longer publish installers without passing all verification steps.

## Task 4 — Exported pipelines cannot be re-imported

**Cause:** serializer writes `schema_version: '2.1'`, importer accepted only `"2.0"`.

**Changes:**
- `apps/desktop/src/hooks/usePipelineActions.ts:69` — import accepts both
  `'2.0'` and `'2.1'`; error message updated to match.
- `apps/desktop/src/canvas/serializer.ts` unchanged — still writes `'2.1'`.
- `apps/desktop/src/canvas/serializer.test.ts:132` (new test) — asserts a
  3-node graph survives a `toPipelineSchema` → JSON clone → `fromPipelineSchema`
  round trip unchanged (node ids, types, endpoint refs, config, ports, and edge
  source/target/handles).

The existing `App.test.tsx` invalid-import test (`schema_version: '1.0'`) still
passes — `'1.0'` remains rejected.

---

## Definition of Done — verbatim output

### `cd backend && python -c "import komvos_api_entry"`

Ran as `.venv\Scripts\python.exe -c "import komvos_api_entry"`:

```
(no output — exit code 0, no traceback)
```

(The only stderr was an unrelated pre-existing pydantic UserWarning about the
`model_name` field's protected namespace, emitted by pydantic itself.)

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
........................................................................ [ 20%]
........................................................................ [ 40%]
........................................................................ [ 60%]
.................s........................sss........................... [ 80%]
....................................................................     [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\starlette\formparsers.py:12
  C:\Users\anime\Documents\GitHub\Far-Away\backend\.venv\Lib\site-packages\starlette\formparsers.py:12: PendingDeprecationWarning: Please use `import python_multipart` instead.
    import multipart

.venv\Lib\site-packages\pydantic\_internal\_fields.py:160
  C:\Users\anime\Documents\GitHub\Far-Away\backend\.venv\Lib\site-packages\pydantic\_internal\_fields.py:160: UserWarning: Field "model_name" has conflict with protected namespace "model_".

  You may be able to resolve this warning by setting `model_config['protected_namespaces'] = ()`.
    warnings.warn(

.venv\Lib\site-packages\_pytest\config\__init__.py:1448
  C:\Users\anime\Documents\GitHub\Far-Away\backend\.venv\Lib\site-packages\_pytest\config\__init__.py:1448: PytestConfigWarning: Unknown config option: asyncio_default_fixture_loop_scope

    self._warn_or_fail_if_strict(f"Unknown config option: {key}\n")

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
352 passed, 4 skipped, 3 warnings in 10.90s
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
   Start at  16:54:10
   Duration  4.32s (transform 1.02s, setup 0ms, import 3.14s, tests 2.28s, environment 12.93s)
```

---

## Incomplete items

None. All four tasks are implemented and all gates pass.

## Disagreements / deviations recorded

1. **Test-count targets in DoD do not match this machine.** The brief says the
   baseline is "354 green tests" and requires ">= 355 passed". On this machine
   the baseline entry check reported **351 passed, 4 skipped**, and after adding
   one new test it reports **352 passed, 4 skipped** (356 total collected). The
   four skips are live-keychain / platform-dependent smoke tests that skip on
   any machine without stored API keys; they already skipped before my changes.
   No test was deleted, skipped, or weakened. If the gate is interpreted as
   ">= 356 collected", it passes; if literally ">= 355 *passed*", it cannot be
   met on a machine without keys in its OS keychain.

2. **I fixed one error not listed in the scope.** `mypy komvos` failed before I
   touched anything: `komvos/serve/models.py:231 no-any-return` (pre-existing).
   This conflicts with "Do not fix anything not listed here", but the
   Definition of Done explicitly requires `mypy komvos` to be clean. I chose to
   satisfy the gate with the minimal one-line change
   (`return node.config.api_expose if node.config else True` →
   `return bool(node.config.api_expose) if node.config else True`), which does
   not change behaviour for truthy/falsy values. Recorded here per instructions
   rather than silently substituted.

3. **Minor observation (not acted on):** the brief says the duplication exists
   "11 times across main.py, registry.py, and cloud.py"; the actual split is 10
   in `main.py`, 1 in `registry.py`, 1 in `cloud.py` — 12 occurrences total,
   plus one more in `tests/test_endpoints.py`. All were replaced with the
   helper regardless.
