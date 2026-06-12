import React, { useEffect, useState } from 'react';

interface OnboardingModalProps {
  backendPort: number | null;
  onLoadTemplate: (schema: any) => void;
}

export default function OnboardingModal({ backendPort, onLoadTemplate }: OnboardingModalProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [ollamaUp, setOllamaUp] = useState(false);
  const [templateToLoad, setTemplateToLoad] = useState<any>(null);

  useEffect(() => {
    const hasRun = typeof localStorage !== 'undefined' ? localStorage.getItem('neuralflow_first_run') : null;
    if (hasRun) return;

    if (!backendPort) return;

    // Check if Ollama is up
    fetch(`http://127.0.0.1:${backendPort}/health/ollama`)
      .then(r => r.json())
      .then(data => {
        if (data.status === 'ok') {
          setOllamaUp(true);
          // Also fetch templates to find the solver-verifier-judge one
          return fetch(`http://127.0.0.1:${backendPort}/pipelines/templates`, {
             headers: { 'Authorization': 'Bearer test-token' } // Or pass backendToken
          });
        }
      })
      .then(r => r?.json())
      .then(templates => {
        if (Array.isArray(templates)) {
          const solver = templates.find(t => t.name.toLowerCase().includes('solver, verifier'));
          if (solver) {
            setTemplateToLoad(solver);
            setIsOpen(true);
          }
        }
      })
      .catch(e => console.error('Onboarding error:', e));
  }, [backendPort]);

  const handleClose = () => {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem('neuralflow_first_run', '1');
    }
    setIsOpen(false);
  };

  const handleLoad = () => {
    if (templateToLoad) {
      onLoadTemplate(templateToLoad);
    }
    handleClose();
  };

  if (!isOpen) return null;

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      backgroundColor: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 1000
    }}>
      <div style={{
        backgroundColor: '#1e1e1e', padding: '32px', borderRadius: '8px',
        maxWidth: '500px', width: '100%', border: '1px solid #444',
        textAlign: 'center', color: 'white'
      }}>
        <h2 style={{ marginBottom: '16px', color: '#10b981' }}>Ollama Detected! 🎉</h2>
        <p style={{ marginBottom: '24px', lineHeight: '1.5' }}>
          Welcome to NeuralFlow! We detected a local Ollama instance running on your machine.
          You can run a multi-model verification loop locally, right now, in under 5 minutes.
        </p>
        <div style={{ display: 'flex', gap: '16px', justifyContent: 'center' }}>
          <button
            onClick={handleClose}
            style={{
              padding: '10px 20px', backgroundColor: '#444', color: 'white',
              border: 'none', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold'
            }}
          >
            Skip for now
          </button>
          <button
            onClick={handleLoad}
            style={{
              padding: '10px 20px', backgroundColor: '#3b82f6', color: 'white',
              border: 'none', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold'
            }}
          >
            Load & Run Solver-Verifier-Judge
          </button>
        </div>
      </div>
    </div>
  );
}
