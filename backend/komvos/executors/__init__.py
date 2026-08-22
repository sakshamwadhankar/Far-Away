"""
backend/komvos/executors/__init__.py

Registry for all node executors.
"""

from komvos.executors.access import AccessExecutor
from komvos.executors.base import BaseExecutor, ExecutorContext
from komvos.executors.input_output import InputExecutor, OutputExecutor
from komvos.executors.logic import (
    CompareExecutor,
    JudgeExecutor,
    RouterExecutor,
    TransformExecutor,
)
from komvos.executors.model import ModelExecutor

EXECUTOR_REGISTRY: dict[str, type[BaseExecutor]] = {
    "input": InputExecutor,
    "output": OutputExecutor,
    "model": ModelExecutor,
    "judge": JudgeExecutor,
    "router": RouterExecutor,
    "transform": TransformExecutor,
    "compare": CompareExecutor,
    "access": AccessExecutor,
}

__all__ = ["EXECUTOR_REGISTRY", "BaseExecutor", "ExecutorContext"]
