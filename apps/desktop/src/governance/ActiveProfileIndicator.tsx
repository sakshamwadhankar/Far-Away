/**
 * Surface (a): ACTIVE PROFILE INDICATOR.
 *
 * Always visible — fixed to the viewport, not inside any collapsible panel
 * — so the profile in force is never more than a glance away, including
 * mid-run. Clicking it opens the dial (ProfilePicker).
 */

import { DOMAIN_LABELS } from './types';
import type { DomainKey, ProfileSpec } from './types';

interface ActiveProfileIndicatorProps {
  activeName: string | null;
  activeProfile: ProfileSpec | null;
  connected: boolean;
  onOpenPicker: () => void;
}

const PROFILE_DOT: Record<string, string> = {
  explore: 'var(--highlight)',
  review: '#B8960A',
  locked: 'var(--danger)',
};

const POSTURE_MARK: Record<string, string> = {
  enforce: '■',
  ask: '?',
  audit: '○',
};

export default function ActiveProfileIndicator({
  activeName,
  activeProfile,
  connected,
  onOpenPicker,
}: ActiveProfileIndicatorProps) {
  const name = (activeName || 'locked').toLowerCase();
  const dot = PROFILE_DOT[name] ?? 'var(--text-3)';
  const postures = activeProfile?.postures;

  return (
    <div className="nf-gov-indicator" data-testid="governance-indicator">
      <button
        type="button"
        className="nf-gov-indicator-btn"
        data-testid="governance-indicator-button"
        data-active-profile={name}
        onClick={onOpenPicker}
        title="Governance profile — click to change"
      >
        <span className="nf-dot" style={{ background: dot }} />
        {!connected && (
          <span className="nf-tag nf-tag--checking" title="Backend offline">offline</span>
        )}
        <span className="nf-gov-indicator-label">GOVERNANCE</span>
        <span className="nf-gov-indicator-name" data-testid="active-profile-name">{name}</span>
        {postures && (
          <span className="nf-gov-indicator-postures">
            {(Object.keys(DOMAIN_LABELS) as DomainKey[]).map((d) => (
              <span key={d} className="nf-gov-posture-mark" title={`${DOMAIN_LABELS[d]}: ${postures[d]}`}>
                {POSTURE_MARK[postures[d]]}
              </span>
            ))}
          </span>
        )}
        <span className="nf-gov-indicator-chevron">▾</span>
      </button>
    </div>
  );
}
