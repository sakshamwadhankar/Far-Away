"""
backend/komvos/serve/models.py

Pydantic models for a deployment, plus the request/response mapping rules
that turn a pipeline's input/output nodes into an HTTP contract.

BREAKING CHANGE: Deployment / DeploymentSummary are a shared contract with the
desktop UI (DeployModal.tsx). Announce before modifying field names or types.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from komvos.compiler.models import Pipeline

# ---------------------------------------------------------------------------
# Deployment record
# ---------------------------------------------------------------------------


class Deployment(BaseModel):
    """
    A deployed pipeline.

    Persisted shape (serve/store.py). NEVER carries the plaintext key — only
    `key_hash`. `chat_input_node` / `chat_output_node` are resolved once, at
    deploy time, by `resolve_chat_io` below; a deployment that failed to
    resolve them unambiguously is never created (see 3.3 mapping rules).

    `profile_name` snapshots the governance profile in force when the
    deployment was created; every request to the deployment uses THAT
    profile, never whatever is active on the desktop right now.
    """

    id: str
    name: str
    pipeline: dict[str, Any]
    key_hash: str
    expose_lan: bool = False
    rate_limit_per_minute: int = Field(default=60, ge=1)
    chat_input_node: str
    chat_output_node: str
    created_at: int
    request_count: int = 0
    error_count: int = 0
    last_request_at: int | None = None
    profile_name: str = "locked"
    spend_cap_usd_per_request: float | None = Field(
        default=None,
        ge=0.0,
        description="Per-request USD spending ceiling for this deployment.",
    )
    """
    Profile in force for this deployment. Rows from before Gov-2 predate the
    column and load as 'locked' (LOCKED), which reproduces exactly the
    behaviour those deployments had before profiles existed: the pipeline's
    own policy decides, nothing loosens.
    """


class DeploymentCreateRequest(BaseModel):
    """Request body for POST /deployments."""

    pipeline: dict[str, Any] = Field(
        description="Pipeline schema v2.1 JSON object. Must contain an access "
        "node reachable from every node it exposes — compiled with "
        "mode='served', which refuses a pipeline with none."
    )
    name: str | None = Field(
        default=None, description="Display name. Defaults to the pipeline's own name."
    )
    expose_lan: bool = Field(
        default=False,
        description=(
            "Opt-in to accepting requests from outside 127.0.0.1. Never the "
            "default — the UI must show an explicit confirmation naming the "
            "risk before setting this true."
        ),
    )
    rate_limit_per_minute: int = Field(default=60, ge=1, le=6000)
    spend_cap_usd_per_request: float | None = Field(
        default=None, ge=0.0, description="Per-request USD spend ceiling."
    )


class DeploymentCreateResponse(BaseModel):
    """
    Response body for POST /deployments.

    `key` is plaintext and shown exactly once — it is never retrievable again
    after this response. GET /deployments never includes it.
    """

    deployment_id: str
    key: str
    base_url: str
    warning: str = (
        "This key is shown only once. Store it now — it cannot be retrieved again."
    )


class DeploymentSummary(BaseModel):
    """A deployment as listed/detailed. Never carries key material."""

    id: str
    name: str
    expose_lan: bool
    rate_limit_per_minute: int
    chat_input_node: str
    chat_output_node: str
    created_at: int
    request_count: int
    error_count: int
    last_request_at: int | None
    profile_name: str = "locked"
    spend_cap_usd_per_request: float | None = None


class DeploymentListResponse(BaseModel):
    deployments: list[DeploymentSummary]


class RotateKeyResponse(BaseModel):
    """POST /deployments/{id}/rotate-key response. Same one-time rule as creation."""

    deployment_id: str
    key: str
    warning: str = (
        "This key is shown only once. The previous key stops working immediately."
    )


class UndeployResponse(BaseModel):
    deployment_id: str
    deleted: bool


# ---------------------------------------------------------------------------
# Chat-completions I/O mapping (3.3)
# ---------------------------------------------------------------------------


class DeploymentMappingError(Exception):
    """
    Raised when a pipeline's input/output nodes don't unambiguously resolve
    to a single chat-completions input and output node.

    Deployment fails outright rather than guessing — see resolve_chat_io.
    """


def resolve_chat_io(pipeline: Pipeline) -> tuple[str, str]:
    """
    Determine which input node feeds `messages` and which output node
    produces `content` for the OpenAI-compatible chat-completions path.

    Rules (upgrade.md 3.3):
      - Input: the node explicitly marked config.api_field == "messages", or
        the sole input node if there is exactly one.
      - Output: the node explicitly marked config.api_field == "content", or
        the sole EXPOSED output node (api_expose defaults to True) if there is
        exactly one.
      - Anything else is ambiguous: multiple candidates and none designated.
        Raises DeploymentMappingError naming every candidate rather than
        guessing.

    Returns (input_node_id, output_node_id).
    """
    input_nodes = [n for n in pipeline.nodes if n.type == "input"]
    output_nodes = [n for n in pipeline.nodes if n.type == "output"]

    tagged_inputs = [n for n in input_nodes if _api_field(n) == "messages"]
    if len(tagged_inputs) == 1:
        input_id = tagged_inputs[0].id
    elif len(tagged_inputs) > 1:
        raise DeploymentMappingError(
            "Ambiguous chat input: more than one input node has "
            f"config.api_field='messages': {_ids(tagged_inputs)}. "
            "Only one node may claim 'messages'."
        )
    elif len(input_nodes) == 1:
        input_id = input_nodes[0].id
    elif len(input_nodes) == 0:
        raise DeploymentMappingError(
            "Pipeline has no input node to receive 'messages'."
        )
    else:
        raise DeploymentMappingError(
            "Ambiguous chat input: this pipeline has "
            f"{len(input_nodes)} input nodes ({_ids(input_nodes)}) and none is "
            "marked config.api_field='messages'. Mark exactly one, or reduce "
            "the pipeline to a single input node."
        )

    exposed_outputs = [n for n in output_nodes if _api_expose(n)]
    tagged_outputs = [n for n in exposed_outputs if _api_field(n) == "content"]
    if len(tagged_outputs) == 1:
        output_id = tagged_outputs[0].id
    elif len(tagged_outputs) > 1:
        raise DeploymentMappingError(
            "Ambiguous chat output: more than one output node has "
            f"config.api_field='content': {_ids(tagged_outputs)}. "
            "Only one node may claim 'content'."
        )
    elif len(exposed_outputs) == 1:
        output_id = exposed_outputs[0].id
    elif len(exposed_outputs) == 0:
        raise DeploymentMappingError(
            "Pipeline has no exposed output node (api_expose=False on all of "
            "them, or no output nodes at all) to produce 'content'."
        )
    else:
        raise DeploymentMappingError(
            "Ambiguous chat output: this pipeline has "
            f"{len(exposed_outputs)} exposed output nodes ({_ids(exposed_outputs)}) "
            "and none is marked config.api_field='content'. Mark exactly one, "
            "set api_expose=False on the others, or reduce to a single "
            "exposed output node."
        )

    return input_id, output_id


def native_input_fields(pipeline: Pipeline) -> dict[str, str]:
    """
    node_id -> request field name for the native run path (3.3, native).

    Every input node participates; a node without an explicit api_field is
    keyed by its own node id, so the native path works without requiring any
    configuration.
    """
    return {n.id: (_api_field(n) or n.id) for n in pipeline.nodes if n.type == "input"}


def native_output_fields(pipeline: Pipeline) -> dict[str, str]:
    """node_id -> response field name for every EXPOSED output node."""
    return {
        n.id: (_api_field(n) or n.id)
        for n in pipeline.nodes
        if n.type == "output" and _api_expose(n)
    }


def _api_field(node: Any) -> str | None:
    return node.config.api_field if node.config else None


def _api_expose(node: Any) -> bool:
    return bool(node.config.api_expose) if node.config else True


def _ids(nodes: list[Any]) -> str:
    return ", ".join(f"'{n.id}'" for n in nodes)


# ---------------------------------------------------------------------------
# OpenAI-compatible wire types
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ChatCompletionRequest(BaseModel):
    """
    POST /v1/chat/completions request body.

    `model` conventionally carries the deployment id. Unrecognized OpenAI
    parameters (temperature, top_p, tools, ...) are accepted and ignored
    rather than rejected, so existing client configs don't need editing to
    point at Komvos.
    """

    model_config = {"extra": "ignore"}

    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False


class NativeRunResponse(BaseModel):
    """POST /v1/deployments/{id}/run response body."""

    outputs: dict[str, Any]
