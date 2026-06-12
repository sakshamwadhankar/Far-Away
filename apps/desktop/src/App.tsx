import { useEffect, useState, useCallback } from 'react';
import { useNodesState, useEdgesState, Connection, Edge, addEdge } from 'reactflow';
import Canvas from './canvas/Canvas';
import LeftSidebar from './panels/LeftSidebar';
import RightPanel from './panels/RightPanel';
import { PipelineNodeData } from './canvas/nodes/PipelineNode';


export default function App() {
  const [backendPort, setBackendPort] = useState<number | null>(null);
  
  const [nodes, setNodes, onNodesChange] = useNodesState<PipelineNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  useEffect(() => {
    // Listen for backend info from Electron
    if (window.electron) {
      window.electron.onBackendReady((data: { port: number; token: string }) => {
        console.log('Backend is ready on port:', data.port, 'with token:', data.token);
        setBackendPort(data.port);
      });
    }
  }, []);

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

  const updateNodeData = (id: string, newData: Partial<PipelineNodeData>) => {
    setNodes((nds) => nds.map((n) => {
      if (n.id === id) {
        return { ...n, data: { ...n.data, ...newData } };
      }
      return n;
    }));
  };

  return (
    <div style={{ display: 'flex', width: '100vw', height: '100vh' }}>
      <LeftSidebar backendPort={backendPort} />
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
