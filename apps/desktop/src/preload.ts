import { contextBridge, ipcRenderer } from 'electron';

let cachedBackendData: { port: number; token: string } | null = null;

ipcRenderer.on('backend-ready', (_event, data) => {
  cachedBackendData = data;
});

// --------- Expose some API to the Renderer process ---------
contextBridge.exposeInMainWorld('electron', {
  onBackendReady: (callback: (data: { port: number; token: string }) => void) => {
    if (cachedBackendData) {
      callback(cachedBackendData);
    }
    ipcRenderer.on('backend-ready', (_event, data) => {
      cachedBackendData = data;
      callback(data);
    });
  },
  // Path of the file the main process writes backend spawn/health logs to,
  // so the renderer can point the user at it when the backend never starts.
  getBackendLogPath: (): Promise<string> => ipcRenderer.invoke('backend-log-path'),
});
