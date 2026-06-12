import { describe, it, expect } from 'vitest';
import { toPipelineSchema, fromPipelineSchema } from './serializer';
import { Node as RFNode, Edge as RFEdge } from 'reactflow';
import { PipelineNodeData } from './nodes/PipelineNode';

describe('Serializer', () => {
  it('serializes a 3-node graph to a valid schema v2 JSON', () => {
    const rfNodes: RFNode<PipelineNodeData>[] = [
      {
        id: 'node-1',
        type: 'pipelineNode',
        position: { x: 0, y: 0 },
        data: {
          type: 'input',
          outputs: [{ name: 'prompt', type: 'text' }]
        }
      },
      {
        id: 'node-2',
        type: 'pipelineNode',
        position: { x: 200, y: 0 },
        data: {
          type: 'model',
          endpoint_ref: 'ep_mock',
          inputs: [{ name: 'prompt', type: 'text' }],
          outputs: [{ name: 'response', type: 'text' }],
          config: { temperature: 0.5, max_tokens: 100 }
        }
      },
      {
        id: 'node-3',
        type: 'pipelineNode',
        position: { x: 400, y: 0 },
        data: {
          type: 'output',
          inputs: [{ name: 'response', type: 'text' }]
        }
      }
    ];

    const rfEdges: RFEdge[] = [
      {
        id: 'e1-2',
        source: 'node-1',
        target: 'node-2',
        sourceHandle: 'text:prompt',
        targetHandle: 'text:prompt'
      },
      {
        id: 'e2-3',
        source: 'node-2',
        target: 'node-3',
        sourceHandle: 'text:response',
        targetHandle: 'text:response'
      }
    ];

    const pipeline = toPipelineSchema(rfNodes, rfEdges, 'Test Pipeline');

    expect(pipeline.schema_version).toBe('2.0');
    expect(pipeline.name).toBe('Test Pipeline');
    expect(pipeline.nodes).toHaveLength(3);
    expect(pipeline.edges).toHaveLength(2);
    
    // Check nodes mapped correctly
    const modelNode = pipeline.nodes.find(n => n.id === 'node-2');
    expect(modelNode?.type).toBe('model');
    expect(modelNode?.endpoint_ref).toBe('ep_mock');
    expect(modelNode?.config?.temperature).toBe(0.5);

    // Check edges formatted correctly
    expect(pipeline.edges[0].from).toBe('node-1.prompt');
    expect(pipeline.edges[0].to).toBe('node-2.prompt');
    expect(pipeline.edges[1].from).toBe('node-2.response');
    expect(pipeline.edges[1].to).toBe('node-3.response');

    // Check endpoint was inferred
    expect(pipeline.endpoints['ep_mock']).toBeDefined();
  });

  it('deserializes a Pipeline back to React Flow format', () => {
    const pipeline = toPipelineSchema(
      [
        {
          id: 'n1',
          type: 'pipelineNode',
          position: { x: 0, y: 0 },
          data: { type: 'input', outputs: [{ name: 'out', type: 'text' }] }
        },
        {
          id: 'n2',
          type: 'pipelineNode',
          position: { x: 0, y: 0 },
          data: { type: 'output', inputs: [{ name: 'in', type: 'text' }] }
        }
      ],
      [
        {
          id: 'e1',
          source: 'n1',
          target: 'n2',
          sourceHandle: 'text:out',
          targetHandle: 'text:in'
        }
      ]
    );

    const { nodes, edges } = fromPipelineSchema(pipeline);

    expect(nodes).toHaveLength(2);
    expect(nodes[0].data.type).toBe('input');
    
    expect(edges).toHaveLength(1);
    expect(edges[0].source).toBe('n1');
    expect(edges[0].target).toBe('n2');
    expect(edges[0].sourceHandle).toBe('text:out');
    expect(edges[0].targetHandle).toBe('text:in');
  });
});
