import React from 'react';
import { Handle, Position } from 'reactflow';
import type { Node as SchemaNode, Port, PortType } from '@shared/types';

const PORT_COLORS: Record<PortType, string> = {
  text: '#3b82f6',
  number: '#10b981',
  boolean: '#f59e0b',
  json: '#8b5cf6',
  image: '#ec4899',
  audio: '#f97316',
};

// React Flow node data
export interface PipelineNodeData extends Omit<SchemaNode, 'id'> {
  // We omit ID here because React Flow provides an ID on the wrapping Node object itself
}

export default function PipelineNode({ data, selected }: { data: PipelineNodeData; selected: boolean }) {
  const { type, role, endpoint_ref, inputs = [], outputs = [] } = data;

  return (
    <div
      style={{
        background: '#1e1e1e',
        border: `1px solid ${selected ? '#3b82f6' : '#555'}`,
        borderRadius: '8px',
        minWidth: '150px',
        color: '#fff',
        fontFamily: 'sans-serif',
        fontSize: '12px',
        boxShadow: selected ? '0 0 0 1px #3b82f6' : '0 4px 6px -1px rgba(0, 0, 0, 0.5)',
      }}
    >
      {/* Header */}
      <div
        style={{
          background: '#2d2d2d',
          padding: '8px',
          borderTopLeftRadius: '8px',
          borderTopRightRadius: '8px',
          borderBottom: '1px solid #444',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <strong style={{ textTransform: 'uppercase' }}>{type}</strong>
        {role && <span style={{ color: '#888', fontSize: '10px' }}>{role}</span>}
      </div>

      {/* Body */}
      <div style={{ padding: '8px' }}>
        {endpoint_ref && (
          <div style={{ marginBottom: '8px', color: '#aaa' }}>
            Model: {endpoint_ref}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '10px' }}>
          {/* Inputs */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {inputs.map((port: Port) => (
              <div key={`in-${port.name}`} style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                <Handle
                  type="target"
                  position={Position.Left}
                  id={`${port.type}:${port.name}`}
                  style={{
                    background: PORT_COLORS[port.type],
                    width: '10px',
                    height: '10px',
                    left: '-13px',
                  }}
                />
                <span style={{ marginLeft: '4px' }}>{port.name}</span>
              </div>
            ))}
          </div>

          {/* Outputs */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', alignItems: 'flex-end' }}>
            {outputs.map((port: Port) => (
              <div key={`out-${port.name}`} style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                <span style={{ marginRight: '4px' }}>{port.name}</span>
                <Handle
                  type="source"
                  position={Position.Right}
                  id={`${port.type}:${port.name}`}
                  style={{
                    background: PORT_COLORS[port.type],
                    width: '10px',
                    height: '10px',
                    right: '-13px',
                  }}
                />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
