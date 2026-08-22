import { Component, ErrorInfo, ReactNode } from 'react';
import { DRAFT_STORAGE_KEY, loadDraft } from '../hooks/useDraftPersistence';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Top-level render guard. A crash in any child no longer blanks the whole
 * application: the shell stays alive, shows what failed, and offers the two
 * recovery actions — downloading the last autosaved draft (the canvas state
 * lives in localStorage precisely for this) and reloading the window.
 */
export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Console only — there is no telemetry sink, and the UI below already
    // tells the user what happened.
    console.error('Unhandled render error:', error, info.componentStack);
  }

  private exportDraft = (): void => {
    try {
      const draft = loadDraft();
      const payload = draft
        ? draft.pipeline
        : { schema_version: '2.1', nodes: [], edges: [], endpoints: {} };
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${draft?.pipeline.name || 'pipeline'}-recovered.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // Best-effort recovery; nothing sane left to do if this fails.
    }
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    const hasDraft =
      typeof window !== 'undefined' &&
      !!window.localStorage.getItem(DRAFT_STORAGE_KEY);
    return (
      <div
        role="alert"
        data-testid="app-error-boundary"
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          zIndex: 10002,
          backgroundColor: '#111',
          color: '#fff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: 'sans-serif',
        }}
      >
        <div style={{ maxWidth: 560, padding: 32 }}>
          <h2 style={{ marginTop: 0, color: '#B83232' }}>Something went wrong</h2>
          <p>
            The interface hit an unexpected error and stopped rendering. Your
            work is safe{hasDraft ? ' — an autosaved copy exists' : ''}.
          </p>
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              background: '#1e1e1e',
              border: '1px solid #444',
              borderRadius: 6,
              padding: 12,
              fontSize: 12,
              maxHeight: 160,
              overflowY: 'auto',
            }}
          >
            {error.message || String(error)}
          </pre>
          <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
            {hasDraft && (
              <button data-testid="export-recovery" onClick={this.exportDraft} style={{ padding: '8px 16px', cursor: 'pointer' }}>
                Export pipeline as JSON
              </button>
            )}
            <button data-testid="reload-app" onClick={() => window.location.reload()} style={{ padding: '8px 16px', cursor: 'pointer' }}>
              Reload Komvos
            </button>
          </div>
        </div>
      </div>
    );
  }
}
