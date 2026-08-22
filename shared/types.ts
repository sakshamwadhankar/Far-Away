/**
 * shared/types.ts
 *
 * TypeScript type definitions for NeuralFlow pipeline schema v2.
 * These types MUST stay in sync with:
 *   - shared/pipeline.schema.json
 *   - backend/neuralflow/compiler/models.py (Pydantic)
 *
 * BREAKING CHANGE: any modification here must be announced before P2/P3 continue.
 * No app logic in this file — pure type definitions only.
 */

// ---------------------------------------------------------------------------
// Port types
// ---------------------------------------------------------------------------

export type PortType = "text" | "number" | "boolean" | "json" | "image" | "audio";

export interface Port {
  /** Port identifier, unique within the node's input or output list. */
  name: string;
  type: PortType;
}

// ---------------------------------------------------------------------------
// Node types
// ---------------------------------------------------------------------------

export type NodeType =
  | "input"
  | "output"
  | "model"
  | "loop"
  | "judge"
  | "router"
  | "transform"
  | "compare"
  /** Scope marker carrying an AccessPolicy. Added in schema 2.1. */
  | "access"
  /** Operating system and desktop control node. */
  | "computer";

/**
 * The set of capabilities a scope of the pipeline is permitted to reach.
 *
 * Attached to an `access` node via `NodeConfig.access_policy` and applied to
 * every node downstream of it. Deny-by-default: an empty `providers` list
 * grants no cloud provider, and both booleans start false.
 *
 * When several access nodes are ancestors of the same node their policies
 * INTERSECT — the most restrictive wins. A node can only lose capabilities by
 * being placed further downstream, never gain them.
 */
export interface AccessPolicy {
  /** Cloud/model providers downstream nodes may call. Empty grants none. */
  providers: EndpointKind[];
  /** Whether downstream nodes may call a local Ollama endpoint. */
  allow_local_models: boolean;
  /** Whether downstream nodes may make general network calls. */
  allow_network: boolean;
  /** Hostnames reachable when allow_network is true. Empty means unrestricted. */
  allowed_domains: string[];
  /** USD ceiling for this scope. null means no policy ceiling. */
  max_cost_usd: number | null;
  /** Per-request token ceiling for this scope. */
  max_tokens: number | null;
  /** Whether downstream nodes may control the desktop. */
  allow_desktop?: boolean;
  /** Applications downstream nodes may interact with. Empty means unrestricted. */
  allowed_applications?: string[];
  /** Whether destructive desktop actions are permitted. */
  allow_destructive?: boolean;
}

export interface NodeConfig {
  /**
   * Capability grant. Only meaningful on nodes of type "access"; the compiler
   * rejects it on any other node type.
   */
  access_policy?: AccessPolicy;
  temperature?: number;
  max_tokens?: number;
  /** "text" | "json" — whether the node expects structured JSON output. */
  response_format?: "text" | "json";
  system_prompt?: string;
  role?: string;
  routing_map?: Record<string, string>;
  score_field?: string;
  strategy?: "max_numeric" | "truthy";
  /** Input node: placeholder label shown to the user. */
  label?: string;
  /** Loop node: hard upper bound on iterations (1–100). */
  max_iterations?: number;
  /** Loop node: structured stop condition. */
  stop_when?: StopCondition;
  /** Loop node: what to do when max_iterations is reached. */
  on_max?: OnMax;
  /** Custom node display metadata. */
  custom_node_id?: string;
  custom_label?: string;
  custom_color?: string;
  /**
   * Input/output nodes only (schema 2.1, Phase 3): name of this node in a
   * deployment's HTTP request or response body. "messages" and "content" are
   * the recognized names on the chat-completions path.
   */
  api_field?: string;
  /**
   * Output nodes only: whether this node's value is included in a
   * deployment's response. Defaults to true.
   */
  api_expose?: boolean;
  /** Allow additional config keys for extensibility. */
  [key: string]:
    | string
    | number
    | boolean
    | Record<string, string>
    | StopCondition
    | AccessPolicy
    | undefined;
}

export interface Node {
  /** Unique node identifier within this pipeline. */
  id: string;
  type: NodeType;
  /**
   * Key into the top-level endpoints map.
   * Required for "model" nodes, omitted on all others.
   * No secrets stored here — resolved at runtime from OS keychain.
   */
  endpoint_ref?: string;
  /** Semantic role hint, e.g. "solver", "verifier", "judge". Informational only. */
  role?: string;
  config?: NodeConfig;
  inputs?: Port[];
  outputs?: Port[];
}

// ---------------------------------------------------------------------------
// Loop / StopCondition
// ---------------------------------------------------------------------------

export type StopOp = "==" | "!=" | ">" | "<" | ">=" | "<=" | "contains";

/**
 * Structured stop condition — no raw code or eval permitted.
 * The scheduler evaluates this deterministically at runtime.
 */
export interface StopCondition {
  /** Dot-path to the field being tested, e.g. "verify.output.verified". */
  field: string;
  op: StopOp;
  /** Scalar primitive to compare against. */
  value: string | number | boolean;
}

export type OnMax = "return_best" | "return_last" | "fail";

export interface Loop {
  /** Unique loop identifier. */
  id: string;
  /** Ordered list of node IDs forming the loop body. */
  body: string[];
  /**
   * Hard upper bound on iterations (1–100).
   * Enforced by the scheduler as a kill switch — no infinite loops.
   */
  max_iterations: number;
  stop_when: StopCondition;
  on_max: OnMax;
}

// ---------------------------------------------------------------------------
// Edge
// ---------------------------------------------------------------------------

/**
 * Directed edge between node ports.
 * Format: "nodeId.portName"
 */
export interface Edge {
  from: string; // "sourceNodeId.portName"
  to: string;   // "targetNodeId.portName"
}

// ---------------------------------------------------------------------------
// Endpoint descriptor
// ---------------------------------------------------------------------------

export type EndpointKind =
  | "openai"
  | "anthropic"
  | "google"
  | "openai_compatible"
  | "ollama"
  | "hermes"
  | "mock"
  | "groq"
  | "openrouter"
  | "zhipu"
  | "nvidia";

/**
 * Endpoint descriptor stored in the pipeline file.
 * NO API keys, credentials, or device pins here — resolved at runtime from OS keychain.
 */
export interface EndpointDescriptor {
  kind: EndpointKind;
  /** Optional override base URL for openai_compatible or ollama endpoints. */
  base_url?: string;
  /** Default model name for this endpoint reference. */
  model?: string;
}

// ---------------------------------------------------------------------------
// Pipeline (top-level document)
// ---------------------------------------------------------------------------

export interface Pipeline {
  /** Must be exactly "2.0". */
  /**
   * "2.1" added the access node. A "2.0" document is still valid and is read
   * as a pipeline with no access node.
   */
  schema_version: "2.0" | "2.1";
  /** UUID v4 pipeline identifier. */
  id: string;
  /** Human-readable pipeline name. */
  name: string;
  /** Semantic version string, e.g. "1.0.0". */
  version: string;
  /** Optional description for shared/exported pipelines. */
  description?: string;
  nodes: Node[];
  loops?: Loop[];
  edges: Edge[];
  /** Named endpoint registry. Keys are the endpoint_ref values used by model nodes. */
  endpoints: Record<string, EndpointDescriptor>;
}
