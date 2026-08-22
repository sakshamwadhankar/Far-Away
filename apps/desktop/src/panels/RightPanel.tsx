import { useState } from 'react';
import { PipelineNodeData } from '../canvas/nodes/PipelineNode';
import { Node as RFNode } from 'reactflow';
import { ModelInfo } from '../App';
import type { StopOp, OnMax, NodeConfig, AccessPolicy } from '@shared/types';
import { emptyPolicy } from '../canvas/accessPolicy';
import { isEndpointBearingNode } from '../canvas/serializer';

interface RightPanelProps {
  selectedNode: RFNode<PipelineNodeData> | null;
  updateNodeData: (id: string, newData: Partial<PipelineNodeData>) => void;
  availableModels?: ModelInfo[];
  onDeleteNode: (id: string) => void;
  onManageApis?: () => void;
}

const STOP_OPS: StopOp[] = ['==', '!=', '>', '<', '>=', '<=', 'contains'];
const ON_MAX_OPTIONS: OnMax[] = ['return_best', 'return_last', 'fail'];

const TYPE_COLORS: Record<string, string> = {
  input:     '#3A7D44',
  model:     '#2B4BAA',
  output:    '#7D3A6C',
  loop:      '#8A5A10',
  judge:     '#8A3A1A',
  router:    '#1A6A7D',
  transform: '#4A7D3A',
  compare:   '#5A3A8A',
};

export default function RightPanel({ selectedNode, updateNodeData, availableModels = [], onDeleteNode, onManageApis }: RightPanelProps) {
  if (!selectedNode) {
    return (
      <div className="nf-right-panel">
        <div style={{ padding: '16px 16px 0' }}>
          <div className="nf-section-header" style={{ borderTop: 'none', paddingTop: 0, marginTop: 0 }}>Configuration</div>
        </div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
          <div style={{ textAlign: 'center', color: 'var(--text-3)' }}>
            <div style={{ fontSize: 32, marginBottom: 10 }}>◎</div>
            <div style={{ fontSize: 12.5, lineHeight: 1.6 }}>
              Select a node<br />to view its properties
            </div>
          </div>
        </div>
      </div>
    );
  }

  const { data } = selectedNode;
  const config = data.config || {};
  const typeColor = TYPE_COLORS[data.type] || 'var(--accent)';

  const handleConfigChange = (key: string, value: string | number | boolean | Record<string, string>) => {
    updateNodeData(selectedNode.id, { config: { ...config, [key]: value } });
  };

  const handleBaseChange = (key: string, value: string) => {
    updateNodeData(selectedNode.id, { [key]: value });
  };

  // Access nodes: the per-capability grants live on the node body; the
  // inspector owns the numeric ceilings and the network switch.
  const accessPolicy = (config.access_policy as AccessPolicy | undefined) ?? emptyPolicy();

  const handleAccessPolicyChange = (
    key: 'max_cost_usd' | 'max_tokens' | 'allow_network',
    value: number | boolean | null,
  ) => {
    updateNodeData(selectedNode.id, {
      config: { ...config, access_policy: { ...accessPolicy, [key]: value } },
    });
  };

  const groupedModels = availableModels.reduce((acc, model) => {
    if (!acc[model.provider]) acc[model.provider] = [];
    acc[model.provider].push(model);
    return acc;
  }, {} as Record<string, ModelInfo[]>);

  const providerNames: Record<string, string> = {
    ollama:      'Local / Ngrok (Ollama)',
    openai:      'OpenAI',
    anthropic:   'Anthropic',
    google:      'Google',
    groq:        'Groq',
    openrouter:  'OpenRouter',
    nvidia:      'Nvidia NIM',
    zhipu:       'Zhipu (GLM)',
    mock:        'Mock (Testing)',
  };

  return (
    <div className="nf-right-panel nf-fade-in">
      {/* Node type header */}
      <div style={{
        padding: '14px 16px 12px',
        borderBottom: '1px solid var(--border-subtle)',
        background: 'var(--surface)',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: typeColor,
            boxShadow: `0 0 6px ${typeColor}60`,
          }} />
          <span style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            fontWeight: 500,
            color: typeColor,
            textTransform: 'uppercase',
            letterSpacing: '0.1em',
          }}>
            {data.type} node
          </span>
        </div>
        <div style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--text-3)',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}>
          {selectedNode.id}
        </div>
      </div>

      {/* Scrollable body */}
      <div className="nf-right-panel-inner">

        {/* Role */}
        <div className="nf-field-group">
          <label className="nf-label">Role</label>
          <input
            type="text"
            value={data.role || ''}
            onChange={(e) => handleBaseChange('role', e.target.value)}
            className="nf-input"
            placeholder="e.g. assistant"
          />
        </div>

        {/* ─── INPUT NODE ─────────────────────────────────────────────── */}
        {data.type === 'input' && (
          <>
            <div className="nf-section-header">Input Config</div>
            <div className="nf-field-group">
              <label className="nf-label">Label / Prompt Placeholder</label>
              <input
                type="text"
                value={config.label || ''}
                onChange={(e) => handleConfigChange('label', e.target.value)}
                placeholder="e.g. Enter your question..."
                className="nf-input"
              />
            </div>
          </>
        )}

        {/* ─── OUTPUT NODE ─────────────────────────────────────────────── */}
        {data.type === 'output' && (
          <>
            <div className="nf-section-header">Output Config</div>
            <div className="nf-field-group">
              <label className="nf-label">Display Label</label>
              <input
                type="text"
                value={config.label || ''}
                onChange={(e) => handleConfigChange('label', e.target.value)}
                placeholder="e.g. Final Answer"
                className="nf-input"
              />
            </div>
          </>
        )}

        {/* ─── MODEL / COMPUTER NODE ───────────────────────────────────── */}
        {isEndpointBearingNode(data.type) && (
          <>
            <div className="nf-section-header">{data.type === 'computer' ? 'Computer Agent Config' : 'Model Config'}</div>
            <div className="nf-field-group">
              <label className="nf-label">Endpoint</label>
              <select
                value={data.endpoint_ref || ''}
                onChange={(e) => {
                  if (e.target.value === 'MANAGE_APIS') {
                    if (onManageApis) onManageApis();
                    // Do not update node data
                    return;
                  }
                  handleBaseChange('endpoint_ref', e.target.value);
                }}
                className="nf-input"
              >
                <option value="" disabled>Select a model…</option>
                {Object.entries(groupedModels).map(([provider, models]) => (
                  <optgroup key={provider} label={providerNames[provider] || provider}>
                    {models.map(m => {
                      const isComputer = data.type === 'computer';
                      const isOptionDisabled = isComputer && !m.vision;
                      const visionBadge = m.vision
                        ? ' 👁 Vision'
                        : isComputer
                        ? ' (No Vision - Incompatible)'
                        : '';
                      return (
                        <option
                          key={m.endpoint_id}
                          value={m.endpoint_id}
                          disabled={isOptionDisabled}
                        >
                          {m.model_name}{visionBadge}
                        </option>
                      );
                    })}
                  </optgroup>
                ))}
                <optgroup label="Providers">
                  <option value="MANAGE_APIS">⚙ Add / Manage API Keys…</option>
                </optgroup>
              </select>
            </div>
            {data.type === 'model' && (
              <>
                <div className="nf-field-group">
                  <label className="nf-label">System Prompt</label>
                  <textarea
                    rows={4}
                    value={config.system_prompt || ''}
                    onChange={(e) => handleConfigChange('system_prompt', e.target.value)}
                    className="nf-input"
                  />
                </div>
                <div className="nf-field-group">
                  <label className="nf-label">Temperature — {config.temperature ?? 0.7}</label>
                  <input
                    type="range" min="0" max="2" step="0.1"
                    value={config.temperature ?? 0.7}
                    onChange={(e) => handleConfigChange('temperature', parseFloat(e.target.value))}
                    style={{ width: '100%', accentColor: 'var(--accent)' }}
                  />
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
                    <span>0 precise</span><span>2 creative</span>
                  </div>
                </div>
                <div className="nf-field-group">
                  <label className="nf-label">Max Tokens</label>
                  <input
                    type="number" min="1"
                    value={config.max_tokens ?? 2048}
                    onChange={(e) => handleConfigChange('max_tokens', parseInt(e.target.value, 10))}
                    className="nf-input nf-input--mono"
                  />
                </div>
                <div className="nf-field-group">
                  <label className="nf-label">Response Format</label>
                  <select
                    value={config.response_format || 'text'}
                    onChange={(e) => handleConfigChange('response_format', e.target.value)}
                    className="nf-input"
                  >
                    <option value="text">Text</option>
                    <option value="json">JSON</option>
                  </select>
                </div>
              </>
            )}
          </>
        )}

        {/* ─── JUDGE NODE ──────────────────────────────────────────────── */}
        {data.type === 'judge' && (
          <>
            <div className="nf-section-header">Judge Config</div>
            <div className="nf-field-group">
              <label className="nf-label">Score Field</label>
              <input
                type="text"
                value={config.score_field || ''}
                onChange={(e) => handleConfigChange('score_field', e.target.value)}
                placeholder="e.g. verified"
                className="nf-input nf-input--mono"
              />
            </div>
            <div className="nf-field-group">
              <label className="nf-label">Strategy</label>
              <select
                value={config.strategy || 'truthy'}
                onChange={(e) => handleConfigChange('strategy', e.target.value)}
                className="nf-input"
              >
                <option value="truthy">Truthy</option>
                <option value="max_numeric">Max Numeric</option>
              </select>
            </div>
          </>
        )}

        {/* ─── ROUTER NODE ─────────────────────────────────────────────── */}
        {data.type === 'router' && (
          <>
            <div className="nf-section-header">Router Config</div>
            <RouterConfig config={config} onConfigChange={handleConfigChange} />
          </>
        )}

        {/* ─── ACCESS NODE ─────────────────────────────────────────────── */}
        {data.type === 'access' && (
          <>
            <div className="nf-section-header">Access Policy</div>
            <p style={{ fontSize: 11, color: 'var(--text-2)', lineHeight: 1.5, margin: '0 0 10px' }}>
              Applies to every node downstream. Where several access nodes reach
              the same node, the most restrictive wins. Grant and revoke
              individual capabilities on the node itself.
            </p>
            <div className="nf-field-group">
              <label className="nf-label">Max cost (USD)</label>
              <input
                data-testid="access-max-cost"
                type="number" min={0} step={0.01}
                placeholder="no ceiling"
                value={accessPolicy.max_cost_usd ?? ''}
                onChange={(e) => handleAccessPolicyChange(
                  'max_cost_usd',
                  e.target.value === '' ? null : Math.max(0, parseFloat(e.target.value) || 0),
                )}
                className="nf-input nf-input--mono"
              />
            </div>
            <div className="nf-field-group">
              <label className="nf-label">Max tokens per request</label>
              <input
                data-testid="access-max-tokens"
                type="number" min={1} step={1}
                placeholder="no ceiling"
                value={accessPolicy.max_tokens ?? ''}
                onChange={(e) => handleAccessPolicyChange(
                  'max_tokens',
                  e.target.value === '' ? null : Math.max(1, parseInt(e.target.value, 10) || 1),
                )}
                className="nf-input nf-input--mono"
              />
            </div>
            <div className="nf-field-group">
              <label className="nf-label">
                <input
                  data-testid="access-allow-network"
                  type="checkbox"
                  checked={accessPolicy.allow_network}
                  onChange={(e) => handleAccessPolicyChange('allow_network', e.target.checked)}
                  style={{ marginRight: 6 }}
                />
                Allow general network access
              </label>
            </div>
          </>
        )}

        {/* ─── LOOP NODE ───────────────────────────────────────────────── */}
        {data.type === 'loop' && (
          <>
            <div className="nf-section-header">Loop Config</div>
            <div className="nf-field-group">
              <label className="nf-label">Max Iterations (1–100)</label>
              <input
                type="number" min={1} max={100}
                value={config.max_iterations ?? 5}
                onChange={(e) => handleConfigChange('max_iterations', Math.min(100, Math.max(1, parseInt(e.target.value, 10) || 1)))}
                className="nf-input nf-input--mono"
              />
            </div>
            <div className="nf-field-group">
              <label className="nf-label">On Max</label>
              <select
                value={config.on_max || 'return_last'}
                onChange={(e) => handleConfigChange('on_max', e.target.value)}
                className="nf-input"
              >
                {ON_MAX_OPTIONS.map(opt => (
                  <option key={opt} value={opt}>{opt.replace(/_/g, ' ')}</option>
                ))}
              </select>
            </div>
            <StopConditionEditor config={config} onConfigChange={handleConfigChange} />
          </>
        )}

        {/* Delete button */}
        <div style={{ marginTop: 'auto', paddingTop: 16 }}>
          <button
            data-testid="delete-node-button"
            onClick={() => onDeleteNode(selectedNode.id)}
            className="nf-pill-btn nf-pill-btn--danger"
            style={{ width: '100%', justifyContent: 'center' }}
          >
            <span>✕</span>
            Delete Node
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

interface StopConditionEditorProps {
  config: NodeConfig;
  onConfigChange: (key: string, value: string | number | boolean | Record<string, string>) => void;
}

function StopConditionEditor({ config, onConfigChange }: StopConditionEditorProps) {
  const stopWhen = (config.stop_when || {}) as Record<string, string | number | boolean>;

  const updateStopWhen = (field: string, value: string | number | boolean) => {
    const updated = { ...stopWhen, [field]: value };
    onConfigChange('stop_when', updated as unknown as Record<string, string>);
  };

  return (
    <>
      <div className="nf-section-header">Stop Condition</div>
      <div className="nf-field-group">
        <label className="nf-label">Field (dot-path)</label>
        <input
          type="text"
          value={(stopWhen.field as string) || ''}
          onChange={(e) => updateStopWhen('field', e.target.value)}
          placeholder="e.g. verify.output.verified"
          className="nf-input nf-input--mono"
        />
      </div>
      <div className="nf-field-group">
        <label className="nf-label">Operator</label>
        <select
          value={(stopWhen.op as string) || '=='}
          onChange={(e) => updateStopWhen('op', e.target.value)}
          className="nf-input"
        >
          {STOP_OPS.map(op => (
            <option key={op} value={op}>{op}</option>
          ))}
        </select>
      </div>
      <div className="nf-field-group">
        <label className="nf-label">Value</label>
        <input
          type="text"
          value={String(stopWhen.value ?? '')}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === 'true') updateStopWhen('value', true);
            else if (raw === 'false') updateStopWhen('value', false);
            else if (!isNaN(Number(raw)) && raw.trim() !== '') updateStopWhen('value', Number(raw));
            else updateStopWhen('value', raw);
          }}
          placeholder="e.g. true, 0.8, done"
          className="nf-input nf-input--mono"
        />
      </div>
    </>
  );
}

interface RouterConfigProps {
  config: NodeConfig;
  onConfigChange: (key: string, value: string | number | boolean | Record<string, string>) => void;
}

function RouterConfig({ config, onConfigChange }: RouterConfigProps) {
  const routingMap = (config.routing_map || {}) as Record<string, string>;
  const [newKey, setNewKey] = useState('');
  const [newValue, setNewValue] = useState('');

  const updateMap = (updated: Record<string, string>) => {
    onConfigChange('routing_map', updated);
  };

  const addEntry = () => {
    if (!newKey.trim()) return;
    updateMap({ ...routingMap, [newKey.trim()]: newValue.trim() });
    setNewKey('');
    setNewValue('');
  };

  const removeEntry = (key: string) => {
    const updated = { ...routingMap };
    delete updated[key];
    updateMap(updated);
  };

  return (
    <>
      <div className="nf-section-header">Routing Map</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        {Object.entries(routingMap).map(([key, val]) => (
          <div key={key} style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
            <input
              type="text" value={key} disabled
              className="nf-input nf-input--mono"
              style={{ flex: 1, fontSize: 11, opacity: 0.7 }}
            />
            <span style={{ color: 'var(--text-3)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>→</span>
            <input
              type="text" value={val}
              onChange={(e) => updateMap({ ...routingMap, [key]: e.target.value })}
              className="nf-input nf-input--mono"
              style={{ flex: 1, fontSize: 11 }}
            />
            <button
              onClick={() => removeEntry(key)}
              style={{
                background: 'none', border: 'none',
                color: 'var(--danger)', cursor: 'pointer',
                fontSize: 16, padding: '0 4px', lineHeight: 1,
                opacity: 0.7, transition: 'opacity var(--transition)',
              }}
              title="Remove"
            >
              ×
            </button>
          </div>
        ))}
        <div style={{ display: 'flex', gap: 5, marginTop: 2 }}>
          <input
            type="text" value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            placeholder="key"
            className="nf-input nf-input--mono"
            style={{ flex: 1, fontSize: 11 }}
          />
          <input
            type="text" value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
            placeholder="branch"
            className="nf-input nf-input--mono"
            style={{ flex: 1, fontSize: 11 }}
          />
          <button
            onClick={addEntry}
            className="nf-pill-btn nf-pill-btn--sm nf-pill-btn--accent"
            style={{ whiteSpace: 'nowrap' }}
          >
            Add
          </button>
        </div>
      </div>
    </>
  );
}
