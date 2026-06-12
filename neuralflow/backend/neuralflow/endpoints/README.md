# neuralflow/endpoints

**Owner: P2 — Endpoints & API**

## Purpose

Concrete implementations of the `ModelEndpoint` Protocol (defined by P1 in
`base.py`, coming in Phase 1). Every model backend — cloud or local — implements
exactly one interface, making the scheduler endpoint-agnostic.

## R0 implementations

| Class | Kind | Notes |
| :--- | :--- | :--- |
| `CloudEndpoint` | `openai \| anthropic \| google \| openai_compatible` | Uses official SDKs / httpx. Reads keys from OS keychain via `keyring`. |
| `OllamaEndpoint` (Phase 4) | `ollama` | Single-machine local model via Ollama's OpenAI-compatible API. |

**R1 (future):** `ExoEndpoint` will be added here — the scheduler needs zero
changes.

## API key handling

Keys are **never** hardcoded, never in env vars, and never in config files.
They are read at runtime from the OS keychain using the `keyring` library:

```python
import keyring
api_key = keyring.get_password("neuralflow", "openai")  # example
```

If a key is not present in the keychain, the endpoint must raise a clear,
named error — **never** fall back to a dummy/empty key.

## Phase (roadmap.md)

- **Phase 1:** `ModelEndpoint` Protocol + `base.py` types (P1 delivers); `CloudEndpoint` skeleton (P2).
- **Phase 2:** `CloudEndpoint` full implementation (generate, health, capabilities, estimate_cost).
- **Phase 4:** `OllamaEndpoint` + dynamic provider model-list fetch.
