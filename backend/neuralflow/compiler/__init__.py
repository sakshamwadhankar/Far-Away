"""
backend/neuralflow/compiler/__init__.py

Public API for the compiler module.
"""

from neuralflow.compiler.dag import CompiledDAG, compile
from neuralflow.compiler.models import (
    Edge,
    EndpointDescriptor,
    EndpointKind,
    Loop,
    Node,
    NodeConfig,
    NodeType,
    OnMax,
    Pipeline,
    Port,
    PortType,
    StopCondition,
    StopOp,
    StopValue,
)
from neuralflow.compiler.validation import (
    PipelineValidationError,
    PipelineValidationErrors,
    validate_pipeline,
)

__all__ = [
    # DAG
    "CompiledDAG",
    "compile",
    # Models
    "Edge",
    "EndpointDescriptor",
    "EndpointKind",
    "Loop",
    "Node",
    "NodeConfig",
    "NodeType",
    "OnMax",
    "Pipeline",
    "Port",
    "PortType",
    "StopCondition",
    "StopOp",
    "StopValue",
    # Validation
    "PipelineValidationError",
    "PipelineValidationErrors",
    "validate_pipeline",
]
