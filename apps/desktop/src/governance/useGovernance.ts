/**
 * useGovernance — one hook behind all four governance surfaces.
 *
 * Live events are tapped WITHOUT touching the existing WebSocket handlers:
 * the run's WebSocket lives in App's wsRef (assigned by useRunSocket), and
 * additional 'message' listeners can be attached to the same socket via
 * addEventListener without interfering with its onmessage. An interval
 * re-attaches whenever a new socket instance appears (one per run).
 *
 * Volume discipline (same idea as the token buffering in useRunSocket):
 * decision frames land in a ref buffer and reach React state at most every
 * 400ms, capped to the newest 150 entries. Decisions are far rarer than
 * tokens (a handful per node), so this bounds renders even for wide
 * parallel runs; full history is served by the HTTP API, not this list.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { MutableRefObject } from 'react';
import {
  fetchActiveProfile,
  fetchProfiles,
} from './api';
import type {
  ActiveProfileResponse,
  ApprovalPendingFrame,
  DecisionFrame,
  DecisionRecord,
  ProfilesResponse,
} from './types';

export interface GovernancePrompt extends ApprovalPendingFrame {
  /** Epoch ms when the answer window closes. */
  deadlineMs: number;
}

interface UseGovernanceOptions {
  apiBase: string;
  token: string;
  connected: boolean;
  wsRef?: MutableRefObject<WebSocket | null>;
}

const LIVE_DECISION_CAP = 150;
const FLUSH_INTERVAL_MS = 400;
const PROFILE_POLL_MS = 8000;

export function useGovernance({ apiBase, token, connected, wsRef }: UseGovernanceOptions) {
  const [profiles, setProfiles] = useState<ProfilesResponse | null>(null);
  const [active, setActive] = useState<ActiveProfileResponse | null>(null);
  const [liveDecisions, setLiveDecisions] = useState<DecisionRecord[]>([]);
  const [prompts, setPrompts] = useState<GovernancePrompt[]>([]);
  const [liveScreenshot, setLiveScreenshot] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const decisionBuffer = useRef<DecisionFrame[]>([]);
  const lastFlush = useRef<number>(Date.now());
  const liveSeq = useRef<number>(0);

  // -- profile state ------------------------------------------------------
  const refreshProfiles = useCallback(async () => {
    if (!connected) return;
    try {
      const [list, activeOne] = await Promise.all([
        fetchProfiles(apiBase, token),
        fetchActiveProfile(apiBase, token),
      ]);
      setProfiles(list);
      setActive(activeOne);
    } catch { /* backend briefly down; keep last known state */ }
  }, [apiBase, token, connected]);

  useEffect(() => {
    refreshProfiles();
    const id = setInterval(refreshProfiles, PROFILE_POLL_MS);
    return () => clearInterval(id);
  }, [refreshProfiles]);

  // -- WS tap: decisions + pending approvals + live vision -----------------
  useEffect(() => {
    if (!wsRef) return;
    let attachedTo: WebSocket | null = null;

    const onMessage = (ev: MessageEvent<string>) => {
      let data: Record<string, unknown>;
      try { data = JSON.parse(ev.data); } catch { return; }
      const kind = (data.event || data.kind) as string | undefined;

      // Extract live screenshot if present
      if (typeof data.screenshot === 'string' && data.screenshot) {
        setLiveScreenshot(data.screenshot);
      } else if (typeof data.last_screenshot === 'string' && data.last_screenshot) {
        setLiveScreenshot(data.last_screenshot);
      } else if (data.outputs && typeof (data.outputs as Record<string, unknown>).last_screenshot === 'string') {
        setLiveScreenshot((data.outputs as Record<string, unknown>).last_screenshot as string);
      }

      if (kind === 'governance_decision') {
        decisionBuffer.current.push(data as unknown as DecisionFrame);
        const now = Date.now();
        if (now - lastFlush.current >= FLUSH_INTERVAL_MS) {
          lastFlush.current = now;
          const drained = decisionBuffer.current;
          decisionBuffer.current = [];
          setLiveDecisions((prev) => {
            const mapped = drained.map((frame) => frameToRecord(frame, () => ++liveSeq.current));
            return [...mapped.reverse(), ...prev].slice(0, LIVE_DECISION_CAP);
          });
        }
      } else if (kind === 'approval_pending') {
        const frame = data as unknown as ApprovalPendingFrame;
        setPrompts((prev) => (
          prev.some((p) => p.approval_id === frame.approval_id)
            ? prev
            : [...prev, { ...frame, deadlineMs: frame.timestamp_ms + frame.timeout_seconds * 1000 }]
        ));
      }
    };

    const attach = () => {
      const ws = wsRef.current;
      if (ws && ws !== attachedTo) {
        attachedTo = ws;
        ws.addEventListener('message', onMessage as EventListener);
      }
    };
    attach();
    const id = setInterval(attach, 500);
    return () => {
      clearInterval(id);
      if (attachedTo) attachedTo.removeEventListener('message', onMessage as EventListener);
    };
  }, [wsRef]);

  // Flush whatever is left when the stream goes quiet.
  useEffect(() => {
    const id = setInterval(() => {
      if (decisionBuffer.current.length === 0) return;
      const drained = decisionBuffer.current;
      decisionBuffer.current = [];
      lastFlush.current = Date.now();
      setLiveDecisions((prev) => {
        const mapped = drained.map((frame) => frameToRecord(frame, () => ++liveSeq.current));
        return [...mapped.reverse(), ...prev].slice(0, LIVE_DECISION_CAP);
      });
    }, FLUSH_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  // Countdown tick while prompts exist, so expiry is reflected promptly.
  useEffect(() => {
    if (prompts.length === 0) return;
    const id = setInterval(() => setNowMs(Date.now()), 500);
    return () => clearInterval(id);
  }, [prompts.length]);

  const dismissPrompt = useCallback((approvalId: string) => {
    setPrompts((prev) => prev.filter((p) => p.approval_id !== approvalId));
  }, []);

  const clearLiveDecisions = useCallback(() => setLiveDecisions([]), []);

  const expiredPromptIds = useMemo(
    () => new Set(prompts.filter((p) => p.deadlineMs <= nowMs).map((p) => p.approval_id)),
    [prompts, nowMs],
  );

  return {
    profiles,
    active,
    refreshProfiles,
    liveDecisions,
    clearLiveDecisions,
    prompts,
    dismissPrompt,
    expiredPromptIds,
    liveScreenshot,
    setLiveScreenshot,
  };
}

/** Map a WsGovernanceDecisionEvent frame into the stored-record shape. */
function frameToRecord(frame: DecisionFrame, nextSeq: () => number): DecisionRecord {
  return {
    seq: -nextSeq(), // negative: live entries sort above anything fetched
    decision_id: `live-${frame.timestamp_ms}-${frame.node_id}`,
    run_id: frame.run_id,
    node_id: frame.node_id,
    domain: frame.domain,
    capability: frame.capability,
    outcome: frame.outcome,
    origin: frame.origin,
    reason: frame.reason,
    governed_by: [],
    effective_policy: {},
    when_utc: new Date(frame.timestamp_ms).toISOString(),
    when_ms: frame.timestamp_ms,
  };
}
