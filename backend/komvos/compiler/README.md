# neuralflow/compiler

**Owner: P1 — Backend Core**

## Purpose

Transforms a raw pipeline JSON (schema v2) into a **typed, validated DAG** that
the scheduler can execute. This is the single gate that must reject any
structurally or semantically invalid pipeline before execution begins.

## Validation rules enforced (TRD §4)

1. The main graph (excluding loop subgraphs) must be **acyclic**.
2. Every edge must connect **type-compatible** ports
   (`text | number | boolean | json | image | audio`).
3. Every `endpoint_ref` in a model node must resolve in the pipeline's
   `endpoints` map.
4. `stop_when` must be a **structured condition** (no raw code or `eval`);
   supported ops: `==  !=  >  <  >=  <=  contains`.
5. Every loop must have a **finite** `max_iterations` and a defined `on_max`
   policy (`return_best | fail | return_last`).
6. **Access nodes are scope markers** (schema 2.1). They declare no data ports,
   must carry a `config.access_policy`, and every edge touching one uses the
   reserved port name `scope`. No other node type may carry an `access_policy`.

## Access policy — the intersection rule

An `access` node states what the pipeline is permitted to reach. Its policy
applies to **every node downstream of it** in the DAG.

A node's **effective policy** is computed by walking its ancestors and
collecting every access node among them. When there is more than one, their
policies are combined by **INTERSECTION — the most restrictive wins. Never the
union.**

```
       ┌─────────┐
       │ gate-1  │  providers: [openai, anthropic]   max_cost_usd: 5.00
       └────┬────┘
            │ scope
       ┌────▼────┐
       │ gate-2  │  providers: [openai]              max_cost_usd: 1.00
       └────┬────┘
            │ scope
       ┌────▼──────┐
       │ summarize │  effective: providers [openai], max_cost_usd 1.00
       └───────────┘
```

### Why intersection

The rule exists so that **moving a node further downstream can only ever take
capabilities away, never add them.** If two ancestors combined by union, you
could widen a tightly-scoped node's reach by wiring an unrelated permissive
gate into it from somewhere else in the graph — the permission layer would
then be something an edge could accidentally defeat, which makes it useless as
a boundary in Phase 3.

Per field:

| Field                | Combination                                             |
| -------------------- | ------------------------------------------------------- |
| `providers`          | set intersection                                        |
| `allow_local_models` | logical AND                                             |
| `allow_network`      | logical AND                                             |
| `allowed_domains`    | set intersection; an **empty** list means "unrestricted", so it acts as the identity rather than the empty set |
| `max_cost_usd`       | lower of the two; `null` means "no ceiling" and loses    |
| `max_tokens`         | lower of the two; `null` means "no ceiling" and loses    |

`allowed_domains` is the one asymmetric case: intersecting an unrestricted
policy (`[]`) with a restricted one must yield the restricted list, not the
empty set, or an unrestricted ancestor would silently revoke every domain its
descendant was granted.

### When no access node governs a node

The effective policy is `AccessPolicy.permissive()` — everything allowed. That
is what keeps every pre-2.1 pipeline working unchanged on the canvas.

## Compile modes

`compile(raw_json, mode=...)`:

- **`"local"`** (default) — a canvas run. A pipeline with no access node is
  permissive.
- **`"served"`** — the pipeline is about to be reachable over HTTP. A pipeline
  with no access node is **refused**, because "what can this thing touch" stops
  being an inspector and becomes a security boundary once it is exposed.

The effective policy is carried on `CompiledDAG.effective_policies`
(`node_id → AccessPolicy`) and the access nodes it came from on
`CompiledDAG.policy_sources`. The scheduler passes the per-node policy into
`ExecutorContext`, and the endpoints enforce it **before** any outbound
request leaves the machine.

## Phase (roadmap.md)

- **Phase 2:** Core compiler — DAG construction + all five validation rules.
- **Phase 4:** Validation hardening — friendly error messages per rule; fuzz tests.
