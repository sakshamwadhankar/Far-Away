import React, { useState, useEffect } from 'react';

interface SettingsModalProps {
  onClose: () => void;
  backendPort: number | null;
  backendToken: string | null;
  API_BASE: string;
}

export default function SettingsModal({ onClose, backendToken, API_BASE }: SettingsModalProps) {
  const [keys, setKeys] = useState<Record<string, string>>({
    openai: '',
    anthropic: '',
    google: '',
    groq: '',
    openrouter: '',
    zhipu: '',
    nvidia: ''
  });
  const [status, setStatus] = useState<Record<string, boolean>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  const providers = [
    { id: 'openai', label: 'OpenAI API Key', placeholder: 'sk-...' },
    { id: 'anthropic', label: 'Anthropic API Key', placeholder: 'sk-ant-...' },
    { id: 'google', label: 'Google Gemini API Key', placeholder: 'AIzaSy...' },
    { id: 'groq', label: 'Groq API Key', placeholder: 'gsk_...' },
    { id: 'openrouter', label: 'OpenRouter API Key', placeholder: 'sk-or-v1-...' },
    { id: 'zhipu', label: 'Zhipu (GLM) API Key', placeholder: '...' },
    { id: 'nvidia', label: 'Nvidia NIM API Key', placeholder: 'nvapi-...' },
  ];

  useEffect(() => {
    if (!backendToken) return;
    fetch(`${API_BASE}/settings/api-keys`, {
      headers: { 'Authorization': `Bearer ${backendToken}` }
    })
      .then(res => res.json())
      .then(data => {
        setStatus(data.keys || {});
        setIsLoading(false);
      })
      .catch(err => {
        console.error('Failed to fetch API keys status', err);
        setIsLoading(false);
      });
  }, [backendToken, API_BASE]);

  const handleChange = (id: string, value: string) => {
    setKeys(prev => ({ ...prev, [id]: value }));
  };

  const handleSave = async () => {
    if (!backendToken) return;
    setIsSaving(true);
    try {
      const res = await fetch(`${API_BASE}/settings/api-keys`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${backendToken}`
        },
        body: JSON.stringify({ keys })
      });
      if (res.ok) {
        onClose();
        // Force reload models list globally
        window.dispatchEvent(new Event('focus')); // quick hack to trigger re-fetch if app is listening to focus, or we just rely on next fetch
      } else {
        console.error('Failed to save API keys');
      }
    } catch (e) {
      console.error(e);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0,0,0,0.5)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center'
    }}>
      <div style={{
        background: 'var(--bg)', width: 480, borderRadius: 'var(--radius-lg)',
        boxShadow: 'var(--shadow-lg)', padding: '24px 32px',
        maxHeight: '90vh', overflowY: 'auto'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
          <h2 style={{ margin: 0, fontSize: 20, color: 'var(--text)' }}>Manage API Providers</h2>
          <button onClick={onClose} className="nf-pill-btn" style={{ padding: '4px 10px' }}>✕</button>
        </div>

        {isLoading ? (
          <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-2)' }}>Loading...</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <p style={{ fontSize: 13, color: 'var(--text-2)', margin: '0 0 8px 0', lineHeight: 1.5 }}>
              Enter your API keys below to unlock models from these providers. 
              Keys are securely stored in your OS keychain. Leave blank to keep existing keys.
            </p>

            {providers.map(p => (
              <div key={p.id} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <label style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)' }}>
                  {p.label} {status[p.id] && <span style={{ color: 'var(--success)', marginLeft: 8, fontSize: 11 }}>✓ Configured</span>}
                </label>
                <input
                  type="password"
                  value={keys[p.id] || ''}
                  onChange={e => handleChange(p.id, e.target.value)}
                  placeholder={status[p.id] ? '•••••••••••••••• (Leave blank to keep)' : p.placeholder}
                  className="nf-input"
                  style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}
                />
              </div>
            ))}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12, marginTop: 24 }}>
              <button onClick={onClose} className="nf-pill-btn" style={{ background: 'transparent', border: '1px solid var(--border)' }}>
                Cancel
              </button>
              <button onClick={handleSave} disabled={isSaving} className="nf-create-custom-btn" style={{ margin: 0 }}>
                {isSaving ? 'Saving...' : 'Save Keys'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
