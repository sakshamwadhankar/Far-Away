/**
 * Run-totals and node-status bookkeeping in the monitor panel.
 *
 * Both cases here were visible in a real run: the header read "0 in / 0 out"
 * while the computer_agent row showed 485 tokens out, and that same row sat on
 * RUNNING under a run already labelled FINISHED.
 */
import { describe, it, expect, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useRunSocket } from './useRunSocket';
import type { NodeStat } from '../panels/MonitorPanel';

type Totals = { costUsd: number; tokensIn: number; tokensOut: number; iterations: number };

function harness() {
  let stats: Record<string, NodeStat> = {};
  let totals: Totals = { costUsd: 0, tokensIn: 0, tokensOut: 0, iterations: 0 };
  const nodeData: Record<string, string> = {};

  const setNodeStats = ((fn: unknown) => {
    stats = typeof fn === 'function'
      ? (fn as (p: Record<string, NodeStat>) => Record<string, NodeStat>)(stats)
      : (fn as Record<string, NodeStat>);
  }) as React.Dispatch<React.SetStateAction<Record<string, NodeStat>>>;

  const setRunTotals = ((fn: unknown) => {
    totals = typeof fn === 'function' ? (fn as (p: Totals) => Totals)(totals) : (fn as Totals);
  }) as React.Dispatch<React.SetStateAction<Totals>>;

  const { result } = renderHook(() =>
    useRunSocket({
      updateNodeDataSilent: (id, d) => { if (d.status) nodeData[id] = d.status; },
      setNodeStats,
      setRunTotals,
      setAnimatedEdgeIds: vi.fn() as never,
      setIsRunning: vi.fn() as never,
      edgesRef: { current: [] },
    }),
  );
  return {
    send: (e: Record<string, unknown>) => result.current.handleWsEvent(e),
    stats: () => stats,
    totals: () => totals,
    nodeData: () => nodeData,
  };
}

describe('useRunSocket bookkeeping', () => {
  it('counts tokens_out into the run totals, not just tokens_in', () => {
    const h = harness();
    h.send({ event: 'node_started', node_id: 'computer_agent' });
    h.send({ event: 'node_done', node_id: 'computer_agent', tokens_in: 12, tokens_out: 485 });

    expect(h.stats().computer_agent.tokensOut).toBe(485);
    expect(h.totals().tokensIn).toBe(12);
    // The header used to report 0 here while the row showed 485.
    expect(h.totals().tokensOut).toBe(485);
  });

  it('does not strand a node on RUNNING when the run ends', () => {
    const h = harness();
    h.send({ event: 'node_started', node_id: 'computer_agent' });
    expect(h.stats().computer_agent.status).toBe('running');

    h.send({ event: 'run_halted', run_id: 'r1', reason: 'stopped' });

    expect(h.stats().computer_agent.status).not.toBe('running');
    expect(h.stats().computer_agent.status).toBe('error');
    expect(h.nodeData().computer_agent).toBe('error');
  });

  it('marks a stranded node done when the run completed cleanly', () => {
    const h = harness();
    h.send({ event: 'node_started', node_id: 'n1' });
    h.send({ event: 'run_completed', run_id: 'r1' });
    expect(h.stats().n1.status).toBe('done');
  });
});
