import { useEffect, useState } from 'react';
import { diffLines, Change } from 'diff';

/** Shape returned by GET /runs/{run_id}/trace (see StateManager.get_full_trace). */
export interface TraceNodeExecution {
  node_id: string;
  cost?: number | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
  error?: string | null;
  inputs?: unknown;
  outputs?: unknown;
}

export interface TraceLoopIteration {
  loop_id: string;
  iteration: number;
  inputs?: unknown;
  outputs?: unknown;
}

export interface RunTrace {
  run: Record<string, unknown>;
  nodes: TraceNodeExecution[];
  loops: TraceLoopIteration[];
}

interface TraceModalProps {
  runId: string;
  backendPort: number | null;
  backendToken: string | null;
  onClose: () => void;
}

function isBase64Image(val: unknown): boolean {
  if (typeof val !== 'string') return false;
  return val.startsWith('data:image/') || (/^[A-Za-z0-9+/=]{100,}$/.test(val.replace(/\s+/g, '')) && val.length > 300);
}

function renderPayload(data: unknown): JSX.Element {
  if (data === null || data === undefined) {
    return <pre style={{ backgroundColor: '#111', padding: '8px', borderRadius: '4px', margin: 0 }}>null</pre>;
  }

  if (typeof data === 'string') {
    if (isBase64Image(data)) {
      const src = data.startsWith('data:') ? data : `data:image/jpeg;base64,${data}`;
      return (
        <div style={{ marginTop: 4 }}>
          <img src={src} alt="Visual payload" style={{ maxWidth: '100%', maxHeight: '240px', borderRadius: '4px', border: '1px solid #444', objectFit: 'contain' }} />
        </div>
      );
    }
    return <pre style={{ backgroundColor: '#111', padding: '8px', borderRadius: '4px', margin: 0, whiteSpace: 'pre-wrap' }}>{data}</pre>;
  }

  if (typeof data === 'object' && !Array.isArray(data)) {
    const obj = data as Record<string, unknown>;
    const imageEntries: [string, string][] = [];
    const nonImageEntries: Record<string, unknown> = {};

    for (const [k, v] of Object.entries(obj)) {
      if ((k.includes('screenshot') || k.includes('image') || k.includes('screen')) && typeof v === 'string' && v.length > 50) {
        imageEntries.push([k, v]);
      } else if (isBase64Image(v)) {
        imageEntries.push([k, v as string]);
      } else {
        nonImageEntries[k] = v;
      }
    }

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {Object.keys(nonImageEntries).length > 0 && (
          <pre style={{ backgroundColor: '#111', padding: '8px', borderRadius: '4px', margin: 0, overflowX: 'auto', maxHeight: '200px' }}>
            {JSON.stringify(nonImageEntries, null, 2)}
          </pre>
        )}
        {imageEntries.map(([key, imgVal]) => {
          const src = imgVal.startsWith('data:') ? imgVal : `data:image/jpeg;base64,${imgVal}`;
          return (
            <div key={key} style={{ marginTop: 4, background: '#111', padding: 8, borderRadius: 4, border: '1px solid #333' }}>
              <div style={{ fontSize: 11, color: '#aaa', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                📷 {key}:
              </div>
              <img
                src={src}
                alt={key}
                style={{ maxWidth: '100%', maxHeight: '240px', borderRadius: '4px', border: '1px solid #444', objectFit: 'contain', display: 'block' }}
              />
            </div>
          );
        })}
        {imageEntries.length === 0 && Object.keys(nonImageEntries).length === 0 && (
          <pre style={{ backgroundColor: '#111', padding: '8px', borderRadius: '4px', margin: 0 }}>{"{}"}</pre>
        )}
      </div>
    );
  }

  return (
    <pre style={{ backgroundColor: '#111', padding: '8px', borderRadius: '4px', margin: 0, overflowX: 'auto', maxHeight: '200px' }}>
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

export default function TraceModal({ runId, backendPort, backendToken, onClose }: TraceModalProps) {
  const [trace, setTrace] = useState<RunTrace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchTrace() {
      if (!backendPort) {
        setError('Backend not connected');
        setLoading(false);
        return;
      }
      try {
        const port = backendPort || 8000;
        const token = backendToken || 'test-token';
        const res = await fetch(`http://127.0.0.1:${port}/runs/${runId}/trace`, {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        });
        if (!res.ok) {
          throw new Error(`Failed to fetch trace: ${await res.text()}`);
        }
        const data: RunTrace = await res.json();
        setTrace(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch trace');
      } finally {
        setLoading(false);
      }
    }
    fetchTrace();
  }, [runId, backendPort, backendToken]);

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0,0,0,0.7)',
        zIndex: 50,
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
      }}
    >
      <div
        style={{
          width: '80%',
          height: '80%',
          backgroundColor: '#1e1e1e',
          borderRadius: '8px',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
          overflow: 'hidden',
          border: '1px solid #444',
        }}
      >
        <div style={{ padding: '16px', borderBottom: '1px solid #333', display: 'flex', justifyContent: 'space-between', backgroundColor: '#252526' }}>
          <h2 style={{ margin: 0, color: '#fff' }}>Post-Run Trace: {runId}</h2>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: '#aaa', fontSize: '20px', cursor: 'pointer' }}>&times;</button>
        </div>
        
        <div style={{ padding: '16px', overflowY: 'auto', flex: 1, color: '#ccc', fontFamily: 'monospace' }}>
          {loading && <p>Loading trace...</p>}
          {error && <p style={{ color: 'red' }}>{error}</p>}
          {trace && (
            <div>
              <h3>Run Record</h3>
              <pre style={{ backgroundColor: '#111', padding: '12px', borderRadius: '4px' }}>
                {JSON.stringify(trace.run, null, 2)}
              </pre>

              <h3>Node Executions ({trace.nodes?.length})</h3>
              {trace.nodes?.map((node: TraceNodeExecution, idx: number) => (
                <div key={idx} style={{ marginBottom: '16px', border: '1px solid #333', padding: '12px', borderRadius: '4px' }}>
                  <strong>Node ID:</strong> {node.node_id} <br />
                  <strong>Cost:</strong> ${node.cost} | <strong>Tokens:</strong> {node.tokens_in} in, {node.tokens_out} out <br />
                  {node.error && <div style={{ color: 'red' }}><strong>Error:</strong> {node.error}</div>}
                  <div style={{ display: 'flex', gap: '16px', marginTop: '8px' }}>
                    <div style={{ flex: 1 }}>
                      <strong>Inputs:</strong>
                      {renderPayload(node.inputs)}
                    </div>
                    <div style={{ flex: 1 }}>
                      <strong>Outputs:</strong>
                      {renderPayload(node.outputs)}
                    </div>
                  </div>
                </div>
              ))}

              <h3>Loop Iterations ({trace.loops?.length})</h3>
              {trace.loops?.length > 0 ? (
                trace.loops.map((loop: TraceLoopIteration, idx: number) => {
                  let diffElements: JSX.Element[] | null = null;
                  if (idx > 0) {
                    const prevOutputs = JSON.stringify(trace.loops[idx - 1].outputs, null, 2) || '';
                    const currOutputs = JSON.stringify(loop.outputs, null, 2) || '';
                    if (prevOutputs !== currOutputs) {
                      const changes = diffLines(prevOutputs, currOutputs);
                      diffElements = changes.map((part: Change, i: number) => {
                        const color = part.added ? '#10b981' : part.removed ? '#ef4444' : '#ccc';
                        const bgColor = part.added ? 'rgba(16, 185, 129, 0.1)' : part.removed ? 'rgba(239, 68, 68, 0.1)' : 'transparent';
                        return (
                          <span key={i} style={{ color, backgroundColor: bgColor }}>
                            {part.value}
                          </span>
                        );
                      });
                    }
                  }

                  return (
                    <div key={idx} style={{ marginBottom: '16px', border: '1px solid #333', padding: '12px', borderRadius: '4px' }}>
                      <strong>Loop ID:</strong> {loop.loop_id} | <strong>Iteration:</strong> {loop.iteration}
                      <div style={{ display: 'flex', gap: '16px', marginTop: '8px' }}>
                        <div style={{ flex: 1 }}>
                          <strong>Inputs:</strong>
                          {renderPayload(loop.inputs)}
                        </div>
                        <div style={{ flex: 1 }}>
                          <strong>Outputs:</strong>
                          {renderPayload(loop.outputs)}
                        </div>
                      </div>
                      {diffElements && (
                        <div style={{ marginTop: '16px' }}>
                          <strong>Changes from previous iteration (Outputs):</strong>
                          <pre style={{ backgroundColor: '#111', padding: '8px', borderRadius: '4px', overflowX: 'auto', maxHeight: '200px', whiteSpace: 'pre-wrap' }}>
                            {diffElements}
                          </pre>
                        </div>
                      )}
                    </div>
                  );
                })
              ) : (
                <p>No loop iterations.</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
