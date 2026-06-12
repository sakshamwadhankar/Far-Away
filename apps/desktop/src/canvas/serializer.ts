import type { Pipeline, Node as SchemaNode, Edge as SchemaEdge, EndpointDescriptor } from '@shared/types';
import { Node as RFNode, Edge as RFEdge } from 'reactflow';
import { PipelineNodeData } from './nodes/PipelineNode';

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
      endpoint_ref: n.data.endpoint_ref,
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
    if (n.type === 'model' && n.endpoint_ref) {
      if (!endpoints[n.endpoint_ref]) {
        if (n.endpoint_ref.startsWith('mock:')) {
          endpoints[n.endpoint_ref] = {
            kind: 'mock',
            model: 'default',
          };
        } else {
          // Default mock endpoint for serialization if not registered elsewhere
          endpoints[n.endpoint_ref] = {
            kind: 'openai',
            model: 'gpt-4o-mini',
          };
        }
      }
    }
  });

  return {
    schema_version: '2.0',
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
      type: 'pipelineNode',
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

  const edges: RFEdge[] = pipeline.edges.map((e, index) => {
    const [sourceNode, sourcePort] = e.from.split('.');
    const [targetNode, targetPort] = e.to.split('.');

    // We need to guess the port type from the node definitions to construct the handle ID
    const sNode = pipeline.nodes.find((n) => n.id === sourceNode);
    const tNode = pipeline.nodes.find((n) => n.id === targetNode);

    const sPortDef = sNode?.outputs?.find((p) => p.name === sourcePort);
    const tPortDef = tNode?.inputs?.find((p) => p.name === targetPort);

    const sourceHandleType = sPortDef?.type || 'text';
    const targetHandleType = tPortDef?.type || 'text';

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
