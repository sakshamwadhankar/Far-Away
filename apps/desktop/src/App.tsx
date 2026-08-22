/// <reference types="vite/client" />
import { useEffect, useState, useCallback } from 'react';
import { Node, Edge } from 'reactflow';
import Canvas from './canvas/Canvas';
import LeftSidebar from './panels/LeftSidebar';
import RightPanel from './panels/RightPanel';
import MonitorPanel from './panels/MonitorPanel';
import TraceModal from './panels/TraceModal';
import OnboardingModal from './panels/OnboardingModal';
import ChatPanel, { ChatMessage } from './panels/ChatPanel';
import { toPipelineSchema, scrubSecrets } from './canvas/serializer';
import { useToast } from './contexts/ToastContext';
import ExportModal from './components/ExportModal';
import PublishModal from './components/PublishModal';
import DeployModal from './components/DeployModal';
import CustomNodeModal from './components/CustomNodeModal';
import SettingsModal from './components/SettingsModal';
import LicensesModal from './components/LicensesModal';
import Tour from './components/Tour';
import type { CustomNodeDef } from './panels/LeftSidebar';
import type { PipelineNodeData } from './canvas/nodes/PipelineNode';

// Extracted hooks & stores
import { useBackend } from './hooks/useBackend';
import { usePipelineStore } from './state/pipelineStore';
import { useRunStore } from './state/runStore';
import { useRunSocket } from './hooks/useRunSocket';
import { usePipelineActions } from './hooks/usePipelineActions';
import { useGovernance } from './governance/useGovernance';
import ActiveProfileIndicator from './governance/ActiveProfileIndicator';
import ProfilePicker from './governance/ProfilePicker';
import DecisionHistory from './governance/DecisionHistory';
import ApprovalPrompt from './governance/ApprovalPrompt';

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
  const [showLicensesModal, setShowLicensesModal] = useState(false);
  const [showProfilePicker, setShowProfilePicker] = useState(false);
  const [showDecisionHistory, setShowDecisionHistory] = useState(false);
  const [customNodes, setCustomNodes] = useState<CustomNodeDef[]>([]);
  const { showToast } = useToast();
  const [pipelineEstimate, setPipelineEstimate] = useState<EstimateResponse | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInputValues, setChatInputValues] = useState<Record<string, string>>({});

  const { backendPort, backendToken, backendConnected, availableModels, API_BASE } = useBackend();
  const { nodes, setNodes, onNodesChange, edges, setEdges, onEdgesChange, selectedNodeIds, setSelectedNodeIds, nodesRef, edgesRef, onConnect, updateNodeData, updateNodeDataSilent, deleteNodes, handleBeforeDelete, handleUndo, handleRedo, handleDuplicate, takeSnapshot, canUndo, canRedo } = usePipelineStore(showToast);
  const { runId, setRunId, startTime, setStartTime, nodeStats, setNodeStats, runTotals, setRunTotals, showTrace, setShowTrace, isRunning, setIsRunning, animatedEdgeIds, setAnimatedEdgeIds } = useRunStore();
  const { handleWsEvent, wsRef } = useRunSocket({ updateNodeDataSilent, setNodeStats, setRunTotals, setAnimatedEdgeIds, setIsRunning, edgesRef });
  const { profiles, active, refreshProfiles, liveDecisions, prompts, dismissPrompt, expiredPromptIds } = useGovernance({ apiBase: API_BASE, token: backendToken || '', connected: !!backendConnected, wsRef });

  const selectedNode = nodes.find(n => selectedNodeIds.includes(n.id)) || null;

  const fetchCustomNodes = useCallback(async () => {
    const token = backendToken || 'test-token';
    try {
      const res = await fetch(`${API_BASE}/custom-nodes`, { headers: { 'Authorization': `Bearer ${token}` } });
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
        setNodes((nds) => nds.map((n) => { const est = data.nodes[n.id]; return est ? { ...n, data: { ...n.data, estimate: est } } : n; }));
      } catch (err) { console.warn('Failed to estimate pipeline', err); }
    }, 1000);
    return () => clearTimeout(timeout);
  }, [nodes, edges, API_BASE, backendToken, backendConnected, setNodes, nodesRef, edgesRef]);

  const resetAllNodes = useCallback(() => {
    setNodes(nds => nds.map(n => ({ ...n, data: { ...n.data, status: 'idle' } })));
    setAnimatedEdgeIds(new Set());
  }, [setNodes, setAnimatedEdgeIds]);

  const runPipeline = async () => {
    if (nodes.length === 0) return;
    const missingEndpoint = nodes.filter(n => n.data.type === 'model').filter(n => !n.data.endpoint_ref);
    if (missingEndpoint.length > 0) return showToast(`Please select a model for: ${missingEndpoint.map(n => n.data.role || n.id).join(', ')}`, 'error');

    setIsRunning(true); setRunId(null); setShowTrace(false); setStartTime(Date.now());
    setNodeStats({}); setRunTotals({ costUsd: 0, tokensIn: 0, tokensOut: 0, iterations: 0 }); resetAllNodes();
    const token = backendToken || 'test-token';

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
    if (runId) await fetch(`${API_BASE}/runs/${runId}/stop`, { method: 'POST', headers: { 'Authorization': `Bearer ${backendToken || 'test-token'}` } }).catch(() => {});
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
      <LeftSidebar backendPort={backendPort} backendToken={backendToken} backendConnected={!!backendConnected} onLoadTemplate={loadPipelineFromJson} onPublishClick={() => setShowPublishModal(true)} onCreateCustomNode={() => setShowCustomNodeModal(true)} customNodes={customNodes} onDeleteCustomNode={handleDeleteCustomNode} onDeployClick={() => setDeployModalTarget('new')} onManageDeploymentClick={(id) => setDeployModalTarget(id)} deploymentsRefreshKey={deploymentsRefreshKey} API_BASE={API_BASE} />
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
                <button onClick={() => setShowDecisionHistory(true)} className="nf-pill-btn" style={{ boxShadow: 'var(--shadow-sm)' }}>🛡 History</button>
                <button onClick={() => setShowSettingsModal(true)} title="Manage API Keys" className="nf-pill-btn" style={{ boxShadow: 'var(--shadow-sm)', color: 'var(--text)' }}>⚙ API</button>
                <button onClick={() => setShowLicensesModal(true)} title="Open Source Licences & Attributions" className="nf-pill-btn" style={{ boxShadow: 'var(--shadow-sm)' }}>📜 Licences</button>
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
      <OnboardingModal API_BASE={API_BASE} onLoadTemplate={loadPipelineFromJson} />
      <Tour />
      {showExportModal && <ExportModal initialName={toPipelineSchema(nodes as Node<PipelineNodeData>[], edges).name || 'My Pipeline'} onExport={handleExport} onCancel={() => setShowExportModal(false)} />}
      {showPublishModal && <PublishModal initialName={toPipelineSchema(nodes as Node<PipelineNodeData>[], edges).name || 'My Pipeline'} onPublish={handlePublishToLibrary} onCancel={() => setShowPublishModal(false)} />}
      {deployModalTarget && <DeployModal pipeline={scrubSecrets(toPipelineSchema(nodes as Node<PipelineNodeData>[], edges))} existingDeploymentId={deployModalTarget === 'new' ? undefined : deployModalTarget} backendToken={backendToken} API_BASE={API_BASE} onClose={() => setDeployModalTarget(null)} onChanged={() => setDeploymentsRefreshKey(k => k + 1)} />}
      {showCustomNodeModal && <CustomNodeModal onSave={handleSaveCustomNode} onCancel={() => setShowCustomNodeModal(false)} />}
      {showSettingsModal && <SettingsModal onClose={() => setShowSettingsModal(false)} backendPort={backendPort} backendToken={backendToken} API_BASE={API_BASE} />}
      {showLicensesModal && <LicensesModal isOpen={showLicensesModal} onClose={() => setShowLicensesModal(false)} />}
      <ActiveProfileIndicator activeName={active?.name || null} activeProfile={active?.profile || null} connected={!!backendConnected} onOpenPicker={() => setShowProfilePicker(true)} />
      {showProfilePicker && <ProfilePicker apiBase={API_BASE} token={backendToken || ''} profiles={profiles} active={active} refreshProfiles={refreshProfiles} onClose={() => setShowProfilePicker(false)} />}
      {showDecisionHistory && <DecisionHistory apiBase={API_BASE} token={backendToken || ''} onClose={() => setShowDecisionHistory(false)} liveDecisions={liveDecisions} />}
      {prompts.length > 0 && <ApprovalPrompt apiBase={API_BASE} token={backendToken || ''} prompt={prompts[0]} isExpired={expiredPromptIds.has(prompts[0].approval_id)} onDismiss={dismissPrompt} />}
    </div>
  );
}

declare global { interface Window { electron?: { onBackendReady: (callback: (data: { port: number; token: string }) => void) => void; }; } }
