import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import App from './App';
import React from 'react';

// Mock ReactFlow since it requires DOM measurements not available in jsdom
vi.mock('reactflow', () => ({
  default: () => <div data-testid="react-flow-mock">Canvas</div>,
  Background: () => <div />,
  Controls: () => <div />,
  MiniMap: () => <div />
}));

describe('App', () => {
  it('renders LeftSidebar, Canvas, and RightPanel', () => {
    render(<App />);
    
    // Check LeftSidebar
    expect(screen.getByText('Node Palette')).toBeDefined();
    
    // Check Canvas (mocked)
    expect(screen.getByTestId('react-flow-mock')).toBeDefined();
    
    // Check RightPanel
    expect(screen.getByText('Configuration')).toBeDefined();
  });
});
