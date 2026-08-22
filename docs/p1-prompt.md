# P1 — SPLIT INTO TWO RUNS (lean, no test-writing)

**What changed:** the agent no longer writes tests. Testing and verification is
handled outside. Existing tests stay as a gate because that costs the agent
nothing and catches regressions for free — only NEW test authoring is cut, which
is where the time was going.

**Also split into P1a (backend) and P1b (UI).** Shorter runs, and the backend gets
banked and verified before the UI is built on top of it.

Run P1a → I verify → run P1b. Both prompts are below; you can paste them
back to back if P1a's gates come out clean.

---

## P1a — PROMPT (backend only)

```
You are working in the Komvos repository (Electron + React + TypeScript desktop app
in apps/desktop, Python 3.11 FastAPI backend in backend/, package name `komvos`).

WORKING STYLE FOR THIS RUN — read carefully, this overrides your defaults:
- DO NOT write any new tests. No new test files, no new test functions, no test
  fixtures, no dummy/sample data harnesses, no mock scaffolding.
- DO NOT temporarily insert placeholder data into source files and remove it later.
  Write the real implementation once.
- Existing tests must keep passing. You may READ them to understand contracts. You
  may not edit them.
- Verification is being done outside this run. Your job is the implementation.
- Keep the report SHORT. Bullet points, not prose.
Spend your effort on correct code, not on proving it.

ENTRY CHECK — only these may HALT you:
  cd backend
  ./.venv/Scripts/python.exe -c "import komvos.governance.api, komvos.governance.approvals"
If it fails, STOP and write docs/p1a-report.md saying what is red.

HANDS OFF — do not touch:
  .github/workflows/   packaging/   apps/desktop/ (ALL — P1a is backend only)
  backend/komvos/executors/logic.py   backend/pyproject.toml   README.md
PARTITIONED:
  backend/komvos/api/main.py - append include_router lines at the bottom only.
No new third-party dependencies. If you think you need one, STOP and report it.

CONTEXT.
backend/komvos/governance/ already has: an async decision path emitting a
GovernanceDecision on ALLOW as well as DENY (domain, capability, outcome, reason,
effective policy, governing access nodes, DecisionOrigin); postures
Enforce/Ask/Audit; three profiles EXPLORE/REVIEW/LOCKED with LOCKED as the safe
default; bidirectional profile resolution; real mid-run suspend/resume for Ask; an
approvals registry; and an HTTP API for profiles, active profile, and answering
approvals.

Missing: decisions are held in an in-memory sink and vanish on exit, there is no
way to query them, and they never reach the UI live. This run fixes all three.

Read first: backend/komvos/governance/ (all .py + README.md),
backend/komvos/state/sqlite.py, backend/komvos/scheduler/events.py,
backend/komvos/scheduler/runner.py.

TASK 1 — Fix a defect found in review. Do this first.
DecisionOrigin has PIPELINE_POLICY, PROFILE, PIPELINE_AND_PROFILE and nothing for
"a human decided this". posture.py records an Ask-approved action as
origin=PROFILE, so "the profile auto-granted it" and "the user personally approved
it" are indistinguishable in the log. Those are completely different events and
the second one is the more important.

Add an origin for a decision produced by a human answering an approval, and record
which answer they gave (allow-once vs allow-for-run) so a one-time approval reads
differently from a standing one. A human DENY must also be distinguishable from a
policy deny and from a TIMEOUT (TIMEOUT already exists — keep it). Update
posture.py to use the new origin on the approval path.

TASK 2 — Persist the governance log.
Decisions must survive a restart; the whole feature is graded on history a person
can inspect later.

Add a decisions table through StateManager using the additive
CREATE TABLE IF NOT EXISTS pattern already in that file. A database created before
this change must still open. Writes go through asyncio.to_thread — sqlite3 is
blocking and doing it on the event loop stalls the WebSocket pump; the reasoning is
already commented in runner.py, read it.

Keep the in-memory sink working. Compose, do not replace — a run should write to
both. Add indexes suited to the queries in TASK 3; a log that crawls after a few
hundred runs is a log nobody opens.

Do NOT implement retention or recording-level enforcement. That is a later phase.

TASK 3 — Query, filter and export API.
Extend the governance router with: list decisions filtered by run, node, domain,
outcome, origin and time range; pagination; a summary endpoint giving counts by
outcome and by domain (for one run and overall); and export of the filtered set as
JSON and as CSV.

Pagination must be keyset/cursor based, NOT OFFSET. This table only grows and
OFFSET degrades badly. Use the existing session-token auth dependency the way the
other routers do.

TASK 4 — Live decisions on the WebSocket.
The canvas streams WsEvents during a run. Decisions must arrive there too so the
user sees governance happening live, not only in history. Add a typed WsEvent
following the existing patterns in scheduler/events.py exactly. Check whether G2
already added an event for pending approvals — if so, match that shape rather than
inventing a second style.

Volume matters: a run can emit many decisions fast. Do not flood the queue. Look at
how useRunSocket.ts already buffers token events on an interval and apply the same
discipline on the backend side. Say in one line what you did about volume.

CONSTRAINTS:
- No new tests. Do not edit existing tests. Do not weaken the G1 served-mode check
  or the G2 fail-closed defaults.
- No UI. If you open a .tsx file you have gone off scope.

DEFINITION OF DONE:
  cd backend
  ./.venv/Scripts/python.exe -m ruff check komvos
  ./.venv/Scripts/python.exe -m mypy komvos
  ./.venv/Scripts/python.exe -m pytest -q
ruff and mypy clean. pytest must show NO new failures.

DELIVERABLES:
1. docs/p1a-report.md — SHORT, bullets only:
   - New origin values, and how an Ask-approved decision now reads
   - Decisions table schema + which indexes and why (2-3 lines)
   - Pagination approach, one line
   - What you did about decision volume, one line
   - Every new API route, as a list of method + path
   - Full DEFINITION OF DONE output
   - Anything incomplete or that you disagreed with
2. One commit, prefixed exactly: "p1a: "
```

---

## P1b — PROMPT (UI only — run after P1a is verified)

```
You are working in the Komvos repository (Electron + React + TypeScript desktop app
in apps/desktop, Python 3.11 FastAPI backend in backend/, package name `komvos`).

WORKING STYLE FOR THIS RUN — this overrides your defaults:
- DO NOT write any new tests. No new test files, no test fixtures, no mock
  scaffolding, no placeholder data inserted and later removed.
- Existing tests must keep passing. Read them if useful; do not edit them.
- Verification happens outside this run. Build the feature.
- Keep the report SHORT. Bullets.

ENTRY CHECK — only this may HALT you:
  cd apps/desktop && npm run typecheck
If it fails, STOP and write docs/p1b-report.md saying what is red.

HANDS OFF — do not touch:
  .github/workflows/   packaging/
  apps/desktop/src/main.ts
  apps/desktop/src/hooks/useBackend.ts
  apps/desktop/src/hooks/usePipelineActions.ts
  apps/desktop/index.html
  apps/desktop/src/components/SettingsModal.tsx   ← the profile picker does NOT go
                                                    here. Build your own panel.
  backend/   (ALL — P1b is frontend only)
  README.md
PARTITIONED:
  apps/desktop/src/App.tsx - MOUNT POINTS ONLY. Add imports and render your
                             components. Do NOT restructure existing layout, state
                             or handlers. Keep your diff here under ~20 lines.
                             Everything else goes in your own files.
No new frontend dependencies. If you think you need one, STOP and report it.

CONTEXT.
The governance backend is complete: profiles (EXPLORE/REVIEW/LOCKED, default
LOCKED), an active-profile setting, a persisted decision log with filtering and
export, mid-run Ask suspension with an approvals API, and live decision events on
the run WebSocket. Read docs/p1a-report.md for the exact route list and event shape.

There is currently NO user interface for any of it. A user cannot see the active
profile, change it, see a single decision, or answer an Ask prompt. That is this
run. This is the surface the challenge is graded on — treat it as product work, not
plumbing.

Read first: apps/desktop/src/App.tsx, apps/desktop/src/index.css,
apps/desktop/src/panels/MonitorPanel.tsx, apps/desktop/src/panels/TraceModal.tsx,
apps/desktop/src/contexts/ToastContext.tsx, apps/desktop/src/hooks/useRunSocket.ts,
docs/p1a-report.md.

Everything you build lives in new files under apps/desktop/src/governance/.

SURFACE 1 — Active profile indicator.
Always visible, never more than a glance away. Shows which profile is in force
right now. This is the "state" the challenge asks for, so it must remain visible
DURING a run, not hidden behind a menu.

SURFACE 2 — Profile picker. This is the dial.
Switching profile is the ONE BEHAVIOR the user adjusts, so this is the most
important control in the application. Show the three built-ins with what each one
actually does per domain — a person must understand the consequence BEFORE
choosing, not after. Support creating and editing a custom profile through the
existing API. Built-ins are not editable: make that visually obvious rather than
failing on submit.

SURFACE 3 — Decision history panel. This is the evidence.
Filterable by domain, outcome, origin and run. Each entry must answer, without the
user clicking into it: what was requested, what happened, why, which access node or
profile was responsible, and where relevant that a HUMAN approved or denied it.
Include the export action.

SURFACE 4 — Approval prompt.
When a run suspends under Ask posture, the user must be asked clearly and the run
must resume on their answer. Show what is being requested and what each answer will
do. Wire it to the approvals API. Handle the timeout case: if the window expired,
the prompt must show the run already failed closed rather than sitting there stale.

LIVE FEEDBACK.
Decisions arrive on the run WebSocket. Surface them as they happen — the user
should see governance working during a run, not only afterwards. useRunSocket.ts
already buffers high-frequency token events on an interval; match that discipline
so a burst of decisions cannot stutter the canvas.

DESIGN REQUIREMENTS — this is graded, treat it as product work:
- Match the existing visual language. Read index.css and reuse the existing class
  conventions and palette. Do not introduce a second design system.
- Outcome must be readable at a glance without reading text — encode allow, deny,
  timeout and awaiting-approval in FORM as well as colour, never colour alone.
- The history panel must stay usable at a few thousand rows.
- Empty states must be written, not blank. Someone who has never triggered a denial
  should see text explaining what the panel will show.
- Visible keyboard focus state on every interactive element.
- No third-party product names or logos anywhere in the interface.

CONSTRAINTS:
- No new tests. Do not edit existing tests.
- No backend changes. If the API is missing something you need, STOP and report it
  rather than reaching into backend/.

DEFINITION OF DONE:
  cd apps/desktop
  npm run typecheck && npm run lint && npm test
All three clean, with no new test failures.

DELIVERABLES:
1. docs/p1b-report.md — SHORT, bullets only:
   - The files you created, one line each on what it does
   - Where each of the four surfaces appears in the UI (which panel/position)
   - How you encoded outcome in form, not just colour
   - What you did about live decision volume
   - Full DEFINITION OF DONE output
   - Anything you could not build because the API did not support it
   - Anything incomplete or that you disagreed with
2. docs/p1-demo.md — the 60-second demo path: exact numbered click sequence that
   shows a judge the dial changing behaviour and the log proving it. Written so
   someone else can follow it without you present.
3. One commit, prefixed exactly: "p1b: "
```
