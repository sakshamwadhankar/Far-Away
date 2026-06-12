/**
 * src/merge_a.test.ts
 *
 * MERGE A integration test — TypeScript side (Phase 1).
 *
 * Verifies that shared/types.ts can be imported by apps/desktop and that
 * the contract types line up (no loose `any`, no type errors).
 *
 * This test does NOT render React components; it is a pure type-contract
 * and runtime-shape check.
 *
 * Pass = `tsc --noEmit` succeeds AND vitest runs this file with 0 failures.
 */

import { describe, it, expect } from 'vitest';

// ─── The import under test ────────────────────────────────────────────────────
// If shared/types.ts has a type error or the path alias is broken,
// tsc (and vitest) will fail HERE before any test body runs.
import type {
  Pipeline,
  Node,
  Edge,
  Loop,
  StopCondition,
  EndpointDescriptor,
  Port,
  PortType,
  NodeType,
  EndpointKind,
  OnMax,
  StopOp,
} from '@shared/types';

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Build the minimal valid Pipeline that matches schema v2. */
function buildMinimalPipeline(): Pipeline {
  const inputPort: Port = { name: 'prompt', type: 'text' as PortType };
  const outputPort: Port = { name: 'response', type: 'text' as PortType };

  const inputNode: Node = {
    id: 'n_input',
    type: 'input' as NodeType,
    inputs: [],
    outputs: [inputPort],
  };

  const modelNode: Node = {
    id: 'n_model',
    type: 'model' as NodeType,
    endpoint_ref: 'ep_mock',
    inputs: [inputPort],
    outputs: [outputPort],
  };

  const outputNode: Node = {
    id: 'n_output',
    type: 'output' as NodeType,
    inputs: [outputPort],
    outputs: [],
  };

  const edge1: Edge = { from: 'n_input.prompt', to: 'n_model.prompt' };
  const edge2: Edge = { from: 'n_model.response', to: 'n_output.response' };

  const endpoint: EndpointDescriptor = {
    kind: 'openai' as EndpointKind,
    model: 'gpt-4o-mini',
  };

  const pipeline: Pipeline = {
    schema_version: '2.0',
    id: '00000000-0000-0000-0000-000000000001',
    name: 'Merge A test pipeline',
    version: '1.0.0',
    nodes: [inputNode, modelNode, outputNode],
    edges: [edge1, edge2],
    endpoints: { ep_mock: endpoint },
  };

  return pipeline;
}

/** Build a Loop with a StopCondition — exercises the loop contract. */
function buildLoop(): Loop {
  const stop: StopCondition = {
    field: 'verify.output.verified',
    op: '==' as StopOp,
    value: true,
  };

  const loop: Loop = {
    id: 'loop_1',
    body: ['n_model', 'n_judge'],
    max_iterations: 5,
    stop_when: stop,
    on_max: 'return_last' as OnMax,
  };

  return loop;
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('Merge A — shared/types.ts TS contract', () => {
  it('constructs a minimal valid Pipeline without type errors', () => {
    const pipeline = buildMinimalPipeline();

    expect(pipeline.schema_version).toBe('2.0');
    expect(pipeline.nodes).toHaveLength(3);
    expect(pipeline.edges).toHaveLength(2);
    expect(Object.keys(pipeline.endpoints)).toContain('ep_mock');
  });

  it('model node has endpoint_ref and input/output ports', () => {
    const pipeline = buildMinimalPipeline();
    const modelNode = pipeline.nodes.find((n) => n.type === 'model');

    expect(modelNode).toBeDefined();
    expect(modelNode!.endpoint_ref).toBe('ep_mock');
    expect(modelNode!.inputs).toHaveLength(1);
    expect(modelNode!.outputs).toHaveLength(1);
  });

  it('edges use nodeId.portName format', () => {
    const pipeline = buildMinimalPipeline();
    for (const edge of pipeline.edges) {
      expect(edge.from).toMatch(/^[^.]+\.[^.]+$/);
      expect(edge.to).toMatch(/^[^.]+\.[^.]+$/);
    }
  });

  it('constructs a Loop with a structured StopCondition', () => {
    const loop = buildLoop();

    expect(loop.max_iterations).toBe(5);
    expect(loop.stop_when.op).toBe('==');
    expect(loop.stop_when.value).toBe(true);
    expect(loop.on_max).toBe('return_last');
  });

  it('EndpointDescriptor carries no secrets — only kind, model, base_url', () => {
    const pipeline = buildMinimalPipeline();
    const ep = pipeline.endpoints['ep_mock'];

    // These are the ONLY allowed fields on EndpointDescriptor.
    // If shared/types.ts adds an `api_key` field this test would need review.
    const allowedKeys = new Set(['kind', 'model', 'base_url']);
    for (const key of Object.keys(ep)) {
      expect(allowedKeys.has(key)).toBe(true);
    }
  });
});
