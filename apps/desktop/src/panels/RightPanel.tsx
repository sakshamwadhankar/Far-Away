import { PipelineNodeData } from '../canvas/nodes/PipelineNode';
import { Node as RFNode } from 'reactflow';

interface RightPanelProps {
  selectedNode: RFNode<PipelineNodeData> | null;
  updateNodeData: (id: string, newData: Partial<PipelineNodeData>) => void;
}

export default function RightPanel({ selectedNode, updateNodeData }: RightPanelProps) {
  if (!selectedNode) {
    return (
      <div style={{ width: 300, borderLeft: '1px solid #333', padding: 16, backgroundColor: '#252526' }}>
        <h3>Configuration</h3>
        <p style={{ color: '#888', fontSize: '0.9em' }}>Select a node to view properties.</p>
      </div>
    );
  }

  const { data } = selectedNode;
  const config = data.config || {};

  const handleConfigChange = (key: string, value: string | number) => {
    updateNodeData(selectedNode.id, { config: { ...config, [key]: value } });
  };

  const handleBaseChange = (key: string, value: string) => {
    updateNodeData(selectedNode.id, { [key]: value });
  };

  return (
    <div style={{ width: 300, borderLeft: '1px solid #333', padding: 16, backgroundColor: '#252526', display: 'flex', flexDirection: 'column', gap: '16px', overflowY: 'auto' }}>
      <h3>Configuration</h3>
      
      <div>
        <label style={{ display: 'block', fontSize: '12px', color: '#aaa', marginBottom: '4px' }}>Node ID</label>
        <input type="text" value={selectedNode.id} disabled style={{ width: '100%', padding: '6px', background: '#1e1e1e', border: '1px solid #444', color: '#fff', borderRadius: '4px' }} />
      </div>

      <div>
        <label style={{ display: 'block', fontSize: '12px', color: '#aaa', marginBottom: '4px' }}>Type</label>
        <input type="text" value={data.type} disabled style={{ width: '100%', padding: '6px', background: '#1e1e1e', border: '1px solid #444', color: '#fff', borderRadius: '4px' }} />
      </div>

      <div>
        <label style={{ display: 'block', fontSize: '12px', color: '#aaa', marginBottom: '4px' }}>Role</label>
        <input type="text" value={data.role || ''} onChange={(e) => handleBaseChange('role', e.target.value)} style={{ width: '100%', padding: '6px', background: '#1e1e1e', border: '1px solid #555', color: '#fff', borderRadius: '4px' }} />
      </div>

      {data.type === 'model' && (
        <>
          <div>
            <label style={{ display: 'block', fontSize: '12px', color: '#aaa', marginBottom: '4px' }}>Endpoint Ref</label>
            <input type="text" value={data.endpoint_ref || ''} onChange={(e) => handleBaseChange('endpoint_ref', e.target.value)} placeholder="e.g. ep_mock" style={{ width: '100%', padding: '6px', background: '#1e1e1e', border: '1px solid #555', color: '#fff', borderRadius: '4px' }} />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '12px', color: '#aaa', marginBottom: '4px' }}>System Prompt</label>
            <textarea rows={4} value={config.system_prompt || ''} onChange={(e) => handleConfigChange('system_prompt', e.target.value)} style={{ width: '100%', padding: '6px', background: '#1e1e1e', border: '1px solid #555', color: '#fff', borderRadius: '4px', resize: 'vertical' }} />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '12px', color: '#aaa', marginBottom: '4px' }}>Temperature ({config.temperature ?? 0.7})</label>
            <input type="range" min="0" max="2" step="0.1" value={config.temperature ?? 0.7} onChange={(e) => handleConfigChange('temperature', parseFloat(e.target.value))} style={{ width: '100%' }} />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '12px', color: '#aaa', marginBottom: '4px' }}>Max Tokens</label>
            <input type="number" min="1" value={config.max_tokens ?? 2048} onChange={(e) => handleConfigChange('max_tokens', parseInt(e.target.value, 10))} style={{ width: '100%', padding: '6px', background: '#1e1e1e', border: '1px solid #555', color: '#fff', borderRadius: '4px' }} />
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '12px', color: '#aaa', marginBottom: '4px' }}>Response Format</label>
            <select value={config.response_format || 'text'} onChange={(e) => handleConfigChange('response_format', e.target.value)} style={{ width: '100%', padding: '6px', background: '#1e1e1e', border: '1px solid #555', color: '#fff', borderRadius: '4px' }}>
              <option value="text">Text</option>
              <option value="json">JSON</option>
            </select>
          </div>
        </>
      )}
    </div>
  );
}
