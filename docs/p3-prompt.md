# P3 — MASTER PROMPT (make spend and retention honest; connect Hermes)

## P2 review verdict — passed, with one real gap

Verified directly, not from the report:

| Check | Result |
|---|---|
| AGPL risk | **Clear.** `cua-computer-server==0.1.25` resolves to PyAutoGUI / pynput / pillow only. No `ultralytics`, `torch`, `opencv`, or OmniParser anywhere in the tree. Choosing an older lean version was a good call. |
| Port collision | Avoided — 8100, loopback-only validated in the client |
| Diff discipline | `App.tsx` +4 lines, `pyproject.toml` +1 line. Exactly as scoped. |
| Gates | ruff clean, mypy clean (53 files), 423 passed / 4 skipped |
| Gate bypass | **None.** `execute_action` has exactly one call site, and `_gate_action` runs before it and raises on denial. |
| Verifier | **Real.** Five distinct `passed=False` paths. Not a rubber stamp. |
| Backward compatibility | **Correct.** A profile saved before P2 defaults its desktop posture to `ENFORCE` — the strictest, so an old profile can never accidentally grant desktop access. |

**The gap:** the destructive-action classifier is English-keyword-only.

```
Delete    -> destructive  ✓
Eliminar  -> SAFE         ✗   (Spanish for "Delete")
```

On any non-English desktop, deletions, formats and uninstalls classify as safe, so
under REVIEW the user is never asked. That is a hole in a safety control. TASK 5
below fixes it.

Also note: `cua-computer-server` is declared in `pyproject.toml` but **not installed
in the venv**, so the desktop path has never been exercised live. Install it before
demoing P2.

---

```
You are working in the Komvos repository (Electron + React + TypeScript desktop app
in apps/desktop, Python 3.11 FastAPI backend in backend/, package name `komvos`).

═══ WORKING STYLE — THIS OVERRIDES YOUR DEFAULTS ═══
DO NOT WRITE TESTS. Not one. No test files, no test functions, no fixtures, no mock
scaffolding, no sample-data harnesses. Do not create any file whose name contains
"test" or "spec". Do not edit any existing test.
DO NOT insert placeholder or dummy data into a source file intending to remove it
later. Write the real implementation once, directly.
Verification is performed by someone else outside this run.
Keep the report SHORT — bullets. Report what you DID, not what the spec asked for.
═══════════════════════════════════════════════════

ENTRY CHECK — only these may HALT you:
  cd backend && ./.venv/Scripts/python.exe -m pytest -q
  cd ../apps/desktop && npm run typecheck
If either fails, STOP, write docs/p3-report.md saying what is red, change nothing.

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
PARTITIONED — edit only as described:
  apps/desktop/src/App.tsx  - mount points only, diff under ~20 lines.
  backend/pyproject.toml    - you may add ONE dependency if TASK 6 needs it, and
                              nothing else. No version bumps, no reordering.
  backend/komvos/endpoints/cloud.py and ollama.py
                            - ⚠ HIGH MERGE RISK. The second operator's phase-4
                              rewrites client construction, timeouts and retries in
                              these files. You may add USAGE EXTRACTION only —
                              reading what the provider reports back. Do NOT
                              restructure client creation, do NOT add timeouts or
                              retries, do NOT touch _get_api_key. Keep your edits
                              additive and localised so the merge stays cheap.
  backend/komvos/api/registry.py
                            - endpoint resolution and detection only. Do NOT touch
                              the run registry or get_state_manager.

═══ CONTEXT ═══
Governance is working across five domains — providers, egress, spend, retention,
desktop — with three profiles, real mid-run approval, a persisted decision log, and
a full UI. Two of those five domains are currently DISHONEST, and this phase fixes
them. Nothing about the dial changes; what changes is that the numbers behind it
become real.

Read before writing code and confirm in the report:
backend/komvos/endpoints/base.py, backend/komvos/endpoints/cloud.py,
backend/komvos/endpoints/ollama.py, backend/komvos/executors/model.py,
backend/komvos/scheduler/runner.py, backend/komvos/state/sqlite.py,
backend/komvos/serve/routes.py, backend/komvos/governance/profiles.py,
backend/komvos/governance/posture.py, backend/komvos/desktop/destructive.py,
backend/komvos/api/registry.py.

TASK 1 — Cost is currently a guess presented as a measurement. Fix it.
Three compounding errors, all in the same path:
  a) estimate_cost derives input tokens from character count divided by four.
  b) It reports output tokens as the configured max_tokens — the CEILING, not the
     actual usage. A node capped at 2048 that returns 40 tokens is billed at 2048,
     including inside the budget enforcer, so a run can be halted for exceeding a
     budget it never approached.
  c) The runner increments the output-token total once per streaming chunk, which
     is a chunk count, not a token count.
Nothing anywhere reads the usage figures providers actually return. Note that
ollama.py already asks its provider to include usage in the stream and then throws
the result away.

Extend the endpoint contract in endpoints/base.py so an endpoint can report ACTUAL
usage at the end of a generation, and implement it for the cloud and Ollama
endpoints. Keep estimate_cost for the PRE-FLIGHT budget gate — an estimate is the
right tool for a before-the-call decision — but reconcile against real usage for
every number that gets reported, persisted, or logged as a governance decision.

Where a provider returns no usage, fall back to the estimate and make that FALLBACK
VISIBLE in the data, not silent. A user must be able to tell a measured number from
a guessed one.

TASK 2 — The budget-exceeded event names the wrong thing.
In scheduler/runner.py the budget-enforcing wrapper records the node at which the
budget was exceeded, but assigns it the wrapped ENDPOINT's identifier — a value
like "openai:gpt-4o", not a node id. That value is sent to the UI as a node id, so
the renderer looks up a node that does not exist and highlights nothing. Fix it so
the event carries the real node id.

TASK 3 — Deployed pipelines still have no spend ceiling.
A pipeline deployed as an HTTP API is constructed with a wall-clock budget only; no
USD budget is ever passed. Combined with a default rate limit of 60 requests per
minute and no bound on concurrent runs, a leaked deployment key is unbounded spend.

Add a per-deployment USD cap per request, persisted with the deployment using the
additive column-migration pattern already used in that table — existing deployment
rows must still load, and you must choose and document a sensible value for rows
that predate the column. Surface the setting in DeployModal.tsx next to the existing
rate limit. Also add a process-wide bound on concurrent served runs, rejecting
clearly rather than queueing forever. Put the bound next to the existing
SERVED_WALL_CLOCK_BUDGET_SECONDS constant so it is discoverable.

TASK 4 — Retention is declared but does nothing.
The profile model carries a retention setting and the governance domain exists, but
nothing enforces it. Meanwhile node_executions stores the full prompt and full
completion of every node of every run, forever, with no way to delete any of it.
This is both the largest and the most sensitive thing the application writes.

Implement it:
  - An endpoint to delete a single run and every row associated with it.
  - A retention window applied by a sweep at startup.
  - Recording levels honoured per the active profile: full node input/output, or
    metadata only. LOCKED already declares metadata-only — make that real.
  - Every retention action is itself a governance decision in the log. Deleting
    history must leave a trace that it happened.

Defaults must PRESERVE today's behaviour. A user upgrading must not silently lose
existing traces. State plainly in the report what an existing installation
experiences on first launch after this change.

TASK 5 — The destructive-action classifier only understands English.
Verified: an element named "Delete" classifies as destructive; "Eliminar" — the
Spanish word for exactly the same button — classifies as SAFE. The same holds for
German, Chinese and every other language. On a non-English desktop, deletions,
formats and uninstalls sail through as safe, so under REVIEW posture the user is
never asked. That is a hole in a safety control, not a cosmetic issue.

Fix it so classification does not depend on the language of the label. Prefer
signals that are language-independent — the accessibility role and control type,
the invoked command or automation identifier, the application in context — over
matching English words. Keep a keyword layer if it adds value, but it must not be
the only thing standing between a user and an unannounced deletion.

Where the classifier genuinely cannot tell, it must fail SAFE — treat the action as
destructive. Today an unrecognised element name is treated as safe; only a
completely missing target fails safe. State in the report exactly what your new
uncertain-case behaviour is and why you chose it.

TASK 6 — Connect Hermes Agent.
Hermes Agent (github.com/NousResearch/hermes-agent, MIT) exposes an
OpenAI-compatible /v1/chat/completions server on port 8642, enabled by the user via
API_SERVER_ENABLED=true in ~/.hermes/.env.

Because it is OpenAI-compatible, this needs almost no new machinery — the codebase
already supports an openai-compatible endpoint kind. Add detection following the
EXISTING pattern this codebase uses to detect a local Ollama and the desktop
server: probe it, report availability, let the UI say the feature is unavailable
rather than failing mid-run. Make its base URL configurable and default it to the
documented port.

Traffic to Hermes is EGRESS and must be governed exactly like any other endpoint —
it does not get a bypass for being local. Confirm in the report that a Hermes call
produces a governance decision.

CONSTRAINTS:
- No tests. No edits to existing tests.
- Do not change the shape of any WebSocket event the frontend already consumes
  without updating the frontend in the same commit.
- Do not weaken the served-mode access check, the fail-closed defaults, the LOCKED
  default profile, or the desktop action gate.
- Retention defaults must not destroy anything on upgrade.
- If an instruction looks wrong, implement it anyway and record the disagreement.

DEFINITION OF DONE:
  cd backend
  ./.venv/Scripts/python.exe -m ruff check komvos
  ./.venv/Scripts/python.exe -m mypy komvos
  ./.venv/Scripts/python.exe -m pytest -q
  cd ../apps/desktop && npm run typecheck && npm run lint && npm test
ruff and mypy clean. No NEW failures in either suite.

DELIVERABLES:
1. docs/p3-report.md — SHORT, bullets:
   - Which providers now report REAL usage, and which still fall back to an
     estimate — name them individually
   - How a fallback is made visible in the data
   - The deployment spend-cap migration, and what pre-existing rows get
   - The concurrency bound you chose
   - What an existing installation experiences on first launch after retention
     lands — be specific about whether anything is deleted
   - Your new destructive-classification signals, and the uncertain-case behaviour
   - Confirmation that a Hermes call produces a governance decision
   - Full DEFINITION OF DONE output
   - Anything incomplete or that you disagreed with
2. One commit, prefixed exactly: "p3: "
```
