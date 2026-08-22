# Gov-1 Report — governance phase

One commit, prefixed `gov-1:`. All work scoped to the partition I own;
HANDS OFF files untouched (verified by diff at the end).

---

## 1. ENTRY CHECK result

Both entry-check commands passed:

```
IMPORTS OK
..........................................................               [100%]
58 passed, 194 warnings in 0.16s   (test_compiler.py test_access_policy.py test_executors.py)
```

## 2. BASELINE (recorded before any change)

```
$ ./.venv/Scripts/python.exe -m pytest -q
352 passed, 4 skipped, 779 warnings in 11.49s

$ ./.venv/Scripts/python.exe -m ruff check .
All checks passed!

$ ./.venv/Scripts/python.exe -m mypy komvos
Success: no issues found in 35 source files
```

## 3. Files read in full before writing code

Confirmed read end-to-end:

- `backend/komvos/compiler/models.py`
- `backend/komvos/compiler/dag.py`
- `backend/komvos/compiler/validation.py`
- `backend/komvos/compiler/README.md`
- `backend/komvos/endpoints/base.py`
- `backend/komvos/executors/model.py`
- `backend/komvos/scheduler/runner.py`

Plus, for wiring/context (read fully or in the relevant entirety):
`executors/base.py`, `executors/logic.py` (read-only; HANDS OFF),
`scheduler/engine.py`, `endpoints/cloud.py`, `endpoints/ollama.py`,
`endpoints/mock.py`, `api/registry.py`, `api/main.py` (call-site survey only),
`tests/conftest.py`, `tests/test_access_policy.py`, `tests/test_serve.py`,
`komvos/endpoints/README.md`, `pyproject.toml` (read-only).

## 4. TASK 2 reproduction (BEFORE the fix)

Script (run from `backend/`, since deleted — its permanent regression form is
`tests/test_governance.py::test_decoy_pipeline_rejected_in_served_mode`):

```python
from komvos.compiler.dag import compile

doc = {
    "schema_version": "2.1",
    "id": "00000000-0000-4000-a000-00000000de01",
    "name": "Decoy bypass", "version": "1.0.0",
    "nodes": [
        {"id": "in", "type": "input", "outputs": [{"name": "prompt", "type": "text"}]},
        {"id": "summarize", "type": "model", "endpoint_ref": "openai:model",
         "inputs": [{"name": "prompt", "type": "text"}],
         "outputs": [{"name": "out", "type": "text"}]},
        {"id": "out", "type": "output", "inputs": [{"name": "r", "type": "text"}]},
        {"id": "decoy-transform", "type": "transform",
         "inputs": [{"name": "x", "type": "text"}],
         "outputs": [{"name": "y", "type": "text"}]},
        {"id": "gate-nothing", "type": "access",
         "config": {"access_policy": {"providers": []}}},
    ],
    "edges": [
        {"from": "in.prompt", "to": "summarize.prompt"},
        {"from": "summarize.out", "to": "out.r"},
        {"from": "in.prompt", "to": "decoy-transform.x"},
        {"from": "gate-nothing.scope", "to": "decoy-transform.x"},
    ],
    "endpoints": {"openai:model": {"kind": "openai", "model": "gpt-4o-mini"}},
}

dag = compile(doc, mode="served")
print("COMPILED OK in served mode (bypass reproduced)")
for node_id in ("in", "summarize", "out", "decoy-transform"):
    p = dag.effective_policies[node_id]
    gates = str(dag.policy_sources[node_id] or "()")
    print(f"  {node_id:16s} governed_by={gates:<14} providers={p.providers}")
```

Output BEFORE the fix:

```
COMPILED OK in served mode (bypass reproduced)
  in               governed_by=()             providers=['openai', 'anthropic', 'google', 'openai_compatible', 'ollama', 'mock', 'groq', 'openrouter', 'zhipu', 'nvidia']
  summarize        governed_by=()             providers=['openai', 'anthropic', 'google', 'openai_compatible', 'ollama', 'mock', 'groq', 'openrouter', 'zhipu', 'nvidia']
  out              governed_by=()             providers=['openai', 'anthropic', 'google', 'openai_compatible', 'ollama', 'mock', 'groq', 'openrouter', 'zhipu', 'nvidia']
  decoy-transform  governed_by=('gate-nothing',) providers=[]
```

Exactly as described: compilation succeeded in served mode; the model node's
effective policy was fully permissive while only the dead-end transform was
restricted.

AFTER the fix, the same document raises:

```
komvos.compiler.validation.PipelineValidationErrors: [Access Required] Node 'summarize' (model:openai) is governed by no access node, so it would run with a fully permissive policy. Every model node must sit downstream of an access node before this pipeline can be served. Add an access node and connect it through its 'scope' port to 'summarize' (or any node upstream of it), stating what 'summarize' may reach.
```

## 5. TASK 3 claim verification (both fields were dead)

Searched all reads of `allow_network` / `allowed_domains` under `backend/`
(grep over `komvos/` and `tests/`). Findings outside definitions/tests/docs:

- `allow_network` is read in exactly one non-model place:
  `compiler/dag.py:294` (`_attribute_denials`) — solely to build the *text*
  of a denial-attribution record (`reasons.setdefault("allow_network",
  gate_id)`); it feeds error messages, never enforcement. Everything else is
  the field definition and intersect logic in `models.py`.
- `allowed_domains` is read by nothing outside `models.py` itself: only the
  intersect logic touches it. No endpoint, executor, scheduler, or API code
  consults it.

Conclusion: verified. Neither field had ever prevented a network call.
(There were no runtime readers at all; the only "use" was message text.)

## 6. What changed, per task

### TASK 1 — governance package and decision record

New package `backend/komvos/governance/`:

- `decisions.py` — `GovernanceDomain` (closed StrEnum: `providers`, `egress`,
  `spend`, `retention`), `DecisionOutcome` (allow/deny), `DecisionOrigin`
  (today only `pipeline_policy`; field exists so a later profile/grant phase
  never has to change call sites), and the `GovernanceDecision` pydantic
  record: `when` (UTC), `run_id`, `node_id`, `domain`, `capability`,
  `outcome`, `reason`, `governed_by` (access-node ids), `effective_policy`
  (snapshot), `origin`. Emitted on ALLOW as well as DENY.
- `sinks.py` — `DecisionSink` Protocol whose `record` is a **coroutine**,
  plus `InMemoryDecisionSink` (list-backed, `for_run()` queryable). No SQLite,
  no tables, by design.
- `context.py` — run-scoped binding via contextvars:
  `bind_run_context`/`unbind_run_context`/`run_context`, `current_sink`,
  `current_run_id`, and `record_decision(...)` which builds the record and
  hands it to the bound sink (no-op when unbound, but still returns the
  decision). This mirrors how the event callback reaches executors: injected
  once at the top of a run, never threaded through call sites.
- `egress.py` — see TASK 3.
- `README.md` — why-first documentation matching `compiler/README.md`'s tone:
  allow-and-deny logging rationale, async-now rationale (future human
  approval suspension point), closed domains, origin visibility, empty-
  domains reading, subdomain rule, loopback exemption, estimates caveat,
  retention declared-but-unimplemented, in-memory-only storage.

Wiring: `scheduler/runner.py:147,172-184` — every `PipelineRunner.run()`
creates a fresh `InMemoryDecisionSink`, exposes it as `runner.decision_sink`,
and binds `(sink, run_id)` around the whole run (`_run()` holds the former
body). Canvas runs, served runs, and tests all get decisions for free.

Attribution plumbing: `executors/base.py:43` adds
`policy_sources: tuple[str, ...]` to `ExecutorContext`;
`scheduler/engine.py:443` fills it from `CompiledDAG.policy_sources`.

### TASK 2 — close the served-mode bypass

- `compiler/dag.py:270-303` — `_check_served_governance(pipeline, sources)`:
  in served mode, any `model` node whose `policy_sources` entry is empty is
  an offender. Uses the already-computed per-node governing record — no
  second graph traversal. Only `model` nodes qualify: they are the only node
  type permitted to carry `endpoint_ref` (enforced in `models.py`), and I
  verified the other executors (`logic.py` judge/router/transform/compare,
  input/output) make no outbound calls.
- `compiler/dag.py:404-407` — `compile()` raises these errors (one line per
  offending node, in node order) after computing effective policies.
- Local/canvas mode never calls this check; pipelines without access nodes
  compile exactly as before (regression-tested).

### TASK 3 — egress control made real

- `governance/egress.py` (new):
  - `PROVIDER_DEFAULT_HOSTS` — provider→default-host table mirroring the
    defaults applied inside `CloudEndpoint.generate` (documented as needing
    to move together with it).
  - `endpoint_egress_host()` (:67) — resolves where an endpoint's traffic
    lands using only attributes that already exist on the implementations
    (CloudEndpoint `.base_url` override else provider default; OllamaEndpoint
    `._base_url` from `resolve_ollama_base`, which may be a remote tunnel
    URL; MockEndpoint → None).
  - `is_loopback()` — `127.0.0.1`, `::1`, `localhost` are not egress (they
    never leave the machine; local models remain governed by
    `allow_local_models`, already enforced).
  - `host_allowed()` (:102) — dot-boundary matching (see §7).
  - `check_egress()` (:120) — the gate: denies when `allow_network` is false,
    then when the host is outside non-empty `allowed_domains`, otherwise
    allows; records a `GovernanceDecision` (EGRESS domain, capability
    `egress:<host>`) on every path and raises `AccessDeniedError` BEFORE any
    socket/key work on denial.
  - `enforce_egress_for_endpoint()` (:205) — resolve host → exempt loopback →
    gate everything else.
- `executors/model.py:88-99` — the model executor calls
  `enforce_egress_for_endpoint` after the provider gate and before
  `generate()`, so a denied destination sees zero network activity.

### Provider-capability decisions (TASK 1 application, TASK 5 dependency)

- `executors/model.py:80-86` — wraps the existing `check_access` call: DENY
  re-raises after recording, ALLOW records too. Centralizing here meant
  cloud.py/ollama.py needed no edits at all (their check_access regions are
  untouched).

### TASK 4 — per-scope cost ceiling

- `executors/model.py:159-215` — inside the attempt loop, right after
  `estimate_cost`: this node's committed spend (`total_usd`) plus this
  request's estimate is compared against **its own** effective policy's
  `max_cost_usd`. Over ceiling → SPEND denial decision +
  `AccessDeniedError(capability="max_cost_usd")` before the call; within →
  SPEND allow decision. The run-wide budget remains a separate outer limit
  enforced unchanged in `_BudgetEnforcingRegistry` (`runner.py`) — both
  apply; for any given call whichever fires first stops it.
  **The ceiling currently operates on estimates** (`estimate_cost` numbers,
  known-inaccurate, fixed later); enforcement is built to be correct once
  the numbers are.
- `scheduler/runner.py:450-456` — `_BudgetCheckingEndpoint.__getattr__`
  delegates unknown attributes to the wrapped endpoint, so governance can
  still see `.provider`/`.base_url`/`._base_url` through the budget wrapper;
  without this the runner-driven paths would have blinded the egress gate.

### Partitioned files status

- `endpoints/cloud.py`, `endpoints/ollama.py`: NOT edited (zero diff) —
  centralizing emission in the executor made editing their check_access
  regions unnecessary.
- `api/main.py`: NOT edited — no new routes exist to mount.
- `api/registry.py`: NOT edited — sink binding lives in the runner, which is
  the same injection point the event callback uses.

## 7. Subdomain-matching decision

**Rule:** an `allowed_domains` entry matches the exact host and any depth of
subdomain, compared on dot boundaries, case-insensitively; ports carry no
policy meaning; a leading dot on an entry is accepted and ignored.
`example.com` matches `example.com`, `api.example.com`, `a.b.example.com`;
it never matches `notexample.com` or `evilexample.com`.

**Rationale:** plain substring matching (`host in entry or entry in host`)
would let attacker-controlled lookalikes (`evil-example.com`,
`example.com.evil.io`) through a list meant to allow `example.com`. Exact-only
matching would break the natural authoring style of listing a registrable
domain to cover its API hosts. Dot-boundary suffix matching is the smallest
rule that fixes both. Empty `allowed_domains` on an allowing policy means "no
restriction" (the reading `intersect()` depends on); that is handled before
matching and covered by tests.

## 8. Outbound-call inventory (how searched, what found)

Grepped `komvos/` for `httpx|requests\.|urllib|aiohttp|AsyncOpenAI|AsyncAnthropic|genai|socket|urlopen`, then read each hit's function.

| Path | Destination | Governed? |
| :--- | :--- | :--- |
| `endpoints/cloud.py:95` `AsyncOpenAI(base_url=...)` — openai/openai_compatible/groq/openrouter/zhipu/nvidia | custom base_url host, else api.openai.com / api.groq.com / openrouter.ai / open.bigmodel.cn / integrate.api.nvidia.com | Yes — executor egress gate before `generate()` |
| `endpoints/cloud.py:123` `AsyncAnthropic` | api.anthropic.com | Yes — same |
| `endpoints/cloud.py:150` `genai.Client` | generativelanguage.googleapis.com | Yes — same |
| `endpoints/ollama.py:73` httpx POST `{base}/chat/completions` | localhost default OR remote tunnel from `resolve_ollama_base` | Yes — loopback exempt, remote gated |
| `endpoints/ollama.py:102` httpx GET `{base}/models` (`health()`) | same as above | Not policy-gated: `health()` is called from operator-initiated API routes with no pipeline/policy context (no node, no ExecutorContext exists there). Listed, deliberately uncovered. |
| `api/registry.py:157` `resolve_ollama_base` probe GET `127.0.0.1:11434/api/tags` | loopback only | Loopback-exempt by definition |
| `api/main.py:164` `/health/ollama` probe | loopback | Operator-initiated diagnostics, no pipeline context; uncovered |
| `api/main.py:484` model-discovery probes (incl. user-configured ollama base) | loopback + configured tunnel | Same as above |

The engine's execution path — anything driven by a node's effective policy —
is fully covered. The three uncovered entries share one property: they run
outside any pipeline execution, where no effective policy exists to check
against. Governing them would mean inventing a policy source for
operator-initiated diagnostics; noted here rather than improvised.

## 9. New error messages (full text)

1. Served-mode ungoverned model node (`compiler/dag.py`, one per offending node):

```
[Access Required] Node '{node.id}' (model:{kind}) is governed by no access node, so it would run with a fully permissive policy. Every model node must sit downstream of an access node before this pipeline can be served. Add an access node and connect it through its 'scope' port to '{node.id}' (or any node upstream of it), stating what '{node.id}' may reach.
```

2. Egress, `allow_network` false (`governance/egress.py`, raised as `AccessDeniedError`, capability `egress:{host}`):

```
Node '{node_id}' requires network access to '{host}', which its access policy does not grant (allow_network is false). Grant network access on the governing access node, or point the endpoint at a local address.
```

3. Egress, host outside `allowed_domains` (capability `egress:{host}`):

```
Node '{node_id}' requires network access to '{host}', which is outside its access policy's allowed domains: [{allowed}]. Add the domain to 'allowed_domains' on the governing access node.
```

4. Spend, scope ceiling exceeded (`executors/model.py`, capability `max_cost_usd`):

```
Node '{node.id}' would exceed this scope's cost ceiling: ${total_usd:.6f} already spent plus ${estimated_cost.usd:.6f} estimated for this request is more than max_cost_usd ${ceiling:.6f}. Raise 'max_cost_usd' on the governing access node for this branch.
```

(Each of 2–4 is preceded by a recorded `GovernanceDecision` carrying a
parallel human-readable reason.)

## 10. Tests added

`tests/test_governance.py` — 27 tests covering every required case:
served-mode rejection of the decoy; governed-pipeline acceptance; local-mode
untouched (decoy and gate-less pipelines compile); two-ungoverned-nodes
error; dot-boundary host matching (parametrized incl. `notexample.com`);
empty-domains-means-unrestricted; host resolution incl. tunnel URL;
allow_network-false denial with booby-trapped keyring/httpx proving the call
never leaves; outside-denied/inside-permitted through the real executor over
a faked OpenAI transport; remote Ollama tunnel subject to egress; loopback
Ollama exempt; per-scope ceilings compiled and enforced independently per
branch; runner-level sink binding; ALLOW decisions recorded on successful
runs with attribution; record mechanics. No real provider is called anywhere.

## 11. DEFINITION OF DONE (real output)

```
$ ./.venv/Scripts/python.exe -m ruff check komvos/governance komvos/compiler komvos/scheduler komvos/endpoints komvos/executors tests
All checks passed!

$ ./.venv/Scripts/python.exe -m mypy komvos/governance komvos/compiler komvos/scheduler
Success: no issues found in 14 source files

$ ./.venv/Scripts/python.exe -m pytest tests/ -q
379 passed, 4 skipped, 851 warnings in 10.86s
```

Baseline was 352 passed / 4 skipped / 0 failed → now 379 passed / 4 skipped /
0 failed: **no new failures, +27 passing** (requirement: ≥8).

## 12. Other operator's territory — observations (not touched)

The existing HEAD commit `eb32550 gov-1: Entry check failure report` documents
an entry-check halt caused by running `import komvos_api_entry` (which imports
`neuralflow.api.main`, a module that does not exist under the `komvos` package
name) rather than the specified check — noting only; not mine to fix or revert.

## 13. Incomplete items, disagreements, notes

- Nothing incomplete. No HANDS OFF file required changing, so the stop-and-
  report clause never triggered. No dependencies added (stdlib `contextvars`,
  `enum`, `urllib.parse` only).
- Disagreement recorded per instructions: the brief says "look at how the
  existing event callback reaches executors and follow that pattern". The
  event callback is explicitly threaded (runner → Scheduler → ctx.emit_fn);
  endpoints sit below even that layer and have no context object at all, so a
  literal copy would have required touching every signature including the
  frozen `ModelEndpoint` protocol. I kept the pattern's *shape* — bind once at
  the top of the run, reach it implicitly below — implemented with
  `contextvars`, which is the stdlib mechanism designed for exactly this.
- Design note, flagged for review: loopback destinations are exempt from
  `allow_network` (they cannot leave the machine); remote Ollama tunnels are
  NOT exempt. If the intent was that `allow_network=false` blocks even
  loopback HTTP, that is a one-line change in `enforce_egress_for_endpoint`.
- Spend ceilings operate on estimates today (see §6, TASK 4).
- `PROVIDER_DEFAULT_HOSTS` in `egress.py` duplicates the default-host table
  inside `cloud.py.generate` because cloud.py is partitioned away from me;
  the duplication is commented in both spirit and README.
