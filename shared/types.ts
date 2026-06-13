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
  | "compare";

export interface NodeConfig {
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
  /** Allow additional config keys for extensibility. */
  [key: string]: string | number | boolean | Record<string, string> | StopCondition | undefined;
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
  | "mock";

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
  schema_version: "2.0";
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
