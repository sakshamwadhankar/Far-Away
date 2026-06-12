import { app, BrowserWindow } from 'electron';
import path from 'node:path';
import http from 'node:http';
import crypto from 'node:crypto';

// The built directory structure
process.env.DIST = path.join(__dirname, '../dist');
process.env.VITE_PUBLIC = app.isPackaged ? process.env.DIST : path.join(process.env.DIST, '../public');

let win: BrowserWindow | null;
const VITE_DEV_SERVER_URL = process.env['VITE_DEV_SERVER_URL'];

function spawnBackendStub(win: BrowserWindow) {
  // Generate random token
  const token = crypto.randomUUID();
  
  // Create a minimal HTTP server to act as a stub for the FastAPI backend
  // This proves we can spawn a process, assign a port, and ping it.
  const server = http.createServer((req, res) => {
    if (req.url === '/health') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'ok', mocked: true }));
    } else {
      res.writeHead(404);
      res.end();
    }
  });

  server.listen(0, '127.0.0.1', () => {
    const address = server.address() as import('net').AddressInfo;
    const port = address.port;
    console.log(`[Stub Backend] Running on http://127.0.0.1:${port}`);
    console.log(`[Stub Backend] Token: ${token}`);
    
    // Simulate pinging it
    http.get(`http://127.0.0.1:${port}/health`, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        console.log(`[Stub Backend] Ping response: ${data}`);
        
        // Inform the renderer that the backend is ready
        win.webContents.send('backend-ready', { port, token });
      });
    }).on('error', (err) => {
      console.error(`[Stub Backend] Ping failed:`, err);
    });
  });

  // Keep reference so it closes with the app
  app.on('will-quit', () => {
    server.close();
  });
}

function createWindow() {
  win = new BrowserWindow({
    icon: path.join(process.env.VITE_PUBLIC as string, 'electron-vite.svg'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.mjs'),
    },
    width: 1200,
    height: 800,
  });

  // Test active push message to Renderer-process.
  win.webContents.on('did-finish-load', () => {
    win?.webContents.send('main-process-message', (new Date).toLocaleString());
    spawnBackendStub(win!);
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
