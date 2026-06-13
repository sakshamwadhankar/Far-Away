import { useCallback, useRef, useEffect } from 'react';
import ReactFlow, { Background, Controls, MiniMap, useReactFlow, OnNodesChange, OnEdgesChange, Connection, Edge, Node, NodeChange, EdgeChange } from 'reactflow';
import PipelineNode, { PipelineNodeData } from './nodes/PipelineNode';

const nodeTypes = {
  pipelineNode: PipelineNode,
};

interface CanvasProps {
  nodes: Node<PipelineNodeData>[];
  edges: Edge[];
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: (connection: Connection | Edge) => void;
  setNodes: React.Dispatch<React.SetStateAction<Node<PipelineNodeData>[]>>;
  onSelectionChange: (ids: string[]) => void;
  /** Called BEFORE a delete is applied so the caller can snapshot for undo. */
  onBeforeDelete?: (nodeIds: string[], edgeIds: string[]) => void;
  onUndo?: () => void;
  onRedo?: () => void;
  onDuplicate?: () => void;
}

export default function Canvas({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  setNodes,
  onSelectionChange,
  onBeforeDelete,
  onUndo,
  onRedo,
  onDuplicate,
}: CanvasProps) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const { screenToFlowPosition } = useReactFlow();

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      const reactFlowBounds = reactFlowWrapper.current?.getBoundingClientRect();
      const rawData = event.dataTransfer.getData('application/reactflow');

      if (!rawData || !reactFlowBounds) {
        return;
      }

      const { type, data } = JSON.parse(rawData);

      // We need to map the screen coordinates to flow coordinates
      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      const newNode: Node<PipelineNodeData> = {
        id: `node-${Date.now()}`,
        type: 'pipelineNode',
        position,
        data: { type, ...data },
      };

      setNodes((nds) => nds.concat(newNode));
    },
    [screenToFlowPosition, setNodes]
  );

  // Intercept node changes to fire onBeforeDelete before removes are applied
  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      const removes = changes.filter(
        (c): c is NodeChange & { type: 'remove'; id: string } => c.type === 'remove'
      );
      if (removes.length > 0 && onBeforeDelete) {
        const removedNodeIds = removes.map((r) => r.id);
        // Also collect edges that will be orphaned
        const orphanedEdgeIds = edges
          .filter((e) => removedNodeIds.includes(e.source) || removedNodeIds.includes(e.target))
          .map((e) => e.id);
        onBeforeDelete(removedNodeIds, orphanedEdgeIds);
      }
      onNodesChange(changes);
    },
    [onNodesChange, onBeforeDelete, edges]
  );

  // Intercept edge changes to fire onBeforeDelete before removes are applied
  const handleEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      const removes = changes.filter(
        (c): c is EdgeChange & { type: 'remove'; id: string } => c.type === 'remove'
      );
      if (removes.length > 0 && onBeforeDelete) {
        onBeforeDelete([], removes.map((r) => r.id));
      }
      onEdgesChange(changes);
    },
    [onEdgesChange, onBeforeDelete]
  );

  // Keyboard shortcuts: Ctrl+Z (undo), Ctrl+Shift+Z (redo), Ctrl+D (duplicate)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't intercept when user is typing in an input/textarea/select
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      if (e.ctrlKey || e.metaKey) {
        if (e.key === 'z' && !e.shiftKey) {
          e.preventDefault();
          onUndo?.();
        } else if ((e.key === 'z' && e.shiftKey) || e.key === 'y') {
          e.preventDefault();
          onRedo?.();
        } else if (e.key === 'd') {
          e.preventDefault();
          onDuplicate?.();
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onUndo, onRedo, onDuplicate]);

  // Memoize selection handler to prevent render loop with React Flow's onSelectionChange
  const lastSelectionRef = useRef<string>('');
  const handleSelectionChange = useCallback(
    (params: { nodes: Node<PipelineNodeData>[]; edges: Edge[] }) => {
      const nodeIds = params.nodes.map((n) => n.id);
      const key = nodeIds.sort().join(',');
      if (key !== lastSelectionRef.current) {
        lastSelectionRef.current = key;
        onSelectionChange(nodeIds);
      }
    },
    [onSelectionChange]
  );

  return (
    <div style={{ width: '100%', height: '100%' }} ref={reactFlowWrapper}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={handleNodesChange}
        onEdgesChange={handleEdgesChange}
        onConnect={onConnect}
        deleteKeyCode={['Backspace', 'Delete']}
        multiSelectionKeyCode="Shift"
        onSelectionChange={handleSelectionChange}
        onInit={() => {}}
        onDrop={onDrop}
        onDragOver={onDragOver}
        nodeTypes={nodeTypes}
        fitView
      >
        <Background color="#ccc" gap={16} />
        <Controls />
        <MiniMap nodeStrokeColor={(_n) => '#666'} nodeColor={(_n) => '#222'} />
      </ReactFlow>
    </div>
  );
}

