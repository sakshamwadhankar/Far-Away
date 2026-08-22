import { useState, useEffect } from 'react';
import type { GovernancePrompt } from './useGovernance';
import { DOMAIN_LABELS } from './types';
import type { DomainKey, AnswerValue } from './types';
import { answerApproval } from './api';

interface ApprovalPromptProps {
  apiBase: string;
  token: string;
  prompt: GovernancePrompt;
  isExpired: boolean;
  onDismiss: (id: string) => void;
}

export default function ApprovalPrompt({ apiBase, token, prompt, isExpired, onDismiss }: ApprovalPromptProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // local countdown for visual only
  const [timeLeft, setTimeLeft] = useState(() => Math.max(0, prompt.deadlineMs - Date.now()));
  
  useEffect(() => {
    if (isExpired) return;
    const id = setInterval(() => {
      const left = Math.max(0, prompt.deadlineMs - Date.now());
      setTimeLeft(left);
      if (left === 0) clearInterval(id);
    }, 100);
    return () => clearInterval(id);
  }, [prompt.deadlineMs, isExpired]);

  const handleAnswer = async (answer: AnswerValue) => {
    if (isSubmitting || isExpired) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await answerApproval(apiBase, token, prompt.approval_id, answer);
      onDismiss(prompt.approval_id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
      setIsSubmitting(false);
    }
  };

  const domainLabel = DOMAIN_LABELS[prompt.domain as DomainKey] || prompt.domain;
  const progressPercent = Math.min(100, Math.max(0, (timeLeft / (prompt.timeout_seconds * 1000)) * 100));

  return (
    <div className="nf-gov-overlay nf-fade-in" data-testid="approval-overlay">
      <div className="nf-gov-prompt nf-card" role="dialog" aria-modal="true" data-testid="approval-prompt">
        <div className={`nf-gov-prompt-header ${isExpired ? 'nf-gov-prompt-header--expired' : ''}`}>
          <h3>{isExpired ? 'Approval Timeout' : 'Approval Required'}</h3>
          {!isExpired && (
            <div className="nf-gov-timer">
              {(timeLeft / 1000).toFixed(1)}s
              <div className="nf-gov-progress-bar">
                <div className="nf-gov-progress-fill" style={{ width: `${progressPercent}%` }} />
              </div>
            </div>
          )}
        </div>
        
        <div className="nf-gov-prompt-body">
          {error && <div className="nf-gov-error">{error}</div>}
          
          <div className="nf-gov-prompt-request">
            <div className="nf-gov-prompt-row">
              <span className="nf-label">Domain</span>
              <span>{domainLabel}</span>
            </div>
            <div className="nf-gov-prompt-row">
              <span className="nf-label">Capability</span>
              <span className="nf-gov-col-mono">{prompt.capability}</span>
            </div>
            <div className="nf-gov-prompt-row">
              <span className="nf-label">Reason</span>
              <span>{prompt.reason}</span>
            </div>
          </div>
          
          {isExpired ? (
            <div className="nf-gov-expired-message">
              <p>This request timed out and was automatically <strong>DENIED</strong>.</p>
              <button className="nf-pill-btn" onClick={() => onDismiss(prompt.approval_id)} autoFocus>Close</button>
            </div>
          ) : (
            <div className="nf-gov-prompt-actions">
              <div className="nf-gov-action-col">
                <button 
                  className="nf-gov-btn-allow-once nf-gov-btn-action"
                  onClick={() => handleAnswer('allow_once')}
                  disabled={isSubmitting}
                >
                  <span className="nf-gov-btn-title">Allow Once</span>
                  <span className="nf-gov-btn-desc">{prompt.allow_once_effect}</span>
                </button>
                <button 
                  className="nf-gov-btn-allow-run nf-gov-btn-action"
                  onClick={() => handleAnswer('allow_for_run')}
                  disabled={isSubmitting}
                >
                  <span className="nf-gov-btn-title">Allow for Run</span>
                  <span className="nf-gov-btn-desc">{prompt.allow_for_run_effect}</span>
                </button>
              </div>
              <div className="nf-gov-action-col">
                <button 
                  className="nf-gov-btn-deny nf-gov-btn-action"
                  onClick={() => handleAnswer('deny')}
                  disabled={isSubmitting}
                >
                  <span className="nf-gov-btn-title">Deny</span>
                  <span className="nf-gov-btn-desc">{prompt.deny_effect}</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
