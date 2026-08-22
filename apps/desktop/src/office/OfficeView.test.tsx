/**
 * office/OfficeView.test.tsx
 *
 * jsdom has no real canvas implementation, so these tests verify that the
 * view renders and interacts correctly even when drawing is unavailable —
 * plus the DOM overlays (legend, name plates, tooltip, selection).
 */
import { describe, it, expect, vi, beforeAll } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import OfficeView from './OfficeView';
import { DESK_H, DESK_W, computeDeskLayout, fitScale } from './layout';
import type { PipelineNodeData } from '../canvas/nodes/PipelineNode';
import type { Node as RFNode, Edge as RFEdge } from 'reactflow';

// jsdom's getContext throws "not implemented"; stub a null-returning 2D ctx.
beforeAll(() => {
  (HTMLCanvasElement.prototype as unknown as { getContext: () => null }).getContext = () => null;
});

function makeNodes(statuses: Array<'idle' | 'running' | 'done' | 'error'>): RFNode<PipelineNodeData>[] {
  const types: PipelineNodeData['type'][] = ['input', 'model', 'judge', 'output'];
  return statuses.map((status, i) => ({
    id: `n${i + 1}`,
    position: { x: i * 100, y: 0 },
    data: { type: types[i % types.length], status },
  }));
}

const baseProps = () => ({
  edges: [] as RFEdge[],
  nodeStats: {} as Record<string, { status: 'idle' | 'running' | 'done' | 'error'; tokensIn: number; tokensOut: number; costUsd: number }>,
  animatedEdgeIds: new Set<string>(),
  isRunning: false,
  startTime: null,
  selectedNodeIds: [] as string[],
  onSelectNode: vi.fn(),
});

describe('OfficeView', () => {
  it('shows the empty-state hint when there are no nodes', () => {
    render(<OfficeView {...baseProps()} nodes={[]} />);
    expect(screen.getByTestId('office-empty-hint')).toBeDefined();
    expect(screen.queryByTestId('office-canvas')).toBeNull();
  });

  it('renders a canvas and legend when nodes exist', () => {
    const nodes = makeNodes(['idle', 'running', 'done', 'error']);
    render(<OfficeView {...baseProps()} nodes={nodes} />);
    expect(screen.getByTestId('office-view')).toBeDefined();
    expect(screen.getByTestId('office-canvas')).toBeDefined();
    for (const label of ['Idle', 'Working…', 'Done', 'Error']) {
      expect(screen.getByText(label)).toBeDefined();
    }
  });

  it('does not crash without canvas 2D support', () => {
    const nodes = makeNodes(['running']);
    expect(() => render(<OfficeView {...baseProps()} nodes={nodes} />)).not.toThrow();
  });

  it('selects a node when its desk is clicked', () => {
    // Map every rect to the origin so mouse math is deterministic.
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      x: 0, y: 0, top: 0, left: 0, width: 800, height: 600, right: 800, bottom: 600,
      toJSON: () => {},
    } as DOMRect);

    const props = baseProps();
    const nodes = makeNodes(['idle']);
    render(<OfficeView {...props} nodes={nodes} />);

    // Compute where desk #1 sits using the same pure helpers as the view
    // (jsdom reports zero-size containers → fitScale falls back to 1).
    const layout = computeDeskLayout(1);
    const scale = fitScale(0, 0, layout.roomW, layout.roomH);
    const slot = layout.slots[0];
    fireEvent.mouseMove(screen.getByTestId('office-view'), {
      clientX: (slot.x + DESK_W / 2) * scale,
      clientY: (slot.y + DESK_H / 2) * scale,
    });
    fireEvent.click(screen.getByTestId('office-view'), {
      clientX: (slot.x + DESK_W / 2) * scale,
      clientY: (slot.y + DESK_H / 2) * scale,
    });
    expect(props.onSelectNode).toHaveBeenCalledWith('n1');

    vi.restoreAllMocks();
  });
});
