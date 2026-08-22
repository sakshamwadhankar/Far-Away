import { useCallback } from 'react';
import type { Node, Edge } from 'reactflow';
import type { PipelineNodeData } from '../canvas/nodes/PipelineNode';
import type { Pipeline } from '@shared/types';
import { toPipelineSchema, fromPipelineSchema, scrubSecrets } from '../canvas/serializer';

import type { ChatMessage } from '../panels/ChatPanel';
import type { CustomNodeDef } from '../panels/LeftSidebar';

interface UsePipelineActionsProps {
  nodes: Node<PipelineNodeData>[];
  edges: Edge[];
  nodesRef: React.MutableRefObject<Node<PipelineNodeData>[]>;
  edgesRef: React.MutableRefObject<Edge[]>;
  setNodes: (nodes: Node<PipelineNodeData>[]) => void;
  setEdges: (edges: Edge[]) => void;
  takeSnapshot: (state: { nodes: Node<PipelineNodeData>[]; edges: Edge[] }) => void;
  setChatMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  setChatInputValues: (vals: Record<string, string>) => void;
  setRunTotals: React.Dispatch<React.SetStateAction<{ costUsd: number; tokensIn: number; tokensOut: number; iterations: number; }>>;
  showToast: (msg: string, type: 'error' | 'success') => void;
  setShowExportModal: (show: boolean) => void;
  setShowPublishModal: (show: boolean) => void;
  setShowCustomNodeModal: (show: boolean) => void;
  setCustomNodes: React.Dispatch<React.SetStateAction<CustomNodeDef[]>>;
  fetchCustomNodes: () => Promise<void>;
  API_BASE: string;
  backendToken: string | null;
}

export function usePipelineActions({
  nodes, edges, nodesRef, edgesRef, setNodes, setEdges, takeSnapshot,
  setChatMessages, setChatInputValues, setRunTotals, showToast,
  setShowExportModal, setShowPublishModal, setShowCustomNodeModal,
  setCustomNodes, fetchCustomNodes, API_BASE, backendToken
}: UsePipelineActionsProps) {
  
  const handleExport = useCallback((name: string, description: string) => {
    const schema = toPipelineSchema(nodes, edges);
    schema.name = name; schema.description = description;
    const blob = new Blob([JSON.stringify(scrubSecrets(schema), null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `${schema.name || 'pipeline'}.json`; a.click();
    URL.revokeObjectURL(url);
    setShowExportModal(false);
    showToast('Pipeline exported successfully', 'success');
  }, [nodes, edges, setShowExportModal, showToast]);

  const loadPipelineFromJson = useCallback((schema: Pipeline) => {
    try {
      takeSnapshot({ nodes: nodesRef.current, edges: edgesRef.current });
      const { nodes: newNodes, edges: newEdges } = fromPipelineSchema(schema);
      newNodes.forEach((node) => { if (node.data.type === 'model') node.data.endpoint_ref = ''; });
      setNodes(newNodes); setEdges(newEdges); setChatMessages([]); setChatInputValues({});
    } catch (err) {
      console.error('Failed to load pipeline from JSON', err);
      showToast(err instanceof Error && err.message ? err.message : 'Invalid pipeline JSON', 'error');
    }
  }, [takeSnapshot, nodesRef, edgesRef, setNodes, setEdges, setChatMessages, setChatInputValues, showToast]);

  const handleLoadPipeline = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const schema = JSON.parse(e.target?.result as string) as Pipeline;
        if (schema.schema_version !== "2.0") throw new Error("Invalid or missing schema_version. Expected '2.0'.");
        if (!schema.id || !schema.nodes || !schema.edges || !schema.endpoints) throw new Error("Invalid pipeline structure: missing required fields.");
        loadPipelineFromJson(schema);
        showToast('Pipeline imported successfully', 'success');
      } catch (err) {
        console.error('Failed to load pipeline', err);
        showToast(err instanceof Error && err.message ? err.message : 'Invalid pipeline JSON file', 'error');
      }
      event.target.value = '';
    };
    reader.readAsText(file);
  }, [loadPipelineFromJson, showToast]);

  const handleClearWorkspace = useCallback(() => {
    if (window.confirm('Are you sure you want to clear the entire workspace?')) {
      takeSnapshot({ nodes: nodesRef.current, edges: edgesRef.current });
      setNodes([]); setEdges([]); setChatMessages([]); setChatInputValues({});
      setRunTotals({ costUsd: 0, tokensIn: 0, tokensOut: 0, iterations: 0 });
      showToast('Workspace cleared', 'success');
    }
  }, [takeSnapshot, nodesRef, edgesRef, setNodes, setEdges, setChatMessages, setChatInputValues, setRunTotals, showToast]);

  const handlePublishToLibrary = useCallback(async (name: string, description: string, author: string, tags: string) => {
    if (nodes.length === 0) {
      showToast('No pipeline to publish — add some nodes first.', 'error');
      setShowPublishModal(false);
      return;
    }
    const scrubbed = scrubSecrets(toPipelineSchema(nodes, edges));
    try {
      const res = await fetch(`${API_BASE}/library/publish`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${backendToken || 'test-token'}` },
        body: JSON.stringify({ name, description, author, tags, pipeline: scrubbed }),
      });
      if (res.ok) showToast('Pipeline published to library!', 'success');
      else showToast(`Publish failed: ${await res.text()}`, 'error');
    } catch (err) {
      console.error('Failed to publish pipeline:', err);
      showToast('Backend not reachable', 'error');
    }
    setShowPublishModal(false);
  }, [nodes, edges, API_BASE, backendToken, showToast, setShowPublishModal]);

  const handleSaveCustomNode = useCallback(async (data: {
    name: string;
    description: string;
    author: string;
    icon_color: string;
    inputs: { name: string; type: string }[];
    outputs: { name: string; type: string }[];
    template: string;
    tags: string;
  }) => {
    try {
      const res = await fetch(`${API_BASE}/custom-nodes`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${backendToken || 'test-token'}` },
        body: JSON.stringify(data),
      });
      if (res.ok) {
        showToast(`Custom node "${data.name}" created!`, 'success');
        fetchCustomNodes();
      } else {
        showToast(`Failed to save node: ${await res.text()}`, 'error');
      }
    } catch (err) {
      console.error('Failed to save custom node:', err);
      showToast('Backend not reachable', 'error');
    }
    setShowCustomNodeModal(false);
  }, [API_BASE, backendToken, showToast, fetchCustomNodes, setShowCustomNodeModal]);

  const handleDeleteCustomNode = useCallback(async (nodeId: string) => {
    try {
      const res = await fetch(`${API_BASE}/custom-nodes/${nodeId}`, {
        method: 'DELETE', headers: { 'Authorization': `Bearer ${backendToken || 'test-token'}` },
      });
      if (res.ok) {
        setCustomNodes(prev => prev.filter(n => n.id !== nodeId));
        showToast('Custom node deleted', 'success');
      }
    } catch (e) {
      console.warn('Failed to delete custom node:', e);
    }
  }, [API_BASE, backendToken, setCustomNodes, showToast]);

  return {
    handleExport, loadPipelineFromJson, handleLoadPipeline, handleClearWorkspace,
    handlePublishToLibrary, handleSaveCustomNode, handleDeleteCustomNode
  };
}
