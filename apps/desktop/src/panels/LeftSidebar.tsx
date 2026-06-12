import React from 'react';
import type { NodeType, Port } from '@shared/types';
import { PipelineNodeData } from '../canvas/nodes/PipelineNode';

const NODE_TYPES: { type: NodeType; label: string; defaultData: Partial<PipelineNodeData> }[] = [
  { type: 'input', label: 'Input Node', defaultData: { outputs: [{ name: 'prompt', type: 'text' }] } },
  { type: 'model', label: 'Model Node', defaultData: { endpoint_ref: 'ep_mock', inputs: [{ name: 'prompt', type: 'text' }], outputs: [{ name: 'response', type: 'text' }], config: { temperature: 0.7, max_tokens: 2048, response_format: 'text' } } },
  { type: 'output', label: 'Output Node', defaultData: { inputs: [{ name: 'response', type: 'text' }] } },
  { type: 'loop', label: 'Loop (Subgraph)', defaultData: {} },
  { type: 'judge', label: 'Judge Node', defaultData: { inputs: [{ name: 'input', type: 'text' }], outputs: [{ name: 'decision', type: 'boolean' }], role: 'judge' } },
  { type: 'router', label: 'Router Node', defaultData: { inputs: [{ name: 'input', type: 'text' }], outputs: [{ name: 'branch_a', type: 'text' }, { name: 'branch_b', type: 'text' }] } },
  { type: 'transform', label: 'Transform Node', defaultData: { inputs: [{ name: 'in', type: 'json' }], outputs: [{ name: 'out', type: 'json' }] } },
];

export default function LeftSidebar({ backendPort }: { backendPort: number | null }) {
  const onDragStart = (event: React.DragEvent, nodeType: NodeType, defaultData: Partial<PipelineNodeData>) => {
    event.dataTransfer.setData('application/reactflow', JSON.stringify({ type: nodeType, data: defaultData }));
    event.dataTransfer.effectAllowed = 'move';
  };

  return (
    <div style={{ width: 250, borderRight: '1px solid #333', padding: 16, backgroundColor: '#252526', display: 'flex', flexDirection: 'column' }}>
      <h3>Node Palette</h3>
      <p style={{ color: '#888', fontSize: '0.9em' }}>Drag nodes to the canvas.</p>
      
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '16px', flex: 1 }}>
        {NODE_TYPES.map((nt) => (
          <div
            key={nt.type}
            draggable
            onDragStart={(e) => onDragStart(e, nt.type, nt.defaultData)}
            style={{
              padding: '10px',
              border: '1px solid #444',
              borderRadius: '4px',
              backgroundColor: '#2d2d2d',
              cursor: 'grab',
              textAlign: 'center',
            }}
          >
            {nt.label}
          </div>
        ))}
      </div>

      <div style={{ marginTop: 'auto', paddingTop: 20, borderTop: '1px solid #444' }}>
        <h4>Backend Status</h4>
        {backendPort ? (
          <span style={{ color: 'lightgreen' }}>Connected (Port {backendPort})</span>
        ) : (
          <span style={{ color: 'orange' }}>Connecting...</span>
        )}
      </div>
    </div>
  );
}
