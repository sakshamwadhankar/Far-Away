# Phase 4 Report — Backend durability and provider resilience

Status: **complete, all gates green.** Per standing instruction: **not
committed or pushed** — waiting for explicit go-ahead.

## Entry check (before changes)

- `ruff check .` → All checks passed!
- `mypy komvos` → Success: no issues found in 35 source files
- `pytest -q` → 354 passed, 4 skipped
- desktop typecheck/lint clean; `npm test` → 63 passed

---

## Task 1 — StateManager built once at startup

**Before:** `get_state_manager()` constructed a fresh `StateManager` on every
call (table creation + pragmas + column-migration probe each time) and
re-checked the legacy `~/.neuralflow` directory migration per request.

**Changes:**
- `backend/komvos/api/registry.py:125-181`
  - `build_default_state_manager()` (line 125) holds the DB-dir resolution,
    the one-time legacy migration, and construction.
  - `ensure_default_state_manager()` (line 156) memoizes it in a module-level
    singleton.
  - `get_state_manager()` (line 164) keeps its exact priority order: an
    injected `app.state.state_manager` **test override wins first** (this is
    the path `backend/tests/test_api.py`, `test_serve.py`, `test_templates.py`
    use — verified before changing anything), then the cached default. No test
    needed modification for this task.
- `backend/komvos/api/main.py:127-152` — FastAPI lifespan (`_lifespan`) calls
  `ensure_default_state_manager()` eagerly at startup, so real runs (uvicorn /
  packaged binary) never construct it mid-request. The lazy fallback still
  covers ASGI transports that don't run lifespan events (i.e., the test suite).

Net effect: one StateManager per process, migration exactly once, unchanged
override semantics.

## Task 2 — Timeouts, client reuse, bounded retries

Partitioned-file rules respected: only client construction / timeouts / retry
logic changed in both endpoints; `check_access` and `estimate_cost` untouched;
`scheduler/runner.py` untouched (retries are logged, not surfaced as new
scheduler events — see Disagreements §1).

### Values chosen and why

| Setting | Value | Rationale |
|---|---|---|
| connect timeout | 10 s | Generous for TLS to remote APIs, still fails fast on a dead host. |
| read timeout | 120 s | Applies *between streamed bytes*, not to total generation — caps a stalled provider without killing slow-but-alive long generations. Matches the previous Ollama scalar timeout. |
| write / pool timeouts | 30 s / 10 s | Request bodies are small; pool waits should fail fast into the retry path. |
| retry attempts | 3 total (1 + 2 retries) | Bounded: worst case adds ~4 s of backoff before failing the node. |
| backoff | 0.5 s base, ×2 per attempt, cap 8 s, ±20% jitter | Standard exponential-with-jitter; jitter prevents synchronized retries when several nodes hit a rate limit together. |

### Changes

- `backend/komvos/endpoints/cloud.py`
  - Constants at lines 37-56; `_http_timeout()` (explicit
    connect/read/write/pool `httpx.Timeout`) shared by HTTP-based SDKs.
  - `_CLIENTS` cache (lines 60-79): one SDK client per
    `(provider kind, resolved base URL, API key)` for the process lifetime.
    The key includes the API key so rotating a key in Settings takes effect on
    the next call instead of being silently masked by the cache (slight
    strengthening over "provider + base URL" — noted in §2).
  - `_is_retryable()` (line 83): rate-limit/server-error classification that
    works across SDK error shapes (`status_code` for openai/anthropic,
    `code` for google-genai, plus the stable class names).
  - `_retry_with_backoff()` (line 98): bounded exponential backoff with jitter,
    logging each retry via `logger.warning`.
  - OpenAI family (line ~191) and Anthropic (line ~244): clients built with
    `max_retries=0` so this policy is the single source of truth; stream
    *creation* wrapped in the retry helper. Anthropic enters its stream manager
    manually (`manager.__aenter__`) so the retry boundary sits before any token
    flows — no replayed partial responses.
  - Google genai: client cached with an explicit ms timeout via
    `http_options`; `generate_content_stream` wrapped in the same helper.
- `backend/komvos/endpoints/ollama.py`
  - Same constants (lines 36-46), documented as mirroring cloud.py so local
    and remote providers behave identically under failure.
  - `_get_client()` (line 50): one cached `httpx.AsyncClient` per base URL
    (previously a brand-new client per generate call).
  - `generate()` (lines 118+): stream opening retried on 429/5xx statuses and
    `httpx.TransportError` with the same backoff/jitter; response always
    closed (`finally`). Health check reuses the cached client with a 2 s
    per-request timeout, preserving prior behaviour.

### Tests

New `backend/tests/test_provider_resilience.py` (14 tests):
- retry classification (429/5xx retryable; 400/401 not; genai `code` shape;
  plain exceptions never retried);
- backoff succeeds after transient 429s, delays increase and respect the cap;
  gives up after the attempt cap; never backs off for non-retryable errors
  (`asyncio.sleep` monkeypatched — no real waiting);
- cloud client cache identity (same provider/base/key reused; different base
  URL or rotated key builds anew);
- ollama client cached per base URL with the explicit timeouts asserted on the
  live `httpx.Timeout`;
- a mock-endpoint pipeline run through `/pipelines/run` completing end-to-end,
  proving execution behaviour is unchanged by the refactor.

## Task 3 — Non-blocking, rotating backend log

`apps/desktop/src/main.ts:55-100`:
- `fs.appendFileSync` replaced by async `fs.appendFile` callbacks, serialized
  through a promise chain (`logChain`, line 61) so rotation and writes can
  never interleave and the main process event loop is never blocked on disk
  during a streaming run.
- Size-based rotation (lines 58-78): active file rotates at 5 MB
  (`LOG_MAX_BYTES`); up to 3 older generations are kept as
  `komvos_backend_spawn.log.1` … `.log.3` (shift-and-rename). Content is not
  lost — the Phase 3 error path still points users at
  `komvos_backend_spawn.log`, which now stays small and readable.
- No new dependency added: plain `node:fs` callback APIs suffice.

---

## Definition of Done — verbatim output

### `cd backend && ruff check .`
```
All checks passed!
```

### `cd backend && mypy komvos`
```
Success: no issues found in 35 source files
```

### `cd backend && pytest -q`
```
368 passed, 4 skipped, 5 warnings in 11.25s
```

(354 prior + 14 new resilience tests.)

### `cd apps/desktop && npm run typecheck && npm run lint`
```
> tsc --noEmit            (clean)
> eslint src --ext ts,tsx --report-unused-disable-directives --max-warnings 0   (clean)
```

### `cd apps/desktop && npm test`
```
 Test Files  7 passed (7)
      Tests  63 passed (63)
```

### App launches and runs a pipeline — how verified
1. **Real launch:** `npm run build`, then started actual Electron
   (`npx electron .`). `%APPDATA%\komvos\komvos_backend_spawn.log` shows the
   lifespan-driven startup ("Application startup complete"), random-port
   backend ready, renderer CORS preflights and authenticated calls
   (`OPTIONS /models → 200`, `GET /models`, `/custom-nodes`,
   `/pipelines/templates` → all 200), written through the new async log path.
2. **Pipeline execution:** rebuilt the PyInstaller binary from current source
   and ran the Phase-2 smoke harness against it:
   ```
   Launching ...\packaging\dist\komvos_backend.exe on 127.0.0.1:62845
   Backend healthy on 127.0.0.1:62845
   Started run dc309b71-8634-4723-88e8-432fc32fb656
   Run completed (3 node executions recorded)
   Smoke test passed.
   EXITCODE=0
   ```
   This drives a full mock pipeline (auth → run → trace polling → completed
   status) through the exact binary Electron ships, now including the
   lifespan-built StateManager and the refactored endpoints.

## Incomplete items / disagreements

1. **Retry visibility (per NOTE).** Retries are logged (`logger.warning`) but
   not surfaced as scheduler/UI events, because `scheduler/runner.py` is
   hands-off and the brief forbids adding a scheduler event this phase.
   Surfacing them in the UI is left to the other workstream.
2. **Cache key includes the API key** (not just provider + base URL as the
   brief phrased it). Without it, rotating a key in Settings would leave the
   cached client using the old credential until process restart. I judge this
   the intent of "cache one client per provider and base URL" done safely;
   recorded here rather than silently substituted.
3. **Log flush on quit.** Log writes are queued asynchronously; if the user
   quits within milliseconds of a line being enqueued, that last line may be
   lost to process exit. All meaningful lifecycle lines (spawn, ready, errors)
   are written well before quit in practice; a synchronous shutdown flush was
   deliberately avoided because blocking I/O at quit is what Phase 3's
   guidance implies we should not reintroduce.
