/**
 * Regression: Use mode must publish its run socket into App's SHARED wsRef.
 *
 * useGovernance taps App's wsRef to pull live screenshots, governance
 * decisions and approval prompts off the run stream. ChatPanel used to open
 * its socket into a private ref, so a Use-mode run left that tap attached to
 * nothing: tokens streamed, but the monitor showed no live view and an "Ask"
 * policy never rendered its approval prompt — it just hung until timeout.
 *
 * TypeScript enforces that the prop is passed; only a test catches ChatPanel
 * quietly going back to a local ref, so that is what this asserts.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { createRef } from 'react';
import type { Node as RFNode } from 'reactflow';
import ChatPanel from './ChatPanel';
import type { ChatMessage } from './ChatPanel';
import type { PipelineNodeData } from '../canvas/nodes/PipelineNode';

class FakeWebSocket {
  static last: FakeWebSocket | null = null;
  url: string;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  close = vi.fn();
  constructor(url: string) {
    this.url = url;
    FakeWebSocket.last = this;
  }
}

const nodes: RFNode<PipelineNodeData>[] = [
  {
    id: 'in', type: 'pipelineNode', position: { x: 0, y: 0 },
    data: { type: 'input', outputs: [{ name: 'prompt', type: 'text' }] },
  },
  {
    id: 'out', type: 'pipelineNode', position: { x: 200, y: 0 },
    data: { type: 'output', inputs: [{ name: 'response', type: 'text' }] },
  },
];

beforeEach(() => {
  FakeWebSocket.last = null;
  vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket);
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true,
    json: async () => ({ run_id: 'run-1' }),
    text: async () => '',
  })) as unknown as typeof fetch);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ChatPanel run socket', () => {
  it('writes the live socket into the shared wsRef it was given', async () => {
    const wsRef = createRef<WebSocket | null>() as React.MutableRefObject<WebSocket | null>;
    wsRef.current = null;

    render(
      <ChatPanel
        nodes={nodes}
        edges={[]}
        backendPort={8000}
        backendToken="tok"
        apiBase="http://127.0.0.1:8000"
        isRunning={false}
        onRunStateChange={() => {}}
        updateNodeData={() => {}}
        resetNodes={() => {}}
        onWsEvent={() => {}}
        wsRef={wsRef}
        onRunStarted={() => {}}
        messages={[]}
        setMessages={() => {}}
        inputValues={{ in: 'hello' }}
        setInputValues={() => {}}
      />,
    );

    fireEvent.click(screen.getByTestId('chat-send-btn'));

    // The socket ChatPanel opened must be the one App (and therefore
    // useGovernance) can see.
    await waitFor(() => expect(wsRef.current).not.toBeNull());
    expect(wsRef.current).toBe(FakeWebSocket.last as unknown as WebSocket);
    expect(FakeWebSocket.last?.url).toContain('/ws/run/run-1');
  });

  it('sends the typed task through as the input node default_value', async () => {
    // The trace showed the input node emitting {"task": ""}. The backend seeds
    // input nodes from config.default_value, so if Use mode failed to set it
    // the agent would be dispatched with no instruction at all.
    const wsRef = createRef<WebSocket | null>() as React.MutableRefObject<WebSocket | null>;
    wsRef.current = null;
    render(
      <ChatPanel
        nodes={nodes} edges={[]} backendPort={8000} backendToken="tok"
        apiBase="http://127.0.0.1:8000" isRunning={false}
        onRunStateChange={() => {}} updateNodeData={() => {}} resetNodes={() => {}}
        onWsEvent={() => {}} wsRef={wsRef} onRunStarted={() => {}}
        messages={[]} setMessages={() => {}}
        inputValues={{ in: 'open browser and search for cu' }} setInputValues={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId('chat-send-btn'));

    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    const body = JSON.parse(
      (vi.mocked(global.fetch).mock.calls[0][1] as RequestInit).body as string,
    );
    const inputNode = body.pipeline.nodes.find(
      (n: { id: string }) => n.id === 'in',
    );
    expect(inputNode.config.default_value).toBe('open browser and search for cu');
  });

  it('surfaces a node error even after reasoning has already streamed', async () => {
    // The stall users hit: a computer node streams its thought, THEN fails.
    // The old code only wrote the error when the message was still empty, so
    // the failure vanished and the run appeared to freeze mid-thought.
    const wsRef = createRef<WebSocket | null>() as React.MutableRefObject<WebSocket | null>;
    wsRef.current = null;
    const messages: ChatMessage[] = [];
    let rendered: ChatMessage[] = [];
    const setMessages = ((fn: unknown) => {
      rendered = typeof fn === 'function'
        ? (fn as (p: ChatMessage[]) => ChatMessage[])(rendered)
        : (fn as ChatMessage[]);
    }) as React.Dispatch<React.SetStateAction<ChatMessage[]>>;

    render(
      <ChatPanel
        nodes={nodes} edges={[]} backendPort={8000} backendToken="tok"
        apiBase="http://127.0.0.1:8000" isRunning={false}
        onRunStateChange={() => {}} updateNodeData={() => {}} resetNodes={() => {}}
        onWsEvent={() => {}} wsRef={wsRef} onRunStarted={() => {}}
        messages={messages} setMessages={setMessages}
        inputValues={{ in: 'do a thing' }} setInputValues={() => {}}
      />,
    );

    fireEvent.click(screen.getByTestId('chat-send-btn'));
    await waitFor(() => expect(FakeWebSocket.last?.onmessage).toBeTruthy());
    const send = (o: unknown) =>
      FakeWebSocket.last!.onmessage!({ data: JSON.stringify(o) } as MessageEvent);

    send({ event: 'token', node_id: 'computer_agent', text: 'I will press win.' });
    send({ event: 'node_error', node_id: 'computer_agent', error: 'Access denied: app not allowed' });

    await waitFor(() => {
      const assistant = rendered.filter(m => m.role === 'assistant').pop();
      expect(assistant?.content).toContain('Access denied: app not allowed');
    });
    const assistant = rendered.filter(m => m.role === 'assistant').pop();
    expect(assistant?.content).toContain('I will press win.');
  });
});
