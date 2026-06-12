import React from 'react';
import ReactFlow, { Background, Controls, MiniMap } from 'reactflow';

export default function Canvas() {
  return (
    <ReactFlow
      nodes={[]}
      edges={[]}
      fitView
    >
      <Background color="#ccc" gap={16} />
      <Controls />
      <MiniMap nodeStrokeColor={(n) => '#666'} nodeColor={(n) => '#222'} />
    </ReactFlow>
  );
}
