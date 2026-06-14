//#region \0rolldown/runtime.js
var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __copyProps = (to, from, except, desc) => {
	if (from && typeof from === "object" || typeof from === "function") for (var keys = __getOwnPropNames(from), i = 0, n = keys.length, key; i < n; i++) {
		key = keys[i];
		if (!__hasOwnProp.call(to, key) && key !== except) __defProp(to, key, {
			get: ((k) => from[k]).bind(null, key),
			enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable
		});
	}
	return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", {
	value: mod,
	enumerable: true
}) : target, mod));
//#endregion
let electron = require("electron");
let node_path = require("node:path");
node_path = __toESM(node_path);
let node_http = require("node:http");
node_http = __toESM(node_http);
let node_crypto = require("node:crypto");
node_crypto = __toESM(node_crypto);
let node_child_process = require("node:child_process");
let node_net = require("node:net");
node_net = __toESM(node_net);
//#region src/main.ts
process.env.DIST = node_path.default.join(__dirname, "../dist");
process.env.VITE_PUBLIC = electron.app.isPackaged ? process.env.DIST : node_path.default.join(process.env.DIST, "../public");
var win;
var VITE_DEV_SERVER_URL = process.env["VITE_DEV_SERVER_URL"];
function checkOllama() {
	node_http.default.get("http://127.0.0.1:11434/", (res) => {
		if (res.statusCode !== 200) showOllamaWarning();
	}).on("error", () => {
		showOllamaWarning();
	});
}
function showOllamaWarning() {
	electron.dialog.showMessageBox({
		type: "info",
		title: "Ollama Not Detected",
		message: "Ollama not detected — local models unavailable. Install from ollama.com and run 'ollama pull qwen2.5:3b'. Cloud models still work.",
		buttons: ["OK"]
	});
}
function spawnBackend(win) {
	const token = node_crypto.default.randomUUID();
	const srv = node_net.default.createServer();
	srv.listen(0, "127.0.0.1", () => {
		const port = srv.address().port;
		srv.close(() => {
			console.log(`[Backend] Starting Python backend on port ${port}...`);
			const isWin = process.platform === "win32";
			const backendDir = electron.app.isPackaged ? node_path.default.join(process.resourcesPath, "backend") : node_path.default.join(__dirname, "../../../backend");
			let backendProcess;
			if (electron.app.isPackaged) backendProcess = (0, node_child_process.spawn)(isWin ? node_path.default.join(backendDir, "komvos_backend.exe") : node_path.default.join(backendDir, "komvos_backend"), [
				"--host",
				"127.0.0.1",
				"--port",
				port.toString()
			], {
				cwd: backendDir,
				env: {
					...process.env,
					NEURALFLOW_SESSION_TOKEN: token
				}
			});
			else backendProcess = (0, node_child_process.spawn)(isWin ? node_path.default.join(backendDir, ".venv", "Scripts", "python.exe") : node_path.default.join(backendDir, ".venv", "bin", "python"), [
				"-m",
				"uvicorn",
				"neuralflow.api.main:app",
				"--host",
				"127.0.0.1",
				"--port",
				port.toString()
			], {
				cwd: backendDir,
				env: {
					...process.env,
					NEURALFLOW_SESSION_TOKEN: token
				}
			});
			backendProcess.stdout.on("data", (data) => console.log(`[Backend] ${data}`));
			backendProcess.stderr.on("data", (data) => console.error(`[Backend ERR] ${data}`));
			const checkHealth = () => {
				node_http.default.get(`http://127.0.0.1:${port}/health`, (res) => {
					if (res.statusCode === 200) {
						console.log(`[Backend] Ready on port ${port} with token ${token}`);
						win.webContents.send("backend-ready", {
							port,
							token
						});
					} else setTimeout(checkHealth, 500);
				}).on("error", () => {
					setTimeout(checkHealth, 500);
				});
			};
			setTimeout(checkHealth, 500);
			electron.app.on("will-quit", () => {
				backendProcess.kill();
			});
		});
	});
}
function createWindow() {
	electron.Menu.setApplicationMenu(null);
	win = new electron.BrowserWindow({
		icon: node_path.default.join(process.env.VITE_PUBLIC, "icon.png"),
		webPreferences: { preload: node_path.default.join(__dirname, "preload.mjs") },
		width: 1200,
		height: 800,
		autoHideMenuBar: true
	});
	win.webContents.on("did-finish-load", () => {
		win?.webContents.send("main-process-message", (/* @__PURE__ */ new Date()).toLocaleString());
		spawnBackend(win);
		checkOllama();
	});
	if (VITE_DEV_SERVER_URL) win.loadURL(VITE_DEV_SERVER_URL);
	else win.loadFile(node_path.default.join(process.env.DIST, "index.html"));
}
electron.app.on("window-all-closed", () => {
	if (process.platform !== "darwin") {
		electron.app.quit();
		win = null;
	}
});
electron.app.on("activate", () => {
	if (electron.BrowserWindow.getAllWindows().length === 0) createWindow();
});
electron.app.whenReady().then(createWindow);
//#endregion
