# Contributing to Komvos

Welcome to the Komvos repository! Since this project involves agent-assisted development, we have specific workflows and rules that all contributors—both human and AI—must follow.

## The Agent Workflow

This repository relies heavily on AI coding agents (such as Claude, Cursor, or the Antigravity Agent). 

When working on this repository, **you must read and adhere to the guidelines specified in [`AGENT.md`](./AGENT.md)**. 

### Key Principles from `AGENT.md`

1. **No Mock or Fake Data**: Do not use placeholder data in application code. All mock data belongs strictly in test files.
2. **No Silent Placeholders**: Do not stub functions with `return True` or `pass`. If something is incomplete, raise an explicit error (e.g., `NotImplementedError`) and report it.
3. **No Secrets in Code**: API keys and secrets must be retrieved securely from the OS keychain via `keyring`. Never hardcode them.
4. **Use Official SDKs**: Do not invent APIs or SDK methods. 
5. **Honor Contracts**: Shared interfaces, especially the frontend-backend contract (like `shared/pipeline.schema.json`), require explicit flagging of any BREAKING CHANGES in commit messages.
6. **Strict Typing**: All Python code must pass `mypy --strict`. All TypeScript code must be strictly typed without using `any`.
7. **Comprehensive Testing**: Every feature must ship with a corresponding test, and all linters and tests must pass cleanly.

Before opening a Pull Request, ensure that your changes pass all CI gates locally:

**Backend:**
```bash
ruff check .
mypy komvos
pytest -q --cov=komvos
```

**Frontend:**
```bash
npm run typecheck
npm run lint
npm run test
```

We appreciate your contributions!
