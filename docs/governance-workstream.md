# Komvos — Governance Workstream (G1–G6)

**Round 2 Challenge #484 — Governance: User-Controlled Behavior Setting**
Team Dead_Pixel (UP59Y37W)

This is our half of the work. The other half (phases 2–6 in
`docs/antigravity-phases.md`) is being run in parallel by a second operator and
must not be touched from here.

Commit prefixes: `gov-1:` … `gov-6:` — deliberately different from `phase-N:`
so both workstreams stay legible in one git log.

---

## The thesis

> **One dial. Four domains. One log.**

The user picks a **governance profile** — a working mode. That single choice sets
how strictly Komvos enforces policy across four domains at once:

| Domain | What it governs |
|---|---|
| **Providers** | Which model providers a pipeline may call |
| **Egress** | Where data may leave to — cloud APIs, custom Ollama hosts, the community library |
| **Spend** | How much a run may cost before it is stopped or questioned |
| **Retention** | What run history is recorded and how long it is kept |

Every decision the engine makes under that profile — allowed *and* denied — lands
in a **governance log** the user can inspect, filter and export.

That satisfies all three parts of the brief: one behavior to adjust, state that is
always visible, feedback at the moment of decision, and history that survives a
restart.

---

## Why Firebase makes this necessary rather than decorative

Today the "community library" is local SQLite. Publishing a template goes nowhere.
Once Firebase is in, two new trust boundaries appear:

- **Outbound** — your pipeline structure, prompts, and endpoint configuration
  leave your machine and become visible to other people.
- **Inbound** — somebody else's pipeline runs on *your* machine, with whatever
  capabilities its access policy declares, against *your* API keys.

That is a real governance problem, not a hypothetical one. It is the strongest
argument we have that this dial matters.

### Architectural constraint — non-negotiable

**All Firebase traffic must go through the Python backend.**

The access policy is enforced in `backend/komvos/`. If the Electron renderer calls
Firestore directly, publishing bypasses the policy engine completely and our
central claim becomes false the first time a judge inspects it. The renderer talks
to the backend; the backend talks to Firebase; the governance layer sits in
between and can see, log, allow or deny every call.

### Credential constraint — non-negotiable

**No Firebase service account key may ship inside the app.** A PyInstaller binary
is not a secret store — anyone who downloads the installer can extract it. See
the open decision below for the three viable approaches.

---

## Ownership boundary

### We own — the other operator will not touch these

```
backend/komvos/compiler/            (all)
backend/komvos/serve/               (all)
backend/komvos/governance/          (all — new package)
backend/komvos/library/             (all — new package, Firebase)
backend/komvos/executors/model.py
backend/komvos/scheduler/runner.py
backend/komvos/endpoints/base.py
backend/komvos/state/sqlite.py      (schema additions are ours)
apps/desktop/src/canvas/accessPolicy.ts
apps/desktop/src/canvas/nodes/AccessNode.tsx
apps/desktop/src/components/DeployModal.tsx
apps/desktop/src/governance/        (new — all governance UI)
apps/desktop/src/library/           (new — all cloud library UI)
```

### They own — we must not touch these

```
.github/workflows/                  (all)
packaging/                          (all)
apps/desktop/src/main.ts
apps/desktop/src/hooks/useBackend.ts
apps/desktop/src/hooks/usePipelineActions.ts
apps/desktop/src/App.tsx            (autosave + error boundary land here)
apps/desktop/src/index.html
apps/desktop/src/components/SettingsModal.tsx
backend/komvos/executors/logic.py
backend/pyproject.toml              (dependency pinning is theirs)
README.md
```

### Partitioned — shared file, split by region

| File | Ours | Theirs |
|---|---|---|
| `backend/komvos/endpoints/cloud.py` | `check_access` only | client construction, timeouts, retries |
| `backend/komvos/endpoints/ollama.py` | `check_access` only | timeouts, retries |
| `backend/komvos/api/main.py` | new `include_router` lines at the bottom | CORS block, FastAPI title |
| `backend/komvos/api/registry.py` | governance service wiring only | run registry, lifespan StateManager |

**Rule:** add new functionality in new modules and mount it with a router. Do not
edit existing route bodies in `api/main.py`. This is what keeps the merge cheap.

**Dependency note:** `pyproject.toml` belongs to the other operator. Any package
we need (Firebase client, etc.) must be requested from them, not added directly —
except in G5, which explicitly claims that file for the Firebase dependency.

---

## The six phases

### G1 — Make every declared control real
**Goal:** the policy engine actually enforces everything it claims to, and every
decision it makes is recorded.

Today three of six `AccessPolicy` fields are enforced. `allow_network` is read
only to build an error message. `allowed_domains` is read by nothing at all.
`max_cost_usd` is collapsed into a single run-wide floor. And served mode's
mandatory-access-node check is satisfied by a decoy node wired to a dead branch.

Delivers: `governance/` package, a `GovernanceDecision` record emitted from every
enforcement point (on allow as well as deny), the bypass closed, egress control
implemented, per-scope cost ceilings enforced.

**No Firebase. No UI. Nothing user-facing yet.** This is the floor everything
else stands on — a dial over an engine that does not enforce is theater.

---

### G2 — The dial: postures and profiles
**Goal:** the one behavior the user adjusts.

A **posture** is what happens when policy is violated: `Enforce` (block and halt),
`Ask` (pause and prompt), `Audit` (permit and record). A **profile** binds a
posture to each of the four domains, plus the concrete limits for that domain.

Delivers: profile model and storage, resolution and precedence rules (what wins
when a pipeline's own access node disagrees with the active profile), built-in
profiles, custom profile editing, backend API, and posture wired into every G1
enforcement point.

Open question resolved here: what `Ask` means mechanically — see open decisions.

---

### G3 — The evidence surface
**Goal:** everything a judge needs to confirm the feature works.

Delivers: the governance log (persisted, queryable, filterable, exportable), the
profile picker UI, an always-visible active-profile indicator, live decision
feedback on the canvas at the moment it happens, and the decision-history panel.

This phase is what the challenge is actually graded on. It gets as much design
attention as the engine did.

---

### G4 — Spend and retention become real domains
**Goal:** two of the four domains currently rest on numbers that are wrong or
storage that is unbounded.

Cost today is estimated, not measured: input tokens are guessed from character
count, output tokens are billed at the configured ceiling rather than actual
usage, and the running total counts stream chunks. A spend dial on those numbers
would be worse than no dial. Retention has no policy at all — full prompts and
completions are kept forever with no way to delete them.

Delivers: real provider usage accounting, the mislabeled budget event fixed,
per-deployment spend caps, a concurrent-run bound, run deletion, retention
windows, recording levels — all wired to the posture dial.

---

### G5 — Firebase: the governed community library
**Goal:** publishing and installing become real, and both are governed actions.

Delivers: Firebase integration behind the backend, the local `library_templates`
and `custom_nodes` tables promoted to a shared cloud library, publish and browse
and install flows, server-side secret scrubbing (client-side scrubbing is a
convenience, not a control), provenance metadata, and publishing treated as an
egress action subject to the active profile.

**Prerequisite: the open decisions below must be answered before this phase starts.**

---

### G6 — Untrusted content and submission readiness
**Goal:** close the inbound trust boundary Firebase opens, and make the whole
thing demonstrable.

An installed community template is somebody else's code running against your API
keys. Delivers: capability review before install (what this template is asking
for, in plain language), a restricted default profile for untrusted content,
trust levels and provenance display, seed data, a rehearsed demo path, and the
written submission material.

---

## Open decisions — needed before G5, not before G1

**1. How does the backend authenticate to Firebase without shipping a secret?**

- *Firestore REST + Firebase Auth ID token* — user signs in, backend uses their
  token. No secret ships. Simplest; security rules do all the work.
- *Cloud Functions as the API layer* — service account stays on Google's side,
  app calls functions with an ID token. Most correct, most setup.
- *Service account in the binary* — **not viable.** Listed only to rule it out.

**2. What identity model?** Anonymous auth (frictionless, weak provenance),
Google sign-in (real authorship, adds a login step), or a hybrid where browsing
is anonymous and publishing requires sign-in.

**3. What are the profiles called, and how many?** Three is the number that reads
cleanly in a demo. Names should describe a way of working, not a threat level.

**4. What does `Ask` mean mechanically?** Pre-flight approval before the run starts
is a fraction of the work and gets most of the demo value. True mid-run pause and
resume is the impressive version and the expensive one.

**5. Profile vs pipeline access node — who wins?** A profile that can only ever
tighten what an access node grants is easy to reason about and easy to defend. A
profile that can loosen it is more flexible and much harder to explain.

---

