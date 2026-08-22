"""
backend/komvos/governance/__init__.py

The governance package: decision records, sinks, and egress enforcement.
"""

from komvos.governance.context import (
    bind_run_context,
    current_run_id,
    current_sink,
    record_decision,
    run_context,
    unbind_run_context,
)
from komvos.governance.decisions import (
    DecisionOrigin,
    DecisionOutcome,
    GovernanceDecision,
    GovernanceDomain,
)
from komvos.governance.egress import (
    check_egress,
    endpoint_egress_host,
    enforce_egress_for_endpoint,
    host_allowed,
    is_loopback,
    url_host,
)
from komvos.governance.sinks import DecisionSink, InMemoryDecisionSink

__all__ = [
    "DecisionOrigin",
    "DecisionOutcome",
    "DecisionSink",
    "GovernanceDecision",
    "GovernanceDomain",
    "InMemoryDecisionSink",
    "bind_run_context",
    "check_egress",
    "current_run_id",
    "current_sink",
    "enforce_egress_for_endpoint",
    "endpoint_egress_host",
    "host_allowed",
    "is_loopback",
    "record_decision",
    "run_context",
    "unbind_run_context",
    "url_host",
]
