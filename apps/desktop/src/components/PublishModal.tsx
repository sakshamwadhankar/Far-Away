import { useState } from 'react';

interface PublishModalProps {
  initialName: string;
  onPublish: (name: string, description: string, author: string, tags: string) => void;
  onCancel: () => void;
}

export default function PublishModal({ initialName, onPublish, onCancel }: PublishModalProps) {
  const [name, setName] = useState(initialName || 'My Pipeline');
  const [description, setDescription] = useState('');
  const [author, setAuthor] = useState('');
  const [tags, setTags] = useState('');

  const canSubmit = name.trim().length > 0;

  return (
    <div
      id="publish-modal-overlay"
      style={{
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
        backgroundColor: 'rgba(0,0,0,0.45)',
        display: 'flex', justifyContent: 'center', alignItems: 'center',
        zIndex: 1000,
        backdropFilter: 'blur(4px)',
        animation: 'nf-fade-in 0.18s ease',
      }}
      onClick={(e) => { if ((e.target as HTMLElement).id === 'publish-modal-overlay') onCancel(); }}
    >
      <div style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-card)',
        padding: '28px 28px 24px',
        width: '420px',
        boxShadow: 'var(--shadow-lg)',
        color: 'var(--text)',
        animation: 'nf-fade-in 0.22s ease',
      }}>
        <h2 style={{
          marginTop: 0, marginBottom: '6px', fontSize: '17px',
          fontFamily: 'var(--font-ui)', fontWeight: 600, color: 'var(--text)',
        }}>
          📚 Publish to Library
        </h2>
        <p style={{
          fontSize: '12px', color: 'var(--text-3)', marginBottom: '20px', lineHeight: 1.5,
        }}>
          Share your pipeline so others can discover and use it.
        </p>

        {/* Name */}
        <div style={{ marginBottom: '14px' }}>
          <label className="nf-label">Pipeline Name *</label>
          <input
            id="publish-name"
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            className="nf-input"
            placeholder="e.g. RAG Pipeline"
          />
        </div>

        {/* Description */}
        <div style={{ marginBottom: '14px' }}>
          <label className="nf-label">Description</label>
          <textarea
            id="publish-description"
            value={description}
            onChange={e => setDescription(e.target.value)}
            className="nf-input"
            rows={3}
            placeholder="What does this pipeline do?"
            style={{ resize: 'vertical', minHeight: '64px' }}
          />
        </div>

        {/* Author */}
        <div style={{ marginBottom: '14px' }}>
          <label className="nf-label">Author</label>
          <input
            id="publish-author"
            type="text"
            value={author}
            onChange={e => setAuthor(e.target.value)}
            className="nf-input"
            placeholder="Your name (default: Anonymous)"
          />
        </div>

        {/* Tags */}
        <div style={{ marginBottom: '22px' }}>
          <label className="nf-label">Tags</label>
          <input
            id="publish-tags"
            type="text"
            value={tags}
            onChange={e => setTags(e.target.value)}
            className="nf-input nf-input--mono"
            placeholder="e.g. rag, chat, multi-agent"
          />
          <div style={{ fontSize: '10px', color: 'var(--text-3)', marginTop: '4px' }}>
            Comma-separated. Helps others find your template.
          </div>
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
          <button
            id="publish-cancel"
            onClick={onCancel}
            className="nf-pill-btn"
          >
            Cancel
          </button>
          <button
            id="publish-submit"
            onClick={() => onPublish(
              name.trim(),
              description.trim(),
              author.trim() || 'Anonymous',
              tags.trim(),
            )}
            disabled={!canSubmit}
            className="nf-pill-btn nf-pill-btn--highlight"
          >
            📤 Publish
          </button>
        </div>
      </div>
    </div>
  );
}
