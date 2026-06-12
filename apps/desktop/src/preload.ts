import { contextBridge, ipcRenderer } from 'electron';

// --------- Expose some API to the Renderer process ---------
contextBridge.exposeInMainWorld('electron', {
  onBackendReady: (callback: (data: { port: number; token: string }) => void) => {
    ipcRenderer.on('backend-ready', (_event, data) => callback(data));
  },
});
