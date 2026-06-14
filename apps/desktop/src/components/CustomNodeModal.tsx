import { useState } from 'react';

const PORT_TYPES = ['text', 'number', 'boolean', 'json', 'image', 'audio'] as const;

const PRESET_COLORS = [
  '#6B3AB8', // purple
  '#2B4BAA', // blue
  '#1A7D9D', // teal
  '#3A7D44', // green
  '#A86A1A', // amber
  '#B83232', // red
  '#7D3A6C', // magenta
  '#5A5E54', // slate
];

interface PortDef {
  name: string;
  type: string;
}

interface CustomNodeModalProps {
  onSave: (data: {
    name: string;
    description: string;
    author: string;
    icon_color: string;
    inputs: PortDef[];
    outputs: PortDef[];
    template: string;
    tags: string;
  }) => void;
  onCancel: () => void;
}

export default function CustomNodeModal({ onSave, onCancel }: CustomNodeModalProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [author, setAuthor] = useState('');
  const [iconColor, setIconColor] = useState(PRESET_COLORS[0]);
  const [inputs, setInputs] = useState<PortDef[]>([{ name: 'input', type: 'text' }]);
  const [outputs, setOutputs] = useState<PortDef[]>([{ name: 'output', type: 'text' }]);
  const [template, setTemplate] = useState('{{ input }}');
  const [tags, setTags] = useState('');

  const canSubmit = name.trim().length > 0 && outputs.length > 0;

  const addPort = (side: 'inputs' | 'outputs') => {
    const setter = side === 'inputs' ? setInputs : setOutputs;
    setter(prev => [...prev, { name: '', type: 'text' }]);
  };

  const removePort = (side: 'inputs' | 'outputs', idx: number) => {
    const setter = side === 'inputs' ? setInputs : setOutputs;
    setter(prev => prev.filter((_, i) => i !== idx));
  };

  const updatePort = (side: 'inputs' | 'outputs', idx: number, field: 'name' | 'type', value: string) => {
    const setter = side === 'inputs' ? setInputs : setOutputs;
    setter(prev => prev.map((p, i) => i === idx ? { ...p, [field]: value } : p));
  };

  const renderPortEditor = (side: 'inputs' | 'outputs', ports: PortDef[]) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      {ports.map((port, idx) => (
        <div key={idx} className="nf-port-editor-row">
          <input
            type="text"
            value={port.name}
            onChange={e => updatePort(side, idx, 'name', e.target.value)}
            className="nf-input nf-input--mono"
            placeholder="port name"
          />
          <select
            value={port.type}
            onChange={e => updatePort(side, idx, 'type', e.target.value)}
            className="nf-input"
            style={{ flex: '0 0 80px', fontSize: 11 }}
          >
            {PORT_TYPES.map(t => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <button
            className="nf-port-remove-btn"
            onClick={() => removePort(side, idx)}
            title="Remove port"
          >
            ✕
          </button>
        </div>
      ))}
      <button
        className="nf-pill-btn nf-pill-btn--sm"
        onClick={() => addPort(side)}
        style={{ alignSelf: 'flex-start', fontSize: 10 }}
      >
        + Add {side === 'inputs' ? 'Input' : 'Output'}
      </button>
    </div>
  );

  return (
    <div
      id="custom-node-modal-overlay"
      style={{
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
        backgroundColor: 'rgba(0,0,0,0.45)',
        display: 'flex', justifyContent: 'center', alignItems: 'center',
        zIndex: 1000,
        backdropFilter: 'blur(4px)',
        animation: 'nf-fade-in 0.18s ease',
      }}
      onClick={(e) => { if ((e.target as HTMLElement).id === 'custom-node-modal-overlay') onCancel(); }}
    >
      <div style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-card)',
        padding: '28px 28px 24px',
        width: '500px',
        maxHeight: '85vh',
        overflowY: 'auto',
        boxShadow: 'var(--shadow-lg)',
        color: 'var(--text)',
        animation: 'nf-fade-in 0.22s ease',
      }}>
        <h2 style={{
          marginTop: 0, marginBottom: '6px', fontSize: '17px',
          fontFamily: 'var(--font-ui)', fontWeight: 600, color: 'var(--text)',
        }}>
          ✦ Create Custom Node
        </h2>
        <p style={{
          fontSize: '12px', color: 'var(--text-3)', marginBottom: '20px', lineHeight: 1.5,
        }}>
          Design a reusable node with custom inputs, outputs, and Jinja2 transform logic.
        </p>

        {/* Name */}
        <div style={{ marginBottom: '12px' }}>
          <label className="nf-label">Node Name *</label>
          <input
            id="custom-node-name"
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            className="nf-input"
            placeholder="e.g. JSON Formatter"
          />
        </div>

        {/* Description */}
        <div style={{ marginBottom: '12px' }}>
          <label className="nf-label">Description</label>
          <input
            id="custom-node-desc"
            type="text"
            value={description}
            onChange={e => setDescription(e.target.value)}
            className="nf-input"
            placeholder="What does this node do?"
          />
        </div>

        {/* Author */}
        <div style={{ marginBottom: '12px' }}>
          <label className="nf-label">Author</label>
          <input
            id="custom-node-author"
            type="text"
            value={author}
            onChange={e => setAuthor(e.target.value)}
            className="nf-input"
            placeholder="Your name (default: Anonymous)"
          />
        </div>

        {/* Color */}
        <div style={{ marginBottom: '16px' }}>
          <label className="nf-label">Accent Color</label>
          <div className="nf-color-picker">
            {PRESET_COLORS.map(c => (
              <div
                key={c}
                className={`nf-color-swatch ${iconColor === c ? 'nf-color-swatch--selected' : ''}`}
                style={{ background: c }}
                onClick={() => setIconColor(c)}
                title={c}
              />
            ))}
          </div>
        </div>

        {/* Inputs */}
        <div style={{ marginBottom: '14px' }}>
          <label className="nf-label">Input Ports</label>
          {renderPortEditor('inputs', inputs)}
        </div>

        {/* Outputs */}
        <div style={{ marginBottom: '14px' }}>
          <label className="nf-label">Output Ports</label>
          {renderPortEditor('outputs', outputs)}
        </div>

        {/* Template */}
        <div style={{ marginBottom: '14px' }}>
          <label className="nf-label">Jinja2 Template</label>
          <textarea
            id="custom-node-template"
            value={template}
            onChange={e => setTemplate(e.target.value)}
            className="nf-input nf-input--mono"
            rows={5}
            style={{ resize: 'vertical', minHeight: '80px', fontSize: 12, lineHeight: 1.5 }}
            placeholder={'{{ input }}\n\nUse port names as variables.\nE.g. {{ name | upper }}'}
          />
          <div style={{ fontSize: '10px', color: 'var(--text-3)', marginTop: '4px', lineHeight: 1.4 }}>
            Port names become Jinja2 variables. Use <code style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{'{{ port_name }}'}</code> to reference them.
          </div>
        </div>

        {/* Tags */}
        <div style={{ marginBottom: '20px' }}>
          <label className="nf-label">Tags</label>
          <input
            id="custom-node-tags"
            type="text"
            value={tags}
            onChange={e => setTags(e.target.value)}
            className="nf-input nf-input--mono"
            placeholder="e.g. formatter, json, utility"
          />
        </div>

        {/* Preview */}
        <div style={{
          marginBottom: '20px',
          padding: '12px',
          background: 'rgba(30,35,25,0.03)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-card)',
        }}>
          <div style={{ fontSize: 10, color: 'var(--text-3)', marginBottom: 8, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Preview
          </div>
          <div style={{
            background: '#F4F2EB',
            border: '1.5px solid rgba(30,35,25,0.15)',
            borderRadius: 12,
            overflow: 'hidden',
            width: 160,
          }}>
            <div style={{
              background: `${iconColor}22`,
              borderBottom: `1px solid ${iconColor}33`,
              padding: '6px 10px',
              display: 'flex',
              alignItems: 'center',
              gap: 5,
            }}>
              <div style={{ width: 6, height: 6, borderRadius: '50%', background: iconColor }} />
              <span style={{
                fontFamily: "'DM Mono', monospace",
                fontSize: 10,
                fontWeight: 700,
                color: iconColor,
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
              }}>
                {name || 'custom'}
              </span>
            </div>
            <div style={{ padding: '8px 10px', display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: "'DM Mono', monospace", color: '#5A5E54' }}>
              <div>
                {inputs.filter(p => p.name).map(p => (
                  <div key={p.name}>● {p.name}</div>
                ))}
              </div>
              <div style={{ textAlign: 'right' }}>
                {outputs.filter(p => p.name).map(p => (
                  <div key={p.name}>{p.name} ●</div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
          <button
            id="custom-node-cancel"
            onClick={onCancel}
            className="nf-pill-btn"
          >
            Cancel
          </button>
          <button
            id="custom-node-save"
            onClick={() => onSave({
              name: name.trim(),
              description: description.trim(),
              author: author.trim() || 'Anonymous',
              icon_color: iconColor,
              inputs: inputs.filter(p => p.name.trim()),
              outputs: outputs.filter(p => p.name.trim()),
              template: template,
              tags: tags.trim(),
            })}
            disabled={!canSubmit}
            className="nf-pill-btn nf-pill-btn--highlight"
          >
            ✦ Create Node
          </button>
        </div>
      </div>
    </div>
  );
}
