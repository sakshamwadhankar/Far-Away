"""
backend/neuralflow/scheduler/stop_eval.py

Safe structured stop_when evaluator — NO eval(), NO exec(), NO code execution.

Resolves a StopCondition's dot-path field against execution state, then
applies the structured comparison operator. This is the ONLY place where
stop_when conditions are evaluated at runtime.

Supported ops (TRD §4 rule 4): ==  !=  >  <  >=  <=  contains
"""

from __future__ import annotations

import json
from typing import Any

from neuralflow.compiler.models import (
    StopCondition,
    StopOp,
    StopValue,
)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class StopFieldResolutionError(Exception):
    """Raised when the dot-path field cannot be resolved in the execution state."""


class StopConditionTypeError(Exception):
    """Raised when the resolved field value is incompatible with the operator."""


# ---------------------------------------------------------------------------
# Field resolution
# ---------------------------------------------------------------------------


def _resolve_field(field_path: str, state: dict[str, dict[str, Any]]) -> Any:
    """
    Resolve a dot-path field like "verify.output.verified" against state.

    Path segments:
      - segment[0]: node_id → look up in state dict
      - segment[1]: port_name → look up in that node's outputs
      - segment[2:]: dict key traversal (for JSON output values)

    The state dict has shape: { node_id: { port_name: value, ... }, ... }
    For JSON ports, the value may be a dict or a JSON string that gets parsed.
    """
    parts = field_path.split(".")
    if len(parts) < 2:
        raise StopFieldResolutionError(
            f"Field path '{field_path}' must have at least 2 segments "
            "(node_id.port_name)."
        )

    node_id = parts[0]
    port_name = parts[1]
    remaining = parts[2:]

    if node_id not in state:
        raise StopFieldResolutionError(
            f"Node '{node_id}' not found in execution state. "
            f"Available nodes: {list(state.keys())}."
        )

    node_outputs = state[node_id]
    if port_name not in node_outputs:
        raise StopFieldResolutionError(
            f"Port '{port_name}' not found in node '{node_id}' outputs. "
            f"Available ports: {list(node_outputs.keys())}."
        )

    value = node_outputs[port_name]

    # If the value is a JSON string and we need to traverse deeper, parse it
    if remaining and isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError) as exc:
            raise StopFieldResolutionError(
                f"Cannot parse JSON from port '{node_id}.{port_name}' "
                f"for deeper field traversal: {exc}"
            ) from exc

    # Traverse remaining path segments through nested dicts
    for segment in remaining:
        if not isinstance(value, dict):
            prior = ".".join(
                remaining[: remaining.index(segment)]
            )
            raise StopFieldResolutionError(
                f"Cannot traverse into non-dict value at "
                f"'{node_id}.{port_name}.{prior}'. "
                f"Got {type(value).__name__}, expected dict."
            )
        if segment not in value:
            prior = ".".join(
                remaining[: remaining.index(segment) + 1]
            )
            raise StopFieldResolutionError(
                f"Key '{segment}' not found at path "
                f"'{node_id}.{port_name}.{prior}'. "
                f"Available keys: {list(value.keys())}."
            )
        value = value[segment]

    return value


# ---------------------------------------------------------------------------
# Operator application
# ---------------------------------------------------------------------------


_COMPARE_OPS: dict[StopOp, str] = {
    "==": "eq",
    "!=": "ne",
    ">": "gt",
    "<": "lt",
    ">=": "ge",
    "<=": "le",
    "contains": "contains",
}


def _apply_op(op: StopOp, resolved: Any, target: StopValue) -> bool:
    """
    Apply a structured comparison operator.

    Type coercion: if the resolved value and target have different types
    but are both numeric (int/float), we compare as floats.
    For "contains", we check `target in resolved` (string containment).
    """
    # Coerce booleans from JSON — JSON bool may arrive as Python bool
    # but the target in StopCondition is also bool, so direct compare works.

    if op == "contains":
        if not isinstance(resolved, str):
            raise StopConditionTypeError(
                f"Operator 'contains' requires a string field value, "
                f"got {type(resolved).__name__}."
            )
        if not isinstance(target, str):
            raise StopConditionTypeError(
                f"Operator 'contains' requires a string target value, "
                f"got {type(target).__name__}."
            )
        return target in resolved

    # Numeric coercion for comparison operators
    if isinstance(resolved, bool) or isinstance(target, bool):
        # Don't coerce bools to float — compare directly
        if op == "==":
            return resolved == target
        if op == "!=":
            return resolved != target
        raise StopConditionTypeError(
            f"Cannot apply '{op}' to boolean values. "
            "Use '==' or '!=' for boolean comparisons."
        )

    # Both numeric? Compare as floats.
    if isinstance(resolved, (int, float)) and isinstance(target, (int, float)):
        r_val = float(resolved)
        t_val = float(target)
        if op == "==":
            return r_val == t_val
        if op == "!=":
            return r_val != t_val
        if op == ">":
            return r_val > t_val
        if op == "<":
            return r_val < t_val
        if op == ">=":
            return r_val >= t_val
        if op == "<=":
            return r_val <= t_val

    # String comparison
    if isinstance(resolved, str) and isinstance(target, str):
        if op == "==":
            return resolved == target
        if op == "!=":
            return resolved != target
        # Lexicographic comparison for strings
        if op == ">":
            return resolved > target
        if op == "<":
            return resolved < target
        if op == ">=":
            return resolved >= target
        if op == "<=":
            return resolved <= target

    # Direct equality/inequality for mixed types
    if op == "==":
        return resolved == target
    if op == "!=":
        return resolved != target

    raise StopConditionTypeError(
        f"Cannot apply '{op}' between {type(resolved).__name__} "
        f"and {type(target).__name__}."
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def evaluate_stop_condition(
    condition: StopCondition,
    state: dict[str, dict[str, Any]],
) -> bool:
    """
    Evaluate a structured stop condition against execution state.

    Args:
        condition: The StopCondition from the loop definition.
        state: Execution state as { node_id: { port_name: value } }.

    Returns:
        True if the stop condition is met; False otherwise.

    Raises:
        StopFieldResolutionError: The dot-path field cannot be resolved.
        StopConditionTypeError: The resolved value is incompatible with the op.
    """
    resolved = _resolve_field(condition.field, state)
    return _apply_op(condition.op, resolved, condition.value)
