"""
backend/neuralflow/executors/__init__.py

Registry for all node executors.
"""

from neuralflow.executors.base import BaseExecutor, ExecutorContext
from neuralflow.executors.input_output import InputExecutor, OutputExecutor
from neuralflow.executors.logic import (
    CompareExecutor,
    JudgeExecutor,
    RouterExecutor,
    TransformExecutor,
)
from neuralflow.executors.model import ModelExecutor

EXECUTOR_REGISTRY: dict[str, type[BaseExecutor]] = {
    "input": InputExecutor,
    "output": OutputExecutor,
    "model": ModelExecutor,
    "judge": JudgeExecutor,
    "router": RouterExecutor,
    "transform": TransformExecutor,
    "compare": CompareExecutor,
}

__all__ = ["EXECUTOR_REGISTRY", "BaseExecutor", "ExecutorContext"]
