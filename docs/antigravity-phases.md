# Komvos — Antigravity Phase Prompts (2–6)

Phase 1 is complete and unpushed. These five phases are re-scoped so they do
**not** touch the files the Round 2 governance feature is being built in.

**Push point:** your friend pushes once, after Phase 2. We branch from that push.
After that both sides work in parallel and merge normally.

Every phase carries the same HANDS OFF list. That list is the conflict-prevention
mechanism — it is not advisory. A phase that edits a denied file has to be redone.

Each phase writes `docs/phase-N-report.md` and makes one commit prefixed
`phase-N:`. Those are the only basis for the final review.

---

## PHASE 2 — Prove the packaged app actually starts

```
You are working in the Komvos repository (Electron + React + TypeScript desktop app
in apps/desktop, Python 3.11 FastAPI backend in backend/, package name `komvos`).

ENTRY CHECK — run first. If any fail, STOP, write docs/phase-2-report.md
explaining what is red, and make no further changes:
  cd backend && python -c "import komvos_api_entry" && ruff check . && mypy komvos && pytest -q
  cd apps/desktop && npm run typecheck && npm run lint && npm test

HANDS OFF — another workstream owns these. Do not create, edit, rename, move,
reformat or delete them, even if a linter or your own judgement suggests it:
  backend/komvos/compiler/          (all files)
  backend/komvos/serve/             (all files)
  backend/komvos/governance/        (all files, if present)
  backend/komvos/executors/model.py
  backend/komvos/scheduler/runner.py
  backend/komvos/endpoints/base.py
  apps/desktop/src/canvas/accessPolicy.ts
  apps/desktop/src/canvas/nodes/AccessNode.tsx
  apps/desktop/src/components/DeployModal.tsx
If a task seems to require touching one of these, STOP and say so in the report
instead of proceeding.

CONTEXT: The PyInstaller entry point had been importing a package that no longer
existed. The build still succeeded and still produced installers — it only failed
at runtime, on the user's machine. No job in CI has ever launched the packaged
binary. This phase closes that gap permanently. It is the highest-value phase in
the plan: it is the test that would have caught the worst bug in the repo the day
it was introduced.

SCOPE: CI only, plus whatever minimal test fixtures the CI steps need.
Do not change application behaviour.

TASK 1 — Smoke-test the packaged backend in the build matrix.
.github/workflows/build.yml already builds the PyInstaller executable via
packaging/build_backend.sh and packaging/build_backend.ps1 across
windows-latest, ubuntu-latest and macos-latest. After that build step, add a
step on each OS that:
  - launches the built executable on a free port, bound to 127.0.0.1
  - polls its /health endpoint until it returns 200, with a hard timeout of
    about 60 seconds
  - executes one complete pipeline end to end through the running binary and
    asserts the run reaches a completed state
  - shuts the process down and fails the job non-zero on timeout or bad status
Note: the backend requires a session token via environment variable and fails
closed without one — read backend/komvos/api/auth.py to see exactly how auth
resolves before writing this, and supply credentials the same way Electron does
in apps/desktop/src/main.ts. There is a mock endpoint kind available for
executing a pipeline without real API keys, but it is gated behind an
environment variable — find that gate in backend/komvos/api/registry.py and use
it rather than weakening it.
Make this step work identically on all three runners. Prefer a single
cross-platform script over three inline shell blocks.

TASK 2 — Run the E2E suite in CI.
apps/desktop/e2e/merge_b.spec.ts and apps/desktop/playwright.config.ts exist,
but no workflow ever invokes `npm run test:e2e`. Wire it into the test job,
including browser installation. If the suite does not currently pass, fix the
suite or the config — do not delete tests and do not mark them skipped to get
green. If a test is genuinely obsolete, say so in the report and leave it in
place for review.

CONSTRAINTS:
- Do not weaken the mock-endpoint environment gate, the auth fail-closed
  behaviour, or the 127.0.0.1 bind in order to make the smoke test easier.
  The smoke test must work with those protections intact.
- Do not add `continue-on-error` or `|| true` to any step.
- If an instruction looks wrong, implement it anyway and note the disagreement.

DEFINITION OF DONE:
- The smoke test genuinely launches the built binary and fails when the binary
  is broken. Prove this: temporarily reintroduce a bad import in
  backend/komvos_api_entry.py, confirm the smoke step fails, then revert it.
  Paste both outcomes into the report.
- All existing gates still pass:
    cd backend && ruff check . && mypy komvos && pytest -q
    cd apps/desktop && npm run typecheck && npm run lint && npm test

DELIVERABLES:
1. docs/phase-2-report.md — what you added, the full YAML you added, evidence of
   the deliberate-failure test above, and anything you could not complete.
2. One commit, message prefixed exactly: "phase-2: "
3. After committing, push. This is the agreed push point for the other
   workstream to branch from.
```

---

## PHASE 3 — Local attack surface and run lifecycle

```
You are working in the Komvos repository (Electron + React + TypeScript desktop app
in apps/desktop, Python 3.11 FastAPI backend in backend/, package name `komvos`).

ENTRY CHECK — run first. If any fail, STOP and report:
  cd backend && ruff check . && mypy komvos && pytest -q
  cd apps/desktop && npm run typecheck && npm run lint && npm test

HANDS OFF — another workstream owns these. Do not create, edit, rename, move,
reformat or delete them:
  backend/komvos/compiler/          (all files)
  backend/komvos/serve/             (all files)
  backend/komvos/governance/        (all files, if present)
  backend/komvos/executors/model.py
  backend/komvos/scheduler/runner.py
  backend/komvos/endpoints/base.py
  apps/desktop/src/canvas/accessPolicy.ts
  apps/desktop/src/canvas/nodes/AccessNode.tsx
  apps/desktop/src/components/DeployModal.tsx
PARTITIONED FILES — you may edit these, but only the parts named:
  backend/komvos/api/main.py       — CORS configuration only. Do not add routes.
  backend/komvos/api/registry.py   — the run registry only. Do not touch
                                     get_state_manager or endpoint resolution.
  backend/komvos/state/sqlite.py   — do not add tables or columns.

CONTEXT: The Electron shell spawns the Python backend on a random port and hands
the renderer a per-session token over IPC. That design is sound. Three things
undermine it.

TASK 1 — A hardcoded fallback token ships in production builds.
apps/desktop/src/hooks/useBackend.ts starts a 2-second timer and, if the
backend-ready IPC message has not arrived, assumes port 8000 and the literal
token string 'test-token'. That branch is inside `if (window.electron)`, so it is
live in packaged builds, not just development. The real packaged backend is on a
random port, so this never reaches it — what it can reach is any other process
listening on 127.0.0.1:8000, which then receives the user's pipeline documents.
The same literal fallback is repeated in three fetch calls in
apps/desktop/src/hooks/usePipelineActions.ts.

Remove the fallback entirely. When the IPC message does not arrive, the app must
show an explicit, actionable error state naming the backend log file path (the
main process already writes one — find it in apps/desktop/src/main.ts) rather
than guessing an endpoint. Keep a development path for running against a manually
started backend, but gate it so it cannot be present in a production bundle.
Remove every occurrence of the 'test-token' literal from src/.

TASK 2 — The CORS allowlist admits any sandboxed page on the web.
backend/komvos/api/main.py allows the origins "null" and "file://" with
credentials enabled. The reasoning in the comment is correct for Electron — a
window loaded with loadFile sends an opaque origin. But "null" is also the origin
every sandboxed iframe on the public internet sends, so the allowlist admits any
web page that embeds one. In development this is a working cross-site attack: the
dev port is a fixed 8000 and the auth check accepts any non-empty bearer token
when the dev environment variable is set.

Fix this properly rather than by patching the symptom: register a custom protocol
scheme for the packaged renderer in the Electron main process so the window loads
from a real, non-forgeable origin, then remove "null" from the backend allowlist
and allow that scheme instead. Read the existing navigation guards in
apps/desktop/src/main.ts first — they allowlist file: today and will need to move
with you. Verify the packaged app still loads and can talk to the backend; a
broken renderer is worse than the problem you are fixing. If you conclude the
protocol change is too risky to complete safely, implement a strict origin check
on all state-changing routes instead, and say clearly in the report that you chose
the fallback and why.

TASK 3 — Abandoned runs leak a runner and an unbounded queue.
In backend/komvos/api/registry.py the run registry entry for a run is removed in
only two places: the WebSocket handler's cleanup, and the serve routes. A run
started by POST /pipelines/run whose client never opens the WebSocket is never
removed. Its event queue is unbounded and has no consumer, so it accumulates one
event per streamed token for the entire run, and the registry only ever grows.
Move ownership of the lifecycle to the background task that drives the run, so
cleanup happens on every path including the abandoned one. Allow a grace period
for a WebSocket that attaches slightly late — the current handler already waits up
to 4 seconds for a run to appear, so do not break that. Bound the queue. Add a
test that starts a run, never attaches a WebSocket, and asserts the registry is
empty afterwards.

CONSTRAINTS:
- Do not weaken the fail-closed auth behaviour in backend/komvos/api/auth.py.
- Do not loosen contextIsolation, sandbox, nodeIntegration or webSecurity in the
  BrowserWindow configuration.
- If an instruction looks wrong, implement it anyway and note the disagreement.

DEFINITION OF DONE:
  cd backend && ruff check . && mypy komvos && pytest -q
  cd apps/desktop && npm run typecheck && npm run lint && npm test
  grep -r "test-token" apps/desktop/src/      # must return nothing
  The app must still launch and reach the backend. State in the report exactly
  how you verified that — an unverified claim here is worse than none.

DELIVERABLES:
1. docs/phase-3-report.md — what changed with file:line references, how you
   verified the app still launches, which approach you took for TASK 2 and why,
   and full verification output.
2. One commit, message prefixed exactly: "phase-3: "
```

---

## PHASE 4 — Backend durability and provider resilience

```
You are working in the Komvos repository (Electron + React + TypeScript desktop app
in apps/desktop, Python 3.11 FastAPI backend in backend/, package name `komvos`).

ENTRY CHECK — run first. If any fail, STOP and report:
  cd backend && ruff check . && mypy komvos && pytest -q
  cd apps/desktop && npm run typecheck && npm run lint && npm test

HANDS OFF — another workstream owns these. Do not create, edit, rename, move,
reformat or delete them:
  backend/komvos/compiler/          (all files)
  backend/komvos/serve/             (all files)
  backend/komvos/governance/        (all files, if present)
  backend/komvos/executors/model.py
  backend/komvos/scheduler/runner.py
  backend/komvos/endpoints/base.py
  apps/desktop/src/canvas/accessPolicy.ts
  apps/desktop/src/canvas/nodes/AccessNode.tsx
  apps/desktop/src/components/DeployModal.tsx
PARTITIONED FILES — you may edit these, but only the parts named:
  backend/komvos/endpoints/cloud.py   — client construction, timeouts, retries.
                                        Do NOT touch check_access or estimate_cost.
  backend/komvos/endpoints/ollama.py  — same restriction.
  backend/komvos/state/sqlite.py      — do not add tables or columns.

CONTEXT: Three problems that never show up in a demo and always show up the
moment someone leaves the app running.

TASK 1 — A new StateManager is constructed on every request.
backend/komvos/api/registry.py returns a brand-new StateManager instance every
time it is called. Each construction re-runs table creation, a pragma, and a
column-migration probe, and the legacy directory migration from an older product
name is re-checked on every request. StateManager then opens a fresh SQLite
connection per operation on top of that.
Build it once at application startup using FastAPI's lifespan mechanism and store
it on application state. The existing test-override path that injects a
StateManager via app.state must keep working exactly as it does now — read how
backend/tests/conftest.py uses it before you change anything. Run the legacy
migration exactly once, at startup.

TASK 2 — Cloud calls have no timeouts, no retries, and no client reuse.
backend/komvos/endpoints/cloud.py constructs a brand-new provider SDK client on
every single generate call — no connection reuse across nodes or loop iterations,
no explicit timeout, and no retry policy. A stalled provider holds a run for the
SDK's default timeout, and a single rate-limit response fails the node outright.
The Ollama endpoint does set a timeout, so the two implementations behave
differently under failure, which is its own problem.
Cache one client per provider and base URL for the process lifetime. Set explicit
connect and read timeouts on both endpoint implementations. Add bounded
exponential backoff with jitter for rate-limit and server-error responses, with a
cap on attempts. Add tests using the mock endpoint.
NOTE: you may not edit backend/komvos/scheduler/runner.py, so do not add a new
scheduler event for retries in this phase. Log retries instead, and note in the
report that surfacing them in the UI is left to the other workstream.

TASK 3 — The Electron backend log is unbounded and written synchronously.
apps/desktop/src/main.ts writes every line of backend stdout and stderr to a log
file using a synchronous append. That is blocking disk I/O on the Electron main
process for every log line the backend produces, which will stutter the UI during
a streaming run, and the file grows without limit for the life of the install.
Make the writes non-blocking and add size-based rotation with a small number of
retained files. Do not lose the log content — the error path in Phase 3 tells
users to look at this file.

CONSTRAINTS:
- Do not change the shape of any event the frontend already consumes.
- Do not introduce a new dependency for logging or rotation if the platform can
  do it; if you conclude one is genuinely required, say which and why in the
  report before adding it.
- If an instruction looks wrong, implement it anyway and note the disagreement.

DEFINITION OF DONE:
  cd backend && ruff check . && mypy komvos && pytest -q
  cd apps/desktop && npm run typecheck && npm run lint && npm test
  The app still launches and runs a pipeline. State how you verified it.

DELIVERABLES:
1. docs/phase-4-report.md — what changed with file:line references, the timeout
   and retry values you chose and why, and full verification output.
2. One commit, message prefixed exactly: "phase-4: "
```

---

## PHASE 5 — Desktop resilience and the unfinished rename

```
You are working in the Komvos repository (Electron + React + TypeScript desktop app
in apps/desktop, Python 3.11 FastAPI backend in backend/, package name `komvos`).

ENTRY CHECK — run first. If any fail, STOP and report:
  cd backend && ruff check . && mypy komvos && pytest -q
  cd apps/desktop && npm run typecheck && npm run lint && npm test

HANDS OFF — another workstream owns these. Do not create, edit, rename, move,
reformat or delete them:
  backend/komvos/compiler/          (all files)
  backend/komvos/serve/             (all files)
  backend/komvos/governance/        (all files, if present)
  backend/komvos/executors/model.py
  backend/komvos/scheduler/runner.py
  backend/komvos/endpoints/base.py
  apps/desktop/src/canvas/accessPolicy.ts
  apps/desktop/src/canvas/nodes/AccessNode.tsx
  apps/desktop/src/components/DeployModal.tsx
PARTITIONED FILES — you may edit these, but only the parts named:
  apps/desktop/src/components/SettingsModal.tsx — renaming and string changes
                                                  only. Do not add new sections,
                                                  fields or settings.

CONTEXT: Losing work is currently trivial, and commit d272c6f left a rename
half-finished in surfaces users can see.

TASK 1 — There is no autosave and no crash recovery.
The canvas exists only in React state. There is no autosave, no draft file, and
no recovery on relaunch — closing the window or crashing the renderer discards
the pipeline. The only durable path is manual export.
Add debounced autosave of the serialized graph to local storage, restore it on
startup, and give the user a clear way to discard the restored draft and start
clean. Do not autosave over a template the user has just loaded without making
that obvious. Add tests.

TASK 2 — A single render error blanks the whole application.
There is no React error boundary anywhere in the tree. Add a top-level error
boundary that keeps the shell alive, shows what failed, and offers exporting the
current pipeline as the recovery action. Add a test that a throwing child does
not take down the app.

TASK 3 — Finish the rename that commit d272c6f started.
The old product name survives in shipped surfaces: two environment variable names
still carry the old prefix; the FastAPI application title still reads as the old
product and appears in the API docs; two local-storage keys in the renderer still
use the old prefix (onboarding state and product-tour state); and several
documentation comments point at directory paths under the old package name that
no longer exist. Search the whole repository, not just the surfaces listed here.
Two migration concerns you must handle rather than ignore: accept the old
environment variable names for one release with a deprecation warning, and migrate
the local-storage keys on read — renaming them naively re-triggers onboarding and
the product tour for every existing user.
NOTE: the FastAPI title lives in a file you may only edit for CORS in another
phase. In THIS phase you may edit the title line and nothing else in that file.

TASK 4 — The README does not match the repository.
It claims 150 backend tests and 37 frontend tests; the real numbers are higher.
Run the suites and state the actual current counts. It advertises a Linux tar.gz
download that no build target produces. It states the packaged binary was verified
standalone, which was true before the rename broke the entry point and is only
true again now that Phase 2 verifies it in CI. Correct all of these against what
the repository actually does. Do not inflate anything — if a claim is no longer
verifiable, remove it rather than restating it.

CONSTRAINTS:
- Autosave must not fire so often that it stalls canvas interaction. State the
  debounce interval you chose and why.
- Do not add a new state-management dependency for autosave.
- If an instruction looks wrong, implement it anyway and note the disagreement.

DEFINITION OF DONE:
  cd backend && ruff check . && mypy komvos && pytest -q
  cd apps/desktop && npm run typecheck && npm run lint && npm test
  Autosave restores a graph across a full app restart. State how you verified it.

DELIVERABLES:
1. docs/phase-5-report.md — what changed with file:line references, the debounce
   interval and reasoning, the full list of rename sites you found, and full
   verification output.
2. One commit, message prefixed exactly: "phase-5: "
```

---

## PHASE 6 — Supply chain, packaging and hardening

```
You are working in the Komvos repository (Electron + React + TypeScript desktop app
in apps/desktop, Python 3.11 FastAPI backend in backend/, package name `komvos`).

ENTRY CHECK — run first. If any fail, STOP and report:
  cd backend && ruff check . && mypy komvos && pytest -q
  cd apps/desktop && npm run typecheck && npm run lint && npm test

HANDS OFF — another workstream owns these. Do not create, edit, rename, move,
reformat or delete them:
  backend/komvos/compiler/          (all files)
  backend/komvos/serve/             (all files)
  backend/komvos/governance/        (all files, if present)
  backend/komvos/executors/model.py
  backend/komvos/scheduler/runner.py
  backend/komvos/endpoints/base.py
  apps/desktop/src/canvas/accessPolicy.ts
  apps/desktop/src/canvas/nodes/AccessNode.tsx
  apps/desktop/src/components/DeployModal.tsx
Note in particular: the per-scope cost ceiling in the access policy is owned by
the other workstream. Do not attempt to enforce or change it here.

CONTEXT: Final phase. Individually small items; together they are most of the
difference between something that looks like a prototype and something that looks
maintained. Complete all of them.

TASK 1 — Builds are not reproducible, and nothing scans dependencies.
backend/pyproject.toml pins FastAPI, uvicorn, pydantic, keyring and httpx to exact
versions, but leaves the four fastest-moving dependencies — the three model
provider SDKs and the templating library — as minimum-version constraints. Three
CI runners resolving independently can produce three different builds from one
tag. Pin them to exact versions.
Neither workflow runs a dependency vulnerability scan. Add one for both Python and
npm as a non-blocking job first. Current known state: production npm dependencies
are clean; the dev tree carries 9 advisories via a transitive dependency of the
build toolchain. Report what the scan finds. Do not attempt to force-upgrade the
build toolchain in this phase.

TASK 2 — Two packaging configs exist and disagree.
There is an electron-builder configuration block inside apps/desktop/package.json
and a separate electron-builder YAML file under packaging/. Only the first is ever
loaded, because electron-builder reads config from its own working directory. They
disagree on application id, output directory, and the resource path the backend
binary is copied to. The dead file is also the only place macOS hardened runtime,
entitlements and notarization appear — so the repo reads as though code signing is
configured when the live config explicitly disables it, and the entitlements file
it references does not exist.
Resolve this to exactly one source of truth. State in the report which one you
kept and what the real signing status now is. Do not claim signing is configured
if it is not.

TASK 3 — Hardening pass. Each is small; do them in one pass.
  a) apps/desktop/index.html has no Content-Security-Policy. The rest of the
     Electron hardening is strong; this is the missing layer. Add one as strict as
     the app actually permits, and verify the app still runs. If something
     genuinely requires loosening it, say so explicitly rather than quietly
     widening the policy.
  b) The PyInstaller spec in packaging/ builds the backend as a console
     application, so a console window appears beside the packaged Windows app.
     Fix that without losing the stdout and stderr the Electron main process
     captures into its log.
  c) backend/komvos/executors/logic.py renders user-supplied Jinja templates in a
     sandbox, which is correct, but with no bound on output size or render time —
     a template can still loop a large range. Add bounds and a clear error message.
  d) The same file performs a module-level import inside a function body. Move it
     to module scope.

CONSTRAINTS:
- Do not introduce new dependencies for anything in TASK 3.
- Do not weaken the CSP to make something convenient work.
- If an instruction looks wrong, implement it anyway and note the disagreement.

DEFINITION OF DONE:
  cd backend && ruff check . && mypy komvos && pytest -q
  cd apps/desktop && npm run typecheck && npm run lint && npm test
  The app launches and the CSP does not break the renderer. State how you verified.

DELIVERABLES:
1. docs/phase-6-report.md — what changed with file:line references, the real
   signing status, what the dependency scan found, and full verification output.
2. One commit, message prefixed exactly: "phase-6: "
3. Additionally write docs/phases-summary.md: one table listing every task across
   phases 1–6 with a status of done / partial / not done, and a plain list of
   anything you were unable to complete or disagreed with. This is the document
   that will be reviewed first.
```

---

## Operator notes

- **Push after Phase 2, then continue.** The other workstream branches from that
  push. Phases 3–6 can be pushed as they complete after that.
- If a phase's **entry check** fails, stop and report rather than pushing through.
  A phase built on a broken predecessor is harder to review than one that halted.
- If a task appears to require touching a HANDS OFF file, that is a scoping error
  on our side, not permission to proceed. Stop and report it.
- Phase 2 is the one not to skip if time runs short.

## What is NOT in these phases

Owned by the Round 2 governance workstream, deliberately excluded:

- The served-mode access-control bypass (a decoy access node satisfies the check)
- Per-deployment spend caps and concurrent-run bounds
- Real provider usage accounting replacing estimated token counts
- The budget-exceeded event carrying an endpoint id instead of a node id
- Trace retention, run deletion, and the recording-level setting
- Per-scope enforcement of the access policy's cost ceiling
- Making `allow_network` and `allowed_domains` actually enforced
