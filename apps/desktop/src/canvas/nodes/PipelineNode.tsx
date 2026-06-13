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

/** Status icon glyphs rendered next to the node type label. */
const STATUS_ICONS: Record<string, string> = {
  done: '✓',
  error: '✗',
};

// React Flow node data
export interface PipelineNodeData extends Omit<SchemaNode, 'id'> {
  // We omit ID here because React Flow provides an ID on the wrapping Node object itself
  status?: 'idle' | 'running' | 'done' | 'error';
  estimate?: {
    usd: number;
    latency_ms: number;
    is_local: boolean;
  };
}

export default function PipelineNode({ data, selected }: { data: PipelineNodeData; selected: boolean }) {
  const { type, role, endpoint_ref, inputs = [], outputs = [], status = 'idle' } = data;

  const getBorderColor = () => {
    if (selected) return '#3b82f6';
    switch (status) {
      case 'running': return '#eab308'; // yellow
      case 'done': return '#10b981'; // green
      case 'error': return '#ef4444'; // red
      default: return '#555';
    }
  };

  const getBoxShadow = () => {
    if (selected) return '0 0 0 1px #3b82f6';
    // Running state uses CSS animation class instead of static shadow
    if (status === 'running') return undefined;
    if (status === 'done') return '0 0 8px 1px rgba(16, 185, 129, 0.4)';
    if (status === 'error') return '0 0 8px 1px rgba(239, 68, 68, 0.6)';
    return '0 4px 6px -1px rgba(0, 0, 0, 0.5)';
  };

  const statusIcon = STATUS_ICONS[status] ?? null;

  return (
    <div
      className={status === 'running' ? 'nf-node-running' : undefined}
      data-testid={`pipeline-node-${type}`}
      data-status={status}
      style={{
        background: '#1e1e1e',
        border: `1px solid ${getBorderColor()}`,
        borderRadius: '8px',
        minWidth: '150px',
        fontFamily: 'sans-serif',
        boxShadow: getBoxShadow(),
        position: 'relative',
        transition: 'border-color 0.2s ease, box-shadow 0.2s ease',
        color: 'white',
      }}
    >
      {type === 'model' && data.estimate && (
        <div style={{
          position: 'absolute',
          top: '-24px',
          right: 0,
          display: 'flex',
          gap: '6px',
          fontSize: '11px',
          fontFamily: 'monospace',
          color: '#aaa'
        }}>
          {data.estimate.is_local ? (
             <span style={{ background: '#059669', color: '#fff', padding: '2px 6px', borderRadius: '4px' }}>Local</span>
          ) : (
             <span style={{ background: '#2563eb', color: '#fff', padding: '2px 6px', borderRadius: '4px' }}>Cloud</span>
          )}
          <span style={{ background: '#333', padding: '2px 6px', borderRadius: '4px' }}>
            ~${data.estimate.usd.toFixed(4)} &middot; ~{(data.estimate.latency_ms / 1000).toFixed(1)}s
          </span>
        </div>
      )}

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
        <strong style={{ textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '5px' }}>
          {type}
          {statusIcon && (
            <span
              data-testid={`node-status-icon-${status}`}
              style={{
                fontSize: '12px',
                color: status === 'done' ? '#10b981' : '#ef4444',
                fontWeight: 'bold',
              }}
            >
              {statusIcon}
            </span>
          )}
          {status === 'running' && (
            <span style={{ fontSize: '10px', color: '#eab308' }}>
              (running)
            </span>
          )}
        </strong>
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
