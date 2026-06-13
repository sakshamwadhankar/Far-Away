import { useState } from 'react';
import { PipelineNodeData } from '../canvas/nodes/PipelineNode';
import { Node as RFNode } from 'reactflow';
import { ModelInfo } from '../App';
import type { StopOp, OnMax, NodeConfig } from '@shared/types';

interface RightPanelProps {
  selectedNode: RFNode<PipelineNodeData> | null;
  updateNodeData: (id: string, newData: Partial<PipelineNodeData>) => void;
  availableModels?: ModelInfo[];
  onDeleteNode: (id: string) => void;
}

const STOP_OPS: StopOp[] = ['==', '!=', '>', '<', '>=', '<=', 'contains'];
const ON_MAX_OPTIONS: OnMax[] = ['return_best', 'return_last', 'fail'];

const labelStyle: React.CSSProperties = { display: 'block', fontSize: '12px', color: '#aaa', marginBottom: '4px' };
const inputStyle: React.CSSProperties = { width: '100%', padding: '6px', background: '#1e1e1e', border: '1px solid #555', color: '#fff', borderRadius: '4px', boxSizing: 'border-box' };
const disabledInputStyle: React.CSSProperties = { ...inputStyle, border: '1px solid #444' };
const sectionHeaderStyle: React.CSSProperties = { fontSize: '11px', color: '#888', textTransform: 'uppercase', letterSpacing: '1px', marginTop: '8px', marginBottom: '4px', borderTop: '1px solid #333', paddingTop: '12px' };

export default function RightPanel({ selectedNode, updateNodeData, availableModels = [], onDeleteNode }: RightPanelProps) {
  if (!selectedNode) {
    return (
      <div style={{ width: 300, borderLeft: '1px solid #333', padding: 16, backgroundColor: '#252526' }}>
        <h3>Configuration</h3>
        <p style={{ color: '#888', fontSize: '0.9em' }}>Select a node to view properties.</p>
      </div>
    );
  }

  const { data } = selectedNode;
  const config = data.config || {};

  const handleConfigChange = (key: string, value: string | number | boolean | Record<string, string>) => {
    updateNodeData(selectedNode.id, { config: { ...config, [key]: value } });
  };

  const handleBaseChange = (key: string, value: string) => {
    updateNodeData(selectedNode.id, { [key]: value });
  };

  const groupedModels = availableModels.reduce((acc, model) => {
    if (!acc[model.provider]) acc[model.provider] = [];
    acc[model.provider].push(model);
    return acc;
  }, {} as Record<string, ModelInfo[]>);

  const providerNames: Record<string, string> = {
    'ollama': 'Local (Ollama)',
    'openai': 'OpenAI',
    'anthropic': 'Anthropic',
    'google': 'Google',
    'mock': 'Mock (Testing)'
  };

  return (
    <div style={{ width: 300, borderLeft: '1px solid #333', padding: 16, backgroundColor: '#252526', display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto' }}>
      <h3>Configuration</h3>
      
      {/* Node ID — always read-only */}
      <div>
        <label style={labelStyle}>Node ID</label>
        <input type="text" value={selectedNode.id} disabled style={disabledInputStyle} />
      </div>

      {/* Type — always read-only */}
      <div>
        <label style={labelStyle}>Type</label>
        <input type="text" value={data.type} disabled style={disabledInputStyle} />
      </div>

      {/* Role — editable */}
      <div>
        <label style={labelStyle}>Role</label>
        <input type="text" value={data.role || ''} onChange={(e) => handleBaseChange('role', e.target.value)} style={inputStyle} />
      </div>

      {/* ─── INPUT NODE ──────────────────────────────────────────────── */}
      {data.type === 'input' && (
        <>
          <div style={sectionHeaderStyle}>Input Config</div>
          <div>
            <label style={labelStyle}>Label / Prompt Placeholder</label>
            <input
              type="text"
              value={config.label || ''}
              onChange={(e) => handleConfigChange('label', e.target.value)}
              placeholder="e.g. Enter your question..."
              style={inputStyle}
            />
          </div>
        </>
      )}

      {/* ─── OUTPUT NODE ──────────────────────────────────────────────── */}
      {data.type === 'output' && (
        <>
          <div style={sectionHeaderStyle}>Output Config</div>
          <div>
            <label style={labelStyle}>Display Label</label>
            <input
              type="text"
              value={config.label || ''}
              onChange={(e) => handleConfigChange('label', e.target.value)}
              placeholder="e.g. Final Answer"
              style={inputStyle}
            />
          </div>
        </>
      )}

      {/* ─── MODEL NODE ──────────────────────────────────────────────── */}
      {data.type === 'model' && (
        <>
          <div style={sectionHeaderStyle}>Model Config</div>
          <div>
            <label style={labelStyle}>Endpoint Ref</label>
            <select 
              value={data.endpoint_ref || ''} 
              onChange={(e) => handleBaseChange('endpoint_ref', e.target.value)} 
              style={inputStyle}
            >
              <option value="" disabled>Select a model...</option>
              {Object.entries(groupedModels).map(([provider, models]) => (
                <optgroup key={provider} label={providerNames[provider] || provider}>
                  {models.map(m => (
                    <option key={m.endpoint_id} value={m.endpoint_id}>
                      {m.model_name}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
          <div>
            <label style={labelStyle}>System Prompt</label>
            <textarea rows={4} value={config.system_prompt || ''} onChange={(e) => handleConfigChange('system_prompt', e.target.value)} style={{ ...inputStyle, resize: 'vertical' }} />
          </div>
          <div>
            <label style={labelStyle}>Temperature ({config.temperature ?? 0.7})</label>
            <input type="range" min="0" max="2" step="0.1" value={config.temperature ?? 0.7} onChange={(e) => handleConfigChange('temperature', parseFloat(e.target.value))} style={{ width: '100%' }} />
          </div>
          <div>
            <label style={labelStyle}>Max Tokens</label>
            <input type="number" min="1" value={config.max_tokens ?? 2048} onChange={(e) => handleConfigChange('max_tokens', parseInt(e.target.value, 10))} style={inputStyle} />
          </div>
          <div>
            <label style={labelStyle}>Response Format</label>
            <select value={config.response_format || 'text'} onChange={(e) => handleConfigChange('response_format', e.target.value)} style={inputStyle}>
              <option value="text">Text</option>
              <option value="json">JSON</option>
            </select>
          </div>
        </>
      )}

      {/* ─── JUDGE NODE ──────────────────────────────────────────────── */}
      {data.type === 'judge' && (
        <>
          <div style={sectionHeaderStyle}>Judge Config</div>
          <div>
            <label style={labelStyle}>Score Field</label>
            <input
              type="text"
              value={config.score_field || ''}
              onChange={(e) => handleConfigChange('score_field', e.target.value)}
              placeholder="e.g. verified"
              style={inputStyle}
            />
          </div>
          <div>
            <label style={labelStyle}>Strategy</label>
            <select
              value={config.strategy || 'truthy'}
              onChange={(e) => handleConfigChange('strategy', e.target.value)}
              style={inputStyle}
            >
              <option value="truthy">Truthy</option>
              <option value="max_numeric">Max Numeric</option>
            </select>
          </div>
          <div>
            <label style={labelStyle}>Endpoint Ref</label>
            <select 
              value={data.endpoint_ref || ''} 
              onChange={(e) => handleBaseChange('endpoint_ref', e.target.value)} 
              style={inputStyle}
            >
              <option value="" disabled>Select a model...</option>
              {Object.entries(groupedModels).map(([provider, models]) => (
                <optgroup key={provider} label={providerNames[provider] || provider}>
                  {models.map(m => (
                    <option key={m.endpoint_id} value={m.endpoint_id}>
                      {m.model_name}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
          <div>
            <label style={labelStyle}>System Prompt</label>
            <textarea rows={3} value={config.system_prompt || ''} onChange={(e) => handleConfigChange('system_prompt', e.target.value)} style={{ ...inputStyle, resize: 'vertical' }} />
          </div>
        </>
      )}

      {/* ─── ROUTER NODE ─────────────────────────────────────────────── */}
      {data.type === 'router' && (
        <>
          <div style={sectionHeaderStyle}>Router Config</div>
          <div>
            <label style={labelStyle}>Endpoint Ref</label>
            <select 
              value={data.endpoint_ref || ''} 
              onChange={(e) => handleBaseChange('endpoint_ref', e.target.value)} 
              style={inputStyle}
            >
              <option value="" disabled>Select a model...</option>
              {Object.entries(groupedModels).map(([provider, models]) => (
                <optgroup key={provider} label={providerNames[provider] || provider}>
                  {models.map(m => (
                    <option key={m.endpoint_id} value={m.endpoint_id}>
                      {m.model_name}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
          <div>
            <label style={labelStyle}>System Prompt</label>
            <textarea rows={3} value={config.system_prompt || ''} onChange={(e) => handleConfigChange('system_prompt', e.target.value)} style={{ ...inputStyle, resize: 'vertical' }} />
          </div>
          <RouterConfig config={config} onConfigChange={handleConfigChange} />
        </>
      )}

      {/* ─── LOOP NODE ───────────────────────────────────────────────── */}
      {data.type === 'loop' && (
        <>
          <div style={sectionHeaderStyle}>Loop Config</div>
          <div>
            <label style={labelStyle}>Max Iterations (1–100)</label>
            <input
              type="number"
              min={1}
              max={100}
              value={config.max_iterations ?? 5}
              onChange={(e) => handleConfigChange('max_iterations', Math.min(100, Math.max(1, parseInt(e.target.value, 10) || 1)))}
              style={inputStyle}
            />
          </div>
          <div>
            <label style={labelStyle}>On Max</label>
            <select
              value={config.on_max || 'return_last'}
              onChange={(e) => handleConfigChange('on_max', e.target.value)}
              style={inputStyle}
            >
              {ON_MAX_OPTIONS.map(opt => (
                <option key={opt} value={opt}>{opt.replace(/_/g, ' ')}</option>
              ))}
            </select>
          </div>
          <StopConditionEditor config={config} onConfigChange={handleConfigChange} />
        </>
      )}

      {/* ─── DELETE BUTTON ───────────────────────────────────────────── */}
      <div style={{ marginTop: 'auto', paddingTop: '16px', borderTop: '1px solid #333' }}>
        <button
          data-testid="delete-node-button"
          onClick={() => onDeleteNode(selectedNode.id)}
          style={{
            width: '100%',
            padding: '8px',
            backgroundColor: '#dc2626',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            fontWeight: 'bold',
            fontSize: '13px',
          }}
        >
          🗑 Delete Node
        </button>
      </div>
    </div>
  );
}

// ─── Sub-components ──────────────────────────────────────────────────────────

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
      <div style={sectionHeaderStyle}>Stop Condition</div>
      <div>
        <label style={labelStyle}>Field (dot-path)</label>
        <input
          type="text"
          value={(stopWhen.field as string) || ''}
          onChange={(e) => updateStopWhen('field', e.target.value)}
          placeholder="e.g. verify.output.verified"
          style={inputStyle}
        />
      </div>
      <div>
        <label style={labelStyle}>Operator</label>
        <select
          value={(stopWhen.op as string) || '=='}
          onChange={(e) => updateStopWhen('op', e.target.value)}
          style={inputStyle}
        >
          {STOP_OPS.map(op => (
            <option key={op} value={op}>{op}</option>
          ))}
        </select>
      </div>
      <div>
        <label style={labelStyle}>Value</label>
        <input
          type="text"
          value={String(stopWhen.value ?? '')}
          onChange={(e) => {
            const raw = e.target.value;
            // Try to parse as number or boolean
            if (raw === 'true') updateStopWhen('value', true);
            else if (raw === 'false') updateStopWhen('value', false);
            else if (!isNaN(Number(raw)) && raw.trim() !== '') updateStopWhen('value', Number(raw));
            else updateStopWhen('value', raw);
          }}
          placeholder="e.g. true, 0.8, done"
          style={inputStyle}
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
      <div style={sectionHeaderStyle}>Router Config</div>
      <div>
        <label style={labelStyle}>Routing Map</label>
        {Object.entries(routingMap).map(([key, val]) => (
          <div key={key} style={{ display: 'flex', gap: '4px', marginBottom: '4px', alignItems: 'center' }}>
            <input type="text" value={key} disabled style={{ ...inputStyle, flex: 1, fontSize: '11px' }} />
            <span style={{ color: '#666' }}>→</span>
            <input
              type="text"
              value={val}
              onChange={(e) => updateMap({ ...routingMap, [key]: e.target.value })}
              style={{ ...inputStyle, flex: 1, fontSize: '11px' }}
            />
            <button
              onClick={() => removeEntry(key)}
              style={{ background: 'none', border: 'none', color: '#ef4444', cursor: 'pointer', fontSize: '14px', padding: '2px 4px' }}
              title="Remove entry"
            >
              ×
            </button>
          </div>
        ))}
        <div style={{ display: 'flex', gap: '4px', marginTop: '8px' }}>
          <input
            type="text"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            placeholder="key"
            style={{ ...inputStyle, flex: 1, fontSize: '11px' }}
          />
          <input
            type="text"
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
            placeholder="branch"
            style={{ ...inputStyle, flex: 1, fontSize: '11px' }}
          />
          <button
            onClick={addEntry}
            style={{ padding: '4px 8px', background: '#3b82f6', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '11px' }}
          >
            Add
          </button>
        </div>
      </div>
    </>
  );
}
