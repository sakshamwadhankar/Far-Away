import { app, BrowserWindow, Menu, dialog, shell } from 'electron';
import path from 'node:path';
import http from 'node:http';
import crypto from 'node:crypto';
import fs from 'node:fs';

// The built directory structure
process.env.DIST = path.join(__dirname, '../dist');
process.env.VITE_PUBLIC = app.isPackaged ? process.env.DIST : path.join(process.env.DIST, '../public');

let win: BrowserWindow | null;
const VITE_DEV_SERVER_URL = process.env['VITE_DEV_SERVER_URL'];

import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import net from 'node:net';

function checkOllama() {
  http.get('http://127.0.0.1:11434/', (res) => {
    if (res.statusCode !== 200) {
      showOllamaWarning();
    }
  }).on('error', () => {
    showOllamaWarning();
  });
}

function showOllamaWarning() {
  dialog.showMessageBox({
    type: 'info',
    title: 'Ollama Not Detected',
    message: "Ollama not detected — local models unavailable. Install from ollama.com and run 'ollama pull qwen2.5:3b'. Cloud models still work.",
    buttons: ['OK']
  });
}

function spawnBackend(win: BrowserWindow) {
  const token = crypto.randomUUID();
  const logFile = path.join(app.getPath('userData'), 'komvos_backend_spawn.log');

  const log = (msg: string) => {
    const line = `[${new Date().toISOString()}] ${msg}\n`;
    fs.appendFileSync(logFile, line);
    console.log(msg);
  };
  const logErr = (msg: string) => {
    const line = `[${new Date().toISOString()}] ERROR: ${msg}\n`;
    fs.appendFileSync(logFile, line);
    console.error(msg);
  };

  log(`--- New App Session ---`);
  log(`isPackaged: ${app.isPackaged}`);

  const srv = net.createServer();
  srv.listen(0, '127.0.0.1', () => {
    const address = srv.address() as net.AddressInfo;
    const port = address.port;
    srv.close(() => {
      log(`Starting Python backend on port ${port}...`);
      
      const isWin = process.platform === 'win32';
      const backendDir = app.isPackaged 
        ? path.join(process.resourcesPath, 'backend')
        : path.join(__dirname, '../../../backend');
      
      let backendProcess: ChildProcessWithoutNullStreams;

      if (app.isPackaged) {
        const backendExe = isWin
          ? path.join(backendDir, 'komvos_backend.exe')
          : path.join(backendDir, 'komvos_backend');
          
        log(`Resolved production backend path: ${backendExe}`);
        
        if (!fs.existsSync(backendExe)) {
          logErr(`Backend executable NOT FOUND at ${backendExe}`);
          dialog.showErrorBox("Backend Missing", `Could not find backend executable at:\n${backendExe}\n\nPlease check ${logFile} for details.`);
          return;
        }

        // A packaged app is never in dev mode. Strip the flag rather than
        // inheriting it, so a KOMVOS_DEV left exported in the user's shell
        // cannot widen CORS or expose /docs in a shipped build.
        const packagedEnv: NodeJS.ProcessEnv = {
          ...process.env,
          NEURALFLOW_SESSION_TOKEN: token,
        };
        delete packagedEnv.KOMVOS_DEV;

        backendProcess = spawn(
          backendExe,
          ['--host', '127.0.0.1', '--port', port.toString()],
          {
            cwd: backendDir,
            env: packagedEnv,
          }
        );
      } else {
        const venvPython = isWin
          ? path.join(backendDir, '.venv', 'Scripts', 'python.exe')
          : path.join(backendDir, '.venv', 'bin', 'python');
        
        log(`Resolved dev backend path: ${venvPython}`);

        backendProcess = spawn(
          venvPython,
          ['-m', 'uvicorn', 'komvos.api.main:app', '--host', '127.0.0.1', '--port', port.toString()],
          {
            cwd: backendDir,
            env: {
              ...process.env,
              NEURALFLOW_SESSION_TOKEN: token,
              // Unpackaged only. The renderer is served by the Vite dev server,
              // so the backend has to allow that origin through CORS — and
              // /docs is useful while developing. Never set for a packaged app.
              KOMVOS_DEV: '1',
            }
          }
        );
      }

      backendProcess.on('error', (err: Error) => {
        logErr(`Spawn error: ${err.message}`);
        dialog.showErrorBox("Backend Error", `Failed to spawn backend process:\n${err.message}\n\nPlease check ${logFile} for details.`);
      });

      backendProcess.stdout.on('data', (data: Buffer) => log(`[STDOUT] ${data.toString().trim()}`));
      backendProcess.stderr.on('data', (data: Buffer) => logErr(`[STDERR] ${data.toString().trim()}`));

      let isReady = false;
      const checkHealth = () => {
        if (isReady) return;
        http.get(`http://127.0.0.1:${port}/health`, (res) => {
          if (res.statusCode === 200) {
            isReady = true;
            log(`Ready on port ${port} with token ${token}`);
            
            // Now load the actual app UI
            if (VITE_DEV_SERVER_URL) {
              win.loadURL(VITE_DEV_SERVER_URL);
            } else {
              win.loadFile(path.join(process.env.DIST as string, 'index.html'));
            }

            win.webContents.once('did-finish-load', () => {
              win.webContents.send('backend-ready', { port, token });
            });
          } else {
            setTimeout(checkHealth, 500);
          }
        }).on('error', () => {
          setTimeout(checkHealth, 500);
        });
      };

      setTimeout(checkHealth, 500);

      app.on('will-quit', () => {
        if (backendProcess) {
          log(`Killing backend process...`);
          backendProcess.kill();
        }
      });
    });
  });
}

/**
 * Origins the app window is allowed to navigate to.
 *
 * Renderer-initiated navigation anywhere else is blocked: model output is
 * untrusted text, and a link in it must never be able to replace the app UI
 * with a remote page that shares the preload bridge.
 */
/**
 * Hand a URL to the user's default browser, but only for http(s).
 *
 * shell.openExternal will happily launch `file:`, `smb:` or a registered custom
 * protocol handler, so anything else from renderer-controlled content is
 * dropped rather than forwarded to the OS.
 */
function openExternally(rawUrl: string): void {
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    return;
  }
  if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
    void shell.openExternal(rawUrl);
  }
}

function isAllowedNavigation(rawUrl: string): boolean {
  // The splash screen the main process loads before the backend is ready.
  if (rawUrl.startsWith('data:text/html')) return true;

  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    return false;
  }

  // Packaged builds load the bundled renderer from disk.
  if (parsed.protocol === 'file:') return true;

  // Dev builds load it from the Vite dev server.
  if (VITE_DEV_SERVER_URL) {
    const devServer = new URL(VITE_DEV_SERVER_URL);
    if (parsed.origin === devServer.origin) return true;
  }

  return false;
}

function createWindow() {
  // Remove native menu bar (File / Edit / View / Window)
  Menu.setApplicationMenu(null);

  win = new BrowserWindow({
    icon: path.join(process.env.VITE_PUBLIC as string, 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      // These match Electron's current defaults. Stated explicitly so a future
      // Electron upgrade or a stray edit cannot silently weaken the renderer
      // sandbox. preload.ts uses only contextBridge/ipcRenderer, so it is
      // compatible with sandbox: true.
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
    width: 1200,
    height: 800,
    autoHideMenuBar: true,
  });

  // ── Navigation guards ────────────────────────────────────────────────────
  // Send external links to the user's real browser instead of opening an
  // unrestricted Electron window for them.
  win.webContents.setWindowOpenHandler(({ url }) => {
    openExternally(url);
    return { action: 'deny' };
  });

  win.webContents.on('will-navigate', (event, url) => {
    if (!isAllowedNavigation(url)) {
      event.preventDefault();
      openExternally(url);
    }
  });

  // Load a splash screen
  win.loadURL(`data:text/html;charset=utf-8,
    <html>
      <body style="background:#111;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;margin:0;">
        <h2>Starting backend...</h2>
      </body>
    </html>
  `);

  spawnBackend(win);
  checkOllama();
}

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
    win = null;
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

app.whenReady().then(createWindow);

