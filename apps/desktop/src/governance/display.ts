/**
 * Presentation helpers for decisions: outcome is encoded in GLYPH + shape +
 * colour together, never colour alone.
 */

import type { OutcomeValue } from './types';

export interface OutcomeStyle {
  glyph: string;
  label: string;
  className: string;
}

export function outcomeStyle(outcome: OutcomeValue | string): OutcomeStyle {
  switch (outcome) {
    case 'allow':
      return { glyph: '✓', label: 'ALLOWED', className: 'nf-gov-outcome--allow' };
    case 'deny':
      return { glyph: '✕', label: 'DENIED', className: 'nf-gov-outcome--deny' };
    case 'timeout':
      return { glyph: '⏱', label: 'TIMEOUT', className: 'nf-gov-outcome--timeout' };
    default:
      return { glyph: '?', label: String(outcome).toUpperCase(), className: '' };
  }
}

/** Human phrasing for each origin value. */
export function originLabel(origin: string): string {
  switch (origin) {
    case 'pipeline_policy': return 'Pipeline policy';
    case 'profile': return 'Profile';
    case 'pipeline_and_profile': return 'Pipeline + profile';
    case 'human_allow_once': return 'Human · allow once';
    case 'human_allow_for_run': return 'Human · allowed for run';
    case 'human_deny': return 'Human denied';
    default: return origin;
  }
}

export const HUMAN_ORIGINS = new Set([
  'human_allow_once',
  'human_allow_for_run',
  'human_deny',
]);

export function timeShort(whenUtc: string): string {
  const d = new Date(whenUtc);
  if (Number.isNaN(d.getTime())) return whenUtc;
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
