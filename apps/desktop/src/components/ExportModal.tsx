import { useState } from 'react';

interface ExportModalProps {
  initialName: string;
  onExport: (name: string, description: string) => void;
  onCancel: () => void;
}

export default function ExportModal({ initialName, onExport, onCancel }: ExportModalProps) {
  const [name, setName] = useState(initialName || 'My Pipeline');
  const [description, setDescription] = useState('');

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      backgroundColor: 'rgba(0,0,0,0.6)',
      display: 'flex', justifyContent: 'center', alignItems: 'center',
      zIndex: 1000
    }}>
      <div style={{
        background: '#1e1e1e',
        border: '1px solid #444',
        borderRadius: '8px',
        padding: '24px',
        width: '400px',
        boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
        color: '#fff'
      }}>
        <h2 style={{ marginTop: 0, marginBottom: '20px', fontSize: '18px' }}>Export Pipeline</h2>
        
        <div style={{ marginBottom: '16px' }}>
          <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', color: '#ccc' }}>Pipeline Name</label>
          <input 
            type="text" 
            value={name}
            onChange={e => setName(e.target.value)}
            style={{
              width: '100%', padding: '8px', 
              background: '#2d2d2d', border: '1px solid #555', 
              borderRadius: '4px', color: '#fff', fontSize: '14px',
              boxSizing: 'border-box'
            }}
          />
        </div>

        <div style={{ marginBottom: '24px' }}>
          <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', color: '#ccc' }}>Description (optional)</label>
          <textarea 
            value={description}
            onChange={e => setDescription(e.target.value)}
            rows={3}
            style={{
              width: '100%', padding: '8px', 
              background: '#2d2d2d', border: '1px solid #555', 
              borderRadius: '4px', color: '#fff', fontSize: '14px',
              boxSizing: 'border-box', resize: 'vertical'
            }}
          />
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          <button 
            onClick={onCancel}
            style={{
              padding: '8px 16px', background: 'transparent',
              border: '1px solid #555', color: '#ccc',
              borderRadius: '4px', cursor: 'pointer'
            }}
          >
            Cancel
          </button>
          <button 
            onClick={() => onExport(name, description)}
            disabled={!name.trim()}
            style={{
              padding: '8px 16px', background: '#3b82f6',
              border: 'none', color: '#fff', fontWeight: 'bold',
              borderRadius: '4px', cursor: name.trim() ? 'pointer' : 'not-allowed',
              opacity: name.trim() ? 1 : 0.5
            }}
          >
            Export
          </button>
        </div>
      </div>
    </div>
  );
}
