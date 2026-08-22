import { useCallback, useRef } from 'react';
import type { NodeStat } from '../panels/MonitorPanel';
import type { PipelineNodeData } from '../canvas/nodes/PipelineNode';
import type { Edge } from 'reactflow';

interface UseRunSocketProps {
  updateNodeDataSilent: (id: string, newData: Partial<PipelineNodeData>) => void;
  setNodeStats: React.Dispatch<React.SetStateAction<Record<string, NodeStat>>>;
  setRunTotals: React.Dispatch<React.SetStateAction<{ costUsd: number; tokensIn: number; tokensOut: number; iterations: number; }>>;
  setAnimatedEdgeIds: React.Dispatch<React.SetStateAction<Set<string>>>;
  setIsRunning: React.Dispatch<React.SetStateAction<boolean>>;
  edgesRef: React.MutableRefObject<Edge[]>;
}

export function useRunSocket({
  updateNodeDataSilent,
  setNodeStats,
  setRunTotals,
  setAnimatedEdgeIds,
  setIsRunning,
  edgesRef
}: UseRunSocketProps) {
  const wsRef = useRef<WebSocket | null>(null);
  
  // Buffers for high-frequency token events
  const tokenStatsBuffer = useRef<Record<string, number>>({});
  const tokenTotalsBuffer = useRef<number>(0);
  const lastStatsUpdate = useRef<number>(Date.now());

  const handleWsEvent = useCallback((data: Record<string, unknown>) => {
    const eventType = (data.event || data.kind) as string;

    if (eventType === 'node_started') {
      const nodeId = data.node_id as string;
      updateNodeDataSilent(nodeId, { status: 'running' });
      setNodeStats(prev => ({
        ...prev,
        [nodeId]: { status: 'running', tokensIn: 0, tokensOut: 0, costUsd: 0 }
      }));
      // Animate edges FROM this node (outgoing)
      const outgoing = edgesRef.current
        .filter(e => e.source === nodeId)
        .map(e => e.id);
      if (outgoing.length > 0) {
        setAnimatedEdgeIds(prev => {
          const next = new Set(prev);
          outgoing.forEach(id => next.add(id));
          return next;
        });
      }
    } else if (eventType === 'node_done') {
      const nodeId = data.node_id as string;
      updateNodeDataSilent(nodeId, { status: 'done' });
      setNodeStats(prev => ({
        ...prev,
        [nodeId]: { 
          status: 'done', 
          tokensIn: (data.tokens_in as number) || 0, 
          tokensOut: (data.tokens_out as number) || prev[nodeId]?.tokensOut || 0, 
          costUsd: (data.cost_usd as number) || 0 
        }
      }));
      if (data.cost_usd || data.tokens_in || data.tokens_out) {
        setRunTotals(prev => ({
          ...prev,
          costUsd: prev.costUsd + ((data.cost_usd as number) || 0),
          tokensIn: prev.tokensIn + ((data.tokens_in as number) || 0),
        }));
      }
      // Animate edges TO downstream nodes
      const downstream = edgesRef.current
        .filter(e => e.source === nodeId)
        .map(e => e.id);
      if (downstream.length > 0) {
        setAnimatedEdgeIds(prev => {
          const next = new Set(prev);
          downstream.forEach(id => next.add(id));
          return next;
        });
      }
    } else if (eventType === 'node_error' || eventType === 'run_error') {
      if (data.node_id) {
        const nodeId = data.node_id as string;
        updateNodeDataSilent(nodeId, { status: 'error' });
        setNodeStats(prev => ({
          ...prev,
          [nodeId]: { ...prev[nodeId], status: 'error' }
        }));
      }
    } else if (eventType === 'run_completed' || eventType === 'run_stopped' || eventType === 'budget_exceeded' || eventType === 'run_halted') {
      // Flush any remaining tokens
      const flushedStats = { ...tokenStatsBuffer.current };
      const flushedTotals = tokenTotalsBuffer.current;
      tokenStatsBuffer.current = {};
      tokenTotalsBuffer.current = 0;
      
      if (flushedTotals > 0) {
        setNodeStats(prev => {
          const next = { ...prev };
          for (const [nid, count] of Object.entries(flushedStats)) {
            if (next[nid]) {
              next[nid] = { ...next[nid], tokensOut: next[nid].tokensOut + count };
            }
          }
          return next;
        });
        setRunTotals(prev => ({ ...prev, tokensOut: prev.tokensOut + flushedTotals }));
      }

      if (data.total_cost_usd !== undefined) {
        setRunTotals(prev => ({
          ...prev,
          costUsd: data.total_cost_usd as number,
          tokensIn: data.total_tokens_in !== undefined ? (data.total_tokens_in as number) : prev.tokensIn,
          tokensOut: data.total_tokens_out !== undefined ? (data.total_tokens_out as number) : prev.tokensOut
        }));
      }
      setIsRunning(false);
      setAnimatedEdgeIds(new Set());
    } else if (eventType === 'token') {
      const nodeId = data.node_id as string;
      tokenStatsBuffer.current[nodeId] = (tokenStatsBuffer.current[nodeId] || 0) + 1;
      tokenTotalsBuffer.current += 1;

      const now = Date.now();
      if (now - lastStatsUpdate.current > 500) {
        lastStatsUpdate.current = now;
        const flushedStats = { ...tokenStatsBuffer.current };
        const flushedTotals = tokenTotalsBuffer.current;
        tokenStatsBuffer.current = {};
        tokenTotalsBuffer.current = 0;

        setNodeStats(prev => {
          const next = { ...prev };
          let changed = false;
          for (const [nid, count] of Object.entries(flushedStats)) {
            if (next[nid]) {
              next[nid] = { ...next[nid], tokensOut: next[nid].tokensOut + count };
              changed = true;
            }
          }
          return changed ? next : prev;
        });

        setRunTotals(prev => ({ ...prev, tokensOut: prev.tokensOut + flushedTotals }));
      }
    } else if (eventType === 'loop_iteration') {
      setRunTotals(prev => ({ ...prev, iterations: prev.iterations + 1 }));
    }
  }, [updateNodeDataSilent, setNodeStats, setAnimatedEdgeIds, edgesRef, setRunTotals, setIsRunning]);

  return {
    wsRef,
    tokenStatsBuffer,
    tokenTotalsBuffer,
    lastStatsUpdate,
    handleWsEvent
  };
}
