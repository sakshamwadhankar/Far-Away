/**
 * Shared types for the governance UI (P1).
 *
 * These mirror the backend contracts exactly:
 *  - profiles:    komvos.governance.profiles.GovernanceProfile + api.py responses
 *  - decisions:   GET /governance/decisions rows (see StateManager schema)
 *  - approvals:   WsApprovalPendingEvent frames (scheduler/events.py)
 */

export type DomainKey = 'providers' | 'egress' | 'spend' | 'retention' | 'desktop';
export type PostureValue = 'enforce' | 'ask' | 'audit';
export type OutcomeValue = 'allow' | 'deny' | 'timeout';
export type RetentionMode = 'full' | 'metadata';

export interface ProfileSpec {
  name: string;
  built_in: boolean;
  postures: Record<DomainKey, PostureValue>;
  spend_cap_usd: number | null;
  spend_ask_threshold_usd: number | null;
  retention: RetentionMode;
  retention_window: string;
}

export interface ProfileEntry {
  profile: ProfileSpec;
  is_active: boolean;
}

export interface ProfilesResponse {
  profiles: ProfileEntry[];
  active_name: string;
}

export interface ActiveProfileResponse {
  name: string;
  profile: ProfileSpec;
}

export interface DecisionRecord {
  seq: number;
  decision_id: string;
  run_id: string;
  node_id: string;
  domain: string;
  capability: string;
  outcome: OutcomeValue;
  origin: string;
  reason: string;
  governed_by: string[];
  effective_policy: Record<string, unknown>;
  when_utc: string;
  when_ms: number;
}

export interface DecisionsPage {
  decisions: DecisionRecord[];
  next_cursor: number | null;
}

export interface DecisionsSummary {
  total: number;
  by_outcome: Record<string, number>;
  by_domain: Record<string, number>;
}

/** Frame shape of WsApprovalPendingEvent (approval_pending). */
export interface ApprovalPendingFrame {
  event: 'approval_pending';
  run_id: string;
  node_id: string;
  approval_id: string;
  domain: string;
  capability: string;
  reason: string;
  allow_once_effect: string;
  allow_for_run_effect: string;
  deny_effect: string;
  timeout_seconds: number;
  screenshot?: string | null;
  timestamp_ms: number;
}

/** Frame shape of WsGovernanceDecisionEvent (governance_decision). */
export interface DecisionFrame {
  event: 'governance_decision';
  run_id: string;
  node_id: string;
  domain: string;
  capability: string;
  outcome: OutcomeValue;
  origin: string;
  reason: string;
  timestamp_ms: number;
}

export type AnswerValue = 'allow_once' | 'allow_for_run' | 'deny';

export const DOMAIN_LABELS: Record<DomainKey, string> = {
  providers: 'Providers',
  egress: 'Egress',
  spend: 'Spend',
  retention: 'Retention',
  desktop: 'Desktop',
};

export const POSTURE_LABELS: Record<PostureValue, string> = {
  enforce: 'Enforce',
  ask: 'Ask',
  audit: 'Audit',
};

/** What a posture actually does when the pipeline's policy withholds an action. */
export const POSTURE_CONSEQUENCES: Record<PostureValue, string> = {
  enforce: "Deny and halt — the pipeline's own policy stands.",
  ask: 'Suspend and ask you before proceeding.',
  audit: 'Permit anyway, recording that this profile allowed it.',
};
