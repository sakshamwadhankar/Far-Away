/**
 * HTTP client for the governance API (komvos.governance.api).
 *
 * Every route requires the session token, exactly like the rest of the
 * management API. No new dependencies: plain fetch.
 */

import type {
  ActiveProfileResponse,
  AnswerValue,
  DecisionsPage,
  DecisionsSummary,
  DomainKey,
  OutcomeValue,
  PostureValue,
  ProfilesResponse,
} from './types';

const ORIGINS = [
  'pipeline_policy',
  'profile',
  'pipeline_and_profile',
  'human_allow_once',
  'human_allow_for_run',
  'human_deny',
] as const;
export type OriginFilter = (typeof ORIGINS)[number];

export interface DecisionFilters {
  run_id?: string;
  domain?: DomainKey | '';
  outcome?: OutcomeValue | '';
  origin?: OriginFilter | '';
}

function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === 'string') return body.detail;
    if (Array.isArray(body?.detail)) return JSON.stringify(body.detail);
  } catch { /* not json */ }
  return `${res.status} ${res.statusText}`;
}

export async function fetchProfiles(apiBase: string, token: string): Promise<ProfilesResponse> {
  const res = await fetch(`${apiBase}/governance/profiles`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function fetchActiveProfile(apiBase: string, token: string): Promise<ActiveProfileResponse> {
  const res = await fetch(`${apiBase}/governance/active`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function setActiveProfile(
  apiBase: string, token: string, name: string,
): Promise<ActiveProfileResponse> {
  const res = await fetch(`${apiBase}/governance/active`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export interface ProfileBody {
  name: string;
  postures: Record<DomainKey, PostureValue>;
  spend_cap_usd: number | null;
  spend_ask_threshold_usd: number | null;
  retention: 'full' | 'metadata';
  retention_window: string;
}

export async function createProfile(
  apiBase: string, token: string, body: ProfileBody,
): Promise<void> {
  const res = await fetch(`${apiBase}/governance/profiles`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
}

export async function updateProfile(
  apiBase: string, token: string, name: string, body: Omit<ProfileBody, 'name'>,
): Promise<void> {
  const res = await fetch(`${apiBase}/governance/profiles/${encodeURIComponent(name)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
}

export async function deleteProfile(apiBase: string, token: string, name: string): Promise<void> {
  const res = await fetch(`${apiBase}/governance/profiles/${encodeURIComponent(name)}`, {
    method: 'DELETE',
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await readError(res));
}

export function buildDecisionQuery(filters: DecisionFilters, extra?: { cursor?: number | null; limit?: number }): string {
  const params = new URLSearchParams();
  if (filters.run_id) params.set('run_id', filters.run_id);
  if (filters.domain) params.set('domain', filters.domain);
  if (filters.outcome) params.set('outcome', filters.outcome);
  if (filters.origin) params.set('origin', filters.origin);
  if (extra?.cursor != null) params.set('cursor', String(extra.cursor));
  if (extra?.limit != null) params.set('limit', String(extra.limit));
  return params.toString();
}

export async function fetchDecisions(
  apiBase: string, token: string,
  filters: DecisionFilters,
  page?: { cursor?: number | null; limit?: number },
): Promise<DecisionsPage> {
  const qs = buildDecisionQuery(filters, page);
  const res = await fetch(`${apiBase}/governance/decisions?${qs}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function fetchDecisionsSummary(
  apiBase: string, token: string, filters: DecisionFilters,
): Promise<DecisionsSummary> {
  const params = new URLSearchParams();
  if (filters.run_id) params.set('run_id', filters.run_id);
  const res = await fetch(`${apiBase}/governance/decisions/summary?${params.toString()}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

/** Download the filtered decision log; returns the bytes for a Blob download. */
export async function exportDecisions(
  apiBase: string, token: string, filters: DecisionFilters, format: 'json' | 'csv',
): Promise<Blob> {
  const qs = buildDecisionQuery(filters);
  const suffix = qs ? `&${qs}` : '';
  const res = await fetch(`${apiBase}/governance/decisions/export?format=${format}${suffix}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.blob();
}

export async function answerApproval(
  apiBase: string, token: string, approvalId: string, answer: AnswerValue,
): Promise<void> {
  const res = await fetch(
    `${apiBase}/governance/approvals/${encodeURIComponent(approvalId)}/answer`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
      body: JSON.stringify({ answer }),
    },
  );
  if (!res.ok) throw new Error(await readError(res));
}
