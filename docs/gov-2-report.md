# Gov-2 Report — posture, profiles, Ask suspension

One commit, prefixed `gov-2:`. HANDS OFF files untouched; the only edit to a
partitioned file (`api/main.py`) is an appended `include_router` block at the
bottom (verified by diff).

---

## 1. ENTRY CHECK result

Both entry-check commands passed:

```
IMPORTS OK
69 passed in 0.89s   (test_governance.py test_compiler.py test_access_policy.py)
```

## 2. BASELINE (recorded before any change)

```
$ ./.venv/Scripts/python.exe -m pytest -q
379 passed, 4 skipped, 851 warnings in 10.11s

$ ./.venv/Scripts/python.exe -m ruff check .
All checks passed!

$ ./.venv/Scripts/python.exe -m mypy komvos
Success: no issues found in 40 source files
```

## 3. Files read in full before writing code

Confirmed read end-to-end:

- `backend/komvos/governance/` — every file including `README.md`
  (`decisions.py`, `sinks.py`, `context.py`, `egress.py`, `__init__.py`)
- `backend/komvos/compiler/dag.py`
- `backend/komvos/compiler/models.py`
- `backend/komvos/executors/model.py`
- `backend/komvos/scheduler/runner.py`
- `backend/komvos/scheduler/engine.py`
- `backend/komvos/serve/routes.py`
- `backend/komvos/serve/models.py`
- `backend/komvos/state/sqlite.py`

Plus, for wiring/context: `scheduler/events.py`, `serve/store.py`,
`api/main.py` (mounting region + route survey), `api/auth.py`,
`tests/conftest.py`, `tests/test_api.py`, `tests/test_serve.py`,
`endpoints/cloud.py`, `endpoints/mock.py`, `endpoints/ollama.py`.

## 4. Built-in profile matrix as implemented, and the default

| Profile | providers | egress | spend | retention posture | retention mode | limits |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **EXPLORE** | Audit | Audit | Audit (record, no cap) | Audit | full | — |
| **REVIEW** | Ask | Ask | Ask above threshold | Ask | full | `spend_ask_threshold_usd=1.0` |
| **LOCKED** | Enforce | Enforce | Enforce (pipeline ceilings stand) | Enforce | metadata | pipeline ceilings only |

(`governance/profiles.py:56-170`. Retention is modelled so the shape is
right — posture + mode — but NOT enforced this phase; nothing produces
retention decisions yet. Later phase.)

**Default profile: LOCKED**, for pre-existing databases, deployment rows,
and any missing/corrupt active-profile setting
(`DEFAULT_PROFILE_NAME`, profiles.py:170). Why: LOCKED reproduces pre-profile
behaviour exactly — the pipeline's own access policy decides, nothing
loosens — so a silent fallback can never permit more than the user
explicitly had. EXPLORE as default would silently grant what pipelines
withheld; REVIEW would suspend runs waiting for answers no UI ever gave.
LOCKED is both the strictest sensible fallback and the only behaviourally
invisible one.

## 5. How resolution records origin (with a worked LOOSENING example)

`resolve.resolve_policy(pipeline_policy, profile)` returns
`ResolvedPolicy(policy, origins)` where `origins` maps capability keys
(`"provider:<kind>"`, `"allow_local_models"`, `"allow_network"`,
`"max_cost_usd"`) to `DecisionOrigin`: `pipeline_policy` (decided alone),
`profile` (granted/constrained only by the profile), or
`pipeline_and_profile` (both agreeing). Decisions carry the origin of the
capability they rule on.

Worked example — profile LOOSENS a provider (REVIEW active):

- Pipeline: gate-a grants only `providers=["openai"]`; endpoint kind `mock`.
- Without a profile this fails compilation ("[Access Denied] … requires
  provider 'mock'"). With REVIEW, resolution adds `mock` to the resolved
  policy and records `origins["provider:mock"] = PROFILE`, so compile-time
  agrees with run-time.
- At run time the executor checks BOTH views (`executors/model.py:129`):
  first the PIPELINE-only policy — which denies — then the posture layer
  (Ask) suspends. The operator answers allow-once, and the decision record
  shows exactly this:

```
domain=providers  capability="provider:mock"  outcome=allow  origin=profile
governed_by=("gate-a",)
reason="Allowed once by operator. The pipeline itself had withheld this:
Node 'model_a' (model:mock) requires provider 'mock', which its access
policy does not grant. Granted providers: [openai]."
```

Asserted by `test_ask_suspends_and_sibling_in_same_tier_completes` (origin +
reason) and `test_audit_allows_and_attributes_the_profile` (Audit variant).
A grant the pipeline never asked for is therefore visibly attributed to the
profile — G1's empty origin field now carries real provenance.

Compile interaction: `compile(raw_json, mode=..., profile=None)`
(`compiler/dag.py:355`). No profile → byte-identical to before (every
existing test passes untouched). With a profile, resolution runs BEFORE the
capability check (`dag.py:434`). `CompiledDAG` carries both views
(`effective_policies` resolved / `pipeline_policies` pipeline-only). The
G1 served-mode structural rule still fires under EVERY profile
(`test_served_structural_rule_holds_under_every_profile`).

Run-time agreement: under Enforce, resolved == pipeline, so compile and
runtime cannot disagree; under Ask/Audit the runtime denial that matters is
the pipeline-only one, which the posture layer owns.

## 6. How suspension is implemented, and evidence the loop is not blocked

- `ApprovalRegistry.request()` (`approvals.py:101`) registers a pending
  question and awaits an `asyncio.Future` via `asyncio.wait(...,
  FIRST_COMPLETED)` racing THREE wake-ups: the answer future, an async
  cancellation waiter, and the timeout. Pure event-driven waits — no sleep
  loops, no blocking calls.
- The executor passes a `notify` callback; it fires at the exact suspension
  moment, emitting a typed `SchedulerEvent(APPROVAL_PENDING)` which the
  runner translates into `WsApprovalPendingEvent`
  (`scheduler/events.py`) carrying run, node, approval id, domain,
  capability, reason, each answer's effect, and the timeout.
- Answers arrive over `POST /governance/approvals/{id}/answer`
  (`governance/api.py`): `allow_once`, `allow_for_run` (exact
  `(domain, capability)` grant for the remainder of THIS run only — never
  widened), or `deny`.

**Evidence the event loop is not blocked:** 
`test_ask_suspends_and_sibling_in_same_tier_completes` builds two model
nodes in the SAME parallel tier, one suspended awaiting approval. While it
waits, the test observes the sibling's `NODE_DONE` already recorded, plus
the typed `approval_pending` event on the wire; only then does the test
answer, and the run completes.

## 7. Approval timeout value, and why

`APPROVAL_TIMEOUT_SECONDS = 300.0` (`approvals.py:46`). Chosen to match the
existing `SERVED_WALL_CLOCK_BUDGET_SECONDS`: long enough for a human to
notice a desktop prompt, short enough that an unanswered question cannot
park a run indefinitely. As instructed, the constant is discoverable next
to the served budget (`serve/routes.py:102` binds the same value rather than
restating it, so the two cannot drift). Timeout is its own outcome —
`DecisionOutcome.TIMEOUT` — distinguishable from a human denial
(`test_timeout_fails_closed_and_is_not_a_human_denial` asserts outcome and
the "failed closed" reason vs "Denied by operator.").

## 8. Cancellation while suspended

`CancelToken.wait_until_cancelled()` was added (`engine.py:126`): an
`asyncio.Event` created lazily and set by `cancel()`, giving the token an
async face without changing its sync contract. The approval wait races it,
so kill switch or wall-clock expiry aborts a waiting node immediately with
`PipelineCancelled` instead of leaving it parked until the timeout. Pending
entries are removed in `finally`; the per-run registry is removed from the
global lookup table when the runner's governance binding is released — on
success, error, and cancellation alike
(`runner.run` finally-block). Tests:
`test_cancelled_while_suspended_aborts_with_no_leak` (executor level),
`test_runner_cleans_up_registry_when_run_ends` (kill-switch mid-suspension;
asserts the registry table no longer holds the run), and
`test_runner_registry_cleaned_up_after_success_too`. Pending approvals are
process-memory-only and do not survive a restart — stated in
`approvals.py`'s docstring and the package README.

## 9. Migration approach for both new columns

- `StateManager._init_db`: two brand-new tables via additive
  `CREATE TABLE IF NOT EXISTS` — `governance_profiles(name PK, spec_json,
  created_at)` and `app_settings(key PK, value)` (`state/sqlite.py:127,136`).
  Old databases simply gain them; nothing ALTERed. Built-ins are never
  stored (they live in code, so a stored copy can't drift); only custom
  profiles persist, plus the active selection as one app_settings row.
- `DeploymentStore._migrate_deployments_profile_name`
  (`serve/store.py:70`): same pattern as `runs.deployment_id` — PRAGMA
  table_info guard, then `ALTER TABLE deployments ADD COLUMN profile_name
  TEXT NOT NULL DEFAULT 'locked'`, idempotent on every startup.
- Pre-existing rows get **LOCKED**: the only choice that reproduces exactly
  what those deployments did before profiles existed (pipeline policy
  decides, nothing loosens). Covered by
  `test_preexisting_database_and_deployment_row_load` (raw old-schema table
  migrated in place) and `get_active_profile_name` falling back to LOCKED on
  missing/corrupt settings.

## 10. TASK 7 — drift guard

`test_provider_default_hosts_match_cloud_endpoint_defaults` regex-extracts
the `base_url = "…"` literals from cloud.py's generate() source (per
provider branch) and compares each host against
`egress.PROVIDER_DEFAULT_HOSTS` — deriving cloud.py's values from its
source rather than restating them a third time. Editing either side alone
fails the test.

## 11. DEFINITION OF DONE (real output)

```
$ ./.venv/Scripts/python.exe -m ruff check komvos/governance komvos/compiler komvos/scheduler komvos/endpoints komvos/executors komvos/serve komvos/state tests
All checks passed!
=== ruff exit: 0 ===

$ ./.venv/Scripts/python.exe -m mypy komvos/governance komvos/compiler komvos/scheduler komvos/serve
Success: no issues found in 25 source files

$ ./.venv/Scripts/python.exe -m pytest tests/ -q
409 passed, 4 skipped, 1075 warnings in 15.93s
```

Baseline 379 passed / 4 skipped → final 409 passed / 4 skipped:
**no new failures, +30 passing** (requirement: ≥15).

New tests live in `tests/test_governance_g2.py` (30 tests): the built-in
matrix, resolution tighten/loosen with origins, compile() identity and
loosening acceptance, served structural rule under every profile, sibling-
tier suspension proof, allow-once/for-run/deny semantics, for-run grants
not widening, timeout-vs-denial distinction, cancellation-while-suspended
at both executor and runner levels, registry cleanup on success too, served
degrade promptness with visible degrade reason, fail-closed with no profile
bound, snapshot survival across active-profile changes, pre-existing DB/row
migration, the full governance CRUD/active/approval HTTP surface, real-app
router mounting, and the drift guard.

## 12. Other operator's territory — observations (not touched)

Nothing of the second operator's looked broken this session: their tree is
unchanged since gov-1 (same four untracked docs/*.md brief files, left
untouched).

## 13. Incomplete items, disagreements, notes

- **Retention is modelled, not enforced** — as instructed. Postures bind the
  domain and profiles carry a `RetentionMode`; no code path emits retention
  decisions yet.
- **Canvas runs do not bind the active profile yet.** Wiring it into
  `/pipelines/run` would require editing that route body in `api/main.py`,
  which is append-only for me this phase. Profiles ARE fully wired through
  served runs (deployment snapshots — TASK 5), the compiler
  (`compile(profile=...)`), the scheduler/executor posture layer, and the
  HTTP API. Binding the canvas dial lands naturally with the UI phase that
  owns those routes. Recorded here deliberately, not silently skipped.
- Disagreement/notes, implemented-as-instructed anyway:
  - The brief asked for the timeout constant "next to
    SERVED_WALL_CLOCK_BUDGET_SECONDS". Done — but bound there from the
    single canonical constant in `approvals.py` rather than duplicating the
    number, so enforcement and discovery share one value.
  - Additive contract growth, all defaulted so no existing caller breaks:
    `ExecutorContext.pipeline_policy`, `CompiledDAG.pipeline_policies`,
    `CancelToken.wait_until_cancelled()`, `DecisionOutcome.TIMEOUT`,
    `EventKind.APPROVAL_PENDING`, `WsApprovalPendingEvent`,
    `Deployment.profile_name` (+ summary field).
  - Deleting the ACTIVE custom profile fails 409 and built-ins fail 403, so
    governance can never be left without an active profile; unknown/corrupt
    active names resolve to LOCKED, never to anything permissive.
