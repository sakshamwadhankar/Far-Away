import React, { useEffect, useState } from 'react';
import Canvas from './canvas/Canvas';
import LeftSidebar from './panels/LeftSidebar';
import RightPanel from './panels/RightPanel';

export default function App() {
  const [backendPort, setBackendPort] = useState<number | null>(null);

  useEffect(() => {
    // Listen for backend info from Electron
    if (window.electron) {
      window.electron.onBackendReady((data: { port: number; token: string }) => {
        console.log('Backend is ready on port:', data.port, 'with token:', data.token);
        setBackendPort(data.port);
      });
    }
  }, []);

  return (
    <div style={{ display: 'flex', width: '100vw', height: '100vh' }}>
      <LeftSidebar backendPort={backendPort} />
      <div style={{ flex: 1, position: 'relative' }}>
        <Canvas />
      </div>
      <RightPanel />
    </div>
  );
}

// Ensure typescript knows about the global electron object from preload
declare global {
  interface Window {
    electron?: {
      onBackendReady: (callback: (data: { port: number; token: string }) => void) => void;
    };
  }
}
