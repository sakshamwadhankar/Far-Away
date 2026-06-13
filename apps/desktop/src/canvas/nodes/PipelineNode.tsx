import { Handle, Position } from 'reactflow';
import type { Node as SchemaNode, Port, PortType } from '@shared/types';

// ─── Per-type color palette (header accent) ────────────────────────────────
const TYPE_ACCENTS: Record<string, { bg: string; fg: string; dot: string }> = {
  input:     { bg: '#D6EDD9', fg: '#1F4D27', dot: '#3A7D44' },
  model:     { bg: '#D4DCF5', fg: '#1A2D6B', dot: '#2B4BAA' },
  output:    { bg: '#EDD6EC', fg: '#4D1F4C', dot: '#7D3A7C' },
  loop:      { bg: '#F5E9D4', fg: '#5C3A0F', dot: '#A86A1A' },
  judge:     { bg: '#F5D9D4', fg: '#5C1F1A', dot: '#B83232' },
  router:    { bg: '#D4EDF5', fg: '#0F3A4D', dot: '#1A7D9D' },
  transform: { bg: '#DFF5D4', fg: '#204D0F', dot: '#4A9D1A' },
  compare:   { bg: '#E4D4F5', fg: '#30175C', dot: '#6B3AB8' },
};

const FALLBACK_ACCENT = { bg: '#E8EDE4', fg: '#2B2E26', dot: '#5A5E54' };

// ─── Port handle colors (kept vibrant for visual distinction) ─────────────
const PORT_COLORS: Record<PortType, string> = {
  text:    '#2B4BAA',
  number:  '#3A7D44',
  boolean: '#A86A1A',
  json:    '#6B3AB8',
  image:   '#B83232',
  audio:   '#1A7D9D',
};

/** Status icon glyphs rendered next to the node type label. */
const STATUS_ICONS: Record<string, string> = {
  done:  '✓',
  error: '✗',
};

// React Flow node data
export interface PipelineNodeData extends Omit<SchemaNode, 'id'> {
  status?: 'idle' | 'running' | 'done' | 'error';
  estimate?: {
    usd: number;
    latency_ms: number;
    is_local: boolean;
  };
}

export default function PipelineNode({ data, selected }: { data: PipelineNodeData; selected: boolean }) {
  const { type, role, endpoint_ref, inputs = [], outputs = [], status = 'idle' } = data;
  const accent = TYPE_ACCENTS[type] ?? FALLBACK_ACCENT;

  const getBorderColor = () => {
    if (selected) return '#C8D94A';
    switch (status) {
      case 'running': return '#A86A1A';
      case 'done':    return '#3A7D44';
      case 'error':   return '#B83232';
      default:        return 'rgba(30,35,25,0.15)';
    }
  };

  const getBoxShadow = () => {
    if (selected)              return `0 0 0 2px #C8D94A, 0 4px 16px rgba(200,217,74,0.25)`;
    if (status === 'running')  return undefined; // handled by CSS animation
    if (status === 'done')     return `0 0 0 1.5px ${PORT_COLORS.number}55, 0 4px 12px rgba(0,0,0,0.08)`;
    if (status === 'error')    return `0 0 0 1.5px ${PORT_COLORS.image}55, 0 4px 12px rgba(0,0,0,0.08)`;
    return '0 2px 8px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)';
  };

  const statusIcon = STATUS_ICONS[status] ?? null;

  return (
    <div
      className={status === 'running' ? 'nf-node-running' : undefined}
      data-testid={`pipeline-node-${type}`}
      data-status={status}
      style={{
        background: '#F4F2EB',
        border: `1.5px solid ${getBorderColor()}`,
        borderRadius: 16,
        minWidth: 160,
        fontFamily: "'Inter', system-ui, sans-serif",
        boxShadow: getBoxShadow(),
        position: 'relative',
        transition: 'border-color 0.2s ease, box-shadow 0.2s ease',
        overflow: 'hidden',
      }}
    >
      {/* Estimate tooltip above node */}
      {type === 'model' && data.estimate && (
        <div style={{
          position: 'absolute',
          top: -28,
          right: 0,
          display: 'flex',
          gap: 5,
          fontSize: 10,
          fontFamily: "'DM Mono', monospace",
        }}>
          <span style={{
            background: data.estimate.is_local ? PORT_COLORS.number : PORT_COLORS.text,
            color: '#fff',
            padding: '2px 8px',
            borderRadius: 99,
            fontWeight: 500,
          }}>
            {data.estimate.is_local ? 'Local' : 'Cloud'}
          </span>
          <span style={{
            background: '#F4F2EB',
            border: '1px solid rgba(30,35,25,0.15)',
            color: '#5A5E54',
            padding: '2px 8px',
            borderRadius: 99,
          }}>
            ~${data.estimate.usd.toFixed(4)} · ~{(data.estimate.latency_ms / 1000).toFixed(1)}s
          </span>
        </div>
      )}

      {/* Colored accent header */}
      <div style={{
        background: accent.bg,
        padding: '8px 12px',
        borderBottom: `1px solid ${accent.dot}33`,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 6,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {/* Type color dot */}
          <div style={{
            width: 7, height: 7, borderRadius: '50%',
            background: accent.dot,
            flexShrink: 0,
          }} />
          <strong style={{
            textTransform: 'uppercase',
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: '0.08em',
            color: accent.fg,
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            fontFamily: "'DM Mono', monospace",
          }}>
            {type}
            {statusIcon && (
              <span
                data-testid={`node-status-icon-${status}`}
                style={{
                  fontSize: 11,
                  color: status === 'done' ? PORT_COLORS.number : PORT_COLORS.image,
                  fontWeight: 700,
                }}
              >
                {statusIcon}
              </span>
            )}
            {status === 'running' && (
              <span style={{ fontSize: 10, color: '#A86A1A', fontWeight: 500 }}>
                ···
              </span>
            )}
          </strong>
        </div>
        {role && (
          <span style={{
            color: accent.fg,
            fontSize: 10,
            opacity: 0.65,
            fontFamily: "'DM Mono', monospace",
            maxWidth: 80,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}>
            {role}
          </span>
        )}
      </div>

      {/* Body */}
      <div style={{ padding: '10px 12px', background: '#F4F2EB' }}>
        {endpoint_ref && (
          <div style={{
            marginBottom: 8,
            fontSize: 11,
            fontFamily: "'DM Mono', monospace",
            color: '#5A5E54',
            background: 'rgba(30,35,25,0.05)',
            border: '1px solid rgba(30,35,25,0.10)',
            borderRadius: 8,
            padding: '3px 8px',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}>
            {endpoint_ref}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, gap: 12 }}>
          {/* Inputs */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {inputs.map((port: Port) => (
              <div key={`in-${port.name}`} style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                <Handle
                  type="target"
                  position={Position.Left}
                  id={`${port.type}:${port.name}`}
                  style={{
                    background: PORT_COLORS[port.type],
                    width: 10, height: 10,
                    left: -13,
                    border: '2px solid #F4F2EB',
                  }}
                />
                <span style={{ marginLeft: 4, fontSize: 11, color: '#5A5E54', fontFamily: "'DM Mono', monospace" }}>
                  {port.name}
                </span>
              </div>
            ))}
          </div>

          {/* Outputs */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end' }}>
            {outputs.map((port: Port) => (
              <div key={`out-${port.name}`} style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                <span style={{ marginRight: 4, fontSize: 11, color: '#5A5E54', fontFamily: "'DM Mono', monospace" }}>
                  {port.name}
                </span>
                <Handle
                  type="source"
                  position={Position.Right}
                  id={`${port.type}:${port.name}`}
                  style={{
                    background: PORT_COLORS[port.type],
                    width: 10, height: 10,
                    right: -13,
                    border: '2px solid #F4F2EB',
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
