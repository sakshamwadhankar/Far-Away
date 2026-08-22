import { useState } from 'react';

interface LicenseEntry {
  name: string;
  version?: string;
  license: string;
  author: string;
  description: string;
  attribution?: string;
  url?: string;
  licenseText?: string;
}

const LICENSES: LicenseEntry[] = [
  {
    name: 'Computer Server (CUA)',
    version: '0.1.25',
    license: 'Apache-2.0',
    author: 'CUA Contributors',
    description: 'Local loopback mechanical action layer for desktop interaction primitives.',
    url: 'https://github.com/cua-ai/computer-server',
    attribution: 'Includes components licensed under Apache License 2.0.',
  },
  {
    name: 'Dataset & Governance Specifications',
    license: 'CC-BY-4.0',
    author: 'Komvos Governance & Open Source Contributors',
    description: 'Domain specifications, safety benchmarks, and pipeline schema definitions.',
    url: 'https://creativecommons.org/licenses/by/4.0/',
    attribution: 'Licensed under Creative Commons Attribution 4.0 International (CC-BY-4.0). You are free to share and adapt this material with appropriate credit.',
  },
  {
    name: 'FastAPI',
    version: '0.115',
    license: 'MIT',
    author: 'Tiangolo & FastAPI Contributors',
    description: 'High-performance Python web framework for local execution API.',
    url: 'https://fastapi.tiangolo.com/',
  },
  {
    name: 'React',
    version: '18.3',
    license: 'MIT',
    author: 'Meta Platforms, Inc.',
    description: 'JavaScript library for building user interfaces.',
    url: 'https://react.dev/',
  },
  {
    name: 'React Flow',
    version: '11.11',
    license: 'MIT',
    author: 'webkid GmbH / xyflow',
    description: 'Customizable library for building interactive node-based UIs.',
    url: 'https://reactflow.dev/',
  },
  {
    name: 'Pydantic',
    version: '2.13',
    license: 'MIT',
    author: 'Samuel Colvin & Pydantic Contributors',
    description: 'Data validation and settings management using Python type annotations.',
    url: 'https://docs.pydantic.dev/',
  },
  {
    name: 'HTTPX',
    version: '0.28',
    license: 'BSD-3-Clause',
    author: 'Encode OSS Ltd.',
    description: 'Next-generation HTTP client for Python with async support.',
    url: 'https://www.python-httpx.org/',
  },
  {
    name: 'Lucide Icons',
    version: '0.470',
    license: 'ISC',
    author: 'Lucide Project Contributors',
    description: 'Beautiful & consistent icon toolkit for modern interfaces.',
    url: 'https://lucide.dev/',
  },
  {
    name: 'Uvicorn',
    version: '0.34',
    license: 'BSD-3-Clause',
    author: 'Encode OSS Ltd.',
    description: 'Lightning-fast ASGI web server implementation.',
    url: 'https://www.uvicorn.org/',
  },
];

interface LicensesModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function LicensesModal({ isOpen, onClose }: LicensesModalProps) {
  const [filter, setFilter] = useState('');

  if (!isOpen) return null;

  const filtered = LICENSES.filter(
    (item) =>
      item.name.toLowerCase().includes(filter.toLowerCase()) ||
      item.license.toLowerCase().includes(filter.toLowerCase()) ||
      item.description.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div
      className="nf-modal-backdrop"
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(15, 20, 15, 0.75)',
        backdropFilter: 'blur(4px)',
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px',
      }}
      onClick={onClose}
    >
      <div
        className="nf-modal"
        style={{
          background: '#FFFFFF',
          borderRadius: '12px',
          width: '100%',
          maxWidth: '720px',
          maxHeight: '85vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 20px 40px rgba(0,0,0,0.25)',
          overflow: 'hidden',
          border: '1px solid #E2E8F0',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          style={{
            padding: '20px 24px',
            borderBottom: '1px solid #E2E8F0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: '#F8FAFC',
          }}
        >
          <div>
            <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 600, color: '#0F172A' }}>
              Open Source Licences & Attributions
            </h2>
            <p style={{ margin: '4px 0 0', fontSize: '0.875rem', color: '#64748B' }}>
              Third-party software libraries, tools, and CC-BY-4.0 material used in this application.
            </p>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              fontSize: '1.25rem',
              cursor: 'pointer',
              color: '#64748B',
              padding: '4px 8px',
              borderRadius: '4px',
            }}
            title="Close modal"
          >
            ✕
          </button>
        </div>

        {/* Filter bar */}
        <div style={{ padding: '12px 24px', borderBottom: '1px solid #F1F5F9', background: '#FFFFFF' }}>
          <input
            type="text"
            placeholder="Search licenses or components..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{
              width: '100%',
              padding: '8px 12px',
              borderRadius: '6px',
              border: '1px solid #CBD5E1',
              fontSize: '0.875rem',
              outline: 'none',
            }}
          />
        </div>

        {/* Content list */}
        <div style={{ padding: '16px 24px', overflowY: 'auto', flex: 1 }}>
          {/* CC-BY-4.0 Highlight Card */}
          <div
            style={{
              marginBottom: '16px',
              padding: '14px 16px',
              background: '#F0FDF4',
              borderRadius: '8px',
              border: '1px solid #BBF7D0',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
              <span style={{ fontSize: '1rem', fontWeight: 600, color: '#166534' }}>
                Creative Commons Attribution 4.0 (CC-BY-4.0)
              </span>
              <span
                style={{
                  fontSize: '0.75rem',
                  padding: '2px 8px',
                  borderRadius: '12px',
                  background: '#DCFCE7',
                  color: '#15803D',
                  fontWeight: 600,
                }}
              >
                Required Attribution
              </span>
            </div>
            <p style={{ margin: 0, fontSize: '0.85rem', color: '#14532D', lineHeight: 1.5 }}>
              This product incorporates schema, capability specifications, and evaluation benchmarks licensed
              under the <strong>Creative Commons Attribution 4.0 International License (CC-BY-4.0)</strong>.
              Detailed terms are available at{' '}
              <a
                href="https://creativecommons.org/licenses/by/4.0/"
                target="_blank"
                rel="noreferrer"
                style={{ color: '#15803D', textDecoration: 'underline' }}
              >
                creativecommons.org/licenses/by/4.0
              </a>.
            </p>
          </div>

          {/* Components list */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {filtered.map((item) => (
              <div
                key={item.name}
                style={{
                  padding: '12px 16px',
                  borderRadius: '8px',
                  border: '1px solid #E2E8F0',
                  background: '#FFFFFF',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontWeight: 600, color: '#0F172A', fontSize: '0.95rem' }}>
                      {item.name}
                    </span>
                    {item.version && (
                      <span style={{ fontSize: '0.75rem', color: '#94A3B8' }}>
                        v{item.version}
                      </span>
                    )}
                  </div>
                  <span
                    style={{
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      padding: '2px 8px',
                      borderRadius: '4px',
                      background: '#F1F5F9',
                      color: '#475569',
                      border: '1px solid #CBD5E1',
                    }}
                  >
                    {item.license}
                  </span>
                </div>
                <p style={{ margin: '0 0 6px', fontSize: '0.85rem', color: '#475569' }}>
                  {item.description}
                </p>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.75rem', color: '#64748B' }}>
                  <span>{item.author}</span>
                  {item.url && (
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      style={{ color: '#2563EB', textDecoration: 'none' }}
                    >
                      Repository ↗
                    </a>
                  )}
                </div>
                {item.attribution && (
                  <p style={{ margin: '6px 0 0', fontSize: '0.75rem', color: '#059669', fontStyle: 'italic' }}>
                    {item.attribution}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '12px 24px',
            borderTop: '1px solid #E2E8F0',
            display: 'flex',
            justifyContent: 'flex-end',
            background: '#F8FAFC',
          }}
        >
          <button
            onClick={onClose}
            style={{
              padding: '8px 16px',
              borderRadius: '6px',
              background: '#0F172A',
              color: '#FFFFFF',
              border: 'none',
              fontWeight: 500,
              fontSize: '0.875rem',
              cursor: 'pointer',
            }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
