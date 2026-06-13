/// <reference types="vite/client" />
import { useEffect, useState, useCallback, useRef } from 'react';
import { useNodesState, useEdgesState, Connection, Edge, addEdge, Node } from 'reactflow';
import Canvas from './canvas/Canvas';
import LeftSidebar from './panels/LeftSidebar';
import RightPanel from './panels/RightPanel';
import MonitorPanel, { NodeStat } from './panels/MonitorPanel';
import TraceModal from './panels/TraceModal';
import OnboardingModal from './panels/OnboardingModal';
import ChatPanel from './panels/ChatPanel';
import { PipelineNodeData } from './canvas/nodes/PipelineNode';
import { toPipelineSchema, fromPipelineSchema, scrubSecrets } from './canvas/serializer';
import { useUndoRedo } from './canvas/useUndoRedo';
import { useToast } from './contexts/ToastContext';
import ExportModal from './components/ExportModal';
import Tour from './components/Tour';

export type AppMode = 'edit' | 'use';

export interface ModelInfo {
  endpoint_id: string;
  provider: string;
  model_name: string;
  max_context: number;
  json_mode: boolean;
  tools: boolean;
  vision: boolean;
}

export interface NodeEstimate {
  usd: number;
  latency_ms: number;
  is_local: boolean;
}

export interface EstimateResponse {
  nodes: Record<string, NodeEstimate>;
  total_usd: number;
  total_latency_ms: number;
  loop_multiplier: number;
}

export default function App() {
  const [backendPort, setBackendPort] = useState<number | null>(null);
  const [backendToken, setBackendToken] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [appMode, setAppMode] = useState<AppMode>('edit');
  const [showExportModal, setShowExportModal] = useState(false);
  
  const [nodes, setNodes, onNodesChange] = useNodesState<PipelineNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);

  const [availableModels, setAvailableModels] = useState<ModelInfo[]>([]);
  const { showToast } = useToast();

  const [backendConnected, setBackendConnected] = useState<boolean | null>(null);
  const [pipelineEstimate, setPipelineEstimate] = useState<EstimateResponse | null>(null);

  // Undo/Redo
  const { takeSnapshot, undo, redo, canUndo, canRedo } = useUndoRedo();

  // Monitor State
  const [runId, setRunId] = useState<string | null>(null);
  const [startTime, setStartTime] = useState<number | null>(null);
  const [nodeStats, setNodeStats] = useState<Record<string, NodeStat>>({});
  const [runTotals, setRunTotals] = useState({ costUsd: 0, tokensIn: 0, tokensOut: 0, iterations: 0 });
  const [showTrace, setShowTrace] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  // Edge animation state
  const [animatedEdgeIds, setAnimatedEdgeIds] = useState<Set<string>>(new Set());

  // We use refs to access latest nodes/edges in callbacks without stale closures
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  useEffect(() => { nodesRef.current = nodes; }, [nodes]);
  useEffect(() => { edgesRef.current = edges; }, [edges]);

  const API_BASE = `http://127.0.0.1:${backendPort || 8000}`;

  useEffect(() => {
    // Listen for backend info from Electron
    if (window.electron) {
      window.electron.onBackendReady((data: { port: number; token: string }) => {
        console.log('Backend is ready on port:', data.port, 'with token:', data.token);
        setBackendPort(data.port);
        setBackendToken(data.token);
      });
    } else {
      // Development fallback
      setBackendPort(8000);
      setBackendToken('test-token');
    }

    if (import.meta.env.DEV) {
      (window as unknown as Record<string, unknown>).setE2EState = (n: Node<PipelineNodeData>[], e: Edge[]) => {
        setNodes(n);
        setEdges(e);
      };
    }
  }, [setNodes, setEdges]);

  useEffect(() => {
    if (!backendPort || !backendToken) return;

    const fetchModels = async () => {
      try {
        const res = await fetch(`${API_BASE}/models`, {
          headers: { 'Authorization': `Bearer ${backendToken}` }
        });
        if (res.ok) {
          const data = await res.json();
          setAvailableModels(data.models || []);
        } else {
          setAvailableModels([]);
        }
      } catch (err) {
        console.warn('Backend not reachable for models fetch:', err);
        setAvailableModels([]);
      }
    };
    
    fetchModels();
  }, [API_BASE, backendToken, showToast]);

  // Polling for backend connection status
  useEffect(() => {
    let mounted = true;
    const checkHealth = async () => {
      try {
        const res = await fetch(`${API_BASE}/health`);
        if (res.ok && mounted) {
          setBackendConnected(true);
        } else if (mounted) {
          setBackendConnected(false);
        }
      } catch {
        if (mounted) setBackendConnected(false);
      }
    };
    checkHealth();
    const interval = setInterval(checkHealth, 5000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [API_BASE]);

  // Fetch estimates when pipeline schema changes
  useEffect(() => {
    if (!backendConnected) return;
    const timeout = setTimeout(async () => {
      try {
        const schema = toPipelineSchema(nodesRef.current as Node<PipelineNodeData>[], edgesRef.current);
        const scrubbed = scrubSecrets(schema);
        if (scrubbed.nodes.length === 0) {
          setPipelineEstimate(null);
          return;
        }

        const headers: Record<string, string> = { 'Content-Type': 'application/json' };
        if (backendToken) headers['Authorization'] = `Bearer ${backendToken}`;

        const res = await fetch(`${API_BASE}/pipelines/estimate`, {
          method: 'POST',
          headers,
          body: JSON.stringify({ pipeline: scrubbed }),
        });

        if (res.ok) {
          const data: EstimateResponse = await res.json();
          setPipelineEstimate(data);
          // Apply estimates to nodes silently
          setNodes((nds) => nds.map((n) => {
            const est = data.nodes[n.id];
            if (est) {
              return { ...n, data: { ...n.data, estimate: est } };
            }
            return n;
          }));
        }
      } catch (err) {
        console.warn('Failed to estimate pipeline', err);
      }
    }, 1000); // debounce 1s

    return () => clearTimeout(timeout);
  }, [nodes, edges, API_BASE, backendToken, backendConnected, setNodes]);

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

  // First selected node for the config panel
  const selectedNode = nodes.find(n => selectedNodeIds.includes(n.id)) || null;

  const updateNodeData = useCallback((id: string, newData: Partial<PipelineNodeData>) => {
    takeSnapshot({ nodes: nodesRef.current, edges: edgesRef.current });
    setNodes((nds) => nds.map((n) => {
      if (n.id === id) {
        return { ...n, data: { ...n.data, ...newData } };
      }
      return n;
    }));
  }, [setNodes, takeSnapshot]);

  /** Update node data WITHOUT taking an undo snapshot (for status-only changes during runs). */
  const updateNodeDataSilent = useCallback((id: string, newData: Partial<PipelineNodeData>) => {
    setNodes((nds) => nds.map((n) => {
      if (n.id === id) {
        return { ...n, data: { ...n.data, ...newData } };
      }
      return n;
    }));
  }, [setNodes]);

  // --- Delete ---
  const deleteNodes = useCallback((nodeIds: string[]) => {
    if (nodeIds.length === 0) return;
    takeSnapshot({ nodes: nodesRef.current, edges: edgesRef.current });
    setNodes((nds) => nds.filter((n) => !nodeIds.includes(n.id)));
    setEdges((eds) => eds.filter((e) => !nodeIds.includes(e.source) && !nodeIds.includes(e.target)));
    setSelectedNodeIds([]);
  }, [setNodes, setEdges, takeSnapshot]);

  /** Called by Canvas before React Flow applies its own remove changes. */
  const handleBeforeDelete = useCallback((nodeIds: string[], edgeIds: string[]) => {
    if (nodeIds.length > 0 || edgeIds.length > 0) {
      takeSnapshot({ nodes: nodesRef.current, edges: edgesRef.current });
    }
  }, [takeSnapshot]);

  // --- Undo / Redo ---
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

  // --- Duplicate ---
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

  // ─── Shared WS Event Handler ────────────────────────────────────────────────
  // Used by both runPipeline (Edit mode) and ChatPanel (Use mode)

  const handleWsEvent = useCallback((data: Record<string, unknown>) => {
    const eventType = (data.event || data.kind) as string;

    if (eventType === 'node_started') {
      const nodeId = data.node_id as string;
      updateNodeDataSilent(nodeId, { status: 'running' });
      setNodeStats(prev => ({
        ...prev,
        [nodeId]: { status: 'running', tokensIn: 0, tokensOut: 0, costUsd: 0 }
      }));
      // Animate edges FROM this node (outgoing)
      const outgoing = edgesRef.current
        .filter(e => e.source === nodeId)
        .map(e => e.id);
      if (outgoing.length > 0) {
        setAnimatedEdgeIds(prev => {
          const next = new Set(prev);
          outgoing.forEach(id => next.add(id));
          return next;
        });
      }
    } else if (eventType === 'node_done') {
      const nodeId = data.node_id as string;
      updateNodeDataSilent(nodeId, { status: 'done' });
      setNodeStats(prev => ({
        ...prev,
        [nodeId]: { 
          status: 'done', 
          tokensIn: (data.tokens_in as number) || 0, 
          tokensOut: (data.tokens_out as number) || prev[nodeId]?.tokensOut || 0, 
          costUsd: (data.cost_usd as number) || 0 
        }
      }));
      if (data.cost_usd || data.tokens_in || data.tokens_out) {
        setRunTotals(prev => ({
          ...prev,
          costUsd: prev.costUsd + ((data.cost_usd as number) || 0),
          tokensIn: prev.tokensIn + ((data.tokens_in as number) || 0),
        }));
      }
      // Animate edges TO downstream nodes
      const downstream = edgesRef.current
        .filter(e => e.source === nodeId)
        .map(e => e.id);
      if (downstream.length > 0) {
        setAnimatedEdgeIds(prev => {
          const next = new Set(prev);
          downstream.forEach(id => next.add(id));
          return next;
        });
      }
    } else if (eventType === 'node_error' || eventType === 'run_error') {
      if (data.node_id) {
        const nodeId = data.node_id as string;
        updateNodeDataSilent(nodeId, { status: 'error' });
        setNodeStats(prev => ({
          ...prev,
          [nodeId]: { ...prev[nodeId], status: 'error' }
        }));
      }
    } else if (eventType === 'run_completed' || eventType === 'run_stopped' || eventType === 'budget_exceeded' || eventType === 'run_halted') {
      if (data.total_cost_usd !== undefined) {
        setRunTotals(prev => ({
          ...prev,
          costUsd: data.total_cost_usd as number,
          tokensIn: data.total_tokens_in !== undefined ? (data.total_tokens_in as number) : prev.tokensIn,
          tokensOut: data.total_tokens_out !== undefined ? (data.total_tokens_out as number) : prev.tokensOut
        }));
      }
      setIsRunning(false);
      setAnimatedEdgeIds(new Set());
    } else if (eventType === 'token') {
      const nodeId = data.node_id as string;
      setNodeStats(prev => {
        const current = prev[nodeId];
        if (!current) return prev;
        return {
          ...prev,
          [nodeId]: { ...current, tokensOut: current.tokensOut + 1 }
        };
      });
      setRunTotals(prev => ({ ...prev, tokensOut: prev.tokensOut + 1 }));
    } else if (eventType === 'loop_iteration') {
      setRunTotals(prev => ({ ...prev, iterations: prev.iterations + 1 }));
    }
  }, [updateNodeDataSilent]);

  /** Reset all node visuals to idle and clear animations. */
  const resetAllNodes = useCallback(() => {
    setNodes(nds => nds.map(n => ({ ...n, data: { ...n.data, status: 'idle' } })));
    setAnimatedEdgeIds(new Set());
  }, [setNodes]);

  const runPipeline = async () => {
    if (nodes.length === 0) return;
    setIsRunning(true);
    setRunId(null);
    setShowTrace(false);
    setStartTime(Date.now());
    setNodeStats({});
    setRunTotals({ costUsd: 0, tokensIn: 0, tokensOut: 0, iterations: 0 });
    
    // reset all statuses on canvas
    resetAllNodes();

    const schema = toPipelineSchema(nodes as Node<PipelineNodeData>[], edges);
    const token = backendToken || 'test-token';

    try {
      const res = await fetch(`${API_BASE}/pipelines/run`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ pipeline: schema, budget_usd: 10.0 })
      });

      if (!res.ok) {
        const text = await res.text();
        console.error('Run failed', text);
        if (res.status === 422) {
          try {
            const errData = JSON.parse(text);
            if (Array.isArray(errData.detail)) {
              errData.detail.forEach((e: any) => {
                showToast(`Validation failed: ${e.msg || JSON.stringify(e)}`, 'error');
              });
            } else {
              showToast(`Validation failed: ${errData.detail || 'Unknown error'}`, 'error');
            }
          } catch {
            showToast(`Validation failed: ${text}`, 'error');
          }
        } else {
          showToast(`Backend error: ${res.statusText}`, 'error');
        }
        setIsRunning(false);
        return;
      }

      const { run_id } = await res.json();
      setRunId(run_id);
      
      const wsUrl = new URL(API_BASE);
      wsUrl.protocol = 'ws:';
      const ws = new WebSocket(`${wsUrl.toString()}/ws/run/${run_id}?token=${token}`.replace('///', '//'));
      wsRef.current = ws;
      
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log('WS event:', data);
        handleWsEvent(data);

        // Terminal events close the WS
        const eventType = (data.event || data.kind) as string;
        if (
          eventType === 'run_completed' ||
          eventType === 'run_stopped' ||
          eventType === 'budget_exceeded' ||
          eventType === 'run_halted'
        ) {
          ws.close();
        }
      };
      
      if (!ws.url.startsWith('ws')) {
          showToast('Invalid websocket URL', 'error');
          setIsRunning(false);
          return;
      }

      ws.onerror = (err) => {
        console.error('WS Error:', err);
        setIsRunning(false);
      };

      ws.onclose = () => {
        setIsRunning(false);
        wsRef.current = null;
      };
    } catch (err) {
      console.error('Failed to start run:', err);
      showToast('Backend not reachable', 'error');
      setIsRunning(false);
    }
  };

  const stopRun = async () => {
    if (!runId) return;
    const token = backendToken || 'test-token';
    try {
      await fetch(`${API_BASE}/runs/${runId}/stop`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
    } catch (err) {
      console.error('Failed to stop run:', err);
    }
  };

  const handleSavePipeline = () => {
    setShowExportModal(true);
  };

  const handleExport = (name: string, description: string) => {
    const schema = toPipelineSchema(nodes as Node<PipelineNodeData>[], edges);
    schema.name = name;
    schema.description = description;
    const scrubbed = scrubSecrets(schema);
    const jsonStr = JSON.stringify(scrubbed, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${schema.name || 'pipeline'}.json`;
    a.click();
    URL.revokeObjectURL(url);
    setShowExportModal(false);
    showToast('Pipeline exported successfully', 'success');
  };

  const handleLoadPipeline = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const jsonStr = e.target?.result as string;
        const schema = JSON.parse(jsonStr);
        if (schema.schema_version !== "2.0") {
          throw new Error("Invalid or missing schema_version. Expected '2.0'.");
        }
        if (!schema.id || !schema.nodes || !schema.edges || !schema.endpoints) {
          throw new Error("Invalid pipeline structure: missing required fields.");
        }
        loadPipelineFromJson(schema);
        showToast('Pipeline imported successfully', 'success');
      } catch (err: any) {
        console.error('Failed to load pipeline', err);
        showToast(err.message || 'Invalid pipeline JSON file', 'error');
      }
      // Reset input so the same file can be loaded again if needed
      event.target.value = '';
    };
    reader.readAsText(file);
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const loadPipelineFromJson = (schema: any) => {
    try {
      takeSnapshot({ nodes: nodesRef.current, edges: edgesRef.current });
      const { nodes: newNodes, edges: newEdges } = fromPipelineSchema(schema);
      setNodes(newNodes);
      setEdges(newEdges);
    } catch (err: any) {
      console.error('Failed to load pipeline from JSON', err);
      showToast(err.message || 'Invalid pipeline JSON', 'error');
    }
  };

  // ─── Chat mode callbacks ──────────────────────────────────────────────────

  const handleChatRunStateChange = useCallback((running: boolean) => {
    setIsRunning(running);
    if (running) {
      setRunId(null);
      setShowTrace(false);
      setStartTime(Date.now());
      setNodeStats({});
      setRunTotals({ costUsd: 0, tokensIn: 0, tokensOut: 0, iterations: 0 });
    }
  }, []);

  return (
    <div style={{ display: 'flex', width: '100vw', height: '100vh' }}>
      <LeftSidebar backendPort={backendPort} backendToken={backendToken} onLoadTemplate={loadPipelineFromJson} API_BASE={API_BASE} />
      <div style={{ flex: 1, position: 'relative', display: 'flex', flexDirection: 'column' }}>
        {/* ─── Top Bar ─── */}
        <div style={{ position: 'absolute', top: 16, left: 16, zIndex: 10, display: 'flex', gap: '8px', alignItems: 'center' }}>
          {/* Mode Switch */}
          <div className="nf-mode-switch" data-testid="mode-switch">
            <button
              className={appMode === 'edit' ? 'active' : ''}
              onClick={() => setAppMode('edit')}
              data-testid="mode-edit"
            >
              ✏️ Edit
            </button>
            <button
              className={appMode === 'use' ? 'active' : ''}
              onClick={() => setAppMode('use')}
              data-testid="mode-use"
            >
              💬 Use
            </button>
          </div>
          
          {/* Connection Status Badge */}
          <div style={{
            marginLeft: '8px',
            padding: '4px 8px',
            borderRadius: '4px',
            fontSize: '12px',
            fontWeight: 'bold',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            background: backendConnected ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)',
            color: backendConnected ? '#10b981' : '#ef4444',
            border: `1px solid ${backendConnected ? '#10b981' : '#ef4444'}`,
          }}>
            <div style={{
              width: '8px', height: '8px', borderRadius: '50%',
              background: backendConnected ? '#10b981' : '#ef4444',
              boxShadow: backendConnected ? '0 0 4px #10b981' : '0 0 4px #ef4444'
            }} />
            {backendConnected === null ? 'Checking...' : backendConnected ? 'Connected' : 'Disconnected — start the backend'}
          </div>

          {appMode === 'edit' && (
            <>
              <button onClick={handleSavePipeline} style={{ padding: '6px 12px', background: '#333', color: '#fff', border: '1px solid #555', borderRadius: '4px', cursor: 'pointer' }}>Export Pipeline</button>
              <label style={{ padding: '6px 12px', background: '#333', color: '#fff', border: '1px solid #555', borderRadius: '4px', cursor: 'pointer' }}>
                Import Pipeline
                <input type="file" accept=".json" onChange={handleLoadPipeline} style={{ display: 'none' }} />
              </label>
              <button
                onClick={handleUndo}
                disabled={!canUndo()}
                title="Undo (Ctrl+Z)"
                style={{
                  padding: '6px 12px',
                  background: canUndo() ? '#333' : '#222',
                  color: canUndo() ? '#fff' : '#666',
                  border: '1px solid #555',
                  borderRadius: '4px',
                  cursor: canUndo() ? 'pointer' : 'not-allowed',
                  fontSize: '14px',
                }}
              >
                ↩ Undo
              </button>
              <button
                onClick={handleRedo}
                disabled={!canRedo()}
                title="Redo (Ctrl+Shift+Z)"
                style={{
                  padding: '6px 12px',
                  background: canRedo() ? '#333' : '#222',
                  color: canRedo() ? '#fff' : '#666',
                  border: '1px solid #555',
                  borderRadius: '4px',
                  cursor: canRedo() ? 'pointer' : 'not-allowed',
                  fontSize: '14px',
                }}
              >
                ↪ Redo
              </button>
            </>
          )}
        </div>

        {/* ─── Top-Right Controls (Edit mode only) ─── */}
        {appMode === 'edit' && (
          <div style={{ position: 'absolute', top: 16, right: 16, zIndex: 10, display: 'flex', gap: '8px' }}>
            {runId && !isRunning && (
              <button 
                onClick={() => setShowTrace(true)}
                style={{
                  padding: '8px 16px',
                  backgroundColor: '#3b82f6',
                  color: 'white',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontWeight: 'bold'
                }}
              >
                View Trace
              </button>
            )}
            <button 
              data-testid="run-pipeline-button"
              onClick={runPipeline}
              disabled={isRunning || nodes.length === 0}
              style={{
                padding: '8px 16px',
                backgroundColor: isRunning ? '#555' : '#10b981',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: isRunning || nodes.length === 0 ? 'not-allowed' : 'pointer',
                fontWeight: 'bold'
              }}
            >
              {isRunning ? 'Running...' : 'Run Pipeline'}
            </button>
            {pipelineEstimate && (
              <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', fontSize: '11px', color: '#aaa', marginLeft: '4px' }}>
                <div>Est: ~${pipelineEstimate.total_usd.toFixed(4)} &middot; ~{(pipelineEstimate.total_latency_ms/1000).toFixed(1)}s</div>
                {pipelineEstimate.loop_multiplier > 1 && (
                  <div style={{ color: '#f59e0b', fontSize: '10px' }}>⚠️ Loop ×{pipelineEstimate.loop_multiplier} applied</div>
                )}
              </div>
            )}
          </div>
        )}
        
        {/* ─── Main Content Area ─── */}
        <div style={{ flex: 1, position: 'relative' }}>
          {appMode === 'edit' ? (
            <Canvas 
              nodes={nodes} 
              edges={edges} 
              onNodesChange={onNodesChange} 
              onEdgesChange={onEdgesChange} 
              onConnect={onConnect}
              setNodes={setNodes}
              onSelectionChange={(ids) => setSelectedNodeIds(ids)}
              onBeforeDelete={handleBeforeDelete}
              onUndo={handleUndo}
              onRedo={handleRedo}
              onDuplicate={handleDuplicate}
              animatedEdgeIds={animatedEdgeIds}
            />
          ) : (
            <ChatPanel
              nodes={nodes}
              edges={edges}
              backendPort={backendPort}
              backendToken={backendToken}
              apiBase={API_BASE}
              isRunning={isRunning}
              onRunStateChange={handleChatRunStateChange}
              updateNodeData={updateNodeDataSilent}
              resetNodes={resetAllNodes}
              onWsEvent={handleWsEvent}
            />
          )}
        </div>

        {(runId || isRunning) && (
          <div style={{ height: 250, position: 'relative' }}>
            <MonitorPanel 
              runId={runId} 
              isRunning={isRunning} 
              nodeStats={nodeStats} 
              runTotals={runTotals} 
              startTime={startTime} 
              onStop={stopRun}
            />
          </div>
        )}
      </div>
      <RightPanel 
        selectedNode={selectedNode} 
        updateNodeData={updateNodeData} 
        availableModels={availableModels}
        onDeleteNode={(id) => deleteNodes([id])}
      />

      {showTrace && runId && (
        <TraceModal 
          runId={runId} 
          backendPort={backendPort} 
          backendToken={backendToken} 
          onClose={() => setShowTrace(false)} 
        />
      )}

      <OnboardingModal API_BASE={API_BASE} onLoadTemplate={loadPipelineFromJson} />
      <Tour />

      {showExportModal && (
        <ExportModal
          initialName={toPipelineSchema(nodes as Node<PipelineNodeData>[], edges).name || 'My Pipeline'}
          onExport={handleExport}
          onCancel={() => setShowExportModal(false)}
        />
      )}
    </div>
  );
}

// Ensure typescript knows about the global electron object from preload
declare global {
  interface Window {
    electron?: {
      onBackendReady: (callback: (data: { port: number; token: string }) => void) => void;
    };
  }
}
