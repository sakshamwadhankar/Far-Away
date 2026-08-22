# P4 — MASTER PROMPT (final phase: make it real, make it provable)

## P3 review verdict — mostly passed, two defects

Verified directly:

| Check | Result |
|---|---|
| mypy | Clean, 54 files |
| pytest | 423 passed / 4 skipped — no new failures |
| Multilingual destructive | Real — `eliminar`, `borrar`, `löschen`, `desinstalar` and more present |
| `DELETE /runs/{id}` | Exists |
| Metadata scrubbing | Implemented in `save_node_execution` / `save_loop_iteration` |
| Hermes | Integrated as an endpoint kind with a health probe |
| Data loss on upgrade | **None.** Two independent safety nets stop the sweep deleting anything |

**On the test edit:** the agent edited `test_scheduler.py`, which the prompt
forbade. That edit was CORRECT and the fault was mine — the old assertion
(`node_id == "mock:expensive"`) was asserting the very bug TASK 2 existed to fix.
Changing it to `"model_2"` made the test stricter and more accurate. No issue.

### Defect 1 — ruff is not clean, and the report claimed it was

```
komvos\endpoints\mock.py:29:5  F401  `Message` imported but unused
```

The P3 summary stated "all test suites, type checkers, and linters are passing
100%." That was false. One-line fix, but the false claim is the part that matters.

### Defect 2 — the retention window is dead code

`lifespan` calls `sweep_retention(profile.retention)`, but `profile.retention` is a
`RetentionMode` — `"full"` or `"metadata"` — while `sweep_retention` expects a
duration like `"7d"`. Neither value ever parses, so the function always returns 0.
Proven by probe:

```
sweep_retention(RetentionMode.METADATA) -> 0
sweep_retention(RetentionMode.FULL)     -> 0
```

There is no retention-window field on the profile at all. The deletion machinery
works; nothing can ever feed it. TASK 1 fixes this.

---

```
You are working in the Komvos repository (Electron + React + TypeScript desktop app
in apps/desktop, Python 3.11 FastAPI backend in backend/, package name `komvos`).
This is the FINAL phase before submission.

═══ WORKING STYLE — THIS OVERRIDES YOUR DEFAULTS ═══
DO NOT WRITE TESTS. No test files, no test functions, no fixtures, no mock
scaffolding. Do not create any file whose name contains "test" or "spec".
You MAY edit an existing test ONLY if a task in this prompt makes its current
assertion factually wrong. If you do, say which test, which assertion, and why the
new one is more correct. Never edit a test to hide a failure.
DO NOT insert placeholder data intending to remove it later.
Keep the report SHORT — bullets.
═══ AND ONE MORE THING, SPECIFIC TO THIS PHASE ═══
This phase is about PROVING things work, not claiming they do. Where a task says
run it, actually run it and paste the real output. If you cannot run something, say
so plainly. A previous run reported "linters passing 100%" while ruff was failing.
Do not do that. An honest "I could not verify this" is worth more than a false
green.
═══════════════════════════════════════════════════

ENTRY CHECK — only these may HALT you:
  cd backend && ./.venv/Scripts/python.exe -m pytest -q
  cd ../apps/desktop && npm run typecheck
If either fails, STOP, write docs/p4-report.md saying what is red, change nothing.

HANDS OFF — a second operator owns these:
  .github/workflows/   packaging/
  apps/desktop/src/main.ts
  apps/desktop/src/hooks/useBackend.ts
  apps/desktop/src/hooks/usePipelineActions.ts
  apps/desktop/src/hooks/useRunSocket.ts
  apps/desktop/index.html
  apps/desktop/src/components/SettingsModal.tsx
  backend/komvos/executors/logic.py
  README.md
PARTITIONED:
  apps/desktop/src/App.tsx  - mount points only, diff under ~20 lines.
  backend/pyproject.toml    - no changes unless a task explicitly requires one.
  backend/komvos/endpoints/cloud.py, ollama.py
                            - ⚠ the second operator's phase-4 rewrites client
                              construction, timeouts and retries here. Keep any
                              edit additive and localised.

TASK 1 — Fix the two defects found in review.

  (a) `komvos/endpoints/mock.py` has an unused `Message` import. Remove it. Then
      run ruff and paste the output.

  (b) The retention window can never fire. `lifespan` passes `profile.retention` —
      a RetentionMode of "full" or "metadata" — into `sweep_retention`, which
      expects a duration string. The recording LEVEL and the retention WINDOW are
      two different settings and they have been conflated into one field.

      Separate them. A profile needs both: how much of each run is recorded, and
      how long runs are kept. Add the missing window as its own field, give each
      built-in profile a sensible value, and feed the sweep the right one.

      The existing safety behaviour must be preserved exactly: a value meaning
      "keep forever" deletes nothing, an unparseable value deletes nothing, and a
      non-positive duration deletes nothing. An existing installation must not lose
      history on first launch — state in the report which window each built-in
      profile gets and what an upgrading user experiences.

      Surface the window in the profile picker alongside the recording level, so a
      user can see and change it.

TASK 2 — Actually exercise the desktop path. It has never run.
`cua-computer-server==0.1.25` is declared in pyproject.toml but is NOT installed in
the virtual environment, so every line of the desktop feature is unexercised code.

Install it. Start it on the configured port. Then run a real Computer node end to
end against a real screen and confirm, with pasted evidence:
  - the health probe reports it available
  - a screenshot is captured
  - element detection returns marks, and grounding resolves a chosen mark to a real
    target
  - the governance gate produces a decision BEFORE the action executes
  - the action executes
  - the verifier runs and returns a result

Fix whatever breaks. This is the most likely place for the implementation to
diverge from the library's actual interface, because it was written against
documentation rather than against a running server.

If you genuinely cannot install or run it in this environment, say so explicitly,
list precisely what remains unverified, and do not describe untested code as
working.

TASK 3 — Desktop safety hardening.
  - The kill switch must stop a desktop run immediately, including mid-action and
    while an approval is pending. Verify it and say how.
  - Bound the loop visibly: when the step limit or wall-clock limit is hit, the run
    must stop with a clear reason that reaches the UI, not fail silently.
  - A denied action must leave the machine untouched. Confirm there is no partial
    execution — no key pressed, no click landed — before a denial.
  - Where the classifier is uncertain it must fail safe. Confirm the current
    behaviour matches what P3's report claimed.

TASK 4 — Seed data and demo paths that actually work.
There are two demo documents already: docs/p1-demo.md and docs/p2-demo.md. Walk
through both against the running app, step by step, and correct anything that does
not match reality. A demo path that has never been walked is a liability, not an
asset.

Then add a small set of seed pipelines that make the demos possible from a clean
install — a governance demo that triggers an approval, and a desktop demo. Put them
where the existing templates live and follow that format exactly.

Write docs/demo-script.md: the single path to walk a judge through, drawing from
the working parts of the other two. It must show one pipeline behaving differently
under Explore, Review and Locked, with the decision log proving it each time. Mark
clearly which steps need a real screen and which do not.

TASK 5 — The submission write-up.
Write docs/submission.md covering: what the feature is, which one behaviour the
user adjusts, how state / feedback / history are each satisfied, what a judge should
click to confirm it, and an honest limitations section.

The limitations section is not optional and must be genuinely honest. Include at
minimum: this is single-user with no team or org-wide policy, nothing is
compliance-certified, desktop control quality depends on the vision model, and
anything you personally could not verify in TASK 2. A judge who finds an
overstatement will discount everything else in the document.

TASK 6 — Final verification.
Run every gate and paste real output:
  cd backend
  ./.venv/Scripts/python.exe -m ruff check komvos
  ./.venv/Scripts/python.exe -m mypy komvos
  ./.venv/Scripts/python.exe -m pytest -q
  cd ../apps/desktop && npm run typecheck && npm run lint && npm test
Then start the app, load a seed pipeline, run it under each of the three profiles,
and confirm the decision log fills correctly each time. Paste what you observed.

CONSTRAINTS:
- Do not weaken the served-mode access check, the fail-closed defaults, the LOCKED
  default profile, or the desktop action gate.
- Retention changes must not delete anything on upgrade.
- No new dependencies beyond installing the one already declared.
- If an instruction looks wrong, implement it anyway and record the disagreement.

DELIVERABLES:
1. docs/p4-report.md — SHORT, bullets:
   - ruff output after the fix
   - The retention window field, each built-in's value, and the upgrade experience
   - TASK 2: exactly what you ran, what worked, what broke, what you fixed, and
     what remains unverified. Be specific and honest.
   - Kill-switch verification, and how you tested it
   - What you corrected in the two existing demo documents
   - Full TASK 6 output plus what you observed running the app
   - Any test you edited, and why the new assertion is more correct
   - Anything incomplete or that you disagreed with
2. docs/demo-script.md and docs/submission.md as described.
3. One commit, prefixed exactly: "p4: "
```
