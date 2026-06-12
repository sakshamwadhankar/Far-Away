/// <reference types="vite/client" />
import { useEffect, useState, useCallback, useRef } from 'react';
import { useNodesState, useEdgesState, Connection, Edge, addEdge } from 'reactflow';
import Canvas from './canvas/Canvas';
import LeftSidebar from './panels/LeftSidebar';
import RightPanel from './panels/RightPanel';
import MonitorPanel, { NodeStat } from './panels/MonitorPanel';
import TraceModal from './panels/TraceModal';
import { PipelineNodeData } from './canvas/nodes/PipelineNode';
import { toPipelineSchema, fromPipelineSchema, scrubSecrets } from './canvas/serializer';

export default function App() {
  const [backendPort, setBackendPort] = useState<number | null>(null);
  const [backendToken, setBackendToken] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  
  const [nodes, setNodes, onNodesChange] = useNodesState<PipelineNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // Monitor State
  const [runId, setRunId] = useState<string | null>(null);
  const [startTime, setStartTime] = useState<number | null>(null);
  const [nodeStats, setNodeStats] = useState<Record<string, NodeStat>>({});
  const [runTotals, setRunTotals] = useState({ costUsd: 0, tokensIn: 0, tokensOut: 0, iterations: 0 });
  const [showTrace, setShowTrace] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

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
      (window as any).setE2EState = (n: any, e: any) => {
        setNodes(n);
        setEdges(e);
      };
    }
  }, [setNodes, setEdges]);

  const onConnect = useCallback((params: Edge | Connection) => {
    const sourceHandleType = params.sourceHandle?.split(':')[0];
    const targetHandleType = params.targetHandle?.split(':')[0];
    if (sourceHandleType !== targetHandleType) {
      console.warn('Incompatible port types', sourceHandleType, targetHandleType);
      return;
    }
    setEdges((eds) => addEdge(params, eds));
  }, [setEdges]);

  const selectedNode = nodes.find(n => n.id === selectedNodeId) || null;

  const updateNodeData = useCallback((id: string, newData: Partial<PipelineNodeData>) => {
    setNodes((nds) => nds.map((n) => {
      if (n.id === id) {
        return { ...n, data: { ...n.data, ...newData } };
      }
      return n;
    }));
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
    setNodes(nds => nds.map(n => ({ ...n, data: { ...n.data, status: 'idle' } })));

    const schema = toPipelineSchema(nodes as any, edges);
    const port = backendPort || 8000;
    const token = backendToken || 'test-token';

    try {
      const res = await fetch(`http://127.0.0.1:${port}/pipelines/run`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ pipeline: schema, budget_usd: 10.0 })
      });

      if (!res.ok) {
        console.error('Run failed', await res.text());
        setIsRunning(false);
        return;
      }

      const { run_id } = await res.json();
      setRunId(run_id);
      
      const ws = new WebSocket(`ws://127.0.0.1:${port}/ws/run/${run_id}?token=${token}`);
      wsRef.current = ws;
      
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log('WS event:', data);
        
        const eventType = data.event || data.kind; // Handle both mapping cases

        if (eventType === 'node_started') {
          updateNodeData(data.node_id, { status: 'running' });
          setNodeStats(prev => ({
            ...prev,
            [data.node_id]: { status: 'running', tokensIn: 0, tokensOut: 0, costUsd: 0 }
          }));
        } else if (eventType === 'node_done') {
          updateNodeData(data.node_id, { status: 'done' });
          setNodeStats(prev => ({
            ...prev,
            [data.node_id]: { 
              status: 'done', 
              tokensIn: data.tokens_in || 0, 
              tokensOut: data.tokens_out || prev[data.node_id]?.tokensOut || 0, 
              costUsd: data.cost_usd || 0 
            }
          }));
          if (data.cost_usd || data.tokens_in || data.tokens_out) {
            setRunTotals(prev => ({
              ...prev,
              costUsd: prev.costUsd + (data.cost_usd || 0),
              tokensIn: prev.tokensIn + (data.tokens_in || 0),
              // We don't add token_out here if it was streamed, but we could sync it
            }));
          }
        } else if (eventType === 'node_error' || eventType === 'run_error') {
          if (data.node_id) {
            updateNodeData(data.node_id, { status: 'error' });
            setNodeStats(prev => ({
              ...prev,
              [data.node_id]: { ...prev[data.node_id], status: 'error' }
            }));
          }
        } else if (eventType === 'run_completed' || eventType === 'run_stopped' || eventType === 'budget_exceeded' || eventType === 'run_halted') {
          if (data.total_cost_usd !== undefined) {
            setRunTotals(prev => ({
              ...prev,
              costUsd: data.total_cost_usd,
              tokensIn: data.total_tokens_in !== undefined ? data.total_tokens_in : prev.tokensIn,
              tokensOut: data.total_tokens_out !== undefined ? data.total_tokens_out : prev.tokensOut
            }));
          }
          setIsRunning(false);
          ws.close();
        } else if (eventType === 'token') {
          setNodeStats(prev => {
            const current = prev[data.node_id];
            if (!current) return prev;
            return {
              ...prev,
              [data.node_id]: { ...current, tokensOut: current.tokensOut + 1 }
            };
          });
          setRunTotals(prev => ({ ...prev, tokensOut: prev.tokensOut + 1 }));
        } else if (eventType === 'loop_iteration') {
          setRunTotals(prev => ({ ...prev, iterations: prev.iterations + 1 }));
        }
      };
      
      ws.onerror = (err) => {
        console.error('WS Error:', err);
        setIsRunning(false);
      };

      ws.onclose = () => {
        setIsRunning(false);
        wsRef.current = null;
      };
    } catch (err) {
      console.error('Fetch error:', err);
      setIsRunning(false);
    }
  };

  const stopRun = async () => {
    if (!runId) return;
    const port = backendPort || 8000;
    const token = backendToken || 'test-token';
    try {
      await fetch(`http://127.0.0.1:${port}/runs/${runId}/stop`, {
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
    const schema = toPipelineSchema(nodes as any, edges);
    const scrubbed = scrubSecrets(schema);
    const jsonStr = JSON.stringify(scrubbed, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${schema.name || 'pipeline'}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleLoadPipeline = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const jsonStr = e.target?.result as string;
        const schema = JSON.parse(jsonStr);
        const { nodes: newNodes, edges: newEdges } = fromPipelineSchema(schema);
        setNodes(newNodes);
        setEdges(newEdges);
      } catch (err) {
        console.error('Failed to load pipeline', err);
        alert('Invalid pipeline JSON');
      }
    };
    reader.readAsText(file);
  };

  return (
    <div style={{ display: 'flex', width: '100vw', height: '100vh' }}>
      <LeftSidebar backendPort={backendPort} />
      <div style={{ flex: 1, position: 'relative', display: 'flex', flexDirection: 'column' }}>
        <div style={{ position: 'absolute', top: 16, left: 16, zIndex: 10, display: 'flex', gap: '8px' }}>
          <button onClick={handleSavePipeline} style={{ padding: '6px 12px', background: '#333', color: '#fff', border: '1px solid #555', borderRadius: '4px', cursor: 'pointer' }}>Save JSON</button>
          <label style={{ padding: '6px 12px', background: '#333', color: '#fff', border: '1px solid #555', borderRadius: '4px', cursor: 'pointer' }}>
            Load JSON
            <input type="file" accept=".json" onChange={handleLoadPipeline} style={{ display: 'none' }} />
          </label>
        </div>
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
        </div>
        
        <div style={{ flex: 1, position: 'relative' }}>
          <Canvas 
            nodes={nodes} 
            edges={edges} 
            onNodesChange={onNodesChange} 
            onEdgesChange={onEdgesChange} 
            onConnect={onConnect}
            setNodes={setNodes}
            onSelectionChange={(id) => setSelectedNodeId(id)}
          />
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
      />

      {showTrace && runId && (
        <TraceModal 
          runId={runId} 
          backendPort={backendPort} 
          backendToken={backendToken} 
          onClose={() => setShowTrace(false)} 
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
