import { useState, useRef, useEffect, useCallback } from 'react';
import { Node as RFNode, Edge as RFEdge } from 'reactflow';
import { PipelineNodeData } from '../canvas/nodes/PipelineNode';
import { toPipelineSchema } from '../canvas/serializer';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  outputs?: { id: string; label: string; value: string }[];
}

interface ChatPanelProps {
  nodes: RFNode<PipelineNodeData>[];
  edges: RFEdge[];
  backendPort: number | null;
  backendToken: string | null;
  apiBase: string;
  isRunning: boolean;
  /** Callback to set running state in App */
  onRunStateChange: (running: boolean) => void;
  /** Callback to update node status during execution */
  updateNodeData: (id: string, data: Partial<PipelineNodeData>) => void;
  /** Callback to reset all nodes to idle */
  resetNodes: () => void;
  /** Callback for WS events — drives monitor panel and node stats */
  onWsEvent: (data: Record<string, unknown>) => void;
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  inputValues: Record<string, string>;
  setInputValues: React.Dispatch<React.SetStateAction<Record<string, string>>>;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Check if the pipeline has exactly 1 input and 1 output node. */
export function isChatCompatible(nodes: RFNode<PipelineNodeData>[]): boolean {
  const inputCount = nodes.filter(n => n.data.type === 'input').length;
  const outputCount = nodes.filter(n => n.data.type === 'output').length;
  return inputCount > 0 && outputCount > 0;
}

function makeId(): string {
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function ChatPanel({
  nodes,
  edges,
  backendPort: _backendPort,
  backendToken,
  apiBase,
  isRunning,
  onRunStateChange,
  updateNodeData,
  resetNodes,
  onWsEvent,
  messages,
  setMessages,
  inputValues,
  setInputValues,
}: ChatPanelProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const compatible = isChatCompatible(nodes);

  // Auto-scroll to bottom on new messages if already near bottom
  useEffect(() => {
    if (!chatContainerRef.current) {
      messagesEndRef.current?.scrollIntoView?.({ behavior: 'auto' });
      return;
    }
    const { scrollTop, scrollHeight, clientHeight } = chatContainerRef.current;
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 150;
    
    if (isNearBottom) {
      messagesEndRef.current?.scrollIntoView?.({ behavior: 'auto' });
    }
  }, [messages]);

  const sendMessage = useCallback(async () => {
    const inputNodes = nodes.filter(n => n.data.type === 'input');
    const outputNodes = nodes.filter(n => n.data.type === 'output');
    if (!inputNodes.length || !outputNodes.length || isRunning || !compatible) return;

    // Build a formatted user message containing all provided inputs
    const textChunks = inputNodes.map(n => {
      const val = (inputValues[n.id] || '').trim();
      if (!val) return '';
      if (inputNodes.length === 1) return val;
      const label = n.data.config?.label || n.id;
      return `**${label}**:\n${val}`;
    }).filter(Boolean);

    const userText = textChunks.join('\n\n');
    if (!userText) return;

    // Add user message
    const userMsg: ChatMessage = {
      id: makeId(),
      role: 'user',
      content: userText,
      timestamp: Date.now(),
    };
    setMessages(prev => [...prev, userMsg]);
    setInputValues({}); // Clear inputs after send

    // Build a modified pipeline with the user's prompt as the input node's default_value
    const modifiedNodes = nodes.map(n => {
      if (n.data.type === 'input') {
        return {
          ...n,
          data: {
            ...n.data,
            config: { ...n.data.config, default_value: inputValues[n.id] || '' },
          },
        };
      }
      return n;
    });

    // Reset all node visuals
    resetNodes();
    onRunStateChange(true);

    // Create assistant message placeholder for streaming
    const assistantMsgId = makeId();
    const assistantMsg: ChatMessage = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
    };
    setMessages(prev => [...prev, assistantMsg]);

    const schema = toPipelineSchema(modifiedNodes, edges);
    const token = backendToken || 'test-token';

    try {
      const res = await fetch(`${apiBase}/pipelines/run`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ pipeline: schema, budget_usd: 10.0 }),
      });

      if (!res.ok) {
        const errText = await res.text();
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantMsgId
              ? { ...m, content: `❌ Error: ${errText}` }
              : m
          )
        );
        onRunStateChange(false);
        return;
      }

      const { run_id } = await res.json() as { run_id: string };

      // Connect WebSocket for streaming
      const wsBase = apiBase.replace(/^http/, 'ws').replace(/\/+$/, '');
      const ws = new WebSocket(
        `${wsBase}/ws/run/${run_id}?token=${token}`
      );
      wsRef.current = ws;

      let tokenBuffer = '';
      let lastUpdate = Date.now();
      
      let streamedContent = '';
      const outputResults: Record<string, string> = {};
      let hasStartedOutputs = false;

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as Record<string, unknown>;
        const eventType = (data.event || data.kind) as string;

        // Forward ALL events to App for node visuals / monitor
        onWsEvent(data);

        // Stream tokens into the assistant bubble (buffered to prevent layout thrashing)
        if (eventType === 'token' && data.text) {
          if (!hasStartedOutputs) {
            tokenBuffer += data.text as string;
            const now = Date.now();
            if (now - lastUpdate > 250) {
              streamedContent += tokenBuffer;
              tokenBuffer = '';
              lastUpdate = now;
              setMessages(prev =>
                prev.map(m =>
                  m.id === assistantMsgId
                    ? { ...m, content: streamedContent }
                    : m
                )
              );
            }
          }
        }

        // On node_done for any output node, capture the final result
        if (eventType === 'node_done' && outputNodes.some(n => n.id === data.node_id)) {
          const outputs = data.outputs as Record<string, string> | undefined;
          if (outputs) {
            const firstValue = Object.values(outputs)[0];
            if (firstValue) {
              const isMultiOutput = outputNodes.length > 1;
              if (!isMultiOutput) {
                // For a single output node, just let the stream stay.
                if (!streamedContent && !tokenBuffer) {
                  setMessages(prev => prev.map(m => m.id === assistantMsgId ? { ...m, content: String(firstValue) } : m));
                } else if (tokenBuffer) {
                  streamedContent += tokenBuffer;
                  tokenBuffer = '';
                  setMessages(prev => prev.map(m => m.id === assistantMsgId ? { ...m, content: streamedContent } : m));
                }
              } else {
                // Multi-output mode! Wipes stream and sets distinct blocks.
                hasStartedOutputs = true;
                outputResults[data.node_id] = String(firstValue);
                
                const outputsArray = Object.entries(outputResults).map(([id, val]) => {
                  const outNode = outputNodes.find(n => n.id === id);
                  const label = outNode?.data.config?.custom_label || outNode?.data.config?.label || `Output (${id.slice(0, 4)})`;
                  return { id, label: String(label), value: val };
                });
                
                setMessages(prev => prev.map(m => m.id === assistantMsgId ? { ...m, content: '', outputs: outputsArray } : m));
              }
            }
          }
        }

        // Terminal events
        if (
          eventType === 'run_completed' ||
          eventType === 'run_stopped' ||
          eventType === 'budget_exceeded' ||
          eventType === 'run_halted' ||
          eventType === 'run_error' ||
          eventType === 'node_error'
        ) {
          // Flush any remaining tokens
          if (tokenBuffer && !hasStartedOutputs) {
            streamedContent += tokenBuffer;
            tokenBuffer = '';
            setMessages(prev =>
              prev.map(m =>
                m.id === assistantMsgId
                  ? { ...m, content: streamedContent }
                  : m
              )
            );
          }
          
          if (eventType === 'run_error' || eventType === 'node_error') {
            setMessages(prev =>
              prev.map(m =>
                m.id === assistantMsgId && !m.content
                  ? { ...m, content: `❌ Pipeline error: ${(data.error || 'Unknown error') as string}` }
                  : m
              )
            );
          } else if (eventType === 'run_completed') {
            setMessages(prev =>
              prev.map(m =>
                m.id === assistantMsgId && !m.content
                  ? { ...m, content: `⚠️ Pipeline completed but produced no output. Please make sure the Output node is connected.` }
                  : m
              )
            );
          }
          onRunStateChange(false);
          ws.close();
        }
      };

      ws.onerror = () => {
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantMsgId && !m.content
              ? { ...m, content: '❌ Connection error' }
              : m
          )
        );
        onRunStateChange(false);
      };

      ws.onclose = () => {
        wsRef.current = null;
        onRunStateChange(false);
      };
    } catch (err) {
      setMessages(prev =>
        prev.map(m =>
          m.id === assistantMsgId
            ? { ...m, content: `❌ Error: ${String(err)}` }
            : m
        )
      );
      onRunStateChange(false);
    }
  }, [
    inputValues,
    isRunning,
    compatible,
    nodes,
    edges,
    backendToken,
    apiBase,
    onRunStateChange,
    updateNodeData,
    resetNodes,
    onWsEvent,
  ]);

  const handleKeyDown = (e: React.KeyboardEvent, nodeId: string) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleInputChange = (nodeId: string, value: string) => {
    setInputValues(prev => ({ ...prev, [nodeId]: value }));
  };

  // ─── Disabled State ───────────────────────────────────────────────────────

  if (!compatible) {
    return (
      <div className="nf-chat-disabled" data-testid="chat-disabled">
        <div className="nf-chat-disabled-card">
          <h3>⚠️ Chat Mode Unavailable</h3>
          <p>
            Chat mode requires at least one Input node and one Output node connected.
          </p>
        </div>
      </div>
    );
  }

  // ─── Chat UI ──────────────────────────────────────────────────────────────

  return (
    <div className="nf-chat-panel" data-testid="chat-panel" style={{ flex: 1, minHeight: 0 }}>
      <div className="nf-chat-messages" ref={chatContainerRef}>
        {messages.length === 0 && (
          <div className="nf-chat-bubble nf-chat-bubble--system">
            Send a message to run the pipeline. Your message becomes the Input node's value,
            and the Output node's result will appear here.
          </div>
        )}
        {messages.map(msg => (
          <div
            key={msg.id}
            className={msg.outputs && msg.outputs.length > 0 ? "" : `nf-chat-bubble nf-chat-bubble--${msg.role}`}
            data-testid={`chat-message-${msg.role}`}
            style={msg.outputs && msg.outputs.length > 0 ? { display: 'flex', gap: '12px', width: '100%', alignSelf: 'flex-start', overflowX: 'auto', paddingBottom: '8px' } : {}}
          >
            {msg.outputs && msg.outputs.length > 0 ? (
              msg.outputs.map(out => (
                <div key={out.id} className="nf-chat-bubble nf-chat-bubble--assistant" style={{ flex: '1 1 0', minWidth: '200px', display: 'flex', flexDirection: 'column' }}>
                  <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-3)', marginBottom: '6px', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '4px' }}>
                    {out.label.toUpperCase()}
                  </div>
                  <span style={{ whiteSpace: 'pre-wrap' }}>
                    {out.value}
                  </span>
                </div>
              ))
            ) : (
              <>
                <span style={{ whiteSpace: 'pre-wrap' }}>
                  {msg.content}
                </span>
                {msg.role === 'assistant' && isRunning && !msg.content && (
                  <span className="nf-streaming-cursor" />
                )}
              </>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      <div className="nf-chat-input-row" style={{ flexDirection: nodes.filter(n => n.data.type === 'input').length > 1 ? 'column' : 'row', gap: 8 }}>
        {nodes.filter(n => n.data.type === 'input').length === 1 ? (
          <textarea
            className="nf-chat-input"
            data-testid="chat-input"
            rows={1}
            value={inputValues[nodes.find(n => n.data.type === 'input')!.id] || ''}
            onChange={e => handleInputChange(nodes.find(n => n.data.type === 'input')!.id, e.target.value)}
            onKeyDown={e => handleKeyDown(e, nodes.find(n => n.data.type === 'input')!.id)}
            placeholder={nodes.find(n => n.data.type === 'input')?.data.config?.label || "Type your message..."}
            disabled={isRunning}
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}>
            {nodes.filter(n => n.data.type === 'input').map(node => (
              <div key={node.id} style={{ display: 'flex', flexDirection: 'column' }}>
                <label style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 4, fontWeight: 500 }}>
                  {node.data.config?.label || node.id}
                </label>
                <textarea
                  className="nf-chat-input"
                  data-testid={`chat-input-${node.id}`}
                  rows={1}
                  value={inputValues[node.id] || ''}
                  onChange={e => handleInputChange(node.id, e.target.value)}
                  onKeyDown={e => handleKeyDown(e, node.id)}
                  placeholder="Enter value..."
                  disabled={isRunning}
                  style={{ minHeight: '36px' }}
                />
              </div>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', width: nodes.filter(n => n.data.type === 'input').length > 1 ? '100%' : 'auto' }}>
          <button
            className="nf-chat-send-btn"
            data-testid="chat-send-btn"
            onClick={sendMessage}
            disabled={isRunning || nodes.filter(n => n.data.type === 'input').every(n => !(inputValues[n.id] || '').trim())}
          >
            {isRunning ? '⏳ Running...' : '▶ Send'}
          </button>
        </div>
      </div>
    </div>
  );
}
