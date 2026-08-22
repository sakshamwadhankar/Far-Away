import { useState, useEffect } from 'react';
import type { ModelInfo } from '../App';

export function useBackend() {
  const [backendPort, setBackendPort] = useState<number | null>(null);
  const [backendToken, setBackendToken] = useState<string | null>(null);
  const [backendConnected, setBackendConnected] = useState<boolean | null>(null);
  const [availableModels, setAvailableModels] = useState<ModelInfo[]>([]);

  const API_BASE = `http://127.0.0.1:${backendPort || 8000}`;

  useEffect(() => {
    // Listen for backend info from Electron IPC
    if (window.electron) {
      // Fallback: if Electron backend-ready never fires (e.g. HMR race),
      // fall back to the start.bat backend on port 8000 after 2s.
      const fallbackTimer = setTimeout(() => {
        setBackendPort(prev => prev ?? 8000);
        setBackendToken(prev => prev ?? 'test-token');
      }, 2000);

      window.electron.onBackendReady((data: { port: number; token: string }) => {
        clearTimeout(fallbackTimer);
        console.log('Backend is ready on port:', data.port);
        setBackendPort(data.port);
        setBackendToken(data.token);
      });

      return () => clearTimeout(fallbackTimer);
    } else {
      // Plain browser / Vite dev server — use the start.bat backend
      setBackendPort(8000);
      setBackendToken('test-token');
    }
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
    API_BASE
  };
}
