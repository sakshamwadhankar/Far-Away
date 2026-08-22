Now a full end-to-end verification of every Phase 0 gate:

Ran 5 shell commands

dist-electron/ regenerates from source, so untracking it is safe. Let me review the final diff shape and stage the commit:

Ran 2 shell commands

Staging only Phase 0 changes (leaving the pre-existing PRD/TRD/roadmap deletions untouched):

Made 1 scratchpad edit +61, ran 4 shell commands

Phase 0 is complete and committed on phase-0/repo-hygiene-ci. Every gate passes.

What I found and fixed

The four sub-tasks were as described, but 0.3 was much larger than "add a test job" — turning CI on exposed the debt it had been hiding:

- 319 ruff findings → 0. Used the project's own pinned black (line-length 88, already declared in pyproject.toml) plus ruff --fix, then hand-fixed B904/E402/E501/SIM/UP/E741. Also moved the deprecated top-level [tool.ruff] select into [tool.ruff.lint] and declared FastAPI's Depends/Query/etc. as immutable calls so B008 stops false-positiving.
- 29 mypy --strict errors → 0, with no baseline file and no weakened config. The doc offered a baseline escape hatch; it wasn't needed. About ten errors shared one root cause: ModelEndpoint.generate was declared async def … -> AsyncIterator[Token], which types every call site as a coroutine and breaks async for. It's an async generator, so the declaration is now a plain def.

Three real bugs surfaced along the way, all now fixed:

1. POST /pipelines/estimate treated NodeConfig as a dict — "max_tokens" in node.config and node.config.get(...) would both raise at runtime for any pipeline with a loop node. max_tokens now reads the typed field, and the loop multiplier reads pipeline.loops[].max_iterations, where the bound actually lives.
2. App.test.tsx has been failing since commit 1bea72d. One assertion was merely stale (the UI- **Phase 1-3:** Completed successfully previously.

### Phase 4 (Current)

- Successfully extracted `useRunSocket.ts`, `useBackend.ts`, `pipelineStore.ts`, `runStore.ts`, and `usePipelineActions.ts`.
- `App.tsx` has been refactored and is now 214 lines (well under the < 300 line constraint).
- Verified that the `App.test.tsx` suite is fully green without any modifications (62 out of 62 tests pass).

### Outstanding Issues & Next Steps

- Transition to Phase 5: Fix project naming, metadata, duplicate files, and documentation cleanup.oint all survived. I restored the wiring rather than deleting the test.

3. ruff legitimately flagged cross-test-module fixture imports as unused; added backend/tests/conftest.py so pytest collects the shared client fixtures properly.

Verification

| Gate | Result |
|---|---|
| file .gitignore | UTF-8 Unicode text, 0 null bytes, 0 CR |
| git check-ignore -v scratch/test_backend.py | matches .gitignore:55 |
| Tracked build artifacts | 0 (package-lock.json still tracked) |
| ruff check . | All checks passed |
| mypy neuralflow | Success, 27 files |
| mypy neuralflow | Success, 27 files |
| pytest -q --cov | 150 passed, 1 skipped, 82% |
| npm run typecheck / lint / test | clean / clean / 37 passed |
| npm run build | succeeds (dist-electron/ regenerates, so untracking is safe) |

Two things I could not fully verify locally

- mypy under CI's Python. Your local interpreter is 3.14; mypy 1.16.0 crashes with an INTERNAL ERROR while analyzing the openai and anthropic packages there. I made this deterministic rather than papering over it: [[tool.mypy.overrides]] sets follow*imports = "skip" for openai.*/anthropic.\_/google.\*, so the result is identical whether or not the SDKs are installed, and local runs agree with CI (Python 3.11). There's a TODO(typing) on that block. google-genai genuinely ships no py.typed, so it needed the override regardless.
- The CI job itself. I ran every step verbatim by hand, but act isn't available here and I haven't pushed. The YAML parses and the needs: test wiring is confirmed.

Blockers / for you to decide

- NeuralFlow_PRD_v3.md, NeuralFlow_TRD_v1.md, and roadmap.md are deleted in your working tree (unstaged, from before I started). I deliberately left those deletions out of the commit — upgrade.md lists the TRD and PRD as required reading for Phases 1–5. Restore them with git restore or confirm the deletion is intentional.
- Phase 4's premise is now partly invalid. It says App.test.tsx "must pass unmodified before and after." It didn't pass before — I had to change one assertion and restore a missing feature. It passes now, so it's a usable safety net going forward, but the file is no longer byte-identical to main.
- App.tsx grew by ~60 lines from the restored estimate feature, which works against Phase 4's under-300-line target. The extraction is still very achievable; just noting the direction.
- Nothing is pushed and no PR is open — say the word and I'll push the branch.

Ready for Phase 1 (security hardening) whenever you are.

✻ Sautéed for 15m 17s

Checkpointing here — backend gate is green. Nothing is committed for Phase 2 yet; all work is in the working tree on phase-2/access-node.

Done so far (2.1–2.4, plus 2.6a/2.6c)

- 2.1 (BREAKING) — AccessPolicy + access NodeType + NodeConfig.access*policy, mirrored in shared/pipeline.schema.json and shared/types.ts, schema_version now "2.0" | "2.1". I also closed pre-existing drift between the three contracts (EndpointKind had 10 kinds in Python vs 6 in TS/JSON; custom*\* config fields were missing from the JSON Schema).
- 2.2/2.3 — ancestor walk computing per-node effective policy with intersection semantics, actionable denial errors, access-node structural rules (no data ports, reserved scope edge port, orphan detection), compile(..., mode="local"|"served"), and the rule documented in compiler/README.md.
- 2.4 — policy on ExecutorContext, AccessDeniedError raised before any network work, check_access on Cloud/Ollama/Mock endpoints, max_tokens capping, max_cost_usd folded into the existing CancelToken budget via \_tightest_budget, and the access_denied WS event.
- 2.6a/2.6c — test_access_policy.py, 34 tests. Suite is 205 passing (was 171). ruff, mypy strict, and pytest all green.

Remaining Phase 2 work

- 2.5 — the UI, the whole point of the feature. AccessNode.tsx with the three capability states (granted-and-used / granted-and-unused / requested-and-denied), one-click grant/tighten writing back to config.access_policy, plus palette and inspector wiring in LeftSidebar.tsx / RightPanel.tsx. This is the largest remaining chunk and none of it is started.
- 2.6b and 2.6d — the two missing tests. Extend test_compiler_fuzz.py to generate access nodes, and write AccessNode.test.tsx covering all three states.
- Then commit with the BREAKING: schema_version 2.1 body, and re-run the frontend gate (typecheck/lint/test) — I have not run it since editing shared/types.ts.

One design note worth your review before I go further: access nodes connect via a reserved port name, gate-1.scope, because the Edge contract requires nodeId.portName. The alternative was loosening Edge to accept a bare node ID, which would have been a wider breaking change affecting every consumer. The serializer in apps/desktop/src/canvas/serializer.ts will need to emit that form when I do 2.5.

✻ Brewed for 20m 3s

Everything green. Let me verify the round-trip end-to-end — a canvas-serialized access pipeline must compile on the backend:

Ran 1 shell command

The three contracts agree end to end. Committing Phase 2:

Made 1 scratchpad edit +125, ran 2 shell commands

Phase 2 is complete and committed on phase-2/access-node.

Todo list — final status

| # | Task | Status |
|---|---|---|
| 2.1a–d | AccessPolicy, access NodeType, schema 2.1 across all three contracts | ✅ |
| 2.2a–e | Effective policy, intersection, denial errors, port rules, README | ✅ |
| 2.3a | mode="local" | "served" | ✅ |
| 2.4a–e | Context policy, AccessDeniedError, Ollama check, budget reuse, WS event | ✅ |
| 2.5a–c | AccessNode.tsx, live toggles, palette + inspector | ✅ |
| 2.6a–d | 34 backend + fuzz + zero-HTTP + 12 UI tests | ✅ |
| 2.7 | Full gate green | ✅ |

Suite: backend 171 → 330 passing, frontend 37 → 49. ruff, mypy strict, typecheck, and lint all clean.

Design decisions worth your review

Scope edges use a reserved port name. Edge requires nodeId.portName, so access nodes connect via gate-1.scope. Loosening Edge to accept a bare node ID would have been a far wider breaking change touching every consumer. Port-type checking is skipped for these edges and orphaned access nodes are rejected.

allowed_domains intersects asymmetrically. An empty list means "unrestricted", so it acts as the identity rather than the empty set — otherwise an unrestricted ancestor would silently revoke every domain its descendant was granted. This is the one field where naive set intersection is wrong.

The zero-outbound-calls test has teeth. keyring.get_password, httpx.AsyncClient.send, and .stream are all booby-trapped to raise, so the test fails loudly if check_access ever runs after the request instead of before it.

I fixed pre-existing contract drift while I was in there. EndpointKind had 10 kinds in Python but only 6 in TS and the JSON Schema, and NodeConfig was missing custom_node_id/custom_label/custom_color under additionalProperties: false — meaning any real pipeline using a custom node would have failed JSON-Schema validation. Flagging it since it widened the diff beyond the phase spec.

Blockers / caveats

- The UI is verified by unit tests only. I mocked React Flow's useNodes/useEdges/useReactFlow rather than launching Electron. The capability logic is well covered, but drag-drop of an Access node onto a real canvas, and whether the scope handles connect cleanly in the actual React Flow surface, are unverified. Worth a manual smoke test.
- allow_network and allowed_domains are inspected and stored but not enforced at runtime. Nothing in the current codebase makes general (non-model) outbound calls, so there's no call site to gate. They'll matter in Phase 3.
- Pre-existing deletions still unstaged — NeuralFlow_PRD_v3.md, NeuralFlow_TRD_v1.md, roadmap.md. Unchanged from Phase 0.
- Nothing pushed. Three phase branches exist locally, each stacked on the last: phase-0/repo-hygiene-ci → phase-1/security-hardening → phase-2/access-node.

Phase 3 (serve pipelines as an OpenAI-compatible API) is next, and its prerequisite — mode="served" refusing a pipeline with no access node — is now in place.

✻ Cogitated for 6m 54s

Ran 1 shell command

Full frontend gate is green — 62 tests. Now let's do a final full-repo gate check (backend + frontend) and a production build sanity check:

Ran 1 shell command

Backend gate fully green with solid coverage on the new serve/ module. Now the frontend build sanity check:

Ran 1 shell command

All checklist items complete. Let's review the full diff before committing:

Ran 3 shell commands

Now composing the commit:

Made 1 scratchpad edit +128, ran 1 shell command

Phase 3 is complete and committed on phase-3/serve-api.

Todo list — final status

| # | Task | Status |
|---|---|---|
| 3.1a–e | serve/ module: models, keys, store, routes, README | ✅ |
| 3.2a–d | Management + public routes (deploy, list, undeploy, rotate, chat, models, native) | ✅ |
| 3.3a–d | api_field/api_expose, chat/native mapping, SSE reusing the existing event queue | ✅ |
| 3.4a–f | Scoped keys, LAN opt-in, access-node requirement, policy enforcement, rate limiting, trace tagging | ✅ |
| 3.5a–b | DeployModal.tsx, Deployments section in LeftSidebar.tsx | ✅ |
| 3.6a–d | 24 backend + 13 frontend tests, real OpenAI SDK acceptance test, SSE well-formedness test | ✅ |
| 3.7 | Full gate green | ✅ |

Suite: backend 330 → 354 passing (85% coverage on serve/). Frontend 49 → 62 passing.

Key design decisions

Circular import avoided via a factory, not a workaround. serve/routes.py can't import api/main.py (main.py mounts it). I moved the shared endpoint-resolution helpers (build_endpoint_registry, get_state_manager, run_pipeline_task) into api/registry.py — which already existed and had zero dependency on main.py — and added a bind_app() call so those helpers still reach app.state for test overrides. This also deleted a ~50-line duplicate: /pipelines/run and /pipelines/estimate now share one build_endpoint_registry.

No second execution pipeline, verified not just claimed. Served requests drive the identical PipelineRunner/Scheduler queue a canvas run uses; routes.py only translates the same WsEvent stream into HTTP/SSE shapes.

The acceptance criterion is real, not simulated. I ran the actual openai SDK (AsyncOpenAI with http_client pointed at the in-process ASGI transport) against a mock-backed deployment before writing the formal test — confirmed the response shape passes the SDK's own strict validation.

Blockers / caveats — read before treating LAN exposure as done

expose_lan is honest but incomplete, and I want to be explicit about this rather than let it read as fully implemented: setting it stores intent and adds a per-request loopback check, but the backend process itself stays bound to 127.0.0.1 (unchanged from Phase 1) — nothing in this phase makes uvicorn listen more widely. Wiring --host 0.0.0.0 into the Electron spawn path was out of scope for Phase 3 per the upgrade doc's own phasing. This is documented in serve/README.md's "Known limitations" and the UI's confirmation dialog says so too, but it's worth your explicit sign-off before anyone relies on it.

Every served request recompiles the pipeline from stored JSON — correct and current by construction, but a real per-request cost if a deployment's pipeline grows large. Noted in the README, not addressed here.

allow_network/allowed_domains are stored and inspected but there's no executor that makes general (non-model) outbound calls yet, so nothing enforces them today.

Three phase branches exist locally, stacked: phase-0 → phase-1 → phase-2 → phase-3. Nothing pushed. Phase 4 (extracting App.tsx, now larger from the Deployments wiring) and Phase 5 (naming/docs, including the README's "Use your pipeline as an API" section this phase deliberately deferred) remain.

✻ Churned for 35m 51s

────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

### Phase 4 (Complete)

- Successfully extracted `useRunSocket.ts`, `useBackend.ts`, `pipelineStore.ts`, `runStore.ts`, and `usePipelineActions.ts`.
- `App.tsx` has been refactored and is now 214 lines (well under the < 300 line constraint).
- Verified that the `App.test.tsx` suite is fully green without any modifications (62 out of 62 tests pass).

### Outstanding Issues & Next Steps

- Transition to Phase 5: Fix project naming, metadata, duplicate files, and documentation cleanup.

# Phase 4 Refactoring Walkthrough

I have successfully completed Phase 4 of the upgrade. `App.tsx` has been aggressively refactored into smaller, cohesive custom hooks and stores. The primary goal was to bring `App.tsx` under 300 lines while ensuring that `App.test.tsx` remains completely unmodified and passing.

## Changes Made

### 1. Extracted Stores to `src/state`

- **[pipelineStore.ts](file:///c:/Users/Asus/Documents/GitHub/Far-Away/apps/desktop/src/state/pipelineStore.ts)**: Encapsulates all React Flow state (`nodes`, `edges`), selected nodes, and complex node manipulation logic including the integration of `useUndoRedo`.
- **[runStore.ts](file:///c:/Users/Asus/Documents/GitHub/Far-Away/apps/desktop/src/state/runStore.ts)**: Isolates all run tracking data (`runId`, `startTime`, `isRunning`), per-node status (`nodeStats`), and token counts (`runTotals`).

### 2. Extracted Hooks to `src/hooks`

- **[useRunSocket.ts](file:///c:/Users/Asus/Documents/GitHub/Far-Away/apps/desktop/src/hooks/useRunSocket.ts)**: Holds the WebSocket logic and event buffering (`tokenStatsBuffer`, `tokenTotalsBuffer`) to handle high-frequency token updates efficiently.
- **[useBackend.ts](file:///c:/Users/Asus/Documents/GitHub/Far-Away/apps/desktop/src/hooks/useBackend.ts)**: Handles the initial Electron IPC handshake (`onBackendReady`), continuous `/health` polling to track connectivity, and model list fetching.
- **[usePipelineActions.ts](file:///c:/Users/Asus/Documents/GitHub/Far-Away/apps/desktop/src/hooks/usePipelineActions.ts)**: Separates the bulky modal handlers and actions such as load, export, publish, delete, and workspace clearing out of `App.tsx`.

### 3. Refactored `App.tsx`

- **[App.tsx](file:///c:/Users/Asus/Documents/GitHub/Far-Away/apps/desktop/src/App.tsx)**: Now acts strictly as the conductor component that coordinates the states and handles the main layout. It successfully dropped from over 1000 lines down to **214 lines**, comfortably satisfying the constraint of being under 300 lines!

## Validation Results

- **Lines of Code Constraint:** `App.tsx` is precisely **214 lines**.
- **Typecheck:** Passes completely (`npm run typecheck`).
- **Linting:** Passes completely (`npm run lint`).
- **Test Suite (`App.test.tsx`):** Unmodified and passing 100% (**62 out of 62 tests pass** locally without errors).

## Next Steps

With Phase 4 completely wrapped up, the repository is ready for the final Phase 5 cleanup where we will consolidate project naming, rectify metadata anomalies, and remove any remaining duplicated specification files.

# Phase 4 and 5 Completion Summary

## Phase 4: Frontend Refactoring

We successfully modularized `App.tsx` from ~1,000 lines down to a clean, maintainable ~200 lines.

- **Extracted Logic:** Split out logic into specialized hooks: `useRunSocket`, `useBackend`, and `usePipelineActions`.
- **State Management:** Abstracted UI and Pipeline state into lightweight Zustand stores (`pipelineStore.ts`, `runStore.ts`).
- **Validation:** Ensured all 62 frontend tests continue to pass with strict typing.

## Phase 5: Name Change & Polish

We performed a massive, repository-wide rename from `neuralflow` to `komvos` while preserving the product's identity.

### Changes Made:

- **Backend Renaming:** Renamed `backend/neuralflow/` to `backend/komvos/` and updated all internal references and imports using automated find-and-replace scripts.
- **Migration & Fallback:**
  - Updated DB path initialization to use `~/.komvos`.
  - Added a silent migration to move existing `~/.neuralflow/neuralflow.db` data to the new path to ensure users don't lose their states on upgrade.
  - Added a fallback regex to read API keys from both `komvos` and `neuralflow` inside the keyring to preserve user API keys seamlessly.
- **Packaging:**
  - Cleaned up build scripts and removed duplicate PyInstaller specs.
  - Updated `electron-builder.yml` and `package.json` with the new appID (`com.komvos.desktop`) and author metadata.
  - Updated `.github/workflows` to build using the `komvos_backend` executable.
- **Documentation:**
  - Added a `CONTRIBUTING.md` file enforcing the agent workflow (`AGENT.md`).
  - Restructured `README.md` to include "Use your pipeline as an API" and "Access Control" sections.

### Validation Results:

- **Backend tests:** 354 passed cleanly using `pytest`.
- **Frontend tests:** 62 passed cleanly.
- **Linters:** `ruff` and `mypy --strict` pass across the backend codebase. `npm run lint` and `npm run typecheck` pass across the frontend.

### Post-Phase Fixes:
- **Electron Shell Launch:** Fixed a bug in `apps/desktop/src/main.ts` where the Electron desktop shell was trying to spawn the old `neuralflow` backend process instead of the newly renamed `komvos` module. The desktop application now successfully connects to the backend.

All Phase 4 and Phase 5 goals have been fully achieved!
