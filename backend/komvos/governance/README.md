# komvos/governance

**Owner: Gov-1 — Governance workstream**

## Purpose

Every point in the system that decides whether something is permitted — a
provider check before a model call, an egress gate before a request leaves
the machine, a cost ceiling before spend is committed — produces one
`GovernanceDecision` and hands it to a sink. This package owns the record,
the sink interface, and the egress gate.

The access policy itself lives in `komvos.compiler.models.AccessPolicy`; the
compiler computes each node's effective policy. This package is what makes
the *enforcement* of that policy observable.

## Why decisions on ALLOW, not just DENY

A log that only records denials looks empty during a successful demo — which
is exactly when someone will be looking at it. An allow record is also the
only way to answer "what did this run actually touch?" after the fact, and it
is how an unexpected allow gets noticed at all. Every enforcement point in
the system emits on both outcomes. There are no silent allows.

## The decision path is async — on purpose

`DecisionSink.record` and every emit helper are coroutines today even though
nothing awaits anything slow yet. A later phase suspends a running pipeline
at exactly this point to ask a human for approval, then resumes it. A
synchronous sink would have forced a rewrite of every call site the day that
landed; an async one makes suspension a property of the sink, not a migration.

## Domains are a closed enumeration

`GovernanceDomain`: `providers`, `egress`, `spend`, `retention`. It is an
enum, not a string, so a typo cannot silently create a fourth domain and an
audit query cannot miss one. Retention is declared but enforced nowhere yet:
the schema carries no retention field. That gap is visible here rather than
hidden behind a string that happens to say "retention".

## Where the constraint came from

Each decision carries `origin`, which names the source that produced the
outcome. Today there is exactly one source: the pipeline's own access policy.
A later phase adds a user profile that can override a pipeline's policy in
either direction — including grants the pipeline never asked for. When a
profile grants something the pipeline withheld, that must show up in the log
as coming from somewhere other than the pipeline. The field exists now,
populated with `pipeline_policy`, so call sites never change when new origins
appear.

Alongside `origin`, each decision records `governed_by` (the access nodes
whose intersection produced the effective policy) and a snapshot of the
effective policy values themselves, so a decision line can be read without
replaying compilation.

## Wiring: bound per run, not threaded per call

Decisions need a run id; enforcement happens deep below the runner. Rather
than threading a sink through every executor and endpoint signature, the
`PipelineRunner` binds `(sink, run_id)` once for the duration of a run — the
same pattern the event callback already uses to reach executors. Code under
the runner asks `governance.context` for the current sink. With nothing
bound (bare-Scheduler tests, non-run paths), recording is a no-op.

The sink is deliberately **in-memory only**. No SQLite, no tables: storage is
designed in a later phase, and a schema chosen now will be wrong.

## Egress semantics

Egress means traffic that would leave the machine:

- **Loopback is not egress.** `127.0.0.1`, `::1`, and `localhost` are exempt
  from `allow_network`; local models are governed by `allow_local_models`,
  which was already enforced. The case that matters is a remote Ollama base
  URL (`resolve_ollama_base` can return a tunnel URL): that is real egress
  and requires `allow_network`.
- **`allow_network=false` denies** every non-loopback destination, including
  cloud provider defaults.
- **An empty `allowed_domains` on a policy that allows network means "no
  domain restriction"**, not "no domains". This matches the compiler's
  intersect logic, where an empty list acts as the identity — if enforcement
  read it as "nothing allowed", any unrestricted ancestor would silently
  revoke its descendants' domains. Do not "tighten" this reading.
- **Host matching is dot-boundary, not substring.** An entry matches itself
  plus any depth of subdomain: `example.com` covers `api.example.com` and
  `a.b.example.com`, but never `notexample.com`. Substring matching would let
  an attacker-hosted domain like `evil-example.com` through a list meant to
  allow `example.com`. Comparison ignores case; ports carry no policy
  meaning. An entry may be written with a leading dot; it is ignored.

Cloud calls are gated on their actual destination: the custom `base_url`
host when one is set, otherwise the provider's default host (see
`PROVIDER_DEFAULT_HOSTS`).

## Spend semantics

Per-scope ceilings (`max_cost_usd`) are enforced against each node's own
effective policy, so two scopes can carry different ceilings. The run-wide
budget remains a separate outer limit; both apply and the tighter wins for a
given call. **Ceilings currently operate on estimates** — `estimate_cost`
numbers, whose accuracy is a known issue being fixed separately. The
enforcement is built to be correct once those numbers are.

## What is not here

- No retention enforcement (schema has no retention field yet).
- No persistence.
- No UI, profiles, or approval flow — later phases build on the async sink
  seam this package leaves open.

---

# Gov-2 additions: posture and profiles

## Posture — the user's dial

The pipeline's access policy decides what a pipeline *asks for*. A PROFILE
decides what happens when that ask is withheld:

| Posture   | Meaning |
| :--- | :--- |
| `Enforce` | deny and halt — exactly as before profiles existed |
| `Ask`     | suspend the run at that node, ask a human, act on the answer |
| `Audit`   | permit anyway, recording that the posture allowed it |

Built-in profiles (never editable; copy one to customize):

| Profile  | providers | egress | spend | retention | limits |
| :--- | :--- | :--- | :--- | :--- | :--- |
| EXPLORE  | Audit | Audit | Audit (record, no cap) | full recording | — |
| REVIEW   | Ask | Ask | Ask above threshold ($1.00) | full recording | `spend_ask_threshold_usd=1.0` |
| LOCKED   | Enforce | Enforce | Enforce | metadata only | pipeline ceilings stand |

**Default: LOCKED.** For databases, deployment rows, and any missing or
corrupt active-profile setting. LOCKED reproduces pre-profile behaviour
exactly (the pipeline's own policy decides, nothing loosens), so a silent
fallback can never grant more than the user explicitly had. EXPLORE would
silently permit; REVIEW would suspend runs waiting for answers no UI ever
gave.

Retention is modelled on profiles (shape only). Nothing produces retention
decisions yet — enforcement is a later phase.

## Resolution — compile-time and run-time must agree

`resolve.resolve_policy(pipeline_policy, profile)` produces the policy
actually in force plus the ORIGIN of every value:

- **Loosen** (Ask/Audit): capabilities the pipeline withheld are granted by
  resolution, because the posture layer will handle them interactively.
  This runs BEFORE the compiler's capability check when `compile()` is given
  a profile, so a profile-permitted pipeline compiles. With no profile
  argument, compile() is byte-identical to the pre-profile compiler.
- **Tighten** (Enforce + cap, Ask threshold): the operative spend ceiling is
  the lower of the pipeline's and the profile's.

Origins: `pipeline_policy` (the pipeline decided alone), `profile` (granted
or constrained only by the profile), `pipeline_and_profile` (both agree —
e.g. Enforce upholding a pipeline denial). A capability granted ONLY by the
profile is attributed to `profile` in every decision about it.

At run time the executor checks BOTH views: first the pipeline-only policy
(a denial there triggers the posture), then the resolved policy (a denial
there is an ordinary tightening). Under Enforce the two views are identical,
which is why the layers cannot disagree. The G1 structural rule stands under
every profile: every model node must be governed by an access node — a
profile adjusts grants, it does not excuse a pipeline from declaring one.

## Ask — how suspension works

A pending approval is an `asyncio.Future`. The suspended node genuinely
awaits it: the event loop, the WebSocket pump, and every other node in the
same parallel tier keep running. The runner emits a typed
`approval_pending` WebSocket event carrying node, domain, capability,
reason, and the effect of each possible answer.

Answers arrive over `POST /governance/approvals/{id}/answer`:

- `allow_once` — proceeds once.
- `allow_for_run` — records an exact `(domain, capability)` grant for the
  remainder of THIS run only; nothing else widens.
- `deny` — the node fails with `AccessDeniedError`.

Fail-closed guarantees:

- **Timeout:** an unanswered approval fails closed after
  `APPROVAL_TIMEOUT_SECONDS` (300s, chosen to match
  `SERVED_WALL_CLOCK_BUDGET_SECONDS`; re-bound beside it in
  `serve/routes.py`). The decision outcome is `timeout`, distinguishable
  from a human denial.
- **Cancellation works while suspended:** the wait races the run's
  CancelToken via `wait_until_cancelled()`, so kill switch and wall-clock
  expiry abort a waiting node immediately instead of leaving it parked.
- **No persistence:** pending approvals live in process memory only and do
  NOT survive a restart. A restart leaves nothing pending and nothing
  answerable.
- **No leaks:** the registry is strictly per-run and removed when the run
  ends — success, error, cancellation, all paths.
- **Served runs never ask:** there is no human at the end of an HTTP
  request. On served runs Ask degrades to Enforce, and the decision record
  says `[Ask degraded to Enforce]` with the reason — not merely "denied".
