import { useEffect, useState, useCallback } from 'react';
import { useNodesState, useEdgesState, Connection, Edge, addEdge } from 'reactflow';
import Canvas from './canvas/Canvas';
import LeftSidebar from './panels/LeftSidebar';
import RightPanel from './panels/RightPanel';
import { PipelineNodeData } from './canvas/nodes/PipelineNode';
import { toPipelineSchema } from './canvas/serializer';

export default function App() {
  const [backendPort, setBackendPort] = useState<number | null>(null);
  const [backendToken, setBackendToken] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  
  const [nodes, setNodes, onNodesChange] = useNodesState<PipelineNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

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
    // Port validation logic
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
    
    // reset all statuses
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
      const ws = new WebSocket(`ws://127.0.0.1:${port}/ws/run/${run_id}?token=${token}`);
      
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log('WS event:', data);
        if (data.event === 'node_started') {
          updateNodeData(data.node_id, { status: 'running' });
        } else if (data.event === 'node_done') {
          updateNodeData(data.node_id, { status: 'done' });
        } else if (data.event === 'node_error' || data.event === 'run_error') {
          if (data.node_id) {
            updateNodeData(data.node_id, { status: 'error' });
          }
        } else if (data.event === 'run_completed' || data.event === 'run_stopped' || data.event === 'budget_exceeded') {
          setIsRunning(false);
          ws.close();
        }
      };
      
      ws.onerror = (err) => {
        console.error('WS Error:', err);
        setIsRunning(false);
      };

      ws.onclose = () => {
        setIsRunning(false);
      };
    } catch (err) {
      console.error('Fetch error:', err);
      setIsRunning(false);
    }
  };

  return (
    <div style={{ display: 'flex', width: '100vw', height: '100vh' }}>
      <LeftSidebar backendPort={backendPort} />
      <div style={{ flex: 1, position: 'relative' }}>
        <div style={{ position: 'absolute', top: 16, right: 16, zIndex: 10 }}>
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
      <RightPanel 
        selectedNode={selectedNode} 
        updateNodeData={updateNodeData} 
      />
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
