"""
backend/tests/test_compiler_fuzz.py

Fuzz tests for the pipeline compiler to ensure that malformed inputs
always result in PipelineValidationErrors and never crash the process.
"""

from __future__ import annotations

import copy
import random
from typing import Any

import pytest

from neuralflow.compiler.dag import compile
from neuralflow.compiler.validation import PipelineValidationErrors
from tests.test_compiler import VALID_WITH_LOOP


def mutate_pipeline(pipeline: dict[str, Any]) -> dict[str, Any]:
    """Apply a random mutation to a valid pipeline document."""
    mutated = copy.deepcopy(pipeline)

    mutation_type = random.choice(
        [
            "delete_field",
            "wrong_type",
            "duplicate_node_id",
            "empty_graph",
            "dangling_edge",
            "add_cycle",
            "bad_loop_body",
        ]
    )

    if mutation_type == "delete_field":
        # Randomly delete a required top-level field
        field = random.choice(
            ["schema_version", "id", "name", "nodes", "edges", "endpoints"]
        )
        mutated.pop(field, None)

    elif mutation_type == "wrong_type":
        # Change a field to an invalid type
        if "nodes" in mutated and len(mutated["nodes"]) > 0:
            mutated["nodes"][0]["type"] = 12345  # should be a string literal

    elif mutation_type == "duplicate_node_id":
        if "nodes" in mutated and len(mutated["nodes"]) > 0:
            node_copy = copy.deepcopy(mutated["nodes"][0])
            mutated["nodes"].append(node_copy)

    elif mutation_type == "empty_graph":
        mutated["nodes"] = []

    elif mutation_type == "dangling_edge":
        if "edges" not in mutated:
            mutated["edges"] = []
        mutated["edges"].append(
            {"from": "nonexistent.output", "to": "alsononexistent.input"}
        )

    elif mutation_type == "add_cycle":
        if "edges" not in mutated:
            mutated["edges"] = []
        # Find some nodes to create a cycle
        if len(mutated.get("nodes", [])) >= 2:
            n1 = mutated["nodes"][0]["id"]
            n2 = mutated["nodes"][1]["id"]
            mutated["edges"].append({"from": f"{n1}.out", "to": f"{n2}.in"})
            mutated["edges"].append({"from": f"{n2}.out", "to": f"{n1}.in"})

    elif mutation_type == "bad_loop_body":
        if "loops" in mutated and len(mutated["loops"]) > 0:
            mutated["loops"][0]["body"].append("garbage_node_id")

    return mutated


def with_random_access_node(pipeline: dict[str, Any]) -> dict[str, Any]:
    """
    Insert an access node with a randomly-shaped policy, wired to a random
    node via a scope edge.

    The policy is deliberately allowed to be nonsense — unknown providers,
    negative ceilings, malformed domain lists — so the fuzz run exercises the
    access path the same way it exercises everything else.
    """
    mutated = copy.deepcopy(pipeline)
    node_ids = [n["id"] for n in mutated.get("nodes", []) if isinstance(n, dict)]
    if not node_ids:
        return mutated

    policy: dict[str, Any] = {
        "providers": random.sample(
            ["openai", "anthropic", "google", "ollama", "mock", "not_a_provider"],
            k=random.randint(0, 3),
        ),
        "allow_local_models": random.choice([True, False]),
        "allow_network": random.choice([True, False]),
        "allowed_domains": random.choice([[], ["example.com"], ["a.com", "b.com"]]),
        "max_cost_usd": random.choice([None, 0.0, 1.5, -1.0]),
        "max_tokens": random.choice([None, 1, 4096, 0]),
    }

    gate_id = f"fuzz-gate-{random.randint(0, 999)}"
    mutated["nodes"].append(
        {"id": gate_id, "type": "access", "config": {"access_policy": policy}}
    )
    # Half the time use the correct reserved port, half the time something
    # else, so both the accepted and rejected wiring shapes get exercised.
    port = random.choice(["scope", "data", "prompt"])
    mutated.setdefault("edges", []).append(
        {"from": f"{gate_id}.{port}", "to": f"{random.choice(node_ids)}.prompt"}
    )
    return mutated


@pytest.mark.parametrize("seed", range(50))
def test_compiler_fuzz_never_crashes(seed: int) -> None:
    """
    Apply random mutations to a valid pipeline and attempt to compile it.
    The compiler must either succeed (if the mutation was harmless) or
    raise PipelineValidationErrors. It must NEVER raise KeyError, AttributeError, etc.
    """
    random.seed(seed)
    mutated_json = mutate_pipeline(VALID_WITH_LOOP)

    try:
        compile(mutated_json)
    except PipelineValidationErrors:
        # Expected behavior: caught validation errors
        pass
    except Exception as e:
        # We must not see standard Python exceptions leaking
        pytest.fail(
            f"Compiler crashed with an unhandled exception: {type(e).__name__}: {e}"
        )


@pytest.mark.parametrize("seed", range(50))
@pytest.mark.parametrize("mode", ["local", "served"])
def test_compiler_fuzz_with_access_nodes_never_crashes(seed: int, mode: str) -> None:
    """
    Same guarantee with access nodes in the mix, in both compile modes.

    The access path walks ancestors and intersects policies, so a malformed
    graph must not be able to reach it with a partially-built adjacency map or
    a missing node id.
    """
    random.seed(seed)
    mutated_json = with_random_access_node(mutate_pipeline(VALID_WITH_LOOP))

    try:
        compile(mutated_json, mode=mode)  # type: ignore[arg-type]
    except PipelineValidationErrors:
        pass
    except Exception as e:
        pytest.fail(
            f"Compiler crashed with an unhandled exception: {type(e).__name__}: {e}"
        )


@pytest.mark.parametrize("seed", range(25))
def test_access_policies_are_complete_and_never_widen(seed: int) -> None:
    """
    Whenever a fuzzed pipeline does compile, two invariants must hold:

      1. every node has an effective policy, and
      2. a governed node's grants are a subset of every governing gate's — the
         intersection rule can only ever take capabilities away.
    """
    random.seed(seed)
    candidate = with_random_access_node(copy.deepcopy(VALID_WITH_LOOP))

    try:
        dag = compile(candidate)
    except PipelineValidationErrors:
        return  # Nothing to assert about a pipeline that did not compile.

    node_ids = {n.id for n in dag.pipeline.nodes}
    assert set(dag.effective_policies) == node_ids
    assert set(dag.policy_sources) == node_ids

    gates = {
        n.id: n.config.access_policy
        for n in dag.pipeline.nodes
        if n.type == "access" and n.config and n.config.access_policy
    }

    for node_id, source_ids in dag.policy_sources.items():
        effective = dag.effective_policies[node_id]
        for gate_id in source_ids:
            granted = gates[gate_id]
            assert set(effective.providers) <= set(granted.providers)
            assert effective.allow_local_models <= granted.allow_local_models
            assert effective.allow_network <= granted.allow_network
