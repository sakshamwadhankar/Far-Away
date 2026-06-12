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
    
    mutation_type = random.choice([
        "delete_field",
        "wrong_type",
        "duplicate_node_id",
        "empty_graph",
        "dangling_edge",
        "add_cycle",
        "bad_loop_body",
    ])
    
    if mutation_type == "delete_field":
        # Randomly delete a required top-level field
        field = random.choice(["schema_version", "id", "name", "nodes", "edges", "endpoints"])
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
        mutated["edges"].append({"from": "nonexistent.output", "to": "alsononexistent.input"})
        
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
        pytest.fail(f"Compiler crashed with an unhandled exception: {type(e).__name__}: {e}")
