import { useCallback, useRef } from 'react';
import { Node as RFNode, Edge as RFEdge } from 'reactflow';
import { PipelineNodeData } from './nodes/PipelineNode';

/** Maximum number of undo snapshots to keep. */
const MAX_HISTORY = 50;

export interface CanvasSnapshot {
  nodes: RFNode<PipelineNodeData>[];
  edges: RFEdge[];
}

export interface UndoRedoActions {
  /** Call BEFORE any mutation to capture the current state. */
  takeSnapshot: (current: CanvasSnapshot) => void;
  /** Undo last action. Returns the restored snapshot or null if stack is empty. */
  undo: (current: CanvasSnapshot) => CanvasSnapshot | null;
  /** Redo last undone action. Returns the restored snapshot or null if stack is empty. */
  redo: (current: CanvasSnapshot) => CanvasSnapshot | null;
  /** Whether undo is possible. */
  canUndo: () => boolean;
  /** Whether redo is possible. */
  canRedo: () => boolean;
}

/**
 * Lightweight undo/redo hook for canvas state.
 *
 * Usage:
 *   const { takeSnapshot, undo, redo, canUndo, canRedo } = useUndoRedo();
 *   // Before any mutation:
 *   takeSnapshot({ nodes, edges });
 *   // To undo:
 *   const prev = undo({ nodes, edges });
 *   if (prev) { setNodes(prev.nodes); setEdges(prev.edges); }
 */
export function useUndoRedo(): UndoRedoActions {
  const undoStack = useRef<CanvasSnapshot[]>([]);
  const redoStack = useRef<CanvasSnapshot[]>([]);

  const takeSnapshot = useCallback((current: CanvasSnapshot) => {
    // Deep clone to avoid reference issues
    const snapshot: CanvasSnapshot = {
      nodes: JSON.parse(JSON.stringify(current.nodes)),
      edges: JSON.parse(JSON.stringify(current.edges)),
    };
    undoStack.current.push(snapshot);
    if (undoStack.current.length > MAX_HISTORY) {
      undoStack.current.shift();
    }
    // Any new action clears redo stack
    redoStack.current = [];
  }, []);

  const undo = useCallback((current: CanvasSnapshot): CanvasSnapshot | null => {
    const prev = undoStack.current.pop();
    if (!prev) return null;

    // Push current state to redo stack
    redoStack.current.push({
      nodes: JSON.parse(JSON.stringify(current.nodes)),
      edges: JSON.parse(JSON.stringify(current.edges)),
    });

    return prev;
  }, []);

  const redo = useCallback((current: CanvasSnapshot): CanvasSnapshot | null => {
    const next = redoStack.current.pop();
    if (!next) return null;

    // Push current state to undo stack
    undoStack.current.push({
      nodes: JSON.parse(JSON.stringify(current.nodes)),
      edges: JSON.parse(JSON.stringify(current.edges)),
    });

    return next;
  }, []);

  const canUndo = useCallback(() => undoStack.current.length > 0, []);
  const canRedo = useCallback(() => redoStack.current.length > 0, []);

  return { takeSnapshot, undo, redo, canUndo, canRedo };
}
