import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ErrorBoundary from './ErrorBoundary';

function Thrower(): never {
  throw new Error('kaboom in canvas');
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('keeps the shell alive when a child throws', () => {
    render(
      <ErrorBoundary>
        <Thrower />
      </ErrorBoundary>,
    );

    const fallback = screen.getByTestId('app-error-boundary');
    expect(fallback).toBeDefined();
    expect(screen.getByText(/Something went wrong/)).toBeDefined();
    // The error itself is shown so the user can see what failed.
    expect(screen.getByText(/kaboom in canvas/)).toBeDefined();
    expect(screen.getByTestId('reload-app')).toBeDefined();
  });

  it('offers exporting the autosaved draft when one exists', () => {
    localStorage.setItem(
      'komvos_autosave_draft_v1',
      JSON.stringify({
        savedAt: Date.now(),
        pipeline: {
          schema_version: '2.1',
          id: 'x',
          name: 'Recovered',
          version: '1.0.0',
          nodes: [],
          edges: [],
          endpoints: {},
        },
      }),
    );

    render(
      <ErrorBoundary>
        <Thrower />
      </ErrorBoundary>,
    );

    expect(screen.getByTestId('export-recovery')).toBeDefined();
    expect(screen.getByText(/an autosaved copy exists/)).toBeDefined();
  });

  it('hides the export action when there is no draft to save', () => {
    render(
      <ErrorBoundary>
        <Thrower />
      </ErrorBoundary>,
    );

    expect(screen.queryByTestId('export-recovery')).toBeNull();
  });

  it('renders children untouched when nothing throws', () => {
    render(
      <ErrorBoundary>
        <div>all fine</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText('all fine')).toBeDefined();
    expect(screen.queryByTestId('app-error-boundary')).toBeNull();
  });
});
