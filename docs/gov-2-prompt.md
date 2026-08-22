# G2 — PROMPT (paste into Antigravity as-is)

## Review verdict on G1 — passed

Verified independently, not from the report:

- Zero HANDS OFF files touched; egress landed in a new module, avoiding the
  partitioned endpoint files entirely.
- `ruff` clean, `mypy` clean (40 files), 379 passed / 4 skipped — +27 tests, no
  new skips.
- Decoy probe **REJECTED** in served mode, still **COMPILED** in local. Bypass
  genuinely closed.
- Host matcher survives substring (`notexample.com`) and suffix
  (`example.com.evil.net`) attacks.
- Decisions recorded from all 4 nodes of a parallel tier — `contextvars`
  propagates correctly through `gather`. No-op when unbound.

Their `contextvars` disagreement was correct and is accepted. Their loopback
exemption is correct and stays.

## Decisions locked for G2

| Question | Answer |
|---|---|
| Profiles | Three: **Explore / Review / Locked** |
| Profile vs access node | Profile is authoritative, **overrides in both directions** |
| `Ask` | **True mid-run pause and resume** |
| `Ask` on a served HTTP run | **Degrades to Enforce, fails closed** |
| Deployments | **Snapshot the profile at deploy time** |

---

```
You are working in the Komvos repository (Electron + React + TypeScript desktop app
in apps/desktop, Python 3.11 FastAPI backend in backend/, package name `komvos`).

A SECOND OPERATOR IS WORKING IN THIS REPOSITORY IN PARALLEL. Their work lands on
its own schedule and may be incomplete at any moment. Do not fix, clean, lint,
reformat or comment on anything in their territory. If something of theirs is
broken, note it in one line in your report and move on.

ENTRY CHECK — the only conditions that may HALT you:
  cd backend
  ./.venv/Scripts/python.exe -c "import komvos.governance.context, komvos.governance.egress"
  ./.venv/Scripts/python.exe -m pytest tests/test_governance.py tests/test_compiler.py tests/test_access_policy.py -q
If either fails, STOP, write docs/gov-2-report.md explaining what is red, and make
no further changes.

BASELINE — run, record in the report, and CONTINUE regardless:
  ./.venv/Scripts/python.exe -m pytest -q
  ./.venv/Scripts/python.exe -m ruff check .
  ./.venv/Scripts/python.exe -m mypy komvos

HANDS OFF — do not create, edit, rename, move, reformat or delete:
  .github/workflows/                  (all)
  packaging/                          (all)
  apps/desktop/src/main.ts
  apps/desktop/src/hooks/useBackend.ts
  apps/desktop/src/hooks/usePipelineActions.ts
  apps/desktop/src/App.tsx
  apps/desktop/index.html
  apps/desktop/src/components/SettingsModal.tsx
  backend/komvos/executors/logic.py
  backend/pyproject.toml
  README.md
PARTITIONED — you may edit these, ONLY the regions named:
  backend/komvos/endpoints/cloud.py   - check_access only.
  backend/komvos/endpoints/ollama.py  - check_access only.
  backend/komvos/api/main.py          - append include_router lines at the bottom
                                        ONLY. Do not edit the CORS block, the
                                        FastAPI title, or any existing route body.
  backend/komvos/api/registry.py      - governance wiring only. Do not touch the
                                        run registry or get_state_manager.
No new third-party dependencies. If you believe you need one, STOP and report it.

THIS PHASE HAS NO UI. No React components, no panels, no buttons. The profile
picker and the governance log viewer are the NEXT phase. Your deliverable is the
engine plus its HTTP API, proven by tests. If you find yourself writing .tsx, you
have gone off scope.

CONTEXT — what exists after G1.
backend/komvos/governance/ contains an async decision path: every enforcement
point calls record_decision(...) and emits a GovernanceDecision on ALLOW as well
as DENY, carrying the domain, capability, outcome, reason, effective policy, and
which access nodes governed it. A run binds a decision sink via contextvars for
its duration. Enforcement today is binary: the pipeline's effective access policy
either permits an action or an AccessDeniedError is raised.

This phase adds the user's dial on top of that. Read these in full before writing
code and confirm in your report: backend/komvos/governance/ (every file including
README.md), backend/komvos/compiler/dag.py, backend/komvos/compiler/models.py,
backend/komvos/executors/model.py, backend/komvos/scheduler/runner.py,
backend/komvos/scheduler/engine.py, backend/komvos/serve/routes.py,
backend/komvos/serve/models.py, backend/komvos/state/sqlite.py.

TASK 1 — Posture and profile model.
A POSTURE is what happens when an action is not permitted by the pipeline's own
policy. Three values:
  Enforce - deny and halt, as today.
  Ask     - suspend the run, ask a human, act on the answer.
  Audit   - permit the action and record that it was permitted by posture.

A PROFILE binds a posture to each of the four governance domains (providers,
egress, spend, retention) plus the concrete limits that domain needs. Ship three
built-in profiles with these semantics:

  EXPLORE - for building something new; nothing should block you.
    providers: Audit    egress: Audit    spend: Audit (record, no cap)
    retention: full recording
  REVIEW - for work you intend to keep; you want to be asked.
    providers: Ask      egress: Ask      spend: Ask above a threshold
    retention: full recording
  LOCKED - for confidential or production work.
    providers: Enforce  egress: Enforce  spend: Enforce (hard cap)
    retention: metadata only

Built-ins are not editable. A user may create a custom profile, including by
copying a built-in. Exactly one profile is active at a time. Persist profiles and
the active selection in SQLite via StateManager, following the additive
CREATE TABLE IF NOT EXISTS migration pattern already used there. A database from
before this phase must open cleanly and default to a named built-in — state in
your report which one you chose as the default and why.

RETENTION NOTE: model the retention domain in the profile now so the shape is
right, but do NOT implement retention enforcement in this phase. That is a later
phase. Say so in the report.

TASK 2 — Profile resolution, in both directions.
The profile is authoritative and may LOOSEN as well as TIGHTEN what a pipeline's
access nodes granted. Write a pure resolution function: given a node's
pipeline-derived effective policy and the active profile, produce the policy
actually in force, plus the ORIGIN of each difference.

Origin is not optional bookkeeping — it is the point. Every decision must be able
to say whether an outcome came from the pipeline's own policy, from the profile,
or from both agreeing. A capability the profile granted that the pipeline never
asked for MUST be visibly attributed to the profile in the decision record. G1
already left a source field on GovernanceDecision for this; populate it properly
now.

CRITICAL INTERACTION — read carefully. The compiler currently fails compilation
when a model node's endpoint kind is not in its effective policy's providers. If
a profile can loosen, a pipeline could fail to compile that the active profile
would have permitted. Compile-time and run-time must not disagree.

Resolve it this way: give compile() an OPTIONAL profile argument. When it is not
supplied, compile() must behave EXACTLY as it does today — every existing test
must pass untouched, and you must not modify those tests. When it is supplied,
resolution is applied before the capability check, so both layers see the same
policy. CompiledDAG should carry both the pipeline-only policies and the resolved
policies, so a later phase can show the user what the profile changed.

The served-mode structural requirement from G1 — every model node must be governed
by an access node — STAYS, and is not affected by the profile. A profile adjusts
what a policy grants; it does not excuse a pipeline from declaring one.

TASK 3 — Ask posture: real mid-run pause and resume.
This is the largest piece of work in the phase. When posture is Ask and an action
would otherwise be denied, the run suspends at that node, a human is asked, and
the run continues or fails based on the answer.

Requirements:
  - Suspension must be a genuine await, not a blocking sleep or a busy loop. The
    event loop, the WebSocket pump, and every OTHER node in the same parallel tier
    must keep running while one node waits. Prove this with a test: a tier of two
    model nodes where one is waiting on approval and the other completes.
  - Emit a typed WebSocket event announcing the pending approval, carrying enough
    for a UI to render the question: run, node, domain, capability, the reason,
    and what will happen on each possible answer. Follow the existing WsEvent
    patterns in backend/komvos/scheduler/events.py exactly.
  - Add an HTTP endpoint that answers a pending approval. Answers: allow this once,
    allow for the remainder of this run, or deny. "Allow for the remainder of this
    run" applies to the same domain and capability only; it must not silently widen
    to anything else. Persisting an answer into the profile is a UI concern for a
    later phase — do not do it here.
  - A pending approval that is never answered must TIME OUT and FAIL CLOSED. Make
    the timeout a named module-level constant next to the existing
    SERVED_WALL_CLOCK_BUDGET_SECONDS so it is discoverable. Record the timeout as
    its own decision outcome, distinguishable from a human denial.
  - Cancellation must work while suspended. If the user hits the kill switch, or
    the wall-clock budget expires, a node awaiting approval must abort cleanly and
    not leak a pending task. Test this.
  - Pending approvals do not survive a process restart. Fail closed. State this in
    the package README.
  - The whole approval registry must be per-run and cleaned up when the run ends,
    on every path including error and cancellation. A run that ends with a pending
    approval must not leak it.

TASK 4 — Ask degrades to Enforce on served runs.
A pipeline deployed as an HTTP API has no human to prompt. For any run started by
a served request, Ask behaves as Enforce and denies. It must never block an HTTP
request waiting for a person. The decision record must show that a degrade
happened and why — not merely that the action was denied. Test that a served run
under a profile with Ask posture returns promptly and does not hang.

TASK 5 — Deployments snapshot their profile.
Changing the active desktop profile must never silently change the behaviour of an
already-deployed API. When a deployment is created, store the profile in force at
that moment with it, and use that snapshot for every request to that deployment.
Add the column with the additive migration pattern already used in the deployments
table; existing deployment rows must still load, and you must choose and document
a sensible profile for rows that predate the column.

TASK 6 — Governance API.
Add a new router module under the governance package, mounted from api/main.py by
appending an include_router line at the bottom. Do not edit existing routes.
Endpoints: list profiles, read one, create, update, delete a custom profile, get
the active profile, set the active profile, and answer a pending approval. Use the
existing session-token auth dependency, matching how other routers do it. Deleting
a built-in profile, or the active profile, must fail with a clear message rather
than leaving the system with no active profile.

TASK 7 — Close a known drift risk from G1.
PROVIDER_DEFAULT_HOSTS in backend/komvos/governance/egress.py duplicates the
provider default base URLs inside CloudEndpoint.generate, because cloud.py is
partitioned away from this workstream. If those two lists drift, egress control
silently checks the wrong host — a governance control that quietly stops
governing. Add a test that fails if they disagree. Derive the comparison from
cloud.py rather than restating the values a third time.

TASK 8 — Tests. At minimum:
  - Each built-in profile produces the expected posture per domain.
  - Resolution tightens correctly, and loosens correctly, with the right origin
    recorded in each case.
  - A capability granted only by the profile is attributed to the profile.
  - compile() with no profile behaves identically to today.
  - compile() with a loosening profile accepts a pipeline that would otherwise
    fail the capability check.
  - The served-mode "every model node must be governed" rule still holds under
    every profile.
  - Ask suspends, and a sibling node in the same tier still completes.
  - Allow-once, allow-for-run, and deny each produce the right outcome.
  - Timeout fails closed and is distinguishable from a human denial.
  - Cancelling a run while a node awaits approval aborts cleanly, no leak.
  - A served run under an Ask profile denies promptly and does not hang.
  - A deployment uses its snapshotted profile after the active profile changes.
  - A pre-existing database and a pre-existing deployment row both still load.
Use the mock endpoint. Do not call a real provider.

CONSTRAINTS:
- Do not modify any existing test to make something pass. If an existing test
  fails, that is a bug in your change.
- Do not weaken the G1 served-mode structural check.
- Everything user-configurable must have a safe default. A missing or corrupt
  profile setting must fall back to the strictest sensible behaviour, never the
  most permissive.
- If an instruction looks wrong, implement it anyway and record the disagreement.

DEFINITION OF DONE — paste real output into the report:
  cd backend
  ./.venv/Scripts/python.exe -m ruff check komvos/governance komvos/compiler komvos/scheduler komvos/endpoints komvos/executors komvos/serve komvos/state tests
  ./.venv/Scripts/python.exe -m mypy komvos/governance komvos/compiler komvos/scheduler komvos/serve
  ./.venv/Scripts/python.exe -m pytest tests/ -q
ruff and mypy must be clean for those paths. pytest must show no NEW failures
against your recorded baseline and at least 15 more passing tests.

DELIVERABLES:
1. docs/gov-2-report.md, in this order:
   - BASELINE output
   - Confirmation of which files you read
   - The built-in profile matrix as implemented, and the default profile you chose
   - How resolution records origin, with a worked example of a profile LOOSENING
     something and what the decision record shows
   - How suspension is implemented, and your evidence the event loop is not blocked
   - The approval timeout value you chose and why
   - How cancellation-while-suspended is handled
   - The migration approach for both new columns, and what pre-existing rows get
   - Full output of every DEFINITION OF DONE command
   - One line on anything of the other operator's that looked broken (do not fix)
   - Anything incomplete, and anything you disagreed with
2. One commit, message prefixed exactly: "gov-2: "
```
