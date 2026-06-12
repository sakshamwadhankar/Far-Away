# backend/tests

**Owner: P1 + P2 (shared test suite)**

## Purpose

All backend pytest tests. The test suite must be runnable in CI **without any
GPU, real API keys, or running Ollama instance**. Tests that require real
credentials must be decorated with a skip condition.

## Conventions

- **Mock/fake code lives here only.** `MockEndpoint` is a clearly-named test
  helper — never imported by production code (AGENT.md rule 1).
- Tests that hit real providers must be marked `@pytest.mark.live` and skipped
  by default: `pytest -k "not live"`.
- Every module in `neuralflow/` must have a corresponding `test_<module>.py`
  here before Phase merge.

## How to run

```bash
# All tests (requires no live services)
pytest

# Skip live / integration tests
pytest -k "not live"

# With coverage report
pytest --cov=neuralflow --cov-report=term-missing

# Lint before commit
ruff check ../neuralflow
black --check ../neuralflow
mypy ../neuralflow
```

## Test ownership

| File pattern | Owner |
| :--- | :--- |
| `test_schema*.py`, `test_compiler*.py`, `test_scheduler*.py`, `test_state*.py` | P1 |
| `test_endpoint*.py`, `test_executor*.py`, `test_api*.py` | P2 |
| Integration tests (`test_integration_*.py`) | P1 + P2 jointly |
