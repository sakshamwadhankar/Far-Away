import React, { useState, useEffect, useCallback } from 'react';
import type { NodeType, Pipeline, PortType } from '@shared/types';
import { PipelineNodeData } from '../canvas/nodes/PipelineNode';
import { emptyPolicy } from '../canvas/accessPolicy';
import KomvosLogo from '../assets/KomvosLogo.png';

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
  access:    '⛨',
  computer:  '🖥',
};

const NODE_TYPES: { type: NodeType; label: string; defaultData: Partial<PipelineNodeData> }[] = [
  { type: 'input',     label: 'Input',     defaultData: { outputs: [{ name: 'prompt', type: 'text' }] } },
  { type: 'model',     label: 'Model',     defaultData: { endpoint_ref: '', inputs: [{ name: 'prompt', type: 'text' }], outputs: [{ name: 'response', type: 'text' }], config: { temperature: 0.7, max_tokens: 2048, response_format: 'text' } } },
  { type: 'computer',  label: 'Computer',  defaultData: { endpoint_ref: '', inputs: [{ name: 'task', type: 'text' }], outputs: [{ name: 'result', type: 'text' }, { name: 'last_screenshot', type: 'image' }], config: { max_steps: 30, timeout_seconds: 300 } } },
  { type: 'output',    label: 'Output',    defaultData: { inputs: [{ name: 'response', type: 'text' }] } },
  { type: 'loop',      label: 'Loop',      defaultData: {} },
  { type: 'judge',     label: 'Judge',     defaultData: { inputs: [{ name: 'input', type: 'text' }], outputs: [{ name: 'decision', type: 'boolean' }], role: 'judge', config: { score_field: 'verified', strategy: 'truthy' } } },
  { type: 'router',    label: 'Router',    defaultData: { inputs: [{ name: 'input', type: 'text' }], outputs: [{ name: 'branch_a', type: 'text' }, { name: 'branch_b', type: 'text' }], config: { routing_map: { true: 'branch_a', false: 'branch_b' } } } },
  { type: 'transform', label: 'Transform', defaultData: { inputs: [{ name: 'in', type: 'json' }], outputs: [{ name: 'out', type: 'json' }] } },
  { type: 'compare',   label: 'Compare',   defaultData: { inputs: [{ name: 'input1', type: 'text' }, { name: 'input2', type: 'text' }], outputs: [{ name: 'diff', type: 'text' }, { name: 'is_different', type: 'boolean' }] } },
  // Access nodes carry no data ports — they are scope markers. A fresh one
  // denies everything, so the capability list immediately shows what the
  // pipeline downstream is reaching for.
  { type: 'access',    label: 'Access',    defaultData: { inputs: [], outputs: [], config: { access_policy: emptyPolicy() } } },
];

export interface LibraryTemplate {
  id: string;
  name: string;
  description: string;
  author: string;
  tags: string;
  pipeline: Pipeline;
  created_at: number;
  downloads: number;
}

const PORT_TYPES: readonly PortType[] = ['text', 'number', 'boolean', 'json', 'image', 'audio'];

/**
 * Custom nodes are user-authored and stored by the backend with free-form port
 * type strings. Narrow to the schema's PortType, falling back to 'text'.
 */
function toPortType(raw: string): PortType {
  return PORT_TYPES.includes(raw as PortType) ? (raw as PortType) : 'text';
}

export interface CustomNodeDef {
  id: string;
  name: string;
  description: string;
  author: string;
  icon_color: string;
  inputs: { name: string; type: string }[];
  outputs: { name: string; type: string }[];
  template: string;
  tags: string;
  created_at: number;
}

export interface DeploymentSummary {
  id: string;
  name: string;
  expose_lan: boolean;
  rate_limit_per_minute: number;
  chat_input_node: string;
  chat_output_node: string;
  created_at: number;
  request_count: number;
  error_count: number;
  last_request_at: number | null;
}

interface LeftSidebarProps {
  backendPort: number | null;
  backendToken: string | null;
  backendConnected: boolean | null;
  onLoadTemplate?: (schema: Pipeline) => void;
  onPublishClick?: () => void;
  onCreateCustomNode?: () => void;
  customNodes?: CustomNodeDef[];
  onDeleteCustomNode?: (id: string) => void;
  onDeployClick?: () => void;
  onManageDeploymentClick?: (deploymentId: string) => void;
  /** Bump this after a deploy/rotate/undeploy so the list refetches. */
  deploymentsRefreshKey?: number;
  API_BASE: string;
}

export default function LeftSidebar({ backendPort: _backendPort, backendToken, backendConnected, onLoadTemplate, onPublishClick, onCreateCustomNode, customNodes = [], onDeleteCustomNode, onDeployClick, onManageDeploymentClick, deploymentsRefreshKey, API_BASE }: LeftSidebarProps) {
  const [templates, setTemplates] = useState<Pipeline[]>([]);
  const [libraryTemplates, setLibraryTemplates] = useState<LibraryTemplate[]>([]);
  const [deployments, setDeployments] = useState<DeploymentSummary[]>([]);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const [deploymentsError, setDeploymentsError] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<'nodes' | 'templates' | 'library' | 'deployments'>('nodes');

  useEffect(() => {
    if (!backendConnected || !backendToken) return;
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
  }, [backendConnected, API_BASE, backendToken]);

  // Fetch library templates
  const fetchLibrary = useCallback(() => {
    if (!backendConnected || !backendToken) return;
    setLibraryError(null);
    fetch(`${API_BASE}/library/templates`, { headers: { 'Authorization': `Bearer ${backendToken}` } })
      .then(r => {
        if (!r.ok) throw new Error('Network response was not ok');
        return r.json();
      })
      .then((data: LibraryTemplate[]) => { if (Array.isArray(data)) setLibraryTemplates(data); })
      .catch(e => {
        console.warn('Failed to fetch library templates:', e);
        setLibraryError('Could not load library');
      });
  }, [backendConnected, API_BASE, backendToken]);

  useEffect(() => {
    if (activeSection === 'library') fetchLibrary();
  }, [activeSection, fetchLibrary]);

  // Fetch deployments
  const fetchDeployments = useCallback(() => {
    if (!backendConnected || !backendToken) return;
    setDeploymentsError(null);
    fetch(`${API_BASE}/deployments`, { headers: { 'Authorization': `Bearer ${backendToken}` } })
      .then(r => {
        if (!r.ok) throw new Error('Network response was not ok');
        return r.json();
      })
      .then((data: { deployments: DeploymentSummary[] }) => {
        if (Array.isArray(data.deployments)) setDeployments(data.deployments);
      })
      .catch(e => {
        console.warn('Failed to fetch deployments:', e);
        setDeploymentsError('Could not load deployments');
      });
  }, [backendConnected, API_BASE, backendToken]);

  useEffect(() => {
    if (activeSection === 'deployments') fetchDeployments();
  }, [activeSection, fetchDeployments, deploymentsRefreshKey]);

  const handleDeleteLibraryTemplate = async (templateId: string) => {
    if (!backendToken) return;
    try {
      const res = await fetch(`${API_BASE}/library/templates/${templateId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${backendToken}` },
      });
      if (res.ok) {
        setLibraryTemplates(prev => prev.filter(t => t.id !== templateId));
      }
    } catch (e) {
      console.warn('Failed to delete library template:', e);
    }
  };

  const handleLoadLibraryTemplate = (tpl: LibraryTemplate) => {
    if (onLoadTemplate) {
      onLoadTemplate(tpl.pipeline);
    }
  };

  const onDragStart = (event: React.DragEvent, nodeType: NodeType, defaultData: Partial<PipelineNodeData>) => {
    event.dataTransfer.setData('application/reactflow', JSON.stringify({ type: nodeType, data: defaultData }));
    event.dataTransfer.effectAllowed = 'move';
  };

  const parseTags = (tags: string): string[] =>
    tags.split(',').map(t => t.trim()).filter(Boolean);

  const TABS = ['nodes', 'templates', 'library', 'deployments'] as const;

  return (
    <div
      data-tour="palette"
      className="nf-sidebar"
      style={{ width: 240, padding: '16px 12px', gap: 0, display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}
    >
      {/* Header */}
      <div style={{ padding: '4px 4px 16px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', flexShrink: 0 }}>
        <img src={KomvosLogo} alt="Komvos Logo" style={{ height: 32, objectFit: 'contain' }} />
      </div>

      {/* Scrollable Content */}
      <div className="nf-scrollable" style={{ flex: 1, overflowY: 'auto', paddingRight: 4, display: 'flex', flexDirection: 'column', paddingBottom: 16 }}>

      {/* Section toggle */}
      <div style={{ display: 'flex', gap: 4, marginTop: 14, marginBottom: 12 }}>
        {TABS.map(s => (
          <button
            key={s}
            id={`sidebar-tab-${s}`}
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
              fontSize: s === 'library' ? 11 : 12,
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

          {/* Custom Nodes sub-section */}
          {customNodes.length > 0 && (
            <div className="nf-custom-node-section">
              <div className="nf-section-header" style={{ borderTop: 'none', paddingTop: 0, marginTop: 0, marginBottom: 4 }}>
                Custom Nodes
              </div>
              {customNodes.map((cn) => (
                <div
                  key={cn.id}
                  draggable
                  onDragStart={(e) => onDragStart(e, 'transform', {
                    inputs: cn.inputs.map(p => ({ name: p.name, type: toPortType(p.type) })),
                    outputs: cn.outputs.map(p => ({ name: p.name, type: toPortType(p.type) })),
                    config: {
                      system_prompt: cn.template,
                      custom_node_id: cn.id,
                      custom_label: cn.name,
                      custom_color: cn.icon_color,
                    },
                  })}
                  className="nf-node-drag-item nf-custom-node-item"
                  style={{ borderLeft: `3px solid ${cn.icon_color}` }}
                >
                  <span style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 13,
                    width: 22,
                    textAlign: 'center',
                    color: cn.icon_color,
                  }}>
                    ✦
                  </span>
                  <span style={{ fontSize: 12, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{cn.name}</span>
                  {onDeleteCustomNode && (
                    <button
                      className="nf-port-remove-btn"
                      style={{ width: 18, height: 18, fontSize: 9, marginLeft: 2 }}
                      title="Delete custom node"
                      onClick={(e) => { e.stopPropagation(); onDeleteCustomNode(cn.id); }}
                    >
                      ✕
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Create custom node button */}
          {onCreateCustomNode && (
            <button
              id="create-custom-node-btn"
              className="nf-create-custom-btn"
              onClick={onCreateCustomNode}
              style={{ marginTop: customNodes.length > 0 ? 6 : 10 }}
            >
              ✦ Create Custom Node
            </button>
          )}
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

      {/* Library Section */}
      {activeSection === 'library' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, animation: 'nf-fade-in 0.18s ease' }}>
          {/* Publish button */}
          {onPublishClick && (
            <button
              id="library-publish-btn"
              className="nf-publish-btn"
              onClick={onPublishClick}
              style={{ marginBottom: 4 }}
            >
              Publish Current Pipeline
            </button>
          )}

          <div className="nf-section-header" style={{ borderTop: 'none', paddingTop: 0, marginTop: 0, marginBottom: 4 }}>
            Community templates
          </div>

          {libraryTemplates.map((tpl) => (
            <div key={tpl.id} className="nf-library-card">
              <div className="nf-library-card-header">
                <span className="nf-library-card-title">{tpl.name}</span>
                <button
                  className="nf-icon-btn--danger"
                  title="Remove from library"
                  onClick={() => handleDeleteLibraryTemplate(tpl.id)}
                >
                  ✕
                </button>
              </div>

              {tpl.description && (
                <div className="nf-library-card-desc">{tpl.description}</div>
              )}

              <div className="nf-library-meta">
                <span className="nf-library-author">👤 {tpl.author}</span>
                {parseTags(tpl.tags).map(tag => (
                  <span key={tag} className="nf-library-tag">{tag}</span>
                ))}
                <span className="nf-library-downloads">↓ {tpl.downloads}</span>
              </div>

              <div className="nf-library-card-actions">
                <button
                  onClick={() => handleLoadLibraryTemplate(tpl)}
                  className="nf-pill-btn nf-pill-btn--sm nf-pill-btn--highlight"
                  style={{ flex: 1, justifyContent: 'center' }}
                >
                  Load template
                </button>
              </div>
            </div>
          ))}

          {libraryTemplates.length === 0 && !libraryError && (
            <div style={{
              color: 'var(--text-3)', fontSize: 12, fontStyle: 'italic',
              padding: '16px 4px', textAlign: 'center', lineHeight: 1.6,
            }}>
              No community templates yet.<br />
              Be the first to publish!
            </div>
          )}
          {libraryError && (
            <div style={{
              background: 'rgba(184,50,50,0.08)',
              border: '1px solid rgba(184,50,50,0.2)',
              borderRadius: 10,
              padding: '10px 12px',
              color: 'var(--danger)',
              fontSize: 11,
              lineHeight: 1.5,
            }}>
              {libraryError}
            </div>
          )}
        </div>
      )}

      {activeSection === 'deployments' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, animation: 'nf-fade-in 0.18s ease' }}>
          {onDeployClick && (
            <button
              id="deploy-current-btn"
              className="nf-publish-btn"
              onClick={onDeployClick}
              style={{ marginBottom: 4 }}
            >
              🚀 Deploy Current Pipeline
            </button>
          )}

          <div className="nf-section-header" style={{ borderTop: 'none', paddingTop: 0, marginTop: 0, marginBottom: 4 }}>
            Active deployments
          </div>

          {deployments.map((dep) => (
            <div key={dep.id} className="nf-library-card" data-testid={`deployment-card-${dep.id}`}>
              <div className="nf-library-card-header">
                <span className="nf-library-card-title">{dep.name}</span>
                <span
                  title={dep.expose_lan ? 'Exposed to LAN' : 'Local only'}
                  style={{
                    fontSize: 9, fontFamily: 'var(--font-mono)', padding: '1px 6px', borderRadius: 99,
                    background: dep.expose_lan ? 'rgba(184,50,50,0.12)' : 'rgba(58,125,68,0.12)',
                    color: dep.expose_lan ? '#B83232' : '#1F4D27',
                  }}
                >
                  {dep.expose_lan ? 'LAN' : 'local'}
                </span>
              </div>

              <div className="nf-library-meta">
                <span className="nf-library-author">{dep.request_count} calls</span>
                {dep.error_count > 0 && (
                  <span style={{ color: 'var(--danger)' }}>{dep.error_count} errors</span>
                )}
              </div>

              <div className="nf-library-card-actions">
                <button
                  onClick={() => onManageDeploymentClick?.(dep.id)}
                  className="nf-pill-btn nf-pill-btn--sm nf-pill-btn--highlight"
                  style={{ flex: 1, justifyContent: 'center' }}
                >
                  Manage
                </button>
              </div>
            </div>
          ))}

          {deployments.length === 0 && !deploymentsError && (
            <div style={{
              color: 'var(--text-3)', fontSize: 12, fontStyle: 'italic',
              padding: '16px 4px', textAlign: 'center', lineHeight: 1.6,
            }}>
              No deployments yet.<br />
              Deploy the current pipeline to call it over HTTP.
            </div>
          )}
          {deploymentsError && (
            <div style={{
              background: 'rgba(184,50,50,0.08)',
              border: '1px solid rgba(184,50,50,0.2)',
              borderRadius: 10,
              padding: '10px 12px',
              color: 'var(--danger)',
              fontSize: 11,
              lineHeight: 1.5,
            }}>
              {deploymentsError}
            </div>
          )}
        </div>
      )}
      </div>

      {/* Footer: backend status */}
      <div style={{ paddingTop: 14, borderTop: '1px solid var(--border-subtle)', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div className={`nf-dot ${backendConnected ? 'nf-dot--green' : 'nf-dot--red'}`} />
          <span style={{ fontSize: 11, color: backendConnected ? 'var(--success)' : 'var(--error)', fontFamily: 'var(--font-mono)' }}>
            {backendConnected ? `Connected · ${API_BASE.split(':').pop()}` : 'Disconnected'}
          </span>
        </div>
      </div>
    </div>
  );
}
