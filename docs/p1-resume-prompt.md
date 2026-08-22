# P1b RESUME — PROMPT for a fresh chat

**Before pasting this, commit the existing work:**

```bash
git add -A && git commit -m "p1a: governance log persistence, query/export API, human-approval origin, live decision events"
```

## State when the previous run was stopped

Verified by running the gates directly, not from a report:

- Backend (P1a) **complete and green** — `ruff` clean, `mypy` clean (45 files),
  **423 passed / 4 skipped**. Was uncommitted; the command above fixes that.
- Frontend `typecheck` clean.
- `apps/desktop/src/governance/` has 5 files. **Surface 1 is done.**
- Surfaces 2, 3, 4 and the App.tsx mounting are not started.

Note: the previous run wrote `backend/tests/test_governance_p1.py` despite being
told not to write tests. Those 14 tests pass, so they stay — deleting working code
is worse than the instruction being ignored. The prompt below is harder on this.

---

```
You are working in the Komvos repository (Electron + React + TypeScript desktop app
in apps/desktop, Python 3.11 FastAPI backend in backend/, package name `komvos`).
This is a RESUME of partially-completed work. Read the state section carefully
before writing anything — most of the foundation already exists.

═══ WORKING STYLE — THIS OVERRIDES YOUR DEFAULTS ═══
DO NOT WRITE TESTS. Not one. No test files, no test functions, no fixtures, no mock
scaffolding, no sample-data harnesses. Do not create any file whose name contains
"test" or "spec".
DO NOT insert placeholder or dummy data into a source file intending to remove it
later. Write the real implementation once, directly.
DO NOT edit any existing test.
A previous run ignored this instruction and it cost hours. Verification is being
done by someone else, outside this run. Your only job is working code.
Keep the report SHORT — bullets, not prose.
═══════════════════════════════════════════════════

ENTRY CHECK — only this may HALT you:
  cd apps/desktop && npm run typecheck
If it fails, STOP and write docs/p1b-report.md saying what is red.

HANDS OFF — do not create, edit, rename, move, reformat or delete:
  backend/                                        (ALL — backend is finished)
  .github/workflows/   packaging/
  apps/desktop/src/main.ts
  apps/desktop/src/hooks/useBackend.ts
  apps/desktop/src/hooks/usePipelineActions.ts
  apps/desktop/src/hooks/useRunSocket.ts
  apps/desktop/index.html
  apps/desktop/src/components/SettingsModal.tsx   ← the profile picker does NOT go
                                                    here. Build your own panel.
  README.md
PARTITIONED:
  apps/desktop/src/App.tsx — MOUNT POINTS ONLY. Add imports and render your
    components. Do NOT restructure existing layout, state or handlers. Keep your
    diff in this file under ~20 lines.
No new dependencies. If you think you need one, STOP and report it.

═══ WHAT ALREADY EXISTS — REUSE, DO NOT REWRITE ═══
All under apps/desktop/src/governance/. Read all five files before starting.

types.ts — DomainKey, PostureValue, OutcomeValue, ProfileSpec, ProfileEntry,
  ProfilesResponse, ActiveProfileResponse, DecisionRecord, DecisionsPage,
  DecisionsSummary, ApprovalPendingFrame, DecisionFrame, AnswerValue,
  DOMAIN_LABELS

api.ts — the complete API client. Already implemented:
  fetchProfiles, fetchActiveProfile, setActiveProfile, createProfile,
  updateProfile, deleteProfile, fetchDecisions, fetchDecisionsSummary,
  exportDecisions, answerApproval, buildDecisionQuery, DecisionFilters,
  ProfileBody, OriginFilter

useGovernance.ts — the central hook. Taps the run WebSocket via addEventListener
  (existing handlers untouched), buffers live decisions, tracks pending approvals.
  Exports useGovernance({ apiBase, token, connected, wsRef }) and GovernancePrompt.

display.ts — outcomeStyle(), originLabel(), HUMAN_ORIGINS, timeShort()

ActiveProfileIndicator.tsx — SURFACE 1, COMPLETE. Do not rebuild it.

If something you need is missing from api.ts or useGovernance.ts, EXTEND those
files. Do not create a parallel second client or a second hook.
═══════════════════════════════════════════════════

YOUR JOB — three UI surfaces, the mounting, and one document.

SURFACE 2 — Profile picker. This is the dial, and it is the single most important
control in the application. Switching profile is the one behaviour the user adjusts.
  - Show the three built-ins (EXPLORE / REVIEW / LOCKED) with what each one
    actually does PER DOMAIN. A person must understand the consequence BEFORE
    choosing, not discover it after. Use DOMAIN_LABELS.
  - Support creating and editing a custom profile through the existing API.
  - Built-ins are not editable. Make that visually obvious rather than letting
    someone fill a form and fail on submit.
  - Switching must reflect immediately in the ActiveProfileIndicator.

SURFACE 3 — Decision history panel. This is the evidence a judge inspects.
  - Filterable by domain, outcome, origin and run.
  - Each row must answer, WITHOUT the user clicking into it: what was requested,
    what happened, why, which access node or profile was responsible, and — where
    relevant — that a HUMAN approved or denied it. display.ts already has
    HUMAN_ORIGINS and originLabel() for exactly this; a human decision must read
    visibly differently from an automatic one.
  - Include the export action (exportDecisions supports JSON and CSV).
  - Pagination is keyset/cursor based — fetchDecisions and buildDecisionQuery
    already handle the cursor. Wire "load more" to it; do not re-fetch from zero.

SURFACE 4 — Approval prompt. This is the moment the feature becomes real.
  - When a run suspends under Ask posture, useGovernance surfaces a pending
    approval. Show it clearly: what is being requested, and what each of the three
    answers will do (allow once / allow for this run / deny).
  - Answering must resume the run.
  - Handle the timeout case: if the approval window expired, the prompt must show
    that the run already failed closed, not sit there looking answerable.

MOUNTING — in App.tsx, within the ~20 line budget:
  - ActiveProfileIndicator must be visible AT ALL TIMES, including during a run.
    This is the "state" the challenge is graded on. Not behind a menu.
  - The profile picker and history panel need a reachable entry point.
  - The approval prompt must appear over whatever the user is looking at — a run
    is blocked waiting for it.

DESIGN REQUIREMENTS — this surface is graded. Treat it as product work.
  - Match the existing visual language. Read apps/desktop/src/index.css and reuse
    its class conventions and palette. Do not introduce a second design system.
  - Encode outcome in FORM as well as colour — allow, deny, timeout and
    awaiting-approval must be distinguishable without reading text and without
    relying on colour alone.
  - The history panel must stay usable at a few thousand rows.
  - Write real empty states. Someone who has never triggered a denial should see
    text explaining what the panel will show, not a blank box.
  - Visible keyboard focus state on every interactive element.
  - No third-party product names or logos anywhere in the interface.

DEFINITION OF DONE:
  cd apps/desktop
  npm run typecheck && npm run lint && npm test
All three clean, with no new test failures. (Existing tests only — you are not
writing any.)

DELIVERABLES:
1. docs/p1b-report.md — SHORT, bullets only:
   - Files created, one line each
   - Where each surface appears in the UI
   - How you encoded outcome in form, not just colour
   - How a human decision reads differently from an automatic one
   - Full DEFINITION OF DONE output
   - Anything the API did not support that you needed
   - Anything incomplete or that you disagreed with
2. docs/p1-demo.md — the 60-second demo path. Exact numbered click sequence showing
   a judge the dial changing behaviour and the log proving it. Written so someone
   else can follow it without you present. Include what they should SEE at each
   step, not just what to click.
3. One commit, prefixed exactly: "p1b: "
```
