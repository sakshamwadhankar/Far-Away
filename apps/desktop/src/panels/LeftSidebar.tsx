import React, { useState, useEffect } from 'react';
import type { NodeType } from '@shared/types';
import { PipelineNodeData } from '../canvas/nodes/PipelineNode';

// ─── Icons (inline SVG, no external dep) ─────────────────────────────────────
const ICON_MAP: Record<string, string> = {
  input:     '→',
  model:     '◈',
  output:    '←',
  loop:      '↺',
  judge:     '⚖',
  router:    '⇌',
  transform: '⟳',
  compare:   '≈',
};

const NODE_TYPES: { type: NodeType; label: string; defaultData: Partial<PipelineNodeData> }[] = [
  { type: 'input',     label: 'Input',     defaultData: { outputs: [{ name: 'prompt', type: 'text' }] } },
  { type: 'model',     label: 'Model',     defaultData: { endpoint_ref: '', inputs: [{ name: 'prompt', type: 'text' }], outputs: [{ name: 'response', type: 'text' }], config: { temperature: 0.7, max_tokens: 2048, response_format: 'text' } } },
  { type: 'output',    label: 'Output',    defaultData: { inputs: [{ name: 'response', type: 'text' }] } },
  { type: 'loop',      label: 'Loop',      defaultData: {} },
  { type: 'judge',     label: 'Judge',     defaultData: { inputs: [{ name: 'input', type: 'text' }], outputs: [{ name: 'decision', type: 'boolean' }], role: 'judge', config: { score_field: 'verified', strategy: 'truthy' } } },
  { type: 'router',    label: 'Router',    defaultData: { inputs: [{ name: 'input', type: 'text' }], outputs: [{ name: 'branch_a', type: 'text' }, { name: 'branch_b', type: 'text' }], config: { routing_map: { true: 'branch_a', false: 'branch_b' } } } },
  { type: 'transform', label: 'Transform', defaultData: { inputs: [{ name: 'in', type: 'json' }], outputs: [{ name: 'out', type: 'json' }] } },
  { type: 'compare',   label: 'Compare',   defaultData: { inputs: [{ name: 'input1', type: 'text' }, { name: 'input2', type: 'text' }], outputs: [{ name: 'diff', type: 'text' }, { name: 'is_different', type: 'boolean' }] } },
];

interface LeftSidebarProps {
  backendPort: number | null;
  backendToken: string | null;
  onLoadTemplate?: (schema: any) => void; // eslint-disable-line @typescript-eslint/no-explicit-any
  API_BASE: string;
}

export default function LeftSidebar({ backendPort: _backendPort, backendToken, onLoadTemplate, API_BASE }: LeftSidebarProps) {
  const [templates, setTemplates] = useState<any[]>([]); // eslint-disable-line @typescript-eslint/no-explicit-any
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<'nodes' | 'templates'>('nodes');

  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then(r => { if (r.ok) setIsConnected(true); else setIsConnected(false); })
      .catch(() => setIsConnected(false));
  }, [API_BASE]);

  useEffect(() => {
    if (!isConnected || !backendToken) return;
    setTemplateError(null);
    fetch(`${API_BASE}/pipelines/templates`, { headers: { 'Authorization': `Bearer ${backendToken}` } })
      .then(r => {
        if (!r.ok) throw new Error('Network response was not ok');
        return r.json();
      })
      .then(data => { if (Array.isArray(data)) setTemplates(data); })
      .catch(e => {
        console.warn('Failed to fetch templates:', e);
        setTemplateError('Backend not reachable');
      });
  }, [isConnected, API_BASE, backendToken]);

  const onDragStart = (event: React.DragEvent, nodeType: NodeType, defaultData: Partial<PipelineNodeData>) => {
    event.dataTransfer.setData('application/reactflow', JSON.stringify({ type: nodeType, data: defaultData }));
    event.dataTransfer.effectAllowed = 'move';
  };

  return (
    <div
      data-tour="palette"
      className="nf-sidebar"
      style={{ width: 240, padding: '16px 12px', gap: 0 }}
    >
      {/* Header */}
      <div style={{ padding: '4px 4px 16px', borderBottom: '1px solid var(--border-subtle)' }}>
        <div style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          fontWeight: 500,
          color: 'var(--text-3)',
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          marginBottom: 8,
        }}>
          Far-Away
        </div>
        <div style={{
          fontFamily: 'var(--font-ui)',
          fontSize: 18,
          fontWeight: 700,
          color: 'var(--text)',
          letterSpacing: '-0.02em',
        }}>
          Pipeline Studio
        </div>
      </div>

      {/* Section toggle */}
      <div style={{ display: 'flex', gap: 4, marginTop: 14, marginBottom: 12 }}>
        {(['nodes', 'templates'] as const).map(s => (
          <button
            key={s}
            onClick={() => setActiveSection(s)}
            style={{
              flex: 1,
              padding: '5px 0',
              background: activeSection === s ? '#C8D94A' : 'transparent',
              color: activeSection === s ? '#2B2E26' : 'var(--text-2)',
              border: '1px solid',
              borderColor: activeSection === s ? '#B8C83A' : 'var(--border)',
              borderRadius: 'var(--radius-pill)',
              fontFamily: 'var(--font-ui)',
              fontSize: 12,
              fontWeight: activeSection === s ? 600 : 500,
              cursor: 'pointer',
              transition: 'all var(--transition)',
              textTransform: 'capitalize',
              boxShadow: activeSection === s ? '0 1px 4px rgba(200,217,74,0.35)' : 'none',
            }}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Nodes Section */}
      {activeSection === 'nodes' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5, animation: 'nf-fade-in 0.18s ease' }}>
          <div className="nf-section-header" style={{ borderTop: 'none', paddingTop: 0, marginTop: 0, marginBottom: 4 }}>
            Drag to canvas
          </div>
          {NODE_TYPES.map((nt) => (
            <div
              key={nt.type}
              draggable
              onDragStart={(e) => onDragStart(e, nt.type, nt.defaultData)}
              className="nf-node-drag-item"
            >
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 15,
                width: 22,
                textAlign: 'center',
                opacity: 0.7,
              }}>
                {ICON_MAP[nt.type] || '●'}
              </span>
              <span style={{ fontSize: 12.5 }}>{nt.label}</span>
              <span style={{
                marginLeft: 'auto',
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                color: 'var(--text-3)',
                opacity: 0.7,
              }}>
                {nt.type}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Templates Section */}
      {activeSection === 'templates' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, animation: 'nf-fade-in 0.18s ease' }}>
          <div className="nf-section-header" style={{ borderTop: 'none', paddingTop: 0, marginTop: 0, marginBottom: 4 }}>
            Click to load
          </div>
          {templates.map((tpl) => (
            <div key={tpl.id} className="nf-template-card">
              <div style={{ fontWeight: 600, fontSize: 12.5, color: 'var(--text)', marginBottom: 6 }}>
                {tpl.name}
              </div>
              {tpl.description && (
                <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 8, lineHeight: 1.4 }}>
                  {tpl.description}
                </div>
              )}
              {onLoadTemplate && (
                <button
                  onClick={() => onLoadTemplate(tpl)}
                  className="nf-pill-btn nf-pill-btn--sm"
                  style={{ width: '100%', justifyContent: 'center' }}
                >
                  Load template
                </button>
              )}
            </div>
          ))}
          {templates.length === 0 && !templateError && (
            <div style={{ color: 'var(--text-3)', fontSize: 12, fontStyle: 'italic', padding: '8px 4px' }}>
              No templates available.
            </div>
          )}
          {templateError && (
            <div style={{
              background: 'rgba(184,50,50,0.08)',
              border: '1px solid rgba(184,50,50,0.2)',
              borderRadius: 10,
              padding: '10px 12px',
              color: 'var(--danger)',
              fontSize: 11,
              lineHeight: 1.5,
            }}>
              {templateError}
            </div>
          )}
        </div>
      )}

      {/* Footer: backend status */}
      <div style={{ marginTop: 'auto', paddingTop: 14, borderTop: '1px solid var(--border-subtle)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div className={`nf-dot ${isConnected ? 'nf-dot--green' : 'nf-dot--red'}`} />
          <span style={{ fontSize: 11, color: isConnected ? 'var(--success)' : 'var(--error)', fontFamily: 'var(--font-mono)' }}>
            {isConnected ? `Connected · ${API_BASE.split(':').pop()}` : 'Disconnected'}
          </span>
        </div>
      </div>
    </div>
  );
}
