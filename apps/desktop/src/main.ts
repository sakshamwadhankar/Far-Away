import { app, BrowserWindow, Menu, dialog } from 'electron';
import path from 'node:path';
import http from 'node:http';
import crypto from 'node:crypto';

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
  
  const srv = net.createServer();
  srv.listen(0, '127.0.0.1', () => {
    const address = srv.address() as net.AddressInfo;
    const port = address.port;
    srv.close(() => {
      console.log(`[Backend] Starting Python backend on port ${port}...`);
      
      const isWin = process.platform === 'win32';
      const backendDir = app.isPackaged 
        ? path.join(process.resourcesPath, 'backend')
        : path.join(__dirname, '../../../backend');
      
      let backendProcess;

      if (app.isPackaged) {
        const backendExe = isWin
          ? path.join(backendDir, 'komvos_backend.exe')
          : path.join(backendDir, 'komvos_backend');
          
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

      backendProcess.stdout.on('data', (data) => console.log(`[Backend] ${data}`));
      backendProcess.stderr.on('data', (data) => console.error(`[Backend ERR] ${data}`));

      const checkHealth = () => {
        http.get(`http://127.0.0.1:${port}/health`, (res) => {
          if (res.statusCode === 200) {
            console.log(`[Backend] Ready on port ${port} with token ${token}`);
            win.webContents.send('backend-ready', { port, token });
          } else {
            setTimeout(checkHealth, 500);
          }
        }).on('error', () => {
          setTimeout(checkHealth, 500);
        });
      };

      
      setTimeout(checkHealth, 500);

      app.on('will-quit', () => {
        backendProcess.kill();
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
      preload: path.join(__dirname, 'preload.mjs'),
    },
    width: 1200,
    height: 800,
    autoHideMenuBar: true,
  });

  // Test active push message to Renderer-process.
  win.webContents.on('did-finish-load', () => {
    win?.webContents.send('main-process-message', (new Date).toLocaleString());
    spawnBackend(win!);
    checkOllama();
  });

  if (VITE_DEV_SERVER_URL) {
    win.loadURL(VITE_DEV_SERVER_URL);
  } else {
    win.loadFile(path.join(process.env.DIST as string, 'index.html'));
  }
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

