/// <reference types="vite/client" />
import { useEffect, useState, useCallback, useRef } from 'react';
import { Node, Edge } from 'reactflow';
import Canvas from './canvas/Canvas';
import LeftSidebar from './panels/LeftSidebar';
import RightPanel from './panels/RightPanel';
import MonitorPanel from './panels/MonitorPanel';
import TraceModal from './panels/TraceModal';
import OnboardingModal from './panels/OnboardingModal';
import ChatPanel, { ChatMessage } from './panels/ChatPanel';
import { toPipelineSchema, fromPipelineSchema, scrubSecrets } from './canvas/serializer';
import type { Pipeline } from '@shared/types';
import { useToast } from './contexts/ToastContext';
import ExportModal from './components/ExportModal';
import PublishModal from './components/PublishModal';
import DeployModal from './components/DeployModal';
import CustomNodeModal from './components/CustomNodeModal';
import SettingsModal from './components/SettingsModal';
import Tour from './components/Tour';
import type { CustomNodeDef } from './panels/LeftSidebar';
import type { PipelineNodeData } from './canvas/nodes/PipelineNode';

// Extracted hooks & stores
import { useBackend } from './hooks/useBackend';
import { usePipelineStore } from './state/pipelineStore';
import { useRunStore } from './state/runStore';
import { useRunSocket } from './hooks/useRunSocket';
import { usePipelineActions } from './hooks/usePipelineActions';
import {
  clearDraft,
  loadDraft,
  useAutosaveDraft,
} from './hooks/useDraftPersistence';

export type AppMode = 'edit' | 'use';

interface ValidationDetail { msg?: string; loc?: (string | number)[]; type?: string; }
export interface ModelInfo { endpoint_id: string; provider: string; model_name: string; max_context: number; json_mode: boolean; tools: boolean; vision: boolean; }
export interface NodeEstimate { usd: number; latency_ms: number; is_local: boolean; }
export interface EstimateResponse { nodes: Record<string, NodeEstimate>; total_usd: number; total_latency_ms: number; loop_multiplier: number; }

export default function App() {
  const [appMode, setAppMode] = useState<AppMode>('edit');
  const [showExportModal, setShowExportModal] = useState(false);
  const [showPublishModal, setShowPublishModal] = useState(false);
  const [deployModalTarget, setDeployModalTarget] = useState<string | 'new' | null>(null);
  const [deploymentsRefreshKey, setDeploymentsRefreshKey] = useState(0);
  const [showCustomNodeModal, setShowCustomNodeModal] = useState(false);
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [customNodes, setCustomNodes] = useState<CustomNodeDef[]>([]);
  const { showToast } = useToast();
  const [pipelineEstimate, setPipelineEstimate] = useState<EstimateResponse | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInputValues, setChatInputValues] = useState<Record<string, string>>({});

  const { backendPort, backendToken, backendConnected, availableModels, backendError, API_BASE } = useBackend();
  const { nodes, setNodes, onNodesChange, edges, setEdges, onEdgesChange, selectedNodeIds, setSelectedNodeIds, nodesRef, edgesRef, onConnect, updateNodeData, updateNodeDataSilent, deleteNodes, handleBeforeDelete, handleUndo, handleRedo, handleDuplicate, takeSnapshot, canUndo, canRedo } = usePipelineStore(showToast);
  const { runId, setRunId, startTime, setStartTime, nodeStats, setNodeStats, runTotals, setRunTotals, showTrace, setShowTrace, isRunning, setIsRunning, animatedEdgeIds, setAnimatedEdgeIds } = useRunStore();
  const { handleWsEvent, wsRef } = useRunSocket({ updateNodeDataSilent, setNodeStats, setRunTotals, setAnimatedEdgeIds, setIsRunning, edgesRef });

  const selectedNode = nodes.find(n => selectedNodeIds.includes(n.id)) || null;

  const fetchCustomNodes = useCallback(async () => {
    if (!backendToken) return;
    try {
      const res = await fetch(`${API_BASE}/custom-nodes`, { headers: { 'Authorization': `Bearer ${backendToken}` } });
      if (res.ok) { const data = await res.json(); if (Array.isArray(data)) setCustomNodes(data); }
    } catch (e) { console.warn('Failed to fetch custom nodes:', e); }
  }, [API_BASE, backendToken]);

  useEffect(() => { if (backendPort) fetchCustomNodes(); }, [backendPort, fetchCustomNodes]);

  const {
    handleExport, loadPipelineFromJson, handleLoadPipeline, handleClearWorkspace, handlePublishToLibrary, handleSaveCustomNode, handleDeleteCustomNode
  } = usePipelineActions({
    nodes, edges, nodesRef, edgesRef, setNodes, setEdges, takeSnapshot, setChatMessages, setChatInputValues, setRunTotals, showToast, setShowExportModal, setShowPublishModal, setShowCustomNodeModal, setCustomNodes, fetchCustomNodes, API_BASE, backendToken
  });

  useEffect(() => {
    if (import.meta.env.DEV) {
      (window as unknown as Record<string, unknown>).setE2EState = (n: Node<PipelineNodeData>[], e: Edge[]) => { setNodes(n); setEdges(e); };
    }
  }, [setNodes, setEdges]);

  // ── Draft autosave & crash recovery ──────────────────────────────────────
  // Set when the current canvas content came from a bundled template, so the
  // autosaved draft (and its restore banner) can say where the work came from
  // instead of silently passing a template off as the user's own.
  const lastLoadedTemplateName = useRef<string | undefined>(undefined);
  const [restoredDraftNotice, setRestoredDraftNotice] = useState<string | null>(null);
  const draftRestoreAttempted = useRef(false);

  const handleLoadTemplate = useCallback((schema: Pipeline) => {
    lastLoadedTemplateName.current = schema.name || undefined;
    loadPipelineFromJson(schema);
    showToast('Autosave note: this template is now your autosaved draft.', 'info');
  }, [loadPipelineFromJson, showToast]);

  // Restore once on mount: only into an empty canvas, so a template or import
  // that loads before this effect can never be clobbered by a stale draft.
  useEffect(() => {
    if (draftRestoreAttempted.current) return;
    draftRestoreAttempted.current = true;
    const draft = loadDraft();
    if (!draft || nodesRef.current.length > 0) return;
    const restored = fromPipelineSchema(draft.pipeline);
    if (restored.nodes.length === 0) return;
    setNodes(restored.nodes);
    setEdges(restored.edges);
    const origin = draft.templateName
      ? ` It was loaded from the “${draft.templateName}” template.`
      : '';
    setRestoredDraftNotice(`Unsaved work from your last session was restored.${origin}`);
    // Run once on mount only — deps are intentionally mount-stable refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useAutosaveDraft(
    useCallback(() => {
      if (isRunning || nodesRef.current.length === 0) return null;
      return {
        savedAt: Date.now(),
        templateName: lastLoadedTemplateName.current,
        pipeline: scrubSecrets(toPipelineSchema(nodesRef.current, edgesRef.current)),
      };
    }, [isRunning, nodesRef, edgesRef]),
    // Re-arm the debounce whenever the graph or run state changes. The deps
    // intentionally differ from useAutosaveDraft's own closure deps.
    [nodes, edges, isRunning],
  );

  const discardRestoredDraft = useCallback(() => {
    clearDraft();
    setNodes([]);
    setEdges([]);
    setChatMessages([]);
    setRestoredDraftNotice(null);
    showToast('Draft discarded — starting clean.', 'success');
  }, [setNodes, setEdges, setChatMessages, showToast]);

  const dismissRestoredDraftNotice = useCallback(() => {
    setRestoredDraftNotice(null);
  }, []);

  useEffect(() => {
    if (!backendConnected) return;
    const timeout = setTimeout(async () => {
      try {
        const schema = toPipelineSchema(nodesRef.current, edgesRef.current);
        const scrubbed = scrubSecrets(schema);
        if (scrubbed.nodes.length === 0) return setPipelineEstimate(null);
        const res = await fetch(`${API_BASE}/pipelines/estimate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(backendToken ? { 'Authorization': `Bearer ${backendToken}` } : {}) },
          body: JSON.stringify({ pipeline: scrubbed }),
        });
        if (!res.ok) return;
        const data: EstimateResponse = await res.json();
        setPipelineEstimate(data);
        setNodes((nds) => {
          let changed = false;
          const mapped = nds.map((n) => {
            const est = data.nodes[n.id];
            if (!est) return n;
            // Skip nodes whose estimate is unchanged: returning the same
            // node/array keeps `nodes` referentially equal, so this effect
            // does not re-trigger itself on every response (it used to
            // refetch forever, one render per second, for as long as the
            // page stayed open).
            if (
              n.data.estimate &&
              n.data.estimate.usd === est.usd &&
              n.data.estimate.latency_ms === est.latency_ms &&
              n.data.estimate.is_local === est.is_local
            ) {
              return n;
            }
            changed = true;
            return { ...n, data: { ...n.data, estimate: est } };
          });
          return changed ? mapped : nds;
        });
      } catch (err) { console.warn('Failed to estimate pipeline', err); }
    }, 1000);
    return () => clearTimeout(timeout);
  }, [nodes, edges, API_BASE, backendToken, backendConnected, setNodes, nodesRef, edgesRef]);

  const resetAllNodes = useCallback(() => {
    setNodes(nds => nds.map(n => ({ ...n, data: { ...n.data, status: 'idle' } })));
    setAnimatedEdgeIds(new Set());
  }, [setNodes, setAnimatedEdgeIds]);

  const runPipeline = async () => {
    if (nodes.length === 0 || !backendToken) return;
    const missingEndpoint = nodes.filter(n => n.data.type === 'model').filter(n => !n.data.endpoint_ref);
    if (missingEndpoint.length > 0) return showToast(`Please select a model for: ${missingEndpoint.map(n => n.data.role || n.id).join(', ')}`, 'error');

    setIsRunning(true); setRunId(null); setShowTrace(false); setStartTime(Date.now());
    setNodeStats({}); setRunTotals({ costUsd: 0, tokensIn: 0, tokensOut: 0, iterations: 0 }); resetAllNodes();
    const token = backendToken;

    try {
      const res = await fetch(`${API_BASE}/pipelines/run`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ pipeline: toPipelineSchema(nodes, edges), budget_usd: 10.0 })
      });

      if (!res.ok) {
        const text = await res.text();
        if (res.status === 422) {
          try {
            const errData = JSON.parse(text);
            if (Array.isArray(errData.detail)) errData.detail.forEach((e: ValidationDetail) => showToast(`Validation failed: ${e.msg || JSON.stringify(e)}`, 'error'));
            else showToast(`Validation failed: ${errData.detail || 'Unknown error'}`, 'error');
          } catch { showToast(`Validation failed: ${text}`, 'error'); }
        } else showToast(`Backend error: ${res.statusText}`, 'error');
        setIsRunning(false); return;
      }
      const { run_id } = await res.json();
      setRunId(run_id);
      
      const ws = new WebSocket(`${API_BASE.replace(/^http/, 'ws').replace(/\/+$/, '')}/ws/run/${run_id}?token=${token}`);
      wsRef.current = ws;
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data); handleWsEvent(data);
        if (['run_completed', 'run_stopped', 'budget_exceeded', 'run_halted'].includes(data.event || data.kind)) ws.close();
      };
      if (!ws.url.startsWith('ws')) { showToast('Invalid websocket URL', 'error'); setIsRunning(false); return; }
      ws.onerror = () => { setIsRunning(false); }; ws.onclose = () => { setIsRunning(false); wsRef.current = null; };
    } catch (err) { showToast('Backend not reachable', 'error'); setIsRunning(false); }
  };

  const stopRun = async () => {
    if (runId && backendToken) await fetch(`${API_BASE}/runs/${runId}/stop`, { method: 'POST', headers: { 'Authorization': `Bearer ${backendToken}` } }).catch(() => {});
  };

  const handleChatRunStateChange = useCallback((running: boolean) => {
    setIsRunning(running);
    if (running) {
      setRunId(null); setShowTrace(false); setStartTime(Date.now());
      setNodeStats({}); setRunTotals({ costUsd: 0, tokensIn: 0, tokensOut: 0, iterations: 0 });
    }
  }, [setIsRunning, setRunId, setShowTrace, setStartTime, setNodeStats, setRunTotals]);

  return (
    <div style={{ display: 'flex', width: '100vw', height: '100vh' }}>
      <LeftSidebar backendPort={backendPort} backendToken={backendToken} backendConnected={backendConnected} onLoadTemplate={handleLoadTemplate} onPublishClick={() => setShowPublishModal(true)} onCreateCustomNode={() => setShowCustomNodeModal(true)} customNodes={customNodes} onDeleteCustomNode={handleDeleteCustomNode} onDeployClick={() => setDeployModalTarget('new')} onManageDeploymentClick={(id) => setDeployModalTarget(id)} deploymentsRefreshKey={deploymentsRefreshKey} API_BASE={API_BASE} />
      <div style={{ flex: 1, position: 'relative', display: 'flex', flexDirection: 'column' }}>
        <div style={{ position: 'absolute', top: 12, left: 12, right: 12, zIndex: 10, display: 'flex', gap: 8, alignItems: 'center', pointerEvents: 'none' }}>
          <div style={{ pointerEvents: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
            <div className="nf-mode-switch" data-testid="mode-switch" style={{ boxShadow: 'var(--shadow-md)' }}>
              <button className={appMode === 'edit' ? 'active' : ''} onClick={() => setAppMode('edit')} data-testid="mode-edit">✏ Edit</button>
              <button className={appMode === 'use' ? 'active' : ''} onClick={() => setAppMode('use')} data-testid="mode-use">◎ Use</button>
            </div>
            {appMode === 'edit' && (
              <>
                <button onClick={() => setShowExportModal(true)} className="nf-pill-btn" style={{ boxShadow: 'var(--shadow-sm)' }}>↑ Export</button>
                <label className="nf-pill-btn" style={{ boxShadow: 'var(--shadow-sm)', cursor: 'pointer' }}>↓ Import<input type="file" accept=".json" onChange={handleLoadPipeline} style={{ display: 'none' }} /></label>
                <button onClick={handleUndo} disabled={!canUndo()} title="Undo (Ctrl+Z)" className="nf-pill-btn" style={{ boxShadow: 'var(--shadow-sm)' }}>↩</button>
                <button onClick={handleRedo} disabled={!canRedo()} title="Redo (Ctrl+Shift+Z)" className="nf-pill-btn" style={{ boxShadow: 'var(--shadow-sm)' }}>↪</button>
                <div className="nf-divider" style={{ width: 1, height: 24, margin: '0 4px' }} />
                <button onClick={() => setShowSettingsModal(true)} title="Manage API Keys" className="nf-pill-btn" style={{ boxShadow: 'var(--shadow-sm)', color: 'var(--text)' }}>⚙ API</button>
              </>
            )}
          </div>
          <div style={{ marginLeft: 'auto', pointerEvents: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
            {appMode === 'edit' && (
              <>
                {runId && !isRunning && <button onClick={() => setShowTrace(true)} className="nf-pill-btn" style={{ boxShadow: 'var(--shadow-sm)' }}>◉ View Trace</button>}
                <button data-testid="run-pipeline-button" onClick={runPipeline} disabled={isRunning || nodes.length === 0} className={`nf-pill-btn nf-pill-btn--lg ${isRunning ? '' : 'nf-pill-btn--highlight'}`} style={{ boxShadow: 'var(--shadow-md)', background: isRunning ? 'var(--surface-2)' : undefined, color: isRunning ? 'var(--text-2)' : undefined, borderColor: isRunning ? 'var(--border)' : undefined }}>
                  {isRunning ? <><span style={{ display: 'inline-block', animation: 'spin 1s linear infinite' }}>◌</span>Running…</> : '▶ Run Pipeline'}
                </button>
                {pipelineEstimate && (
                  <div data-testid="pipeline-estimate" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-2)', marginLeft: 4 }}>
                    <div>Est: ~${pipelineEstimate.total_usd.toFixed(4)} · ~{(pipelineEstimate.total_latency_ms / 1000).toFixed(1)}s</div>
                    {pipelineEstimate.loop_multiplier > 1 && <div style={{ fontSize: 10, color: 'var(--warning, #f59e0b)' }}>⚠ Loop ×{pipelineEstimate.loop_multiplier} applied</div>}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
        <div style={{ flex: 1, position: 'relative', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {appMode === 'edit' ? <Canvas nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} setNodes={setNodes} onSelectionChange={(ids) => setSelectedNodeIds(ids)} onBeforeDelete={handleBeforeDelete} onUndo={handleUndo} onRedo={handleRedo} onDuplicate={handleDuplicate} animatedEdgeIds={animatedEdgeIds} /> : <ChatPanel nodes={nodes} edges={edges} backendPort={backendPort} backendToken={backendToken} apiBase={API_BASE} isRunning={isRunning} onRunStateChange={handleChatRunStateChange} updateNodeData={updateNodeDataSilent} resetNodes={resetAllNodes} onWsEvent={handleWsEvent} messages={chatMessages} setMessages={setChatMessages} inputValues={chatInputValues} setInputValues={setChatInputValues} />}
          {appMode === 'edit' && <div style={{ position: 'absolute', bottom: 16, right: 16, zIndex: 10 }}><button onClick={handleClearWorkspace} title="Clear Workspace" className="nf-pill-btn" style={{ boxShadow: 'var(--shadow-sm)', color: '#D32F2F', background: 'var(--surface)' }}>🗑 Clear</button></div>}
        </div>
        {(runId || isRunning) && <div style={{ height: 250, position: 'relative' }}><MonitorPanel runId={runId} isRunning={isRunning} nodeStats={nodeStats} runTotals={runTotals} startTime={startTime} onStop={stopRun} /></div>}
      </div>
      <RightPanel selectedNode={selectedNode} updateNodeData={updateNodeData} availableModels={availableModels} onDeleteNode={(id) => deleteNodes([id])} onManageApis={() => setShowSettingsModal(true)} />
      {showTrace && runId && <TraceModal runId={runId} backendPort={backendPort} backendToken={backendToken} onClose={() => setShowTrace(false)} />}
      <OnboardingModal API_BASE={API_BASE} backendToken={backendToken} onLoadTemplate={handleLoadTemplate} />
      <Tour />
      {restoredDraftNotice && (
        <div
          data-testid="draft-restored-banner"
          role="status"
          style={{ position: 'fixed', bottom: 24, left: 24, zIndex: 10001, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '12px 16px', boxShadow: 'var(--shadow-md)', maxWidth: 420, fontSize: 13 }}
        >
          <div style={{ marginBottom: 8 }}>{restoredDraftNotice}</div>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button data-testid="discard-draft" onClick={discardRestoredDraft} className="nf-pill-btn nf-pill-btn--sm" style={{ color: '#D32F2F' }}>Start clean</button>
            <button data-testid="keep-draft" onClick={dismissRestoredDraftNotice} className="nf-pill-btn nf-pill-btn--sm">Keep</button>
          </div>
        </div>
      )}
      {showExportModal && <ExportModal initialName={toPipelineSchema(nodes as Node<PipelineNodeData>[], edges).name || 'My Pipeline'} onExport={handleExport} onCancel={() => setShowExportModal(false)} />}
      {showPublishModal && <PublishModal initialName={toPipelineSchema(nodes as Node<PipelineNodeData>[], edges).name || 'My Pipeline'} onPublish={handlePublishToLibrary} onCancel={() => setShowPublishModal(false)} />}
      {deployModalTarget && <DeployModal pipeline={scrubSecrets(toPipelineSchema(nodes as Node<PipelineNodeData>[], edges))} existingDeploymentId={deployModalTarget === 'new' ? undefined : deployModalTarget} backendToken={backendToken} API_BASE={API_BASE} onClose={() => setDeployModalTarget(null)} onChanged={() => setDeploymentsRefreshKey(k => k + 1)} />}
      {showCustomNodeModal && <CustomNodeModal onSave={handleSaveCustomNode} onCancel={() => setShowCustomNodeModal(false)} />}
      {showSettingsModal && <SettingsModal onClose={() => setShowSettingsModal(false)} backendPort={backendPort} backendToken={backendToken} API_BASE={API_BASE} />}
      {backendError && (
        <div role="alert" data-testid="backend-error" style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 10000, backgroundColor: 'rgba(0,0,0,0.85)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ maxWidth: 560, padding: 32, border: '1px solid #B83232', borderRadius: 8, backgroundColor: '#1e1e1e', whiteSpace: 'pre-line' }}>
            <h2 style={{ marginTop: 0, color: '#B83232' }}>Backend failed to start</h2>
            <p>{backendError}</p>
            <p style={{ color: '#aaa' }}>Fix the problem and restart Komvos. Your pipeline documents were not sent anywhere.</p>
          </div>
        </div>
      )}
    </div>
  );
}

declare global { interface Window { electron?: { onBackendReady: (callback: (data: { port: number; token: string }) => void) => void; getBackendLogPath: () => Promise<string>; }; } }
