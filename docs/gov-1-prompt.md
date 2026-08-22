# G1 — PROMPT (paste into Antigravity as-is)

## Decisions locked

| Question | Answer |
|---|---|
| What `Ask` does | **True mid-run pause and resume.** The run suspends at the violating node, prompts, and resumes on approval. |
| Profile vs access node | **Profile is authoritative and may override in both directions.** |
| Profiles | **Three: Explore / Review / Locked.** |

Consequence of the first: the enforcement path must be **async-capable from G1**,
because G2 awaits a human at exactly the point where G1 decides.

Consequence of the second: every decision records **which source produced the
outcome**, so a profile grant the pipeline never asked for is visible in the log.

## Working independently

The other operator's phases land on their own schedule and may be mid-flight at any
moment. Our phases never gate on their territory. Entry checks halt only on
preconditions we own; anything in their files is a recorded observation, not a gate.
We do not fix their breakage.

---

```
You are working in the Komvos repository (Electron + React + TypeScript desktop app
in apps/desktop, Python 3.11 FastAPI backend in backend/, package name `komvos`).

A SECOND OPERATOR IS WORKING IN THIS REPOSITORY IN PARALLEL. Their work lands on
its own schedule and may be incomplete at any moment. You must not fix, clean up,
lint, reformat or comment on anything in their territory. If something of theirs is
broken, note it in one line in your report and move on. It is not your job and
touching it will cause a merge conflict.

ENTRY CHECK — these are the only conditions that may HALT you:
  cd backend
  ./.venv/Scripts/python.exe -c "import komvos.compiler.dag, komvos.endpoints.base"
  ./.venv/Scripts/python.exe -m pytest tests/test_compiler.py tests/test_access_policy.py tests/test_executors.py -q
If either fails, STOP, write docs/gov-1-report.md explaining what is red, and make
no further changes.

BASELINE — run these, record the output in your report, and CONTINUE regardless of
result. These cover the other operator's territory and are observations, not gates:
  ./.venv/Scripts/python.exe -m pytest -q          (record pass/skip/fail counts)
  ./.venv/Scripts/python.exe -m ruff check .       (record any errors)
  ./.venv/Scripts/python.exe -m mypy komvos        (record any errors)

HANDS OFF — do not create, edit, rename, move, reformat or delete any of these,
even if a linter or your own judgement suggests it:
  .github/workflows/                              (all)
  packaging/                                      (all)
  apps/desktop/                                   (ALL - this phase has no UI work)
  backend/komvos/executors/logic.py
  backend/pyproject.toml
  README.md
PARTITIONED FILES — you may edit these, but ONLY the regions named:
  backend/komvos/endpoints/cloud.py   - check_access only. Do NOT touch client
                                        construction, _get_api_key, generate, or
                                        estimate_cost.
  backend/komvos/endpoints/ollama.py  - check_access only. Same restriction.
  backend/komvos/api/main.py          - you may append include_router lines at the
                                        bottom. Do NOT edit the CORS block, the
                                        FastAPI title, or any existing route body.
  backend/komvos/api/registry.py      - governance service wiring only. Do NOT
                                        touch the run registry or get_state_manager.
If a task appears to require touching a HANDS OFF file, STOP and say so in the
report rather than proceeding. Do not add any entry to pyproject.toml - if you
believe you need a dependency, stop and report it.

CONTEXT — read this before starting.
Komvos governs what a pipeline may do through an "access node": a node placed on
the canvas carrying an AccessPolicy that applies to every node downstream of it.
The compiler intersects the policies of all access nodes upstream of a given node
to produce that node's effective policy, and endpoints check it before making a
call. That design is sound. The implementation is incomplete in four specific ways,
and this phase closes all four.

This phase has NO user-facing work. No UI, no settings, no profiles. Those are later
phases. If you find yourself building a toggle, you have gone off scope.

Before writing any code, read these files in full and confirm in your report that
you have: backend/komvos/compiler/models.py, backend/komvos/compiler/dag.py,
backend/komvos/compiler/validation.py, backend/komvos/compiler/README.md,
backend/komvos/endpoints/base.py, backend/komvos/executors/model.py,
backend/komvos/scheduler/runner.py.

TASK 1 — Create the governance package and the decision record.
Create backend/komvos/governance/ with a README.md in the same style as the other
package READMEs here - explain the why, not just the what. Match the tone of
backend/komvos/compiler/README.md.

Define a GovernanceDecision record. Every point in the system that decides whether
something is permitted must produce one. At minimum capture: when, which run, which
node, which domain, which capability was requested, the outcome, a human-readable
reason, which access node or policy source produced the constraint, and the
effective policy values that applied.

Three design requirements that are not negotiable:

  (a) Decisions are emitted on ALLOW as well as DENY. A log that only records
      denials looks empty during a successful demo, which is exactly when someone
      will be looking at it.

  (b) The four domains - providers, egress, spend, retention - are a closed
      enumeration, not strings.

  (c) THE DECISION PATH MUST BE ASYNC. A later phase will suspend a running
      pipeline at exactly this point to ask a human for approval, then resume it.
      Design the decision function and the sink as coroutines now, even though
      nothing awaits anything yet. A synchronous design here forces a rewrite of
      every call site later.

Also record, on every decision, WHICH SOURCE produced the outcome - the pipeline's
own access policy, or something else. A later phase introduces a user profile that
can override a pipeline's policy in either direction, and a grant the pipeline never
asked for must be visible in the log rather than silent. Leave the field present and
populated with the pipeline policy for now.

Define a sink interface that receives decisions, plus an in-memory implementation.
Do NOT persist to SQLite and do NOT add any database tables - storage is designed in
a later phase and a schema chosen now will be wrong. Wire the sink so the scheduler
can reach it for a given run without threading it manually through every call site;
look at how the existing event callback reaches executors and follow that pattern
rather than inventing a new one.

TASK 2 — Close the served-mode access-control bypass.
Deploying a pipeline as an HTTP API compiles it in "served" mode, which is meant to
make an access policy mandatory. It is bypassable.

FIRST, reproduce it. Build a pipeline of input -> model -> output where the model
uses a cloud provider endpoint, plus a separate access node whose policy grants no
providers, connected through its scope port to a transform node that nothing else
touches. Compile it in served mode. It currently succeeds, and the model node's
effective policy is fully permissive while only the dead-end branch is restricted.
Paste the reproduction and its output into your report BEFORE you change anything.
Do not skip this. Without it I cannot distinguish a real fix from a plausible one.

THEN fix it. In served mode, compilation must fail when any node capable of reaching
a model endpoint has no governing access node among its ancestors. The data you need
is already computed: compile() produces a per-node record of which access nodes
governed it, and nothing currently reads it for this purpose. Use it rather than
adding a second graph traversal. The error must name every offending node and say
what to do, matching the voice of the existing "[Access Required]" and
"[Access Denied]" messages.

Local/canvas mode must be COMPLETELY unaffected. Pipelines with no access node must
keep running on the canvas exactly as they do today - that is what keeps every
existing template working. Breaking it is a regression, not a tightening.

TASK 3 — Implement egress control. It is currently declared but dead.
AccessPolicy declares allow_network and allowed_domains. allow_network is read in
exactly one place, to build the text of an error message. allowed_domains is read by
nothing outside the model definition. Neither has ever prevented a single network
call. Verify both claims yourself before starting and record what you found.

Make them real. Every outbound call the engine makes must be checked against the
effective policy of the node making it, BEFORE the call leaves the machine, and must
emit a GovernanceDecision either way. Paths you must cover:
  - cloud provider calls, including the provider's default host and any custom
    base_url override
  - local model calls, including the case where a custom Ollama base URL points
    somewhere that is not localhost. Read resolve_ollama_base in
    backend/komvos/api/registry.py: a remote tunnel URL is a real egress path that is
    currently completely ungoverned.
Search the codebase for other outbound calls before deciding your list is complete.
State in the report what you searched for and what you found.

Semantics you must get right and must document in the package README: an empty
allowed_domains on a policy that allows network means "no domain restriction", not
"no domains" - the existing intersect logic already depends on this reading and
changing it would silently break policy composition. Host matching must not be a
substring check. Decide and document how subdomains are treated.

TASK 4 — Enforce the per-scope cost ceiling.
AccessPolicy declares max_cost_usd per scope, but it is only ever collapsed into a
single run-wide minimum by _tightest_budget in backend/komvos/scheduler/runner.py.
Two scopes with different ceilings both end up governed by the stricter one, so a
policy author cannot express "this branch may spend more than that branch." Enforce
it per scope: a node's spend is checked against the ceiling of its own effective
policy. Keep the run-wide budget as a separate outer limit - both apply, and the
tighter one wins for any given node.

The accuracy of the underlying cost numbers is a known problem being fixed in a later
phase. Do NOT attempt to fix cost accounting here. Build the enforcement so it will be
correct once the numbers are, and say plainly in the report that the ceiling currently
operates on estimates.

TASK 5 — Tests. Add at least these:
  - The decoy pipeline from TASK 2 is REJECTED in served mode.
  - A correctly-governed pipeline still compiles in served mode.
  - Local mode is unaffected: a pipeline with no access node still compiles.
  - Egress is denied when allow_network is false, and the call never leaves.
  - A host outside allowed_domains is denied; one inside is permitted.
  - A remote Ollama base URL is subject to egress policy.
  - Per-scope cost ceilings apply independently to different branches.
  - Decisions are emitted on allow, not only on deny.
Use the existing mock endpoint. Do not call a real provider.

CONSTRAINTS:
- No third-party dependencies.
- No SQLite persistence, no new tables.
- No UI.
- Do not weaken or delete any existing test to make a gate pass. If an existing test
  fails in a way suggesting you changed canvas-mode behaviour, that is a bug in your
  change, not a test to update.
- If an instruction looks wrong, implement it anyway and record the disagreement in
  the report. Do not silently substitute a different approach.

DEFINITION OF DONE — scoped to what you own. Paste real output into the report:
  cd backend
  ./.venv/Scripts/python.exe -m ruff check komvos/governance komvos/compiler komvos/scheduler komvos/endpoints komvos/executors tests
  ./.venv/Scripts/python.exe -m mypy komvos/governance komvos/compiler komvos/scheduler
  ./.venv/Scripts/python.exe -m pytest tests/ -q
The ruff and mypy commands above must be clean for the paths listed. The pytest run
must show no NEW failures compared to the baseline you recorded at the start, and at
least 8 more passing tests than that baseline.

DELIVERABLES:
1. docs/gov-1-report.md containing, in this order:
   - The BASELINE output recorded at the start
   - Confirmation of which files you read before starting
   - The TASK 2 reproduction and its output, from BEFORE your fix
   - Your verification of the TASK 3 claim that both fields were dead
   - Per task: what you changed, with file:line references
   - The full text of every new error message you added
   - Your subdomain-matching decision and its rationale
   - The complete list of outbound call paths you found, and how you searched
   - Full output of every command under DEFINITION OF DONE
   - One line on anything of the other operator's that looked broken (do not fix it)
   - Anything you could not complete, and anything you disagreed with
2. One commit, message prefixed exactly: "gov-1: "
```
