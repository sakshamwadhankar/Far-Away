import { describe, it, expect } from 'vitest';
import { toPipelineSchema, fromPipelineSchema, scrubSecrets } from './serializer';
import { Node as RFNode, Edge as RFEdge } from 'reactflow';
import { PipelineNodeData } from './nodes/PipelineNode';
import type { Pipeline } from '@shared/types';

/**
 * A scrubbed pipeline viewed loosely, so the test can assert that fields which
 * are *not* part of the Pipeline type (injected secrets) were removed.
 */
interface LoosePipeline {
  nodes: { config: Record<string, unknown> }[];
  endpoints: Record<string, Record<string, unknown>>;
}

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
          endpoint_ref: 'mock:default',
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
    expect(modelNode?.endpoint_ref).toBe('mock:default');
    expect(modelNode?.config?.temperature).toBe(0.5);

    // Check edges formatted correctly
    expect(pipeline.edges[0].from).toBe('node-1.prompt');
    expect(pipeline.edges[0].to).toBe('node-2.prompt');
    expect(pipeline.edges[1].from).toBe('node-2.response');
    expect(pipeline.edges[1].to).toBe('node-3.response');

    // Check endpoint was inferred
    expect(pipeline.endpoints['mock:default']).toBeDefined();
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

  it('scrubSecrets removes api_key, token, and secret fields from pipeline', () => {
    const pipeline = {
      schema_version: '2.0',
      id: 'test-1',
      name: 'Test',
      version: '1.0',
      nodes: [
        {
          id: 'n1',
          type: 'model',
          config: {
            temperature: 0.7,
            api_key: 'sk-123',
            secret: 'shh',
            token: 'tkn'
          }
        }
      ],
      edges: [],
      endpoints: {
        'mock:default': {
          kind: 'mock',
          api_key: 'sk-456',
          token: 'tkn2'
        }
      }
      // Cast through unknown: the secret fields above are intentionally not
      // part of the Pipeline type — that is exactly what scrubSecrets removes.
    } as unknown as Pipeline;

    const scrubbed = scrubSecrets(pipeline) as unknown as LoosePipeline;

    expect(scrubbed.endpoints['mock:default'].api_key).toBeUndefined();
    expect(scrubbed.endpoints['mock:default'].token).toBeUndefined();
    expect(scrubbed.endpoints['mock:default'].kind).toBe('mock');

    expect(scrubbed.nodes[0].config.api_key).toBeUndefined();
    expect(scrubbed.nodes[0].config.secret).toBeUndefined();
    expect(scrubbed.nodes[0].config.token).toBeUndefined();
    expect(scrubbed.nodes[0].config.temperature).toBe(0.7);
  });

  it('editing a node config is reflected in the serialized pipeline', () => {
    const rfNodes: RFNode<PipelineNodeData>[] = [
      {
        id: 'node-1',
        type: 'pipelineNode',
        position: { x: 0, y: 0 },
        data: {
          type: 'model',
          endpoint_ref: 'mock:default',
          inputs: [{ name: 'prompt', type: 'text' }],
          outputs: [{ name: 'response', type: 'text' }],
          config: { temperature: 0.7, max_tokens: 2048, system_prompt: '' }
        }
      }
    ];

    // Simulate editing config (same path updateNodeData takes)
    const editedNodes = rfNodes.map(n => ({
      ...n,
      data: {
        ...n.data,
        config: { ...n.data.config, temperature: 1.2, system_prompt: 'You are a pirate.' }
      }
    }));

    const pipeline = toPipelineSchema(editedNodes, []);

    const modelNode = pipeline.nodes.find(n => n.id === 'node-1');
    expect(modelNode?.config?.temperature).toBe(1.2);
    expect(modelNode?.config?.system_prompt).toBe('You are a pirate.');
    expect(modelNode?.config?.max_tokens).toBe(2048);
  });

  it('deleting a node removes its connected edges from serialization', () => {
    const rfNodes: RFNode<PipelineNodeData>[] = [
      {
        id: 'node-1', type: 'pipelineNode', position: { x: 0, y: 0 },
        data: { type: 'input', outputs: [{ name: 'prompt', type: 'text' }] }
      },
      {
        id: 'node-2', type: 'pipelineNode', position: { x: 200, y: 0 },
        data: { type: 'model', endpoint_ref: 'mock:default', inputs: [{ name: 'prompt', type: 'text' }], outputs: [{ name: 'response', type: 'text' }] }
      },
      {
        id: 'node-3', type: 'pipelineNode', position: { x: 400, y: 0 },
        data: { type: 'output', inputs: [{ name: 'response', type: 'text' }] }
      }
    ];

    const rfEdges: RFEdge[] = [
      { id: 'e1-2', source: 'node-1', target: 'node-2', sourceHandle: 'text:prompt', targetHandle: 'text:prompt' },
      { id: 'e2-3', source: 'node-2', target: 'node-3', sourceHandle: 'text:response', targetHandle: 'text:response' }
    ];

    // Simulate deleting node-2 and its connected edges (same as deleteNodes in App.tsx)
    const deletedId = 'node-2';
    const remainingNodes = rfNodes.filter(n => n.id !== deletedId);
    const remainingEdges = rfEdges.filter(e => e.source !== deletedId && e.target !== deletedId);

    const pipeline = toPipelineSchema(remainingNodes, remainingEdges);

    expect(pipeline.nodes).toHaveLength(2);
    expect(pipeline.nodes.map(n => n.id)).toEqual(['node-1', 'node-3']);
    expect(pipeline.edges).toHaveLength(0);
  });
});

