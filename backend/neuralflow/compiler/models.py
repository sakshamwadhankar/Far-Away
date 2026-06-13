"""
backend/neuralflow/compiler/models.py

Pydantic v2 models for NeuralFlow pipeline schema v2.

These models MUST stay in sync with:
  - shared/pipeline.schema.json
  - shared/types.ts

BREAKING CHANGE: any modification to these models is a contract change.
Announce before P2 or P3 proceed.

No application logic here — pure data models and field-level validation only.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Port
# ---------------------------------------------------------------------------

PortType = Literal["text", "number", "boolean", "json", "image", "audio"]


class Port(BaseModel):
    """Typed input or output port on a node."""

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, description="Port identifier, unique within the node's port list.")
    type: PortType


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

NodeType = Literal["input", "output", "model", "loop", "judge", "router", "transform", "compare"]


class NodeConfig(BaseModel):
    """Per-node configuration parameters. All fields optional."""

    model_config = {"extra": "forbid"}

    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    response_format: Literal["text", "json"] | None = None
    system_prompt: str | None = None
    role: str | None = None
    routing_map: dict[str, str] | None = None
    score_field: str | None = Field(default="score")
    strategy: Literal["max_numeric", "truthy"] | None = Field(default="max_numeric")
    default_value: str | None = None
    label: str | None = None


class Node(BaseModel):
    """A single node in the pipeline graph."""

    model_config = {"extra": "forbid"}

    id: str = Field(min_length=1, description="Unique node identifier within this pipeline.")
    type: NodeType
    endpoint_ref: str | None = Field(
        default=None,
        description=(
            "Key into the top-level endpoints map. "
            "Required for 'model' nodes, must be absent on others. "
            "No secrets stored here — resolved at runtime from OS keychain."
        ),
    )
    role: str | None = Field(
        default=None,
        description="Semantic role hint (e.g. 'solver', 'verifier'). Informational only.",
    )
    config: NodeConfig | None = None
    inputs: list[Port] = Field(default_factory=list)
    outputs: list[Port] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_model_node_endpoint(self) -> "Node":
        if self.type == "model" and not self.endpoint_ref:
            raise ValueError(f"[Missing Endpoint] Node '{self.id}' of type 'model' must define an 'endpoint_ref'.")
        if self.type != "model" and self.endpoint_ref is not None:
            raise ValueError(
                f"[Invalid Endpoint] Only 'model' nodes may have 'endpoint_ref'; node '{self.id}' has type '{self.type}'."
            )
        return self


# ---------------------------------------------------------------------------
# StopCondition / Loop
# ---------------------------------------------------------------------------

StopOp = Literal["==", "!=", ">", "<", ">=", "<=", "contains"]

# Scalar value: string, number, or boolean — no raw code / eval.
StopValue = Union[str, float, bool]


class StopCondition(BaseModel):
    """
    Structured loop stop condition.
    NO raw code or eval is permitted — the scheduler evaluates this deterministically.
    Supported ops: ==  !=  >  <  >=  <=  contains
    """

    model_config = {"extra": "forbid"}

    field: Annotated[str, Field(min_length=1, description="Dot-path to the field, e.g. 'verify.output.verified'.")]
    op: StopOp
    value: StopValue


OnMax = Literal["return_best", "return_last", "fail"]


class Loop(BaseModel):
    """
    A bounded loop subgraph.
    max_iterations is a hard kill-switch enforced by the scheduler.
    No back-edges in the main graph — loops are subgraphs.
    """

    model_config = {"extra": "forbid"}

    id: str = Field(min_length=1)
    body: list[str] = Field(min_length=1, description="Ordered node IDs forming the loop body.")
    max_iterations: int = Field(ge=1, le=100, description="Hard upper bound. No infinite loops.")
    stop_when: StopCondition
    on_max: OnMax


# ---------------------------------------------------------------------------
# Edge
# ---------------------------------------------------------------------------

_EDGE_PATTERN = r"^[^.]+\.[^.]+$"


class Edge(BaseModel):
    """
    Directed edge between node ports.
    Both 'from' and 'to' must be in 'nodeId.portName' format.
    Port-type compatibility is enforced by the compiler, not here.
    """

    model_config = {"extra": "forbid"}

    from_: str = Field(alias="from", pattern=_EDGE_PATTERN)
    to: str = Field(pattern=_EDGE_PATTERN)

    model_config = {"extra": "forbid", "populate_by_name": True}

    def source_node(self) -> str:
        return self.from_.split(".")[0]

    def source_port(self) -> str:
        return self.from_.split(".")[1]

    def target_node(self) -> str:
        return self.to.split(".")[0]

    def target_port(self) -> str:
        return self.to.split(".")[1]


# ---------------------------------------------------------------------------
# EndpointDescriptor
# ---------------------------------------------------------------------------

# TODO(R0 Polish Phase): Keep "mock" out of the production schema entirely
# and inject it dynamically in the test environment to avoid schema pollution.
EndpointKind = Literal["openai", "anthropic", "google", "openai_compatible", "ollama", "mock"]


class EndpointDescriptor(BaseModel):
    """
    Endpoint descriptor stored in the pipeline file.
    NO API keys, credentials, or device pins.
    Keys are resolved at runtime from the OS keychain via `keyring`.
    """

    model_config = {"extra": "forbid"}

    kind: EndpointKind
    base_url: str | None = Field(
        default=None,
        description="Optional override base URL for openai_compatible or ollama.",
    )
    model: str | None = Field(default=None, description="Default model name for this endpoint ref.")


# ---------------------------------------------------------------------------
# Pipeline (top-level document)
# ---------------------------------------------------------------------------


class Pipeline(BaseModel):
    """
    Top-level NeuralFlow pipeline document (schema v2).

    Structural validation (field types, required fields, enum constraints) is
    handled here. Semantic validation (acyclicity, port-type compatibility,
    endpoint_ref resolution) is enforced by the compiler in a subsequent pass.
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    schema_version: Literal["2.0"] = Field(alias="schema_version")
    id: str = Field(description="UUID v4 pipeline identifier.")
    name: str = Field(min_length=1)
    description: str = Field(default="", description="Optional description for shared/exported pipelines.")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$", description="Semantic version, e.g. '1.0.0'.")
    nodes: list[Node] = Field(min_length=1)
    loops: list[Loop] = Field(default_factory=list)  # Optional in schema
    edges: list[Edge]  # Required in schema, but can be empty
    endpoints: dict[str, EndpointDescriptor]  # Required in schema, but can be empty

    @field_validator("nodes")
    @classmethod
    def _unique_node_ids(cls, nodes: list[Node]) -> list[Node]:
        ids = [n.id for n in nodes]
        if len(ids) != len(set(ids)):
            seen: set[str] = set()
            dupes = [n for n in ids if n in seen or seen.add(n)]  # type: ignore[func-returns-value]
            raise ValueError(f"[Duplicate Node ID] Duplicate node IDs found: {', '.join(dupes)}")
        return nodes

    @field_validator("loops")
    @classmethod
    def _unique_loop_ids(cls, loops: list[Loop]) -> list[Loop]:
        ids = [lp.id for lp in loops]
        if len(ids) != len(set(ids)):
            seen: set[str] = set()
            dupes = [n for n in ids if n in seen or seen.add(n)]  # type: ignore[func-returns-value]
            raise ValueError(f"[Duplicate Loop ID] Duplicate loop IDs found: {', '.join(dupes)}")
        return loops

    @model_validator(mode="after")
    def _endpoint_refs_resolve(self) -> "Pipeline":
        """Every endpoint_ref used by a model node must exist in endpoints."""
        for node in self.nodes:
            if node.endpoint_ref and node.endpoint_ref not in self.endpoints:
                raise ValueError(
                    f"[Unresolved Endpoint] Node '{node.id}' references endpoint_ref '{node.endpoint_ref}' "
                    f"which is not defined in the 'endpoints' map."
                )
        return self
