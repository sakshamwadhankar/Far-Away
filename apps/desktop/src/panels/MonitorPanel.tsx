import { useEffect, useState } from 'react';

export interface NodeStat {
  status: 'idle' | 'running' | 'done' | 'error';
  tokensIn: number;
  tokensOut: number;
  costUsd: number;
}

interface MonitorPanelProps {
  runId: string | null;
  isRunning: boolean;
  nodeStats: Record<string, NodeStat>;
  runTotals: { costUsd: number; tokensIn: number; tokensOut: number; iterations: number };
  startTime: number | null;
  onStop: () => void;
}

const STATUS_COLORS: Record<string, string> = {
  running: '#2B4BAA',
  done:    '#3A7D44',
  error:   '#B83232',
  idle:    'var(--text-3)',
};

const STATUS_BG: Record<string, string> = {
  running: 'rgba(43,75,170,0.1)',
  done:    'rgba(58,125,68,0.1)',
  error:   'rgba(184,50,50,0.1)',
  idle:    'transparent',
};

export default function MonitorPanel({
  runId, isRunning, nodeStats, runTotals, startTime, onStop,
}: MonitorPanelProps) {
  const [elapsedMs, setElapsedMs] = useState(0);

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    if (isRunning && startTime) {
      interval = setInterval(() => { setElapsedMs(Date.now() - startTime); }, 100);
    } else if (!isRunning && startTime) {
      setElapsedMs(Date.now() - startTime);
    } else {
      setElapsedMs(0);
    }
    return () => clearInterval(interval);
  }, [isRunning, startTime]);

  if (!runId) return null;

  const nodeEntries = Object.entries(nodeStats);

  return (
    <div
      style={{
        position: 'absolute',
        bottom: 0, left: 0, right: 0,
        height: 250,
        background: 'var(--surface)',
        borderTop: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        zIndex: 10,
        fontFamily: 'var(--font-mono)',
      }}
    >
      {/* Header row */}
      <div style={{
        padding: '8px 16px',
        borderBottom: '1px solid var(--border-subtle)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        background: 'var(--bg-alt)',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'center' }}>
          <StatPill label="Run" value={runId.split('-')[0] + '…'} />
          <StatPill label="Time" value={`${(elapsedMs / 1000).toFixed(1)}s`} highlight={isRunning} />
          <StatPill label="Cost" value={`$${runTotals.costUsd.toFixed(5)}`} />
          <StatPill label="Tokens" value={`${runTotals.tokensIn} in / ${runTotals.tokensOut} out`} />
          {runTotals.iterations > 0 && <StatPill label="Loops" value={String(runTotals.iterations)} />}
        </div>
        <div>
          {isRunning ? (
            <button
              onClick={onStop}
              className="nf-pill-btn nf-pill-btn--danger"
              style={{ fontSize: 12, padding: '5px 14px' }}
            >
              ■ Stop
            </button>
          ) : (
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--success)',
              fontWeight: 500,
              letterSpacing: '0.08em',
            }}>
              FINISHED
            </span>
          )}
        </div>
      </div>

      {/* Table */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: 'var(--bg-alt)', position: 'sticky', top: 0 }}>
              {['Node ID', 'Status', 'Tokens In', 'Tokens Out', 'Cost'].map(h => (
                <th key={h} style={{
                  padding: '6px 10px', textAlign: 'left',
                  fontFamily: 'var(--font-mono)', fontWeight: 500,
                  fontSize: 10, color: 'var(--text-3)', textTransform: 'uppercase',
                  letterSpacing: '0.08em', borderBottom: '1px solid var(--border-subtle)',
                }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {nodeEntries.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ padding: 12, textAlign: 'center', color: 'var(--text-3)', fontStyle: 'italic' }}>
                  No nodes executed yet.
                </td>
              </tr>
            ) : nodeEntries.map(([id, stat]) => (
              <tr key={id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <td style={{ padding: '6px 10px', color: 'var(--text)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>{id}</td>
                <td style={{ padding: '6px 10px' }}>
                  <span style={{
                    display: 'inline-block',
                    padding: '2px 8px',
                    borderRadius: 99,
                    fontSize: 10, fontWeight: 600, letterSpacing: '0.08em',
                    color: STATUS_COLORS[stat.status] || 'var(--text-3)',
                    background: STATUS_BG[stat.status] || 'transparent',
                  }}>
                    {stat.status.toUpperCase()}
                  </span>
                </td>
                <td style={{ padding: '6px 10px', color: 'var(--text-2)' }}>{stat.tokensIn}</td>
                <td style={{ padding: '6px 10px', color: 'var(--text-2)' }}>{stat.tokensOut}</td>
                <td style={{ padding: '6px 10px', color: 'var(--text-2)' }}>${stat.costUsd.toFixed(5)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatPill({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <span style={{ fontSize: 9, color: 'var(--text-3)', fontWeight: 500, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
        {label}
      </span>
      <span style={{
        fontSize: 12, color: highlight ? '#2B4BAA' : 'var(--text)',
        fontWeight: highlight ? 600 : 400,
      }}>
        {value}
      </span>
    </div>
  );
}
