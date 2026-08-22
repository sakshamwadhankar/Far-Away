import { useState } from 'react';
import type { NodeStat } from '../panels/MonitorPanel';

export function useRunStore() {
  const [runId, setRunId] = useState<string | null>(null);
  const [startTime, setStartTime] = useState<number | null>(null);
  const [nodeStats, setNodeStats] = useState<Record<string, NodeStat>>({});
  const [runTotals, setRunTotals] = useState({ costUsd: 0, tokensIn: 0, tokensOut: 0, iterations: 0 });
  const [showTrace, setShowTrace] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [animatedEdgeIds, setAnimatedEdgeIds] = useState<Set<string>>(new Set());

  return {
    runId, setRunId,
    startTime, setStartTime,
    nodeStats, setNodeStats,
    runTotals, setRunTotals,
    showTrace, setShowTrace,
    isRunning, setIsRunning,
    animatedEdgeIds, setAnimatedEdgeIds
  };
}
