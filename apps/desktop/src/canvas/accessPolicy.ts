/**
 * Client-side mirror of the backend's access-policy reasoning.
 *
 * The access node's whole point is to tell you what your pipeline is actually
 * reaching for, without running it. That means the canvas has to work out two
 * things locally:
 *
 *   1. which nodes a given access node governs (everything downstream of it),
 *   2. which capabilities those nodes request.
 *
 * Comparing that against the node's own policy produces the three states the
 * node body renders. This is an inspector, not a security boundary — the
 * authoritative check runs in backend/neuralflow/compiler and again at call
 * time in the endpoints. See backend/neuralflow/compiler/README.md.
 */

import type { Edge as RFEdge, Node as RFNode } from 'reactflow';
import type { AccessPolicy, EndpointKind } from '@shared/types';
import type { PipelineNodeData } from './nodes/PipelineNode';

/** Reserved port name for edges attaching an access node to its scope. */
export const ACCESS_SCOPE_PORT = 'scope';

/** Every provider a policy can grant, in the order the UI lists them. */
export const ENDPOINT_KINDS: EndpointKind[] = [
  'openai',
  'anthropic',
  'google',
  'openai_compatible',
  'ollama',
  'mock',
  'groq',
  'openrouter',
  'zhipu',
  'nvidia',
];

/** A capability is either a named provider or one of the boolean switches. */
export type Capability =
  | { kind: 'provider'; provider: EndpointKind }
  | { kind: 'allow_local_models' }
  | { kind: 'allow_network' };

export type CapabilityState =
  /** Policy allows it and something downstream calls it. */
  | 'granted-used'
  /** Policy allows it and nothing downstream calls it — offer to tighten. */
  | 'granted-unused'
  /** Something downstream needs it and the policy blocks it — offer to grant. */
  | 'requested-denied';

export interface CapabilityRow {
  /** Stable identity, e.g. "provider:openai" or "allow_local_models". */
  id: string;
  label: string;
  capability: Capability;
  state: CapabilityState;
}

/** The default policy a freshly-dropped access node carries: deny everything. */
export function emptyPolicy(): AccessPolicy {
  return {
    providers: [],
    allow_local_models: false,
    allow_network: false,
    allowed_domains: [],
    max_cost_usd: null,
    max_tokens: null,
  };
}

/**
 * Every node reachable by following edges forward from `startId`.
 *
 * Excludes the start node itself: an access node does not govern itself. The
 * visited set doubles as cycle protection, so a malformed graph cannot hang
 * the canvas.
 */
export function descendantsOf(startId: string, edges: RFEdge[]): Set<string> {
  const forward = new Map<string, string[]>();
  for (const edge of edges) {
    const list = forward.get(edge.source);
    if (list) list.push(edge.target);
    else forward.set(edge.source, [edge.target]);
  }

  const seen = new Set<string>();
  const queue = [...(forward.get(startId) ?? [])];

  while (queue.length > 0) {
    const current = queue.pop() as string;
    if (current === startId || seen.has(current)) continue;
    seen.add(current);
    queue.push(...(forward.get(current) ?? []));
  }

  return seen;
}

/** The provider half of an `endpoint_ref` like "anthropic:claude-3". */
export function providerOf(endpointRef: string | undefined): EndpointKind | null {
  if (!endpointRef) return null;
  const prefix = endpointRef.split(':')[0];
  return (ENDPOINT_KINDS as string[]).includes(prefix)
    ? (prefix as EndpointKind)
    : null;
}

/**
 * Capability ids the given nodes actually reach for.
 *
 * A model node pointing at `ollama:*` requests `allow_local_models` rather
 * than a provider grant, matching how the backend's OllamaEndpoint checks it.
 */
export function requestedCapabilities(
  nodes: RFNode<PipelineNodeData>[],
  scope: Set<string>,
): Set<string> {
  const requested = new Set<string>();

  for (const node of nodes) {
    if (!scope.has(node.id) || node.data?.type !== 'model') continue;
    const provider = providerOf(node.data.endpoint_ref);
    if (provider === 'ollama') requested.add('allow_local_models');
    else if (provider) requested.add(`provider:${provider}`);
  }

  return requested;
}

function capabilityId(capability: Capability): string {
  return capability.kind === 'provider'
    ? `provider:${capability.provider}`
    : capability.kind;
}

function isGranted(policy: AccessPolicy, capability: Capability): boolean {
  switch (capability.kind) {
    case 'provider':
      return policy.providers.includes(capability.provider);
    case 'allow_local_models':
      return policy.allow_local_models;
    case 'allow_network':
      return policy.allow_network;
  }
}

/**
 * The live capability list rendered in the access node body.
 *
 * Only capabilities that are either granted or requested appear — listing all
 * ten providers unconditionally would bury the one line that matters, which is
 * the thing downstream is reaching for and cannot have.
 *
 * Ordered denied-first, because that is the state the user needs to act on.
 */
export function capabilityRows(
  policy: AccessPolicy,
  requested: Set<string>,
): CapabilityRow[] {
  const all: Capability[] = [
    ...ENDPOINT_KINDS.map(
      (provider): Capability => ({ kind: 'provider', provider }),
    ),
    { kind: 'allow_local_models' },
    { kind: 'allow_network' },
  ];

  const rows: CapabilityRow[] = [];

  for (const capability of all) {
    const id = capabilityId(capability);
    const granted = isGranted(policy, capability);
    const used = requested.has(id);

    if (!granted && !used) continue;

    rows.push({
      id,
      label:
        capability.kind === 'provider'
          ? capability.provider
          : capability.kind === 'allow_local_models'
            ? 'local models'
            : 'network',
      capability,
      state: !granted ? 'requested-denied' : used ? 'granted-used' : 'granted-unused',
    });
  }

  const order: Record<CapabilityState, number> = {
    'requested-denied': 0,
    'granted-used': 1,
    'granted-unused': 2,
  };
  return rows.sort(
    (a, b) => order[a.state] - order[b.state] || a.label.localeCompare(b.label),
  );
}

/** Return a copy of `policy` with `capability` granted or revoked. */
export function togglePolicy(
  policy: AccessPolicy,
  capability: Capability,
  grant: boolean,
): AccessPolicy {
  if (capability.kind === 'provider') {
    const providers = grant
      ? [...new Set([...policy.providers, capability.provider])]
      : policy.providers.filter((p) => p !== capability.provider);
    return { ...policy, providers };
  }
  return { ...policy, [capability.kind]: grant };
}
