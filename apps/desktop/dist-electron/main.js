"use strict";
const electron = require("electron");
const path = require("node:path");
const http = require("node:http");
const crypto = require("node:crypto");
process.env.DIST = path.join(__dirname, "../dist");
process.env.VITE_PUBLIC = electron.app.isPackaged ? process.env.DIST : path.join(process.env.DIST, "../public");
let win;
const VITE_DEV_SERVER_URL = process.env["VITE_DEV_SERVER_URL"];
function spawnBackendStub(win2) {
  const token = crypto.randomUUID();
  const server = http.createServer((req, res) => {
    if (req.url === "/health") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "ok", mocked: true }));
    } else {
      res.writeHead(404);
      res.end();
    }
  });
  server.listen(0, "127.0.0.1", () => {
    const address = server.address();
    const port = address.port;
    console.log(`[Stub Backend] Running on http://127.0.0.1:${port}`);
    console.log(`[Stub Backend] Token: ${token}`);
    http.get(`http://127.0.0.1:${port}/health`, (res) => {
      let data = "";
      res.on("data", (chunk) => data += chunk);
      res.on("end", () => {
        console.log(`[Stub Backend] Ping response: ${data}`);
        win2.webContents.send("backend-ready", { port, token });
      });
    }).on("error", (err) => {
      console.error(`[Stub Backend] Ping failed:`, err);
    });
  });
  electron.app.on("will-quit", () => {
    server.close();
  });
}
function createWindow() {
  win = new electron.BrowserWindow({
    icon: path.join(process.env.VITE_PUBLIC, "electron-vite.svg"),
    webPreferences: {
      preload: path.join(__dirname, "preload.mjs")
    },
    width: 1200,
    height: 800
  });
  win.webContents.on("did-finish-load", () => {
    win == null ? void 0 : win.webContents.send("main-process-message", (/* @__PURE__ */ new Date()).toLocaleString());
    spawnBackendStub(win);
  });
  if (VITE_DEV_SERVER_URL) {
    win.loadURL(VITE_DEV_SERVER_URL);
  } else {
    win.loadFile(path.join(process.env.DIST, "index.html"));
  }
}
electron.app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    electron.app.quit();
    win = null;
  }
});
electron.app.on("activate", () => {
  if (electron.BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
electron.app.whenReady().then(createWindow);
