"use strict";
const electron = require("electron");
electron.contextBridge.exposeInMainWorld("electron", {
  onBackendReady: (callback) => {
    electron.ipcRenderer.on("backend-ready", (_event, data) => callback(data));
  }
});
