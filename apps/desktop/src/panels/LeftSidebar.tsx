import React from 'react';

export default function LeftSidebar({ backendPort }: { backendPort: number | null }) {
  return (
    <div style={{ width: 250, borderRight: '1px solid #333', padding: 16, backgroundColor: '#252526' }}>
      <h3>Node Palette</h3>
      <p style={{ color: '#888', fontSize: '0.9em' }}>Drag nodes from here.</p>
      
      <div style={{ marginTop: 20 }}>
        <h4>Backend Status</h4>
        {backendPort ? (
          <span style={{ color: 'lightgreen' }}>Connected (Port {backendPort})</span>
        ) : (
          <span style={{ color: 'orange' }}>Connecting...</span>
        )}
      </div>
    </div>
  );
}
