import { useState, useEffect, useCallback, useMemo } from 'react';
import type { DecisionRecord, DomainKey, OutcomeValue } from './types';
import { DOMAIN_LABELS } from './types';
import type { DecisionFilters, OriginFilter } from './api';
import { fetchDecisions, exportDecisions } from './api';
import { outcomeStyle, originLabel, timeShort, HUMAN_ORIGINS } from './display';

interface DecisionHistoryProps {
  apiBase: string;
  token: string;
  onClose: () => void;
  liveDecisions: DecisionRecord[];
}

export default function DecisionHistory({ apiBase, token, onClose, liveDecisions }: DecisionHistoryProps) {
  const [filters, setFilters] = useState<DecisionFilters>({});
  const [decisions, setDecisions] = useState<DecisionRecord[]>([]);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportFormat, setExportFormat] = useState<'json' | 'csv'>('csv');

  const loadDecisions = useCallback(async (reset = false) => {
    setIsLoading(true);
    setError(null);
    try {
      const page = reset ? {} : { cursor: nextCursor };
      const res = await fetchDecisions(apiBase, token, filters, page);
      setDecisions(prev => reset ? res.decisions : [...prev, ...res.decisions]);
      setNextCursor(res.next_cursor);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLoading(false);
    }
  }, [apiBase, token, filters, nextCursor]);

  useEffect(() => {
    loadDecisions(true);
  }, [filters]); // eslint-disable-line react-hooks/exhaustive-deps

  const combinedDecisions = useMemo(() => {
    // Merge live decisions at the top if they match filters
    const filteredLive = liveDecisions.filter(d => {
      if (filters.domain && d.domain !== filters.domain) return false;
      if (filters.outcome && d.outcome !== filters.outcome) return false;
      if (filters.origin && d.origin !== filters.origin) return false;
      if (filters.run_id && d.run_id !== filters.run_id) return false;
      return true;
    });
    
    const fetchedIds = new Set(decisions.map(d => d.decision_id));
    const newLive = filteredLive.filter(d => !fetchedIds.has(d.decision_id));
    
    return [...newLive, ...decisions];
  }, [decisions, liveDecisions, filters]);

  const handleExport = async () => {
    try {
      const blob = await exportDecisions(apiBase, token, filters, exportFormat);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `decisions_export.${exportFormat}`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err: unknown) {
      setError(`Export failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  return (
    <div className="nf-gov-panel nf-gov-panel--large nf-card nf-fade-in" role="dialog" aria-modal="true" data-testid="decision-history">
      <div className="nf-gov-panel-header">
        <h3>Decision History</h3>
        <button className="nf-icon-btn--danger" onClick={onClose} aria-label="Close">✕</button>
      </div>
      
      <div className="nf-gov-filters">
        <div className="nf-gov-filter-group">
          <label className="nf-label">Domain</label>
          <select className="nf-input" value={filters.domain || ''} onChange={e => setFilters((f: DecisionFilters) => ({ ...f, domain: (e.target.value as DomainKey) || undefined }))}>
            <option value="">All</option>
            {(Object.keys(DOMAIN_LABELS) as DomainKey[]).map(d => <option key={d} value={d}>{DOMAIN_LABELS[d]}</option>)}
          </select>
        </div>
        <div className="nf-gov-filter-group">
          <label className="nf-label">Outcome</label>
          <select className="nf-input" value={filters.outcome || ''} onChange={e => setFilters((f: DecisionFilters) => ({ ...f, outcome: (e.target.value as OutcomeValue) || undefined }))}>
            <option value="">All</option>
            <option value="allow">Allowed</option>
            <option value="deny">Denied</option>
            <option value="timeout">Timeout</option>
          </select>
        </div>
        <div className="nf-gov-filter-group">
          <label className="nf-label">Origin</label>
          <select className="nf-input" value={filters.origin || ''} onChange={e => setFilters((f: DecisionFilters) => ({ ...f, origin: (e.target.value as OriginFilter) || undefined }))}>
            <option value="">All</option>
            <option value="pipeline_policy">Pipeline policy</option>
            <option value="profile">Profile</option>
            <option value="pipeline_and_profile">Pipeline + profile</option>
            <option value="human_allow_once">Human (Allow Once)</option>
            <option value="human_allow_for_run">Human (Allow for Run)</option>
            <option value="human_deny">Human (Deny)</option>
          </select>
        </div>
        <div className="nf-gov-filter-group" style={{ flex: 1 }}>
          <label className="nf-label">Run ID</label>
          <input className="nf-input" placeholder="Filter by Run ID" value={filters.run_id || ''} onChange={e => setFilters((f: DecisionFilters) => ({ ...f, run_id: e.target.value || undefined }))} />
        </div>
        <div className="nf-gov-filter-group" style={{ alignSelf: 'flex-end', display: 'flex', gap: 4 }}>
          <select className="nf-input" style={{ width: 80 }} value={exportFormat} onChange={e => setExportFormat(e.target.value as 'csv' | 'json')}>
            <option value="csv">CSV</option>
            <option value="json">JSON</option>
          </select>
          <button className="nf-pill-btn" onClick={handleExport}>Export</button>
        </div>
      </div>

      <div className="nf-gov-history-body">
        {error && <div className="nf-gov-error">{error}</div>}
        
        {combinedDecisions.length === 0 && !isLoading ? (
          <div className="nf-gov-empty">
            <div className="nf-gov-empty-icon">🛡️</div>
            <h4>No decisions recorded yet</h4>
            <p>
              When the active profile uses an "Ask" or "Enforce" posture, and a pipeline attempts a restricted action,
              the resulting allow/deny decisions will appear here. This panel provides a full audit trail of what was requested,
              what happened, why, and who approved it.
            </p>
          </div>
        ) : (
          <div className="nf-gov-table-container">
            <table className="nf-gov-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Domain</th>
                  <th>Capability</th>
                  <th>Outcome</th>
                  <th>Origin</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {combinedDecisions.map(d => {
                  const style = outcomeStyle(d.outcome);
                  const isHuman = HUMAN_ORIGINS.has(d.origin);
                  
                  return (
                    <tr key={d.decision_id} tabIndex={0} className={isHuman ? 'nf-gov-row-human' : ''}>
                      <td className="nf-gov-col-time">{timeShort(d.when_utc)}</td>
                      <td>{DOMAIN_LABELS[d.domain as DomainKey] || d.domain}</td>
                      <td className="nf-gov-col-mono">{d.capability}</td>
                      <td>
                        <span className={`nf-gov-outcome ${style.className}`}>
                          {style.glyph} {style.label}
                        </span>
                      </td>
                      <td>
                        <span className={`nf-gov-origin ${isHuman ? 'nf-gov-origin-human' : ''}`}>
                          {originLabel(d.origin)}
                        </span>
                      </td>
                      <td className="nf-gov-col-reason">{d.reason}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            
            {nextCursor && (
              <div className="nf-gov-load-more">
                <button 
                  className="nf-pill-btn" 
                  onClick={() => loadDecisions(false)}
                  disabled={isLoading}
                >
                  {isLoading ? 'Loading...' : 'Load More'}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
