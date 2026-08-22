"""
backend/komvos/compiler/models.py

Pydantic v2 models for NeuralFlow pipeline schema v2.

These models MUST stay in sync with:
  - shared/pipeline.schema.json
  - shared/types.ts

BREAKING CHANGE: any modification to these models is a contract change.
Announce before P2 or P3 proceed.

No application logic here — pure data models and field-level validation only.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Port
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

#: "2.0" — the original schema.
#: "2.1" — adds the `access` node type and NodeConfig.access_policy.
#:
#: Both are accepted. A 2.0 document simply has no access node, which the
#: compiler reads as an unrestricted effective policy for local runs (see
#: compiler/dag.py, `mode="local"`). Documents are written as 2.1 going
#: forward; nothing rewrites an existing file on load.
SchemaVersion = Literal["2.0", "2.1"]

CURRENT_SCHEMA_VERSION: SchemaVersion = "2.1"

PortType = Literal["text", "number", "boolean", "json", "image", "audio"]


class Port(BaseModel):
    """Typed input or output port on a node."""

    model_config = {"extra": "forbid"}

    name: str = Field(
        min_length=1, description="Port identifier, unique within the node's port list."
    )
    type: PortType


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

NodeType = Literal[
    "input",
    "output",
    "model",
    "loop",
    "judge",
    "router",
    "transform",
    "compare",
    "access",
]

# ---------------------------------------------------------------------------
# EndpointKind / AccessPolicy
#
# EndpointKind is declared here rather than next to EndpointDescriptor because
# AccessPolicy.providers references it.
# ---------------------------------------------------------------------------

# TODO(R0 Polish Phase): Keep "mock" out of the production schema entirely
# and inject it dynamically in the test environment to avoid schema pollution.
EndpointKind = Literal[
    "openai",
    "anthropic",
    "google",
    "openai_compatible",
    "ollama",
    "mock",
    "groq",
    "openrouter",
    "zhipu",
    "nvidia",
]

#: Runtime tuple of every EndpointKind, derived from the Literal so the two
#: cannot drift.
ENDPOINT_KINDS: tuple[EndpointKind, ...] = get_args(EndpointKind)


class AccessPolicy(BaseModel):
    """
    The set of capabilities a scope of the pipeline is permitted to reach.

    Attached to an `access` node via `NodeConfig.access_policy`, and applied to
    every node downstream of it. Deny-by-default: an empty `providers` list
    grants no cloud provider at all, and both booleans start False.

    When several access nodes are ancestors of the same node their policies
    INTERSECT — see backend/komvos/compiler/README.md. A node can only ever
    lose capabilities by being placed further downstream, never gain them.
    """

    model_config = {"extra": "forbid"}

    providers: list[EndpointKind] = Field(
        default_factory=list,
        description="Cloud/model providers downstream nodes may call.",
    )
    allow_local_models: bool = Field(
        default=False,
        description="Whether downstream nodes may call a local Ollama endpoint.",
    )
    allow_network: bool = Field(
        default=False,
        description="Whether downstream nodes may make general network calls.",
    )
    allowed_domains: list[str] = Field(
        default_factory=list,
        description="Hostnames reachable when allow_network is True.",
    )
    max_cost_usd: float | None = Field(
        default=None,
        ge=0.0,
        description="USD ceiling for this scope. None means no policy ceiling.",
    )
    max_tokens: int | None = Field(
        default=None,
        ge=1,
        description="Per-request token ceiling for this scope.",
    )

    @staticmethod
    def permissive() -> AccessPolicy:
        """
        The policy applied when no access node governs a node.

        Everything is granted, which is what keeps every pre-2.1 pipeline
        working unchanged on the canvas.
        """
        return AccessPolicy(
            providers=list(ENDPOINT_KINDS),
            allow_local_models=True,
            allow_network=True,
            allowed_domains=[],
            max_cost_usd=None,
            max_tokens=None,
        )

    def intersect(self, other: AccessPolicy) -> AccessPolicy:
        """
        Combine two policies, keeping only what BOTH grant.

        Used when a node has more than one access node among its ancestors.
        Numeric ceilings take the lower of the two; `None` means "no ceiling
        from this policy", so it loses to any concrete number.

        `allowed_domains` is only meaningful while `allow_network` is granted.
        An empty list on a policy that allows network means "no domain
        restriction", so it intersects as the identity rather than as the empty
        set — otherwise an unrestricted policy would silently zero out a
        restricted one.
        """
        if not self.allowed_domains:
            domains = list(other.allowed_domains)
        elif not other.allowed_domains:
            domains = list(self.allowed_domains)
        else:
            # Preserve self's ordering for a stable, readable error message.
            allowed = set(other.allowed_domains)
            domains = [d for d in self.allowed_domains if d in allowed]

        return AccessPolicy(
            providers=[p for p in self.providers if p in set(other.providers)],
            allow_local_models=self.allow_local_models and other.allow_local_models,
            allow_network=self.allow_network and other.allow_network,
            allowed_domains=domains,
            max_cost_usd=_min_optional(self.max_cost_usd, other.max_cost_usd),
            max_tokens=_min_optional(self.max_tokens, other.max_tokens),
        )


def _min_optional(a: float | None, b: float | None) -> Any:
    """Lower of two optional ceilings; None means 'unbounded' and always loses."""
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


class NodeConfig(BaseModel):
    """Per-node configuration parameters. All fields optional."""

    model_config = {"extra": "forbid"}

    access_policy: AccessPolicy | None = Field(
        default=None,
        description="Capability grant. Only meaningful on nodes of type 'access'.",
    )

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
    # Custom node display metadata (used by transform nodes created from
    # custom definitions)
    custom_node_id: str | None = Field(
        default=None, description="ID of the custom node definition."
    )
    custom_label: str | None = Field(
        default=None, description="Display label overriding 'transform'."
    )
    custom_color: str | None = Field(
        default=None, description="Hex accent color for this custom node."
    )

    # ── API serving (schema 2.1, Phase 3) ───────────────────────────────────
    # Meaningful only on 'input' and 'output' nodes; maps the node to a field
    # in a deployment's HTTP request/response body. See backend/komvos/
    # serve/README.md for the full mapping rules.
    api_field: str | None = Field(
        default=None,
        description=(
            "Name of this input/output node in a deployment's request or "
            "response body. For the chat-completions path, 'messages' and "
            "'content' are the recognized names on input and output nodes "
            "respectively."
        ),
    )
    api_expose: bool = Field(
        default=True,
        description=(
            "Output nodes only: whether this node's value is included in a "
            "deployment's response. Ignored on input nodes."
        ),
    )


class Node(BaseModel):
    """A single node in the pipeline graph."""

    model_config = {"extra": "forbid"}

    id: str = Field(
        min_length=1, description="Unique node identifier within this pipeline."
    )
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
        description=(
            "Semantic role hint (e.g. 'solver', 'verifier'). Informational only."
        ),
    )
    config: NodeConfig | None = None
    inputs: list[Port] = Field(default_factory=list)
    outputs: list[Port] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_model_node_endpoint(self) -> Node:
        if self.type == "model" and not self.endpoint_ref:
            raise ValueError(
                f"[Missing Endpoint] Node '{self.id}' of type 'model' "
                "must define an 'endpoint_ref'."
            )
        if self.type != "model" and self.endpoint_ref is not None:
            raise ValueError(
                "[Invalid Endpoint] Only 'model' nodes may have "
                f"'endpoint_ref'; node '{self.id}' has type '{self.type}'."
            )
        return self

    @model_validator(mode="after")
    def _validate_access_node(self) -> Node:
        """
        An access node is a scope marker, not a transform.

        It carries a policy and no data ports; connections into and out of it
        exist only to mark which part of the graph it governs.
        """
        if self.type == "access":
            if self.inputs or self.outputs:
                raise ValueError(
                    f"[Invalid Access Node] Access node '{self.id}' must not "
                    "declare data ports — it is a scope marker, not a "
                    "transform. Remove its inputs and outputs."
                )
            if self.config is None or self.config.access_policy is None:
                raise ValueError(
                    f"[Missing Access Policy] Access node '{self.id}' must "
                    "define 'config.access_policy'."
                )
        elif self.config is not None and self.config.access_policy is not None:
            raise ValueError(
                "[Invalid Access Policy] Only nodes of type 'access' may carry "
                f"'config.access_policy'; node '{self.id}' has type "
                f"'{self.type}'."
            )
        return self


# ---------------------------------------------------------------------------
# StopCondition / Loop
# ---------------------------------------------------------------------------

StopOp = Literal["==", "!=", ">", "<", ">=", "<=", "contains"]

# Scalar value: string, number, or boolean — no raw code / eval.
StopValue = str | float | bool


class StopCondition(BaseModel):
    """
    Structured loop stop condition.
    NO raw code or eval is permitted — the scheduler evaluates this deterministically.
    Supported ops: ==  !=  >  <  >=  <=  contains
    """

    model_config = {"extra": "forbid"}

    field: Annotated[
        str,
        Field(
            min_length=1,
            description="Dot-path to the field, e.g. 'verify.output.verified'.",
        ),
    ]
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
    body: list[str] = Field(
        min_length=1, description="Ordered node IDs forming the loop body."
    )
    max_iterations: int = Field(
        ge=1, le=100, description="Hard upper bound. No infinite loops."
    )
    stop_when: StopCondition
    on_max: OnMax


# ---------------------------------------------------------------------------
# Edge
# ---------------------------------------------------------------------------

_EDGE_PATTERN = r"^[^.]+\.[^.]+$"

#: Reserved port name used by edges that attach an access node to the scope it
#: governs. An access node declares no real ports, but the Edge contract is
#: "nodeId.portName", so scope edges use this fixed name. Nothing flows across
#: them — the compiler skips port-type checking for these edges and validation
#: rejects any other port name on an access node.
ACCESS_SCOPE_PORT = "scope"


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
    model: str | None = Field(
        default=None, description="Default model name for this endpoint ref."
    )


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

    schema_version: SchemaVersion = Field(
        alias="schema_version",
        description=(
            "'2.1' introduced the access node. A '2.0' document is still valid "
            "and is read as a pipeline with no access node, i.e. an unrestricted "
            "effective policy on the canvas."
        ),
    )
    id: str = Field(description="UUID v4 pipeline identifier.")
    name: str = Field(min_length=1)
    description: str = Field(
        default="", description="Optional description for shared/exported pipelines."
    )
    version: str = Field(
        pattern=r"^\d+\.\d+\.\d+$", description="Semantic version, e.g. '1.0.0'."
    )
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
            raise ValueError(
                f"[Duplicate Node ID] Duplicate node IDs found: {', '.join(dupes)}"
            )
        return nodes

    @field_validator("loops")
    @classmethod
    def _unique_loop_ids(cls, loops: list[Loop]) -> list[Loop]:
        ids = [lp.id for lp in loops]
        if len(ids) != len(set(ids)):
            seen: set[str] = set()
            dupes = [n for n in ids if n in seen or seen.add(n)]  # type: ignore[func-returns-value]
            raise ValueError(
                f"[Duplicate Loop ID] Duplicate loop IDs found: {', '.join(dupes)}"
            )
        return loops

    @model_validator(mode="after")
    def _endpoint_refs_resolve(self) -> Pipeline:
        """Every endpoint_ref used by a model node must exist in endpoints."""
        for node in self.nodes:
            if node.endpoint_ref and node.endpoint_ref not in self.endpoints:
                raise ValueError(
                    f"[Unresolved Endpoint] Node '{node.id}' references "
                    f"endpoint_ref '{node.endpoint_ref}' "
                    f"which is not defined in the 'endpoints' map."
                )
        return self
