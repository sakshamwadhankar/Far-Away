import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useUndoRedo, CanvasSnapshot } from './useUndoRedo';

function makeSnapshot(nodeIds: string[], edgeIds: string[] = []): CanvasSnapshot {
  return {
    nodes: nodeIds.map((id) => ({
      id,
      type: 'pipelineNode' as const,
      position: { x: 0, y: 0 },
      data: { type: 'input' as const },
    })),
    edges: edgeIds.map((id) => ({
      id,
      source: 'a',
      target: 'b',
    })),
  };
}

describe('useUndoRedo', () => {
  it('undo restores the previous snapshot', () => {
    const { result } = renderHook(() => useUndoRedo());

    const state1 = makeSnapshot(['n1']);
    const state2 = makeSnapshot(['n1', 'n2']);

    // Take snapshot of state1, then "mutate" to state2
    act(() => result.current.takeSnapshot(state1));

    expect(result.current.canUndo()).toBe(true);

    let restored: CanvasSnapshot | null = null;
    act(() => {
      restored = result.current.undo(state2);
    });

    expect(restored).not.toBeNull();
    expect(restored!.nodes).toHaveLength(1);
    expect(restored!.nodes[0].id).toBe('n1');
  });

  it('redo restores the undone snapshot', () => {
    const { result } = renderHook(() => useUndoRedo());

    const state1 = makeSnapshot(['n1']);
    const state2 = makeSnapshot(['n1', 'n2']);

    act(() => result.current.takeSnapshot(state1));

    // Undo: go from state2 back to state1
    let restored: CanvasSnapshot | null = null;
    act(() => {
      restored = result.current.undo(state2);
    });
    expect(restored!.nodes).toHaveLength(1);

    expect(result.current.canRedo()).toBe(true);

    // Redo: go from state1 back to state2
    let redone: CanvasSnapshot | null = null;
    act(() => {
      redone = result.current.redo(restored!);
    });

    expect(redone).not.toBeNull();
    expect(redone!.nodes).toHaveLength(2);
  });

  it('new action after undo clears the redo stack', () => {
    const { result } = renderHook(() => useUndoRedo());

    const state1 = makeSnapshot(['n1']);
    const state2 = makeSnapshot(['n1', 'n2']);
    const state3 = makeSnapshot(['n1', 'n3']);

    act(() => result.current.takeSnapshot(state1));

    // Undo from state2
    act(() => {
      result.current.undo(state2);
    });
    expect(result.current.canRedo()).toBe(true);

    // New action (takeSnapshot) should clear redo stack
    act(() => result.current.takeSnapshot(state3));
    expect(result.current.canRedo()).toBe(false);
  });

  it('returns null when undo stack is empty', () => {
    const { result } = renderHook(() => useUndoRedo());

    expect(result.current.canUndo()).toBe(false);

    let restored: CanvasSnapshot | null = null;
    act(() => {
      restored = result.current.undo(makeSnapshot(['n1']));
    });
    expect(restored).toBeNull();
  });

  it('returns null when redo stack is empty', () => {
    const { result } = renderHook(() => useUndoRedo());

    expect(result.current.canRedo()).toBe(false);

    let restored: CanvasSnapshot | null = null;
    act(() => {
      restored = result.current.redo(makeSnapshot(['n1']));
    });
    expect(restored).toBeNull();
  });

  it('respects max history depth of 50', () => {
    const { result } = renderHook(() => useUndoRedo());

    // Push 55 snapshots
    for (let i = 0; i < 55; i++) {
      act(() => result.current.takeSnapshot(makeSnapshot([`n${i}`])));
    }

    // Should be able to undo exactly 50 times
    let undoCount = 0;
    let current = makeSnapshot(['latest']);
    while (true) {
      let restored: CanvasSnapshot | null = null;
      act(() => {
        restored = result.current.undo(current);
      });
      if (!restored) break;
      current = restored;
      undoCount++;
    }
    expect(undoCount).toBe(50);
  });
});
