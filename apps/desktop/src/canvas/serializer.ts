import type {
  Pipeline,
  Node as SchemaNode,
  Edge as SchemaEdge,
  EndpointDescriptor,
  EndpointKind,
  NodeType,
} from '@shared/types';
import { Node as RFNode, Edge as RFEdge } from 'reactflow';
import { PipelineNodeData } from './nodes/PipelineNode';

/**
 * Node types that require and carry an `endpoint_ref` into the pipeline `endpoints` map.
 */
export const ENDPOINT_BEARING_NODE_TYPES: readonly NodeType[] = ['model', 'computer'] as const;

/**
 * Predicate checking whether a node or node type carries an `endpoint_ref`.
 */
export function isEndpointBearingNode(
  nodeOrType: { type: NodeType | string } | { data?: { type?: NodeType | string } } | NodeType | string | undefined | null
): boolean {
  if (!nodeOrType) return false;
  if (typeof nodeOrType === 'string') {
    return (ENDPOINT_BEARING_NODE_TYPES as readonly string[]).includes(nodeOrType);
  }
  if ('data' in nodeOrType && nodeOrType.data && typeof nodeOrType.data.type === 'string') {
    return (ENDPOINT_BEARING_NODE_TYPES as readonly string[]).includes(nodeOrType.data.type);
  }
  if ('type' in nodeOrType && typeof nodeOrType.type === 'string') {
    return (ENDPOINT_BEARING_NODE_TYPES as readonly string[]).includes(nodeOrType.type);
  }
  return false;
}

const ENDPOINT_KINDS: readonly EndpointKind[] = [
  'openai',
  'anthropic',
  'google',
  'openai_compatible',
  'ollama',
  'mock',
];

/**
 * Narrow the provider prefix of an `endpoint_ref` to a schema `EndpointKind`.
 * Unknown providers are treated as `openai_compatible`, which is the schema's
 * catch-all for third-party OpenAI-shaped services.
 */
function toEndpointKind(provider: string): EndpointKind {
  return ENDPOINT_KINDS.includes(provider as EndpointKind)
    ? (provider as EndpointKind)
    : 'openai_compatible';
}

/**
 * A pipeline edge as it may appear on disk. The backend pydantic model aliases
 * `from` to `from_`, so files written by older backend versions carry that key.
 */
type SerializedEdge = SchemaEdge & { from_?: string };

// Generate a random UUID v4
function uuidv4() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : ((r & 0x3) | 0x8);
    return v.toString(16);
  });
}

export function toPipelineSchema(
  rfNodes: RFNode<PipelineNodeData>[],
  rfEdges: RFEdge[],
  pipelineName: string = 'Untitled Pipeline'
): Pipeline {
  const schemaNodes: SchemaNode[] = rfNodes.map((n) => {
    return {
      id: n.id,
      type: n.data.type,
      endpoint_ref: isEndpointBearingNode(n.data.type) ? n.data.endpoint_ref : undefined,
      role: n.data.role,
      config: n.data.config,
      inputs: n.data.inputs,
      outputs: n.data.outputs,
    };
  });

  const schemaEdges: SchemaEdge[] = rfEdges.map((e) => {
    // React Flow edge targetHandle looks like "text:prompt", we need "nodeId.portName"
    const sourcePortName = e.sourceHandle?.split(':')[1] || '';
    const targetPortName = e.targetHandle?.split(':')[1] || '';
    
    return {
      from: `${e.source}.${sourcePortName}`,
      to: `${e.target}.${targetPortName}`,
    };
  });

  // Extract unique endpoint refs
  const endpoints: Record<string, EndpointDescriptor> = {};
  schemaNodes.forEach((n) => {
    if (isEndpointBearingNode(n.type) && n.endpoint_ref) {
      if (!endpoints[n.endpoint_ref]) {
        const parts = n.endpoint_ref.split(':');
        const provider = parts[0];
        const modelName = parts.slice(1).join(':') || 'default';

        if (provider === 'mock') {
          endpoints[n.endpoint_ref] = {
            kind: 'mock',
            model: modelName,
          };
        } else {
          endpoints[n.endpoint_ref] = {
            kind: toEndpointKind(provider),
            model: modelName,
          };
        }
      }
    }
  });

  return {
    // 2.1 adds the access node. Documents are written as 2.1 going forward;
    // the backend still accepts 2.0 and reads it as "no access node".
    schema_version: '2.1',
    id: uuidv4(),
    name: pipelineName,
    version: '1.0.0',
    nodes: schemaNodes,
    edges: schemaEdges,
    endpoints,
  };
}

export function fromPipelineSchema(pipeline: Pipeline): { nodes: RFNode<PipelineNodeData>[]; edges: RFEdge[] } {
  const nodes: RFNode<PipelineNodeData>[] = pipeline.nodes.map((n, index) => {
    return {
      id: n.id,
      // Access nodes render a capability list instead of ports, so they map to
      // their own React Flow node type.
      type: n.type === 'access' ? 'accessNode' : 'pipelineNode',
      position: { x: 100 + index * 250, y: 100 }, // Simple layout
      data: {
        type: n.type,
        endpoint_ref: n.endpoint_ref,
        role: n.role,
        config: n.config,
        inputs: n.inputs,
        outputs: n.outputs,
      },
    };
  });

  const edges: RFEdge[] = (pipeline.edges as SerializedEdge[]).map((e, index) => {
    const fromStr = e.from || e.from_ || '';
    const [sourceNode, sourcePort] = fromStr.split('.');
    const [targetNode, targetPort] = e.to.split('.');

    // We need to guess the port type from the node definitions to construct the handle ID
    const sNode = pipeline.nodes.find((n) => n.id === sourceNode);
    const tNode = pipeline.nodes.find((n) => n.id === targetNode);

    const sPortDef = sNode?.outputs?.find((p) => p.name === sourcePort);
    const tPortDef = tNode?.inputs?.find((p) => p.name === targetPort);

    const sourceHandleType = sNode?.type === 'access' || sourcePort === 'scope' ? 'scope' : (sPortDef?.type || 'text');
    const targetHandleType = tNode?.type === 'access' || targetPort === 'scope' ? 'scope' : (tPortDef?.type || 'text');

    return {
      id: `edge-${index}`,
      source: sourceNode,
      target: targetNode,
      sourceHandle: `${sourceHandleType}:${sourcePort}`,
      targetHandle: `${targetHandleType}:${targetPort}`,
    };
  });

  return { nodes, edges };
}

export function scrubSecrets(pipeline: Pipeline): Pipeline {
  // Phase 3 Rule: "export SCRUBS secrets"
  // In v2 schema, secrets are not stored in the pipeline JSON directly.
  // They are resolved via keychain at runtime using endpoint_ref.
  // We perform a deep clone to ensure no accidental ephemeral secret keys are exported.
  const scrubbed = JSON.parse(JSON.stringify(pipeline));
  
  // Explicitly remove anything that looks like a secret if it accidentally made it in
  if (scrubbed.endpoints) {
    for (const ref in scrubbed.endpoints) {
      delete scrubbed.endpoints[ref].api_key;
      delete scrubbed.endpoints[ref].token;
    }
  }

  // Also strip any custom node configs that might be mislabeled
  if (scrubbed.nodes) {
    for (const node of scrubbed.nodes) {
      if (node.config) {
        delete node.config.api_key;
        delete node.config.secret;
        delete node.config.token;
      }
    }
  }

  return scrubbed;
}
