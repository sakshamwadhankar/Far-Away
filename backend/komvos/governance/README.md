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
