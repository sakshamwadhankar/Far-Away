import { useState, useEffect } from 'react';
import { migratedRead, writeMigratedKey } from '../utils/localStorage';

// Renamed during the NeuralFlow -> Komvos rebrand; the old key is migrated on
// first read so existing users are not shown the tour again.
const LEGACY_TOUR_KEY = 'neuralflow_tour_completed';
const TOUR_KEY = 'komvos_tour_completed';

const STEPS = [
  {
    target: '[data-tour="palette"]',
    title: 'Node Palette',
    content: 'This is the node palette. Drag nodes from here onto the canvas to start building your pipeline.',
    position: 'right'
  },
  {
    target: '[data-tour="canvas"]',
    title: 'The Canvas',
    content: 'This is the canvas area. Drop nodes here and connect them by dragging from their output ports to input ports. Or load a template to see an example.',
    position: 'center'
  },
  {
    target: '[data-tour="mode-switch"]',
    title: 'Modes: Edit vs Use',
    content: 'When your pipeline is ready, switch to "Use" mode to chat with it. Ensure your pipeline has exactly one input node and one output node.',
    position: 'bottom'
  }
];

export default function Tour() {
  const [currentStep, setCurrentStep] = useState(0);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const hasLocalStorage = typeof window !== 'undefined' && window.localStorage;
    // No storage at all -> treat as completed (original behaviour: hide).
    const completed = hasLocalStorage ? migratedRead(LEGACY_TOUR_KEY, TOUR_KEY) : 'true';
    if (completed !== 'true') {
      // Delay showing the tour slightly to allow the app to render
      const timer = setTimeout(() => setVisible(true), 500);
      return () => clearTimeout(timer);
    }
  }, []);

  const handleDismiss = () => {
    setVisible(false);
    if (typeof window !== 'undefined' && window.localStorage) {
      writeMigratedKey(TOUR_KEY, 'true');
    }
  };

  const handleNext = () => {
    if (currentStep < STEPS.length - 1) {
      setCurrentStep(currentStep + 1);
    } else {
      handleDismiss();
    }
  };

  if (!visible) return null;

  const step = STEPS[currentStep];
  
  // Find the target element to position the coachmark near it
  const el = document.querySelector(step.target);
  const style: React.CSSProperties = {
    position: 'fixed',
    zIndex: 9999,
    backgroundColor: '#3b82f6',
    color: '#fff',
    padding: '16px',
    borderRadius: '8px',
    boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
    width: '300px',
  };

  if (el && step.position !== 'center') {
    const rect = el.getBoundingClientRect();
    if (step.position === 'right') {
      style.top = rect.top + 20;
      style.left = rect.right + 20;
    } else if (step.position === 'bottom') {
      style.top = rect.bottom + 20;
      style.left = rect.left;
    }
  } else {
    // Center fallback
    style.top = '50%';
    style.left = '50%';
    style.transform = 'translate(-50%, -50%)';
  }

  return (
    <>
      <div style={{
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
        backgroundColor: 'rgba(0,0,0,0.3)', zIndex: 9998
      }} />
      <div style={style}>
        <h3 style={{ marginTop: 0, marginBottom: '8px', fontSize: '16px' }}>{step.title}</h3>
        <p style={{ margin: '0 0 16px 0', fontSize: '14px', lineHeight: '1.4' }}>{step.content}</p>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: '12px', opacity: 0.8 }}>Step {currentStep + 1} of {STEPS.length}</span>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button onClick={handleDismiss} style={{ background: 'transparent', border: '1px solid rgba(255,255,255,0.5)', color: '#fff', padding: '4px 8px', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}>Skip</button>
            <button onClick={handleNext} style={{ background: '#fff', border: 'none', color: '#3b82f6', padding: '4px 12px', borderRadius: '4px', cursor: 'pointer', fontSize: '12px', fontWeight: 'bold' }}>
              {currentStep < STEPS.length - 1 ? 'Next' : 'Got it'}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
