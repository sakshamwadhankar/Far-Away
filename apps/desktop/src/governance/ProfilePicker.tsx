import { useState } from 'react';
import type { ProfileSpec, DomainKey, PostureValue, ProfilesResponse, ActiveProfileResponse } from './types';
import { DOMAIN_LABELS, POSTURE_CONSEQUENCES, POSTURE_LABELS } from './types';
import { createProfile, updateProfile, deleteProfile, setActiveProfile } from './api';

interface ProfilePickerProps {
  apiBase: string;
  token: string;
  profiles: ProfilesResponse | null;
  active: ActiveProfileResponse | null;
  refreshProfiles: () => Promise<void>;
  onClose: () => void;
}

export default function ProfilePicker({
  apiBase,
  token,
  profiles,
  active,
  refreshProfiles,
  onClose
}: ProfilePickerProps) {

  const [editForm, setEditForm] = useState<Partial<ProfileSpec> | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeName = active?.name || 'locked';
  const allProfiles = profiles?.profiles || [];
  
  const handleSelect = async (name: string) => {
    try {
      await setActiveProfile(apiBase, token, name);
      await refreshProfiles();
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleCreateNew = () => {
    setIsCreating(true);
    setEditForm({
      name: '',
      built_in: false,
      postures: { providers: 'ask', egress: 'ask', spend: 'ask', retention: 'ask' },
      spend_cap_usd: null,
      spend_ask_threshold_usd: null,
      retention: '30d'
    });
  };

  const handleEdit = (p: ProfileSpec) => {
    if (p.built_in) return;
    setIsCreating(false);
    setEditForm({ ...p });
  };

  const handleDelete = async (name: string) => {
    if (!window.confirm(`Delete profile ${name}?`)) return;
    try {
      await deleteProfile(apiBase, token, name);
      await refreshProfiles();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleSave = async () => {
    if (!editForm || !editForm.name) return;
    try {
      const payload = {
        name: editForm.name,
        postures: editForm.postures as Record<DomainKey, PostureValue>,
        spend_cap_usd: editForm.spend_cap_usd || null,
        spend_ask_threshold_usd: editForm.spend_ask_threshold_usd || null,
        retention: editForm.retention || '30d'
      };
      
      if (isCreating) {
        await createProfile(apiBase, token, payload);
      } else {
        await updateProfile(apiBase, token, payload.name, payload);
      }
      await refreshProfiles();
      setEditForm(null);
      setIsCreating(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const updatePosture = (domain: DomainKey, val: PostureValue) => {
    setEditForm(prev => {
      if (!prev || !prev.postures) return prev;
      return { ...prev, postures: { ...prev.postures, [domain]: val } };
    });
  };

  if (editForm) {
    return (
      <div className="nf-gov-panel nf-card nf-fade-in" role="dialog" aria-modal="true" data-testid="profile-editor">
        <div className="nf-gov-panel-header">
          <h3>{isCreating ? 'Create Profile' : `Edit Profile: ${editForm.name}`}</h3>
          <button className="nf-icon-btn--danger" onClick={() => setEditForm(null)}>✕</button>
        </div>
        <div className="nf-gov-panel-body">
          {error && <div className="nf-gov-error">{error}</div>}
          <div className="nf-field-group" style={{ marginBottom: 12 }}>
            <label className="nf-label">Profile Name</label>
            <input
              className="nf-input"
              value={editForm.name || ''}
              onChange={e => setEditForm(prev => ({ ...prev!, name: e.target.value }))}
              disabled={!isCreating}
              autoFocus
            />
          </div>
          
          <div className="nf-section-header">Domain Postures</div>
          <div className="nf-gov-postures-grid">
            {(Object.keys(DOMAIN_LABELS) as DomainKey[]).map(domain => (
              <div key={domain} className="nf-gov-posture-row">
                <div className="nf-gov-posture-label">{DOMAIN_LABELS[domain]}</div>
                <select 
                  className="nf-input nf-input--mono" 
                  value={editForm.postures?.[domain] || 'ask'}
                  onChange={e => updatePosture(domain, e.target.value as PostureValue)}
                >
                  <option value="enforce">Enforce</option>
                  <option value="ask">Ask</option>
                  <option value="audit">Audit</option>
                </select>
                <div className="nf-gov-posture-desc">
                  {POSTURE_CONSEQUENCES[editForm.postures?.[domain] as PostureValue || 'ask']}
                </div>
              </div>
            ))}
          </div>
          
          <div className="nf-section-header" style={{ marginTop: 12 }}>Limits</div>
          <div className="nf-field-group">
            <label className="nf-label">Spend Cap (USD)</label>
            <input
              type="number"
              className="nf-input"
              value={editForm.spend_cap_usd || ''}
              onChange={e => setEditForm(prev => ({ ...prev!, spend_cap_usd: e.target.value ? parseFloat(e.target.value) : null }))}
              placeholder="e.g. 100"
            />
          </div>
          <div className="nf-field-group" style={{ marginTop: 8 }}>
            <label className="nf-label">Ask Threshold (USD)</label>
            <input
              type="number"
              className="nf-input"
              value={editForm.spend_ask_threshold_usd || ''}
              onChange={e => setEditForm(prev => ({ ...prev!, spend_ask_threshold_usd: e.target.value ? parseFloat(e.target.value) : null }))}
              placeholder="e.g. 10"
            />
          </div>
        </div>
        <div className="nf-gov-panel-footer" style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="nf-pill-btn" onClick={() => setEditForm(null)}>Cancel</button>
          <button className="nf-pill-btn nf-pill-btn--accent" onClick={handleSave}>Save</button>
        </div>
      </div>
    );
  }

  return (
    <div className="nf-gov-panel nf-card nf-fade-in" role="dialog" aria-modal="true" data-testid="profile-picker">
      <div className="nf-gov-panel-header">
        <h3>Governance Profile</h3>
        <button className="nf-icon-btn--danger" onClick={onClose} aria-label="Close">✕</button>
      </div>
      <div className="nf-gov-panel-body">
        {error && <div className="nf-gov-error">{error}</div>}
        <div className="nf-gov-profiles-list">
          {allProfiles.map(p => (
            <div 
              key={p.profile.name} 
              className={`nf-gov-profile-card ${activeName === p.profile.name ? 'active' : ''}`}
              onClick={() => handleSelect(p.profile.name)}
              tabIndex={0}
              role="button"
              onKeyDown={(e) => e.key === 'Enter' && handleSelect(p.profile.name)}
            >
              <div className="nf-gov-profile-card-header">
                <strong>{p.profile.name}</strong>
                {p.profile.built_in && <span className="nf-tag">Built-in</span>}
                {activeName === p.profile.name && <span className="nf-tag nf-tag--connected">Active</span>}
              </div>
              <div className="nf-gov-profile-details">
                {(Object.keys(DOMAIN_LABELS) as DomainKey[]).map(d => (
                  <div key={d} className="nf-gov-profile-domain-info" title={POSTURE_CONSEQUENCES[p.profile.postures[d]]}>
                    <span className="nf-gov-domain-name">{DOMAIN_LABELS[d]}:</span>
                    <span className="nf-gov-posture-name">{POSTURE_LABELS[p.profile.postures[d]]}</span>
                  </div>
                ))}
              </div>
              {!p.profile.built_in && (
                <div className="nf-gov-profile-actions">
                  <button 
                    className="nf-pill-btn nf-pill-btn--sm"
                    onClick={(e) => { e.stopPropagation(); handleEdit(p.profile); }}
                  >Edit</button>
                  <button 
                    className="nf-pill-btn nf-pill-btn--sm nf-pill-btn--danger"
                    onClick={(e) => { e.stopPropagation(); handleDelete(p.profile.name); }}
                  >Delete</button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      <div className="nf-gov-panel-footer">
        <button className="nf-pill-btn nf-pill-btn--highlight" onClick={handleCreateNew} style={{ width: '100%', justifyContent: 'center' }}>
          + Create Custom Profile
        </button>
      </div>
    </div>
  );
}
