"""
backend/komvos/governance/__init__.py

The governance package: decision records, sinks, and egress enforcement.
"""

from komvos.governance.context import (
    RunGovernance,
    bind_run_context,
    current_governance,
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
from komvos.governance.profiles import (
    BUILT_IN_PROFILES,
    DEFAULT_PROFILE_NAME,
    GovernanceProfile,
    Posture,
    RetentionMode,
)
from komvos.governance.resolve import ResolvedPolicy, resolve_policy
from komvos.governance.sinks import DecisionSink, InMemoryDecisionSink

__all__ = [
    "BUILT_IN_PROFILES",
    "DEFAULT_PROFILE_NAME",
    "DecisionOrigin",
    "DecisionOutcome",
    "DecisionSink",
    "GovernanceDecision",
    "GovernanceDomain",
    "GovernanceProfile",
    "InMemoryDecisionSink",
    "Posture",
    "ResolvedPolicy",
    "RetentionMode",
    "RunGovernance",
    "bind_run_context",
    "check_egress",
    "current_governance",
    "current_run_id",
    "current_sink",
    "enforce_egress_for_endpoint",
    "endpoint_egress_host",
    "host_allowed",
    "is_loopback",
    "record_decision",
    "resolve_policy",
    "run_context",
    "unbind_run_context",
    "url_host",
]
