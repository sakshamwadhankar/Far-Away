import { app, BrowserWindow, Menu, dialog } from 'electron';
import path from 'node:path';
import http from 'node:http';
import crypto from 'node:crypto';
import fs from 'node:fs';

// The built directory structure
process.env.DIST = path.join(__dirname, '../dist');
process.env.VITE_PUBLIC = app.isPackaged ? process.env.DIST : path.join(process.env.DIST, '../public');

let win: BrowserWindow | null;
const VITE_DEV_SERVER_URL = process.env['VITE_DEV_SERVER_URL'];

import { spawn } from 'node:child_process';
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
      
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let backendProcess: any;

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

        backendProcess = spawn(
          backendExe,
          ['--host', '127.0.0.1', '--port', port.toString()],
          {
            cwd: backendDir,
            env: {
              ...process.env,
              NEURALFLOW_SESSION_TOKEN: token,
            }
          }
        );
      } else {
        const venvPython = isWin
          ? path.join(backendDir, '.venv', 'Scripts', 'python.exe')
          : path.join(backendDir, '.venv', 'bin', 'python');
        
        log(`Resolved dev backend path: ${venvPython}`);

        backendProcess = spawn(
          venvPython,
          ['-m', 'uvicorn', 'neuralflow.api.main:app', '--host', '127.0.0.1', '--port', port.toString()],
          {
            cwd: backendDir,
            env: {
              ...process.env,
              NEURALFLOW_SESSION_TOKEN: token,
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

function createWindow() {
  // Remove native menu bar (File / Edit / View / Window)
  Menu.setApplicationMenu(null);

  win = new BrowserWindow({
    icon: path.join(process.env.VITE_PUBLIC as string, 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
    },
    width: 1200,
    height: 800,
    autoHideMenuBar: true,
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

