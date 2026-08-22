import { Handle, Position, useEdges, useNodes, useReactFlow } from 'reactflow';
import type { AccessPolicy } from '@shared/types';
import type { PipelineNodeData } from './PipelineNode';
import {
  ACCESS_SCOPE_PORT,
  capabilityRows,
  descendantsOf,
  emptyPolicy,
  requestedCapabilities,
  togglePolicy,
  type CapabilityRow,
  type CapabilityState,
} from '../accessPolicy';

/**
 * Access node — the permission layer, rendered as a live capability list.
 *
 * The node body is not a form. It reports what the pipeline downstream of it
 * is actually reaching for, and marks each capability as granted-and-used,
 * granted-and-unused, or requested-and-denied. That third state is the point
 * of the feature: drop one of these on the canvas and it tells you what your
 * pipeline wants to touch.
 *
 * Toggling a row writes straight back into `config.access_policy`, so the list
 * re-derives immediately — no run required to see the effect.
 */

const ACCENT = { bg: '#F5E4D4', fg: '#5C2F0F', dot: '#B8642B' };

const STATE_STYLE: Record<
  CapabilityState,
  { fg: string; bg: string; border: string; glyph: string; action: string | null }
> = {
  'granted-used': {
    fg: '#1F4D27',
    bg: 'rgba(58,125,68,0.10)',
    border: 'rgba(58,125,68,0.35)',
    glyph: '✓',
    action: null,
  },
  'granted-unused': {
    fg: '#5C3A0F',
    bg: 'rgba(168,106,26,0.10)',
    border: 'rgba(168,106,26,0.30)',
    glyph: '○',
    action: 'tighten',
  },
  'requested-denied': {
    fg: '#5C1F1A',
    bg: 'rgba(184,50,50,0.12)',
    border: 'rgba(184,50,50,0.40)',
    glyph: '✗',
    action: 'grant',
  },
};

const STATE_TITLE: Record<CapabilityState, string> = {
  'granted-used': 'Granted, and used by a node downstream.',
  'granted-unused': 'Granted, but nothing downstream uses it.',
  'requested-denied': 'A node downstream needs this, and the policy blocks it.',
};

export interface AccessNodeData extends PipelineNodeData {
  type: 'access';
}

export default function AccessNode({
  id,
  data,
  selected,
}: {
  id: string;
  data: AccessNodeData;
  selected: boolean;
}) {
  const nodes = useNodes<PipelineNodeData>();
  const edges = useEdges();
  const { setNodes } = useReactFlow();

  const policy = (data.config?.access_policy as AccessPolicy | undefined) ?? emptyPolicy();
  const scope = descendantsOf(id, edges);
  const requested = requestedCapabilities(nodes, scope);
  const rows = capabilityRows(policy, requested);

  const deniedCount = rows.filter((r) => r.state === 'requested-denied').length;

  const applyToggle = (row: CapabilityRow, grant: boolean) => {
    const next = togglePolicy(policy, row.capability, grant);
    setNodes((current) =>
      current.map((node) =>
        node.id === id
          ? { ...node, data: { ...node.data, config: { ...node.data.config, access_policy: next } } }
          : node,
      ),
    );
  };

  return (
    <div
      data-testid="access-node"
      style={{
        background: '#F4F2EB',
        border: `1.5px solid ${selected ? '#C8D94A' : deniedCount > 0 ? 'rgba(184,50,50,0.55)' : 'rgba(30,35,25,0.15)'}`,
        borderRadius: 16,
        minWidth: 210,
        maxWidth: 260,
        fontFamily: "'Inter', system-ui, sans-serif",
        boxShadow: selected
          ? '0 0 0 2px #C8D94A, 0 4px 16px rgba(200,217,74,0.25)'
          : '0 2px 8px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)',
        overflow: 'hidden',
      }}
    >
      {/* Scope ports. Nothing flows through them — they mark which part of the
          graph this policy governs, so they use the reserved port name the
          compiler expects. */}
      <Handle
        type="target"
        position={Position.Left}
        id={`scope:${ACCESS_SCOPE_PORT}`}
        style={{ background: ACCENT.dot, width: 10, height: 10, left: -13, border: '2px solid #F4F2EB' }}
      />
      <Handle
        type="source"
        position={Position.Right}
        id={`scope:${ACCESS_SCOPE_PORT}`}
        style={{ background: ACCENT.dot, width: 10, height: 10, right: -13, border: '2px solid #F4F2EB' }}
      />

      <div
        style={{
          background: ACCENT.bg,
          padding: '8px 12px',
          borderBottom: `1px solid ${ACCENT.dot}33`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 6,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 7, height: 7, borderRadius: '50%', background: ACCENT.dot }} />
          <strong
            style={{
              textTransform: 'uppercase',
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: '0.08em',
              color: ACCENT.fg,
              fontFamily: "'DM Mono', monospace",
            }}
          >
            access
          </strong>
        </div>
        {deniedCount > 0 && (
          <span
            data-testid="access-denied-count"
            style={{
              fontSize: 10,
              fontFamily: "'DM Mono', monospace",
              color: '#5C1F1A',
              background: 'rgba(184,50,50,0.15)',
              border: '1px solid rgba(184,50,50,0.35)',
              borderRadius: 99,
              padding: '1px 7px',
              fontWeight: 600,
            }}
          >
            {deniedCount} denied
          </span>
        )}
      </div>

      <div style={{ padding: '9px 10px', display: 'flex', flexDirection: 'column', gap: 4 }}>
        {rows.length === 0 ? (
          <div
            data-testid="access-empty"
            style={{ fontSize: 11, color: '#5A5E54', fontFamily: "'DM Mono', monospace", lineHeight: 1.5 }}
          >
            Nothing granted, nothing requested. Connect this node to the part of
            the pipeline it should limit.
          </div>
        ) : (
          rows.map((row) => {
            const style = STATE_STYLE[row.state];
            return (
              <div
                key={row.id}
                data-testid={`capability-${row.id}`}
                data-state={row.state}
                title={STATE_TITLE[row.state]}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  fontSize: 11,
                  fontFamily: "'DM Mono', monospace",
                  color: style.fg,
                  background: style.bg,
                  border: `1px solid ${style.border}`,
                  borderRadius: 8,
                  padding: '3px 7px',
                }}
              >
                <span aria-hidden style={{ fontWeight: 700, width: 10 }}>{style.glyph}</span>
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {row.label}
                </span>
                {style.action && (
                  <button
                    type="button"
                    data-testid={`capability-action-${row.id}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      applyToggle(row, row.state === 'requested-denied');
                    }}
                    style={{
                      border: `1px solid ${style.border}`,
                      background: 'transparent',
                      color: style.fg,
                      borderRadius: 99,
                      fontSize: 9.5,
                      fontFamily: "'DM Mono', monospace",
                      padding: '1px 7px',
                      cursor: 'pointer',
                      textTransform: 'uppercase',
                      letterSpacing: '0.04em',
                    }}
                  >
                    {style.action}
                  </button>
                )}
              </div>
            );
          })
        )}

        {(policy.max_cost_usd !== null || policy.max_tokens !== null) && (
          <div
            data-testid="access-ceilings"
            style={{
              marginTop: 2,
              fontSize: 10,
              color: '#5A5E54',
              fontFamily: "'DM Mono', monospace",
              display: 'flex',
              gap: 8,
            }}
          >
            {policy.max_cost_usd !== null && <span>≤ ${policy.max_cost_usd.toFixed(2)}</span>}
            {policy.max_tokens !== null && <span>≤ {policy.max_tokens} tok</span>}
          </div>
        )}
      </div>
    </div>
  );
}
