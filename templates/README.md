# templates

**Owner: P3 — Desktop UI (Phase 4 delivery)**

## Purpose

First-party pipeline JSON files. Each file must validate against
`shared/pipeline.schema.json` (schema v2) and be immediately importable into
the canvas as a runnable pipeline.

## R0 template list (target: 10–20 files)

| File (planned) | Pattern |
| :--- | :--- |
| `solver_verifier_judge.json` | DeepSeek-style Solver → Verifier → Judge loop |
| `rag_pipeline.json` | Retriever → Generator → Validator |
| `ensemble_voting.json` | N models answer → aggregator selects best |
| `cascade.json` | Cheap/fast model first → escalate on low confidence |
| `self_refinement.json` | Model critiques and revises its own output |
| `multi_perspective.json` | 3 models, 1 aggregator |
| `debate.json` | 2 models argue → 1 adjudicates |

> **This directory is intentionally empty for now.**
> Templates will be authored in Phase 4 once the schema is finalised and the
> canvas can validate imports. No placeholder JSON files will be checked in —
> see AGENT.md rule 2.
