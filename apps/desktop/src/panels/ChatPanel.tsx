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
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Check if the pipeline has exactly 1 input and 1 output node. */
export function isChatCompatible(nodes: RFNode<PipelineNodeData>[]): boolean {
  const inputCount = nodes.filter(n => n.data.type === 'input').length;
  const outputCount = nodes.filter(n => n.data.type === 'output').length;
  return inputCount === 1 && outputCount === 1;
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
}: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const compatible = isChatCompatible(nodes);

  // Auto-scroll to bottom on new messages if already near bottom
  useEffect(() => {
    if (!chatContainerRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'auto' });
      return;
    }
    const { scrollTop, scrollHeight, clientHeight } = chatContainerRef.current;
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 150;
    
    if (isNearBottom) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'auto' });
    }
  }, [messages]);

  const sendMessage = useCallback(async () => {
    const text = inputValue.trim();
    if (!text || isRunning || !compatible) return;

    // Add user message
    const userMsg: ChatMessage = {
      id: makeId(),
      role: 'user',
      content: text,
      timestamp: Date.now(),
    };
    setMessages(prev => [...prev, userMsg]);
    setInputValue('');

    // Find the input node and inject the user's message
    const inputNode = nodes.find(n => n.data.type === 'input');
    const outputNode = nodes.find(n => n.data.type === 'output');
    if (!inputNode || !outputNode) return;

    // Build a modified pipeline with the user's prompt as the input node's default_value
    const modifiedNodes = nodes.map(n => {
      if (n.id === inputNode.id) {
        return {
          ...n,
          data: {
            ...n.data,
            config: { ...n.data.config, default_value: text },
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

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as Record<string, unknown>;
        const eventType = (data.event || data.kind) as string;

        // Forward ALL events to App for node visuals / monitor
        onWsEvent(data);

        // Stream tokens into the assistant bubble (buffered to prevent layout thrashing)
        if (eventType === 'token' && data.text) {
          tokenBuffer += data.text as string;
          const now = Date.now();
          if (now - lastUpdate > 250) {
            const flushed = tokenBuffer;
            tokenBuffer = '';
            lastUpdate = now;
            setMessages(prev =>
              prev.map(m =>
                m.id === assistantMsgId
                  ? { ...m, content: m.content + flushed }
                  : m
              )
            );
          }
        }

        // On node_done for the output node, capture the final result
        if (eventType === 'node_done' && data.node_id === outputNode.id) {
          const outputs = data.outputs as Record<string, string> | undefined;
          if (outputs) {
            const firstValue = Object.values(outputs)[0];
            if (firstValue) {
              // Flush any remaining buffer before applying the final output
              const flushed = tokenBuffer;
              tokenBuffer = '';
              setMessages(prev => {
                const existing = prev.find(m => m.id === assistantMsgId);
                // Only replace if we haven't streamed tokens (some pipelines don't stream)
                if (existing && !existing.content && !flushed) {
                  return prev.map(m =>
                    m.id === assistantMsgId
                      ? { ...m, content: String(firstValue) }
                      : m
                  );
                } else if (flushed) {
                  return prev.map(m =>
                    m.id === assistantMsgId
                      ? { ...m, content: m.content + flushed }
                      : m
                  );
                }
                return prev;
              });
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
          if (tokenBuffer) {
            const flushed = tokenBuffer;
            tokenBuffer = '';
            setMessages(prev =>
              prev.map(m =>
                m.id === assistantMsgId
                  ? { ...m, content: m.content + flushed }
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
    inputValue,
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

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // ─── Disabled State ───────────────────────────────────────────────────────

  if (!compatible) {
    return (
      <div className="nf-chat-disabled" data-testid="chat-disabled">
        <div className="nf-chat-disabled-card">
          <h3>⚠️ Chat Mode Unavailable</h3>
          <p>
            Chat mode needs exactly one Input node and one Output node.
            Use Run mode for complex graphs with multiple inputs or outputs.
          </p>
        </div>
      </div>
    );
  }

  // ─── Chat UI ──────────────────────────────────────────────────────────────

  return (
    <div className="nf-chat-panel" data-testid="chat-panel">
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
            className={`nf-chat-bubble nf-chat-bubble--${msg.role}`}
            data-testid={`chat-message-${msg.role}`}
          >
            <span style={{ whiteSpace: 'pre-wrap' }}>
              {msg.content}
            </span>
            {msg.role === 'assistant' && isRunning && !msg.content && (
              <span className="nf-streaming-cursor" />
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      <div className="nf-chat-input-row">
        <textarea
          className="nf-chat-input"
          data-testid="chat-input"
          rows={1}
          value={inputValue}
          onChange={e => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type your message..."
          disabled={isRunning}
        />
        <button
          className="nf-chat-send-btn"
          data-testid="chat-send-btn"
          onClick={sendMessage}
          disabled={isRunning || !inputValue.trim()}
        >
          {isRunning ? '⏳ Running...' : '▶ Send'}
        </button>
      </div>
    </div>
  );
}
