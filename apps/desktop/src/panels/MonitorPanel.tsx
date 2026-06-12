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

export default function MonitorPanel({
  runId,
  isRunning,
  nodeStats,
  runTotals,
  startTime,
  onStop,
}: MonitorPanelProps) {
  const [elapsedMs, setElapsedMs] = useState(0);

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    if (isRunning && startTime) {
      interval = setInterval(() => {
        setElapsedMs(Date.now() - startTime);
      }, 100);
    } else if (!isRunning && startTime) {
      // Keep the final time
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
        bottom: 0,
        left: 0,
        right: 0,
        height: 250,
        backgroundColor: '#1e1e1e',
        borderTop: '1px solid #444',
        display: 'flex',
        flexDirection: 'column',
        zIndex: 10,
        fontFamily: 'monospace',
      }}
    >
      <div
        style={{
          padding: '8px 16px',
          borderBottom: '1px solid #333',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          backgroundColor: '#252526',
        }}
      >
        <div style={{ display: 'flex', gap: '20px', color: '#ccc' }}>
          <span><strong>Run ID:</strong> {runId.split('-')[0]}...</span>
          <span><strong>Time:</strong> {(elapsedMs / 1000).toFixed(1)}s</span>
          <span><strong>Cost:</strong> ${runTotals.costUsd.toFixed(5)}</span>
          <span><strong>Tokens:</strong> {runTotals.tokensIn} in / {runTotals.tokensOut} out</span>
          <span><strong>Loops:</strong> {runTotals.iterations}</span>
        </div>
        <div>
          {isRunning ? (
            <button
              onClick={onStop}
              style={{
                backgroundColor: '#dc2626',
                color: 'white',
                border: 'none',
                padding: '4px 12px',
                borderRadius: '4px',
                cursor: 'pointer',
                fontWeight: 'bold',
              }}
            >
              KILL SWITCH (Stop)
            </button>
          ) : (
            <span style={{ color: '#aaa', fontWeight: 'bold' }}>FINISHED</span>
          )}
        </div>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '0' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', color: '#ddd' }}>
          <thead style={{ backgroundColor: '#2d2d2d', textAlign: 'left', position: 'sticky', top: 0 }}>
            <tr>
              <th style={{ padding: '8px' }}>Node ID</th>
              <th style={{ padding: '8px' }}>Status</th>
              <th style={{ padding: '8px' }}>Tokens In</th>
              <th style={{ padding: '8px' }}>Tokens Out</th>
              <th style={{ padding: '8px' }}>Cost</th>
            </tr>
          </thead>
          <tbody>
            {nodeEntries.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ padding: '8px', textAlign: 'center', color: '#666' }}>
                  No nodes executed yet.
                </td>
              </tr>
            ) : (
              nodeEntries.map(([id, stat]) => (
                <tr key={id} style={{ borderBottom: '1px solid #333' }}>
                  <td style={{ padding: '6px 8px' }}>{id}</td>
                  <td style={{ padding: '6px 8px' }}>
                    <span
                      style={{
                        color:
                          stat.status === 'running'
                            ? '#3b82f6'
                            : stat.status === 'done'
                            ? '#10b981'
                            : stat.status === 'error'
                            ? '#ef4444'
                            : '#888',
                      }}
                    >
                      {stat.status.toUpperCase()}
                    </span>
                  </td>
                  <td style={{ padding: '6px 8px' }}>{stat.tokensIn}</td>
                  <td style={{ padding: '6px 8px' }}>{stat.tokensOut}</td>
                  <td style={{ padding: '6px 8px' }}>${stat.costUsd.toFixed(5)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
