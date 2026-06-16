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
});
