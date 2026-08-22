import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { Edge as RFEdge, Node as RFNode } from 'reactflow';
import type { AccessPolicy } from '@shared/types';
import type { PipelineNodeData } from './PipelineNode';
import { emptyPolicy } from '../accessPolicy';

/**
 * Canvas state the mocked React Flow hooks serve to the component under test.
 * Reassigned per test rather than re-mocking the module each time.
 */
let mockNodes: RFNode<PipelineNodeData>[] = [];
let mockEdges: RFEdge[] = [];
const setNodes = vi.fn();

vi.mock('reactflow', () => ({
  Handle: () => <div data-testid="handle-mock" />,
  Position: { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' },
  useNodes: () => mockNodes,
  useEdges: () => mockEdges,
  useReactFlow: () => ({ setNodes }),
}));

const { default: AccessNode } = await import('./AccessNode');

/** A model node wired downstream of the gate, requesting `provider`. */
function modelNode(id: string, provider: string): RFNode<PipelineNodeData> {
  return {
    id,
    position: { x: 0, y: 0 },
    data: {
      type: 'model',
      endpoint_ref: `${provider}:some-model`,
      inputs: [{ name: 'prompt', type: 'text' }],
      outputs: [{ name: 'out', type: 'text' }],
    },
  };
}

function scopeEdge(from: string, to: string): RFEdge {
  return { id: `${from}->${to}`, source: from, target: to };
}

function renderGate(policy: AccessPolicy) {
  return render(
    <AccessNode
      id="gate-1"
      selected={false}
      data={{ type: 'access', config: { access_policy: policy } }}
    />,
  );
}

describe('AccessNode', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockNodes = [];
    mockEdges = [];
  });

  it('renders as an access node', () => {
    renderGate(emptyPolicy());
    expect(screen.getByTestId('access-node')).toBeDefined();
  });

  // ── State 1: granted & used ──────────────────────────────────────────────

  it('marks a capability granted-used when something downstream calls it', () => {
    mockNodes = [modelNode('summarize', 'anthropic')];
    mockEdges = [scopeEdge('gate-1', 'summarize')];

    renderGate({ ...emptyPolicy(), providers: ['anthropic'] });

    const row = screen.getByTestId('capability-provider:anthropic');
    expect(row.getAttribute('data-state')).toBe('granted-used');
    // Nothing to act on — it is already in the state the user wants.
    expect(screen.queryByTestId('capability-action-provider:anthropic')).toBeNull();
  });

  // ── State 2: granted & unused ────────────────────────────────────────────

  it('marks a capability granted-unused when nothing downstream calls it', () => {
    mockNodes = [modelNode('summarize', 'anthropic')];
    mockEdges = [scopeEdge('gate-1', 'summarize')];

    // openai is granted but only anthropic is actually reached for.
    renderGate({ ...emptyPolicy(), providers: ['anthropic', 'openai'] });

    const row = screen.getByTestId('capability-provider:openai');
    expect(row.getAttribute('data-state')).toBe('granted-unused');
    expect(
      screen.getByTestId('capability-action-provider:openai').textContent,
    ).toBe('tighten');
  });

  it('one-click tighten revokes an unused grant', () => {
    mockNodes = [modelNode('summarize', 'anthropic')];
    mockEdges = [scopeEdge('gate-1', 'summarize')];
    renderGate({ ...emptyPolicy(), providers: ['anthropic', 'openai'] });

    fireEvent.click(screen.getByTestId('capability-action-provider:openai'));

    expect(setNodes).toHaveBeenCalledTimes(1);
    const updater = setNodes.mock.calls[0][0] as (
      n: RFNode<PipelineNodeData>[],
    ) => RFNode<PipelineNodeData>[];
    const [updated] = updater([
      {
        id: 'gate-1',
        position: { x: 0, y: 0 },
        data: {
          type: 'access',
          config: { access_policy: { ...emptyPolicy(), providers: ['anthropic', 'openai'] } },
        },
      },
    ]);
    const policy = updated.data.config?.access_policy as AccessPolicy;
    expect(policy.providers).toEqual(['anthropic']);
  });

  // ── State 3: requested & denied ──────────────────────────────────────────

  it('marks a capability requested-denied when downstream needs what the policy blocks', () => {
    mockNodes = [modelNode('summarize', 'anthropic')];
    mockEdges = [scopeEdge('gate-1', 'summarize')];

    renderGate(emptyPolicy());

    const row = screen.getByTestId('capability-provider:anthropic');
    expect(row.getAttribute('data-state')).toBe('requested-denied');
    expect(
      screen.getByTestId('capability-action-provider:anthropic').textContent,
    ).toBe('grant');
    expect(screen.getByTestId('access-denied-count').textContent).toContain('1 denied');
  });

  it('one-click grant adds the denied capability to the policy', () => {
    mockNodes = [modelNode('summarize', 'anthropic')];
    mockEdges = [scopeEdge('gate-1', 'summarize')];
    renderGate(emptyPolicy());

    fireEvent.click(screen.getByTestId('capability-action-provider:anthropic'));

    const updater = setNodes.mock.calls[0][0] as (
      n: RFNode<PipelineNodeData>[],
    ) => RFNode<PipelineNodeData>[];
    const [updated] = updater([
      {
        id: 'gate-1',
        position: { x: 0, y: 0 },
        data: { type: 'access', config: { access_policy: emptyPolicy() } },
      },
    ]);
    const policy = updated.data.config?.access_policy as AccessPolicy;
    expect(policy.providers).toEqual(['anthropic']);
  });

  it('shows all three states side by side', () => {
    mockNodes = [modelNode('a', 'anthropic'), modelNode('b', 'google')];
    mockEdges = [scopeEdge('gate-1', 'a'), scopeEdge('gate-1', 'b')];

    // anthropic: granted + used. openai: granted, unused. google: needed, denied.
    renderGate({ ...emptyPolicy(), providers: ['anthropic', 'openai'] });

    expect(
      screen.getByTestId('capability-provider:anthropic').getAttribute('data-state'),
    ).toBe('granted-used');
    expect(
      screen.getByTestId('capability-provider:openai').getAttribute('data-state'),
    ).toBe('granted-unused');
    expect(
      screen.getByTestId('capability-provider:google').getAttribute('data-state'),
    ).toBe('requested-denied');
  });

  // ── Scope ────────────────────────────────────────────────────────────────

  it('only governs nodes downstream of it', () => {
    // `upstream` feeds the gate; it is NOT governed by it.
    mockNodes = [modelNode('upstream', 'google'), modelNode('downstream', 'anthropic')];
    mockEdges = [scopeEdge('upstream', 'gate-1'), scopeEdge('gate-1', 'downstream')];

    renderGate(emptyPolicy());

    expect(screen.getByTestId('capability-provider:anthropic')).toBeDefined();
    expect(screen.queryByTestId('capability-provider:google')).toBeNull();
  });

  it('follows the graph transitively', () => {
    mockNodes = [modelNode('far', 'anthropic')];
    mockEdges = [scopeEdge('gate-1', 'middle'), scopeEdge('middle', 'far')];

    renderGate(emptyPolicy());

    expect(
      screen.getByTestId('capability-provider:anthropic').getAttribute('data-state'),
    ).toBe('requested-denied');
  });

  it('treats an ollama node as a request for local models', () => {
    mockNodes = [modelNode('local', 'ollama')];
    mockEdges = [scopeEdge('gate-1', 'local')];

    renderGate(emptyPolicy());

    expect(
      screen.getByTestId('capability-allow_local_models').getAttribute('data-state'),
    ).toBe('requested-denied');
    expect(screen.queryByTestId('capability-provider:ollama')).toBeNull();
  });

  // ── Empty and ceilings ───────────────────────────────────────────────────

  it('explains itself when it governs nothing', () => {
    renderGate(emptyPolicy());
    expect(screen.getByTestId('access-empty')).toBeDefined();
    expect(screen.queryByTestId('access-denied-count')).toBeNull();
  });

  it('renders the numeric ceilings when set', () => {
    renderGate({ ...emptyPolicy(), max_cost_usd: 1.5, max_tokens: 256 });
    const ceilings = screen.getByTestId('access-ceilings');
    expect(ceilings.textContent).toContain('$1.50');
    expect(ceilings.textContent).toContain('256 tok');
  });
});
