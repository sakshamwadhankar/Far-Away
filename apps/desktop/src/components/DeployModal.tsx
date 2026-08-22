import { useEffect, useState } from 'react';
import type { Pipeline } from '@shared/types';
import { capabilityRows, ENDPOINT_KINDS, emptyPolicy } from '../canvas/accessPolicy';
import type { AccessPolicy } from '@shared/types';

/**
 * Deploy a pipeline as an OpenAI-compatible HTTP endpoint, or manage one
 * that's already deployed.
 *
 * Two modes, chosen by whether `existingDeploymentId` is given:
 *   - create: a short form (name, rate limit, LAN toggle) -> POST /deployments.
 *     The response's key is shown exactly once, right here.
 *   - manage: fetches the deployment's live status and lets the user rotate
 *     its key or undeploy it. The key is never shown here (it isn't
 *     retrievable) unless the user rotates, which mints a fresh one-time key.
 */

interface DeploySummary {
  id: string;
  name: string;
  expose_lan: boolean;
  rate_limit_per_minute: number;
  chat_input_node: string;
  chat_output_node: string;
  created_at: number;
  request_count: number;
  error_count: number;
  last_request_at: number | null;
  spend_cap_usd_per_request?: number | null;
}

interface DeployModalProps {
  pipeline: Pipeline;
  existingDeploymentId?: string;
  backendToken: string | null;
  API_BASE: string;
  onClose: () => void;
  onChanged?: () => void;
}

const STATUS_POLL_MS = 5000;

export default function DeployModal({
  pipeline,
  existingDeploymentId,
  backendToken,
  API_BASE,
  onClose,
  onChanged,
}: DeployModalProps) {
  const token = backendToken || 'test-token';
  const authHeaders = { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' };

  const [name, setName] = useState(pipeline.name || 'My Pipeline');
  const [rateLimit, setRateLimit] = useState(60);
  const [spendCapUsd, setSpendCapUsd] = useState<number | ''>('');
  const [exposeLan, setExposeLan] = useState(false);
  const [showLanConfirm, setShowLanConfirm] = useState(false);

  const [deploymentId, setDeploymentId] = useState<string | null>(existingDeploymentId ?? null);
  const [baseUrl, setBaseUrl] = useState<string>(`${API_BASE}/v1`);
  const [key, setKey] = useState<string | null>(null);
  const [summary, setSummary] = useState<DeploySummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const policy = summarizePolicy(pipeline);
  // Every row here is, by construction, something the pipeline's access
  // node(s) grant — capabilityRows only ever returns 'requested-denied' or
  // 'granted-used' rows when something downstream is actually requesting the
  // capability, and this summary passes no requested set. So every surviving
  // row is a plain "granted" fact; there is no used/unused/denied distinction
  // to render here (that distinction belongs to AccessNode.tsx on the canvas).
  const grantedLabels = capabilityRows(policy, new Set()).map(row => row.label);

  const refreshStatus = async (id: string) => {
    try {
      const res = await fetch(`${API_BASE}/deployments`, { headers: authHeaders });
      if (!res.ok) return;
      const data: { deployments: DeploySummary[] } = await res.json();
      const found = data.deployments.find(d => d.id === id);
      if (found) setSummary(found);
    } catch {
      // A failed poll shouldn't disrupt the modal — just try again next tick.
    }
  };

  useEffect(() => {
    if (!deploymentId) return;
    refreshStatus(deploymentId);
    const interval = setInterval(() => refreshStatus(deploymentId), STATUS_POLL_MS);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deploymentId]);

  const handleDeploy = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/deployments`, {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({
          pipeline,
          name: name.trim() || undefined,
          expose_lan: exposeLan,
          rate_limit_per_minute: rateLimit,
          spend_cap_usd_per_request: spendCapUsd === '' ? undefined : Number(spendCapUsd),
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(Array.isArray(data.detail) ? data.detail.join(' ') : (data.detail || 'Deployment failed'));
      }
      setDeploymentId(data.deployment_id);
      setBaseUrl(data.base_url);
      setKey(data.key);
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to deploy pipeline');
    } finally {
      setBusy(false);
    }
  };

  const handleRotate = async () => {
    if (!deploymentId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/deployments/${deploymentId}/rotate-key`, {
        method: 'POST',
        headers: authHeaders,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to rotate key');
      setKey(data.key);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to rotate key');
    } finally {
      setBusy(false);
    }
  };

  const handleUndeploy = async () => {
    if (!deploymentId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/deployments/${deploymentId}`, {
        method: 'DELETE',
        headers: authHeaders,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Failed to undeploy');
      }
      onChanged?.();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to undeploy');
      setBusy(false);
    }
  };

  const displayedKey = key || '<YOUR_DEPLOYMENT_KEY>';

  return (
    <div
      id="deploy-modal-overlay"
      style={{
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
        backgroundColor: 'rgba(0,0,0,0.45)',
        display: 'flex', justifyContent: 'center', alignItems: 'center',
        zIndex: 1000,
        backdropFilter: 'blur(4px)',
      }}
      onClick={(e) => { if ((e.target as HTMLElement).id === 'deploy-modal-overlay') onClose(); }}
    >
      <div style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-card)',
        padding: '28px 28px 24px',
        width: '520px',
        maxHeight: '86vh',
        overflowY: 'auto',
        boxShadow: 'var(--shadow-lg)',
        color: 'var(--text)',
      }}>
        <h2 style={{ marginTop: 0, marginBottom: 6, fontSize: 17, fontWeight: 600 }}>
          {deploymentId ? '🔌 Deployment' : '🔌 Deploy as API'}
        </h2>
        <p style={{ fontSize: 12, color: 'var(--text-3)', marginBottom: 18, lineHeight: 1.5 }}>
          {deploymentId
            ? 'Manage this deployment: rotate its key, check its status, or take it down.'
            : 'Turn this pipeline into an OpenAI-compatible HTTP endpoint — call it from curl, LangChain, OpenWebUI, or your own code.'}
        </p>

        {error && (
          <div style={{
            background: 'var(--error-bg, rgba(184,50,50,0.12))', border: '1px solid rgba(184,50,50,0.4)',
            borderRadius: 8, padding: '8px 10px', fontSize: 12, color: '#B83232', marginBottom: 14,
          }}>
            {error}
          </div>
        )}

        {!deploymentId && (
          <>
            <div style={{ marginBottom: 14 }}>
              <label className="nf-label">Name</label>
              <input
                data-testid="deploy-name"
                type="text" value={name} onChange={e => setName(e.target.value)}
                className="nf-input" placeholder="e.g. Summarizer API"
              />
            </div>

            <div style={{ marginBottom: 14 }}>
              <label className="nf-label">Rate limit (requests / minute)</label>
              <input
                data-testid="deploy-rate-limit"
                type="number" min={1} max={6000} value={rateLimit}
                onChange={e => setRateLimit(Math.max(1, parseInt(e.target.value, 10) || 60))}
                className="nf-input nf-input--mono"
              />
            </div>

            <div style={{ marginBottom: 14 }}>
              <label className="nf-label">Spend cap (USD / request, optional)</label>
              <input
                data-testid="deploy-spend-cap"
                type="number" step="0.0001" min={0} value={spendCapUsd}
                onChange={e => setSpendCapUsd(e.target.value === '' ? '' : parseFloat(e.target.value) || 0)}
                className="nf-input nf-input--mono" placeholder="e.g. 0.05 (unlimited if empty)"
              />
            </div>

            <div style={{ marginBottom: 14 }}>
              <label className="nf-label" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input
                  data-testid="deploy-lan-toggle"
                  type="checkbox"
                  checked={exposeLan}
                  onChange={(e) => {
                    if (e.target.checked) setShowLanConfirm(true);
                    else setExposeLan(false);
                  }}
                />
                Allow requests from other devices on my network (LAN)
              </label>
              {exposeLan && (
                <div style={{ fontSize: 10.5, color: '#B8642B', marginTop: 4 }}>
                  ⚠ Enabled — anyone on your network who can reach this machine can call this deployment.
                </div>
              )}
            </div>

            {showLanConfirm && (
              <div
                data-testid="deploy-lan-confirm"
                style={{
                  background: 'rgba(184,50,50,0.08)', border: '1px solid rgba(184,50,50,0.35)',
                  borderRadius: 8, padding: '12px', marginBottom: 14, fontSize: 12, lineHeight: 1.5,
                }}
              >
                <strong style={{ color: '#B83232' }}>Confirm LAN access</strong>
                <p style={{ margin: '6px 0' }}>
                  This lets any device on your network reach this deployment — not just this
                  computer. It only takes effect if the backend is also launched with
                  network binding enabled; by default Komvos stays on 127.0.0.1 regardless.
                  Only continue if you understand and accept that risk.
                </p>
                <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                  <button
                    data-testid="deploy-lan-confirm-cancel"
                    className="nf-pill-btn nf-pill-btn--sm"
                    onClick={() => setShowLanConfirm(false)}
                  >
                    Cancel
                  </button>
                  <button
                    data-testid="deploy-lan-confirm-accept"
                    className="nf-pill-btn nf-pill-btn--sm"
                    style={{ borderColor: '#B83232', color: '#B83232' }}
                    onClick={() => { setExposeLan(true); setShowLanConfirm(false); }}
                  >
                    I understand, enable it
                  </button>
                </div>
              </div>
            )}
          </>
        )}

        {/* Effective access policy summary — the moment the user most needs
            to see what they're about to expose to the network. */}
        <div style={{ marginBottom: 14 }}>
          <div className="nf-section-header" style={{ borderTop: 'none', paddingTop: 0 }}>
            Access policy
          </div>
          {grantedLabels.length === 0 ? (
            <div style={{ fontSize: 11.5, color: 'var(--text-3)' }}>
              No access node found — this pipeline cannot be deployed.
            </div>
          ) : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {grantedLabels.map(label => (
                <span
                  key={label}
                  data-testid={`deploy-policy-${label}`}
                  style={{
                    fontSize: 10.5, fontFamily: 'var(--font-mono)', padding: '2px 8px', borderRadius: 99,
                    background: 'rgba(58,125,68,0.12)', color: '#1F4D27',
                    border: '1px solid rgba(30,35,25,0.15)',
                  }}
                >
                  {label}
                </span>
              ))}
            </div>
          )}
        </div>

        {key && (
          <div style={{ marginBottom: 14 }}>
            <div className="nf-section-header" style={{ borderTop: 'none', paddingTop: 0 }}>
              Deployment key
            </div>
            <div style={{
              fontSize: 10.5, color: '#B8642B', marginBottom: 6, fontWeight: 600,
            }}>
              ⚠ Shown only once — copy it now. It cannot be retrieved again.
            </div>
            <KeyField value={key} testId="deploy-key-value" />
          </div>
        )}

        {deploymentId && (
          <>
            <div style={{ marginBottom: 14 }}>
              <div className="nf-section-header" style={{ borderTop: 'none', paddingTop: 0 }}>
                Endpoint
              </div>
              <KeyField value={baseUrl} testId="deploy-base-url" />
              <div style={{ fontSize: 10.5, color: 'var(--text-3)', marginTop: 4 }}>
                Model name: <code>{deploymentId}</code>
              </div>
            </div>

            <div style={{ marginBottom: 14 }}>
              <div className="nf-section-header" style={{ borderTop: 'none', paddingTop: 0 }}>
                Status
              </div>
              <div data-testid="deploy-status-row" style={{ fontSize: 11.5, color: 'var(--text-2)', display: 'flex', gap: 16 }}>
                <span>{summary ? summary.request_count : 0} requests served</span>
                <span>{summary?.error_count ? `${summary.error_count} errors` : 'no errors'}</span>
                <span>
                  {summary?.last_request_at
                    ? `last call ${new Date(summary.last_request_at).toLocaleTimeString()}`
                    : 'no calls yet'}
                </span>
              </div>
            </div>

            <Snippets baseUrl={baseUrl} deploymentId={deploymentId} apiKey={displayedKey} />
          </>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, marginTop: 22 }}>
          <div style={{ display: 'flex', gap: 10 }}>
            {deploymentId && (
              <>
                <button
                  data-testid="deploy-rotate"
                  onClick={handleRotate}
                  disabled={busy}
                  className="nf-pill-btn"
                >
                  🔄 Rotate key
                </button>
                <button
                  data-testid="deploy-undeploy"
                  onClick={handleUndeploy}
                  disabled={busy}
                  className="nf-pill-btn"
                  style={{ borderColor: '#B83232', color: '#B83232' }}
                >
                  🗑 Undeploy
                </button>
              </>
            )}
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button data-testid="deploy-close" onClick={onClose} className="nf-pill-btn">
              {deploymentId ? 'Close' : 'Cancel'}
            </button>
            {!deploymentId && (
              <button
                data-testid="deploy-submit"
                onClick={handleDeploy}
                disabled={busy || grantedLabels.length === 0}
                className="nf-pill-btn nf-pill-btn--highlight"
              >
                {busy ? 'Deploying…' : '🚀 Deploy'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function KeyField({ value, testId }: { value: string; testId: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      <input
        data-testid={testId}
        readOnly
        value={value}
        onFocus={(e) => e.target.select()}
        className="nf-input nf-input--mono"
        style={{ flex: 1 }}
      />
      <button
        data-testid={`${testId}-copy`}
        className="nf-pill-btn nf-pill-btn--sm"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch {
            // Clipboard access can be denied by the OS; the field is still
            // selectable and readable, so this is a soft failure.
          }
        }}
      >
        {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
  );
}

function Snippets({ baseUrl, deploymentId, apiKey }: { baseUrl: string; deploymentId: string; apiKey: string }) {
  const [tab, setTab] = useState<'curl' | 'python' | 'js' | 'generic'>('curl');

  const snippets: Record<typeof tab, string> = {
    curl: `curl ${baseUrl}/chat/completions \\
  -H "Authorization: Bearer ${apiKey}" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "${deploymentId}", "messages": [{"role": "user", "content": "Hello"}]}'`,
    python: `from openai import OpenAI

client = OpenAI(base_url="${baseUrl}", api_key="${apiKey}")
resp = client.chat.completions.create(
    model="${deploymentId}",
    messages=[{"role": "user", "content": "Hello"}],
)
print(resp.choices[0].message.content)`,
    js: `const res = await fetch("${baseUrl}/chat/completions", {
  method: "POST",
  headers: {
    "Authorization": "Bearer ${apiKey}",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    model: "${deploymentId}",
    messages: [{ role: "user", content: "Hello" }],
  }),
});
const data = await res.json();
console.log(data.choices[0].message.content);`,
    generic: `Any OpenAI-compatible tool (OpenClaw, OpenWebUI, Cursor, LangChain, ...):

  Base URL:  ${baseUrl}
  API Key:   ${apiKey}
  Model:     ${deploymentId}`,
  };

  const labels: Record<typeof tab, string> = { curl: 'curl', python: 'Python', js: 'JavaScript', generic: 'Generic' };

  return (
    <div style={{ marginBottom: 4 }}>
      <div className="nf-section-header" style={{ borderTop: 'none', paddingTop: 0 }}>
        Use it
      </div>
      <div style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
        {(Object.keys(snippets) as (typeof tab)[]).map(t => (
          <button
            key={t}
            data-testid={`deploy-snippet-tab-${t}`}
            onClick={() => setTab(t)}
            className="nf-pill-btn nf-pill-btn--sm"
            style={tab === t ? { background: 'var(--accent)', color: '#fff' } : undefined}
          >
            {labels[t]}
          </button>
        ))}
      </div>
      <pre
        data-testid="deploy-snippet-body"
        style={{
          background: 'rgba(30,35,25,0.06)', border: '1px solid rgba(30,35,25,0.12)',
          borderRadius: 8, padding: '10px 12px', fontSize: 11, fontFamily: 'var(--font-mono)',
          whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: 0,
        }}
      >
        {snippets[tab]}
      </pre>
    </div>
  );
}

/**
 * Merge every access node's policy in the pipeline into one informational
 * summary. This is a DISPLAY aid only — actual enforcement is the
 * intersection-per-descendant computed by the compiler
 * (backend/neuralflow/compiler/dag.py); a pipeline with several gates in
 * series may enforce something narrower than this union suggests.
 */
function summarizePolicy(pipeline: Pipeline): AccessPolicy {
  const gates = pipeline.nodes.filter(n => n.type === 'access');
  if (gates.length === 0) return emptyPolicy();

  const merged = emptyPolicy();
  for (const gate of gates) {
    const policy = gate.config?.access_policy as AccessPolicy | undefined;
    if (!policy) continue;
    merged.providers = [...new Set([...merged.providers, ...policy.providers])];
    merged.allow_local_models = merged.allow_local_models || policy.allow_local_models;
    merged.allow_network = merged.allow_network || policy.allow_network;
  }
  // Keep provider order stable and predictable for the UI.
  merged.providers = ENDPOINT_KINDS.filter(k => merged.providers.includes(k));
  return merged;
}
