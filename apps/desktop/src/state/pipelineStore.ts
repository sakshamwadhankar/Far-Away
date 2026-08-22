import { useState, useCallback, useRef, useEffect } from 'react';
import { useNodesState, useEdgesState, addEdge, Connection, Edge } from 'reactflow';
import { useUndoRedo } from '../canvas/useUndoRedo';
import type { PipelineNodeData } from '../canvas/nodes/PipelineNode';

export function usePipelineStore(showToast: (msg: string, type: 'error' | 'success') => void) {
  const [nodes, setNodes, onNodesChange] = useNodesState<PipelineNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);

  const { takeSnapshot, undo, redo, canUndo, canRedo } = useUndoRedo();

  // We use refs to access latest nodes/edges in callbacks without stale closures
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  useEffect(() => { nodesRef.current = nodes; }, [nodes]);
  useEffect(() => { edgesRef.current = edges; }, [edges]);

  const onConnect = useCallback((params: Edge | Connection) => {
    const sourceHandleType = params.sourceHandle?.split(':')[0];
    const targetHandleType = params.targetHandle?.split(':')[0];
    if (sourceHandleType !== targetHandleType) {
      showToast(`Incompatible port types: cannot connect ${sourceHandleType} to ${targetHandleType}`, 'error');
      return;
    }
    takeSnapshot({ nodes: nodesRef.current, edges: edgesRef.current });
    setEdges((eds) => addEdge(params, eds));
  }, [setEdges, takeSnapshot, showToast]);

  const updateNodeData = useCallback((id: string, newData: Partial<PipelineNodeData>) => {
    takeSnapshot({ nodes: nodesRef.current, edges: edgesRef.current });
    setNodes((nds) => nds.map((n) => {
      if (n.id === id) {
        return { ...n, data: { ...n.data, ...newData } };
      }
      return n;
    }));
  }, [setNodes, takeSnapshot]);

  const updateNodeDataSilent = useCallback((id: string, newData: Partial<PipelineNodeData>) => {
    setNodes((nds) => nds.map((n) => {
      if (n.id === id) {
        return { ...n, data: { ...n.data, ...newData } };
      }
      return n;
    }));
  }, [setNodes]);

  const deleteNodes = useCallback((nodeIds: string[]) => {
    if (nodeIds.length === 0) return;
    takeSnapshot({ nodes: nodesRef.current, edges: edgesRef.current });
    setNodes((nds) => nds.filter((n) => !nodeIds.includes(n.id)));
    setEdges((eds) => eds.filter((e) => !nodeIds.includes(e.source) && !nodeIds.includes(e.target)));
    setSelectedNodeIds([]);
  }, [setNodes, setEdges, takeSnapshot]);

  const handleBeforeDelete = useCallback((nodeIds: string[], edgeIds: string[]) => {
    if (nodeIds.length > 0 || edgeIds.length > 0) {
      takeSnapshot({ nodes: nodesRef.current, edges: edgesRef.current });
    }
  }, [takeSnapshot]);

  const handleUndo = useCallback(() => {
    const prev = undo({ nodes: nodesRef.current, edges: edgesRef.current });
    if (prev) {
      setNodes(prev.nodes);
      setEdges(prev.edges);
    }
  }, [undo, setNodes, setEdges]);

  const handleRedo = useCallback(() => {
    const next = redo({ nodes: nodesRef.current, edges: edgesRef.current });
    if (next) {
      setNodes(next.nodes);
      setEdges(next.edges);
    }
  }, [redo, setNodes, setEdges]);

  const handleDuplicate = useCallback(() => {
    if (selectedNodeIds.length === 0) return;
    takeSnapshot({ nodes: nodesRef.current, edges: edgesRef.current });
    const toDuplicate = nodesRef.current.filter((n) => selectedNodeIds.includes(n.id));
    const newNodes = toDuplicate.map((n) => ({
      ...n,
      id: `node-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      position: { x: n.position.x + 50, y: n.position.y + 50 },
      data: { ...n.data },
      selected: false,
    }));
    setNodes((nds) => [...nds, ...newNodes]);
  }, [selectedNodeIds, setNodes, takeSnapshot]);

  return {
    nodes,
    setNodes,
    onNodesChange,
    edges,
    setEdges,
    onEdgesChange,
    selectedNodeIds,
    setSelectedNodeIds,
    nodesRef,
    edgesRef,
    onConnect,
    updateNodeData,
    updateNodeDataSilent,
    deleteNodes,
    handleBeforeDelete,
    handleUndo,
    handleRedo,
    handleDuplicate,
    takeSnapshot,
    canUndo,
    canRedo
  };
}
