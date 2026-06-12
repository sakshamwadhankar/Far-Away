import { useCallback, useRef } from 'react';
import ReactFlow, { Background, Controls, MiniMap, useReactFlow, OnNodesChange, OnEdgesChange, Connection, Edge, Node } from 'reactflow';
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
  onSelectionChange: (id: string | null) => void;
}

export default function Canvas({ nodes, edges, onNodesChange, onEdgesChange, onConnect, setNodes, onSelectionChange }: CanvasProps) {
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

  return (
    <div style={{ width: '100%', height: '100%' }} ref={reactFlowWrapper}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onSelectionChange={(params) => {
          if (params.nodes.length > 0) {
            onSelectionChange(params.nodes[0].id);
          } else {
            onSelectionChange(null);
          }
        }}
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
