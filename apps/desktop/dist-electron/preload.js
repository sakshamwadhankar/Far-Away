let electron = require("electron");
//#region src/preload.ts
electron.contextBridge.exposeInMainWorld("electron", { onBackendReady: (callback) => {
	electron.ipcRenderer.on("backend-ready", (_event, data) => callback(data));
} });
//#endregion
