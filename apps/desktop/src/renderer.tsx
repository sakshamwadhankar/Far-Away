import React from 'react';
import ReactDOM from 'react-dom/client';
import { ReactFlowProvider } from 'reactflow';
import App from './App';
import './index.css';
import 'reactflow/dist/style.css';

import { ToastProvider } from './contexts/ToastContext';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ToastProvider>
      <ReactFlowProvider>
        <App />
      </ReactFlowProvider>
    </ToastProvider>
  </React.StrictMode>,
);
