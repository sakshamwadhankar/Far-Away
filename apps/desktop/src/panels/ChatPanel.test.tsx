import { describe, it, expect } from 'vitest';
import { isChatCompatible } from './ChatPanel';
import type { Node as RFNode } from 'reactflow';
import type { PipelineNodeData } from '../canvas/nodes/PipelineNode';

describe('ChatPanel - isChatCompatible', () => {
  it('returns true for exactly 1 input and 1 output', () => {
    const nodes: RFNode<PipelineNodeData>[] = [
      {
        id: 'in', type: 'pipelineNode', position: { x: 0, y: 0 },
        data: { type: 'input', outputs: [{ name: 'prompt', type: 'text' }] },
      },
      {
        id: 'model', type: 'pipelineNode', position: { x: 200, y: 0 },
        data: { type: 'model', endpoint_ref: 'mock:default', inputs: [{ name: 'prompt', type: 'text' }], outputs: [{ name: 'response', type: 'text' }] },
      },
      {
        id: 'out', type: 'pipelineNode', position: { x: 400, y: 0 },
        data: { type: 'output', inputs: [{ name: 'response', type: 'text' }] },
      },
    ];

    expect(isChatCompatible(nodes)).toBe(true);
  });

  it('returns false for 0 input nodes', () => {
    const nodes: RFNode<PipelineNodeData>[] = [
      {
        id: 'model', type: 'pipelineNode', position: { x: 0, y: 0 },
        data: { type: 'model', endpoint_ref: 'mock:default' },
      },
      {
        id: 'out', type: 'pipelineNode', position: { x: 200, y: 0 },
        data: { type: 'output', inputs: [{ name: 'response', type: 'text' }] },
      },
    ];

    expect(isChatCompatible(nodes)).toBe(false);
  });

  it('returns false for multiple output nodes', () => {
    const nodes: RFNode<PipelineNodeData>[] = [
      {
        id: 'in', type: 'pipelineNode', position: { x: 0, y: 0 },
        data: { type: 'input', outputs: [{ name: 'prompt', type: 'text' }] },
      },
      {
        id: 'out1', type: 'pipelineNode', position: { x: 200, y: 0 },
        data: { type: 'output', inputs: [{ name: 'response', type: 'text' }] },
      },
      {
        id: 'out2', type: 'pipelineNode', position: { x: 200, y: 100 },
        data: { type: 'output', inputs: [{ name: 'response', type: 'text' }] },
      },
    ];

    expect(isChatCompatible(nodes)).toBe(false);
  });

  it('returns false for multiple input nodes', () => {
    const nodes: RFNode<PipelineNodeData>[] = [
      {
        id: 'in1', type: 'pipelineNode', position: { x: 0, y: 0 },
        data: { type: 'input', outputs: [{ name: 'prompt', type: 'text' }] },
      },
      {
        id: 'in2', type: 'pipelineNode', position: { x: 0, y: 100 },
        data: { type: 'input', outputs: [{ name: 'prompt', type: 'text' }] },
      },
      {
        id: 'out', type: 'pipelineNode', position: { x: 200, y: 0 },
        data: { type: 'output', inputs: [{ name: 'response', type: 'text' }] },
      },
    ];

    expect(isChatCompatible(nodes)).toBe(false);
  });

  it('returns false for empty node list', () => {
    expect(isChatCompatible([])).toBe(false);
  });

  it('returns true for complex pipeline with exactly 1 input and 1 output', () => {
    const nodes: RFNode<PipelineNodeData>[] = [
      {
        id: 'in', type: 'pipelineNode', position: { x: 0, y: 0 },
        data: { type: 'input', outputs: [{ name: 'prompt', type: 'text' }] },
      },
      {
        id: 'solver', type: 'pipelineNode', position: { x: 200, y: 0 },
        data: { type: 'model', role: 'solver', endpoint_ref: 'ollama:qwen2.5:3b', inputs: [{ name: 'prompt', type: 'text' }], outputs: [{ name: 'response', type: 'text' }] },
      },
      {
        id: 'verifier', type: 'pipelineNode', position: { x: 400, y: 0 },
        data: { type: 'model', role: 'verifier', endpoint_ref: 'ollama:qwen2.5:3b', inputs: [{ name: 'prompt', type: 'text' }], outputs: [{ name: 'response', type: 'text' }] },
      },
      {
        id: 'judge', type: 'pipelineNode', position: { x: 600, y: 0 },
        data: { type: 'judge', role: 'judge', inputs: [{ name: 'input', type: 'text' }], outputs: [{ name: 'decision', type: 'boolean' }] },
      },
      {
        id: 'out', type: 'pipelineNode', position: { x: 800, y: 0 },
        data: { type: 'output', inputs: [{ name: 'response', type: 'text' }] },
      },
    ];

    expect(isChatCompatible(nodes)).toBe(true);
  });
});
