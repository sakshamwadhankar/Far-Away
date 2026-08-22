import { app, BrowserWindow, Menu, dialog, shell, ipcMain, protocol, net as electronNet } from 'electron';
import path from 'node:path';
import http from 'node:http';
import crypto from 'node:crypto';
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';

// The built directory structure
process.env.DIST = path.join(__dirname, '../dist');
process.env.VITE_PUBLIC = app.isPackaged ? process.env.DIST : path.join(process.env.DIST, '../public');

let win: BrowserWindow | null;
const VITE_DEV_SERVER_URL = process.env['VITE_DEV_SERVER_URL'];

// Must run before app ready: marks "komvos" as a standard, secure scheme so
// pages served through it get a real origin (komvos://bundle) instead of the
// opaque "null" origin a file:// load produces. The backend CORS allowlist
// admits this origin; it cannot be forged by web content.
const APP_PROTOCOL = 'komvos';
const APP_ORIGIN = `${APP_PROTOCOL}://bundle`;
protocol.registerSchemesAsPrivileged([
  { scheme: APP_PROTOCOL, privileges: { standard: true, secure: true, supportFetchAPI: true } },
]);

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

  // The renderer surfaces this path when the backend never becomes ready.
  ipcMain.handle('backend-log-path', () => logFile);

  // Size-based rotation: the active file caps at 5 MB; up to 3 older
  // generations are kept as komvos_backend_spawn.log.1..3 so nothing the
  // error path points users at is lost, while the install cannot grow the
  // log without bound.
  const LOG_MAX_BYTES = 5 * 1024 * 1024;
  const LOG_RETAINED_FILES = 3;

  let logChain: Promise<void> = Promise.resolve();

  const rotateIfNeeded = (): Promise<void> =>
    new Promise((resolve) => {
      fs.stat(logFile, (err, stats) => {
        if (err || !stats || stats.size < LOG_MAX_BYTES) return resolve();
        const shift = (i: number): void => {
          if (i <= 0) return resolve();
          const from = i === 1 ? logFile : `${logFile}.${i - 1}`;
          const to = `${logFile}.${i}`;
          fs.access(from, fs.constants.F_OK, (accessErr) => {
            if (accessErr) return shift(i - 1);
            fs.rename(from, to, () => shift(i - 1));
          });
        };
        shift(LOG_RETAINED_FILES);
      });
    });

  const enqueueLogLine = (line: string): void => {
    // Writes are serialized through a promise chain and use async fs calls,
    // so streaming a chatty run never blocks the main process on disk I/O.
    logChain = logChain
      .then(rotateIfNeeded)
      .then(
        () =>
          new Promise<void>((resolve) => {
            fs.appendFile(logFile, line, () => resolve());
          })
      )
      .catch(() => {});
  };

  const log = (msg: string) => {
    console.log(msg);
    enqueueLogLine(`[${new Date().toISOString()}] ${msg}\n`);
  };
  const logErr = (msg: string) => {
    console.error(msg);
    enqueueLogLine(`[${new Date().toISOString()}] ERROR: ${msg}\n`);
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
          KOMVOS_SESSION_TOKEN: token,
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
              KOMVOS_SESSION_TOKEN: token,
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
              // Packaged builds load from the app protocol so the renderer has
              // a real, non-forgeable origin (komvos://bundle) that the backend
              // CORS allowlist can admit — a file:// window would send the
              // opaque origin "null", which every sandboxed iframe on the web
              // also sends.
              void win.loadURL(`${APP_ORIGIN}/index.html`);
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

  // Packaged builds load the bundled renderer from the app protocol. Only the
  // bundle host is allowed — other komvos:// hosts are not ours.
  if (parsed.protocol === `${APP_PROTOCOL}:`) {
    return parsed.origin === APP_ORIGIN;
  }

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

app.whenReady().then(() => {
  // Serve the built renderer over the app protocol. komvos://bundle/<path>
  // maps to files under DIST; requests that escape the dist root (path
  // traversal) are refused.
  //
  // Production CSP: served as a header so it applies to every document from
  // this origin and cannot be stripped from the HTML. The index.html <meta>
  // copy is looser only where the Vite dev server requires it; in packaged
  // builds both policies apply and this stricter one wins. Inline STYLE is
  // required (the entire UI uses style attributes); Google Fonts origins are
  // allowed because index.css imports them — both are documented loosening.
  const PROD_CSP = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com data:",
    "img-src 'self' data: blob:",
    "connect-src http://127.0.0.1:* ws://127.0.0.1:*",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
  ].join('; ');

  protocol.handle(APP_PROTOCOL, async (request) => {
    try {
      const { pathname } = new URL(request.url);
      const rel = decodeURIComponent(pathname).replace(/^\/+/, '') || 'index.html';
      const dist = process.env.DIST as string;
      const resolved = path.resolve(dist, rel);
      if (resolved !== dist && !resolved.startsWith(dist + path.sep)) {
        return new Response('forbidden', { status: 403 });
      }
      const response = await electronNet.fetch(pathToFileURL(resolved).toString());
      const headers = new Headers(response.headers);
      headers.set('Content-Security-Policy', PROD_CSP);
      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers,
      });
    } catch {
      return new Response('not found', { status: 404 });
    }
  });
  createWindow();
});

