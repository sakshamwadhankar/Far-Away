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
//#region src/main.ts
process.env.DIST = node_path.default.join(__dirname, "../dist");
process.env.VITE_PUBLIC = electron.app.isPackaged ? process.env.DIST : node_path.default.join(process.env.DIST, "../public");
var win;
var VITE_DEV_SERVER_URL = process.env["VITE_DEV_SERVER_URL"];
function spawnBackendStub(win) {
	const token = node_crypto.default.randomUUID();
	const server = node_http.default.createServer((req, res) => {
		if (req.url === "/health") {
			res.writeHead(200, { "Content-Type": "application/json" });
			res.end(JSON.stringify({
				status: "ok",
				mocked: true
			}));
		} else {
			res.writeHead(404);
			res.end();
		}
	});
	server.listen(0, "127.0.0.1", () => {
		const port = server.address().port;
		console.log(`[Stub Backend] Running on http://127.0.0.1:${port}`);
		console.log(`[Stub Backend] Token: ${token}`);
		node_http.default.get(`http://127.0.0.1:${port}/health`, (res) => {
			let data = "";
			res.on("data", (chunk) => data += chunk);
			res.on("end", () => {
				console.log(`[Stub Backend] Ping response: ${data}`);
				win.webContents.send("backend-ready", {
					port,
					token
				});
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
		icon: node_path.default.join(process.env.VITE_PUBLIC, "electron-vite.svg"),
		webPreferences: { preload: node_path.default.join(__dirname, "preload.mjs") },
		width: 1200,
		height: 800
	});
	win.webContents.on("did-finish-load", () => {
		win?.webContents.send("main-process-message", (/* @__PURE__ */ new Date()).toLocaleString());
		spawnBackendStub(win);
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
