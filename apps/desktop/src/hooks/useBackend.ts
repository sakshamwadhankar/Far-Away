import { useState, useEffect } from 'react';
import type { ModelInfo } from '../App';

// Development-only credentials for driving a manually started backend from the
// Vite dev server (plain-browser mode). They come from .env.development so no
// credential literal lives in source; import.meta.env.DEV is statically
// replaced by Vite at build time, so this branch cannot ship in a packaged app.
const DEV_BACKEND_PORT = Number(import.meta.env.VITE_DEV_BACKEND_PORT) || 8000;
const DEV_BACKEND_TOKEN = (import.meta.env.VITE_DEV_BACKEND_TOKEN as string | undefined) ?? '';

// How long to wait for the main process' backend-ready IPC before giving up.
const BACKEND_READY_TIMEOUT_MS = 15000;

export function useBackend() {
  const [backendPort, setBackendPort] = useState<number | null>(null);
  const [backendToken, setBackendToken] = useState<string | null>(null);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [backendConnected, setBackendConnected] = useState<boolean | null>(null);
  const [availableModels, setAvailableModels] = useState<ModelInfo[]>([]);

  const API_BASE = `http://127.0.0.1:${backendPort || 8000}`;

  useEffect(() => {
    const electron = window.electron;
    if (electron) {
      // The main process spawns the backend on a random port and hands the
      // session token over IPC. If it never arrives there is nothing safe to
      // fall back to: guessing port 8000 would send pipeline documents to
      // whatever unrelated process happens to be listening there. Fail with
      // an actionable error naming the backend log file instead.
      const failTimer = setTimeout(() => {
        void electron.getBackendLogPath().then((logPath) => {
          setBackendError(
            'The Komvos backend did not start.' +
              (logPath ? `\nCheck the backend log for details:\n${logPath}` : '')
          );
        });
      }, BACKEND_READY_TIMEOUT_MS);

      electron.onBackendReady((data: { port: number; token: string }) => {
        clearTimeout(failTimer);
        console.log('Backend is ready on port:', data.port);
        setBackendPort(data.port);
        setBackendToken(data.token);
      });

      return () => clearTimeout(failTimer);
    } else if (import.meta.env.DEV) {
      // Plain browser via the Vite dev server — development only. Compiled out
      // of production bundles together with the DEV guard above it.
      setBackendPort(DEV_BACKEND_PORT);
      setBackendToken(DEV_BACKEND_TOKEN || null);
    }
    // Packaged production builds always have window.electron; if neither
    // branch ran, backendError stays null but no requests are made either —
    // the UI surfaces the disconnected state via backendConnected polling.
  }, []);

  useEffect(() => {
    if (!backendPort || !backendToken) return;

    const fetchModels = async () => {
      try {
        const res = await fetch(`${API_BASE}/models`, {
          headers: { 'Authorization': `Bearer ${backendToken}` }
        });
        if (res.ok) {
          const data = await res.json();
          setAvailableModels(data.models || []);
        } else {
          setAvailableModels([]);
        }
      } catch (err) {
        console.warn('Backend not reachable for models fetch:', err);
        setAvailableModels([]);
      }
    };
    fetchModels();

    window.addEventListener('focus', fetchModels);
    return () => window.removeEventListener('focus', fetchModels);
  }, [API_BASE, backendToken, backendPort]);

  // Polling for backend connection status
  useEffect(() => {
    let mounted = true;
    const checkHealth = async () => {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 3000);
      try {
        const res = await fetch(`${API_BASE}/health`, { signal: controller.signal });
        if (res.ok && mounted) {
          setBackendConnected(true);
        } else if (mounted) {
          setBackendConnected(false);
        }
      } catch {
        if (mounted) setBackendConnected(false);
      } finally {
        clearTimeout(timeout);
      }
    };
    checkHealth();
    const interval = setInterval(checkHealth, 2000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [API_BASE]);

  return {
    backendPort,
    setBackendPort,
    backendToken,
    setBackendToken,
    backendConnected,
    availableModels,
    backendError,
    API_BASE
  };
}
