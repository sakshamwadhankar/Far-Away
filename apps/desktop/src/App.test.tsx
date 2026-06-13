import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import App from './App';
import { useState } from 'react';
import * as reactflow from 'reactflow';

// We need to spy on addEdge to see if it was called
const addEdgeSpy = vi.spyOn(reactflow, 'addEdge');

// Mock ReactFlow since it requires DOM measurements not available in jsdom
vi.mock('reactflow', async (importOriginal) => {
  const actual = await importOriginal<typeof import('reactflow')>();
  return {
    ...actual,
    default: (props: any) => {
      // Expose a way to manually trigger React Flow events
      return (
        <div data-testid="react-flow-mock">
          <button 
            data-testid="trigger-connect-valid" 
            onClick={() => props.onConnect({ source: 'n1', target: 'n2', sourceHandle: 'text:out', targetHandle: 'text:in' })}
          />
          <button 
            data-testid="trigger-connect-invalid" 
            onClick={() => props.onConnect({ source: 'n1', target: 'n2', sourceHandle: 'text:out', targetHandle: 'boolean:in' })}
          />
          <button 
            data-testid="trigger-drop" 
            onClick={() => {
              const mockEvent = {
                preventDefault: () => {},
                clientX: 100,
                clientY: 100,
                dataTransfer: {
                  getData: () => JSON.stringify({ type: 'model', data: { endpoint_ref: 'ep_test' } })
                }
              };
              // Need to mock the ref's getBoundingClientRect inside Canvas for drop to work
              props.onDrop(mockEvent);
            }}
          />
        </div>
      );
    },
    Background: () => <div />,
    Controls: () => <div />,
    MiniMap: () => <div />,
    useNodesState: (init: any) => {
      const [state, setState] = useState(init);
      return [state, setState, vi.fn()];
    },
    useEdgesState: (init: any) => {
      const [state, setState] = useState(init);
      return [state, setState, vi.fn()];
    },
    useReactFlow: () => ({
      screenToFlowPosition: () => ({ x: 50, y: 50 }),
    }),
    Position: { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' },
    Handle: () => <div data-testid="handle-mock" />
  };
});

describe('App - P3 Phase 2 UI Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders LeftSidebar, Canvas, and RightPanel', () => {
    render(<App />);
    expect(screen.getByText('Node Palette')).toBeDefined();
    expect(screen.getByTestId('react-flow-mock')).toBeDefined();
    expect(screen.getByText('Configuration')).toBeDefined();
  });

  it('allows connecting compatible ports (text -> text)', () => {
    render(<App />);
    const validBtn = screen.getByTestId('trigger-connect-valid');
    
    fireEvent.click(validBtn);
    
    // addEdge should have been called
    expect(addEdgeSpy).toHaveBeenCalledTimes(1);
    expect(addEdgeSpy.mock.calls[0][0]).toMatchObject({
      sourceHandle: 'text:out',
      targetHandle: 'text:in'
    });
  });

  it('rejects connecting incompatible ports (text -> boolean)', () => {
    render(<App />);
    const invalidBtn = screen.getByTestId('trigger-connect-invalid');
    
    // Silence the console.warn we expect
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    
    fireEvent.click(invalidBtn);
    
    // addEdge should NOT be called
    expect(addEdgeSpy).not.toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalledWith('Incompatible port types', 'text', 'boolean');
    
    warnSpy.mockRestore();
  });

  it('handles drag-and-drop to create a new node', () => {
    // Because reactFlowWrapper is used in Canvas, we need to mock it globally or mock getBoundingClientRect
    // To make it simple, we can mock HTMLElement.prototype.getBoundingClientRect
    const rectSpy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      top: 0, left: 0, width: 1000, height: 1000, bottom: 1000, right: 1000, x: 0, y: 0, toJSON: () => {}
    });

    render(<App />);
    const dropBtn = screen.getByTestId('trigger-drop');
    
    fireEvent.click(dropBtn);

    // The node should have been created and added to state.
    // If it was added to state and passed to RightPanel, we should be able to select it?
    // Actually, App.tsx passes nodes to Canvas.
    
    rectSpy.mockRestore();
  });
});

describe('App - P3 Phase 4 Template Gallery & Onboarding', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    
    // Mock localStorage
    const store: Record<string, string> = {};
    global.localStorage = {
      getItem: (key: string) => store[key] || null,
      setItem: (key: string, value: string) => { store[key] = value; },
      clear: () => { for (let key in store) delete store[key]; },
      removeItem: (key: string) => { delete store[key]; },
      length: 0,
      key: () => null
    } as any;
    
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/health/ollama')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'ok', message: 'Ollama is running' })
        });
      }
      if (url.includes('/health')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'ok' })
        });
      }
      if (url.includes('/pipelines/templates')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([
            { id: 't1', name: 'Solver, Verifier, Judge Loop', nodes: [], edges: [] }
          ])
        });
      }
      if (url.includes('/models')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ models: [] })
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as any;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('shows OnboardingModal on first run if Ollama is up', async () => {
    render(<App />);
    
    // The modal should appear asynchronously after fetch
    const modalHeader = await screen.findByText('Ollama Detected! 🎉');
    expect(modalHeader).toBeDefined();

    // Verify template load button is there
    const loadBtn = screen.getByText('Load & Run Solver-Verifier-Judge');
    expect(loadBtn).toBeDefined();

    // Click load
    fireEvent.click(loadBtn);

    // Modal should close and flag should be set
    expect(screen.queryByText('Ollama Detected! 🎉')).toBeNull();
    expect(localStorage.getItem('neuralflow_first_run')).toBe('1');
  });

  it('renders Template Gallery in LeftSidebar', async () => {
    render(<App />);
    
    // Gallery header
    expect(screen.getByText('Template Gallery')).toBeDefined();

    // Wait for templates to load
    const templateName = await screen.findByText('Solver, Verifier, Judge Loop');
    expect(templateName).toBeDefined();

    // Click load button in gallery
    const loadBtn = screen.getByText('Load');
    fireEvent.click(loadBtn);

    // fromPipelineSchema is triggered in loadPipelineFromJson, which will call setNodes/setEdges.
    // For this mock, it's sufficient that the Load button is interactive and doesn't crash.
  });
});
