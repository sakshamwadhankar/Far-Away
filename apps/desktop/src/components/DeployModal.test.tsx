import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import DeployModal from './DeployModal';
import type { Pipeline } from '@shared/types';

const PIPELINE: Pipeline = {
  schema_version: '2.1',
  id: '00000000-0000-4000-a000-000000000dm1',
  name: 'Test Pipeline',
  version: '1.0.0',
  nodes: [
    { id: 'in', type: 'input', outputs: [{ name: 'prompt', type: 'text' }], inputs: [] },
    {
      id: 'bot',
      type: 'model',
      endpoint_ref: 'openai:gpt-4o-mini',
      inputs: [{ name: 'prompt', type: 'text' }],
      outputs: [{ name: 'reply', type: 'text' }],
    },
    { id: 'out', type: 'output', inputs: [{ name: 'result', type: 'text' }], outputs: [] },
    {
      id: 'gate-1',
      type: 'access',
      inputs: [],
      outputs: [],
      config: {
        access_policy: {
          providers: ['openai', 'anthropic'],
          allow_local_models: false,
          allow_network: false,
          allowed_domains: [],
          max_cost_usd: null,
          max_tokens: null,
        },
      },
    },
  ],
  edges: [
    { from: 'in.prompt', to: 'bot.prompt' },
    { from: 'bot.reply', to: 'out.result' },
    { from: 'gate-1.scope', to: 'bot.prompt' },
  ],
  endpoints: { 'openai:gpt-4o-mini': { kind: 'openai', model: 'gpt-4o-mini' } },
};

function mockFetchSequence(responses: Record<string, unknown>) {
  global.fetch = vi.fn().mockImplementation((url: string | URL | Request) => {
    const urlStr = typeof url === 'string' ? url : url.toString();
    for (const [pattern, body] of Object.entries(responses)) {
      if (urlStr.includes(pattern)) {
        return Promise.resolve({ ok: true, json: async () => body });
      }
    }
    return Promise.resolve({ ok: true, json: async () => ({}) });
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

describe('DeployModal — create mode', () => {
  it('renders the access policy summary from the pipeline', () => {
    mockFetchSequence({});
    render(
      <DeployModal
        pipeline={PIPELINE}
        backendToken="tok"
        API_BASE="http://127.0.0.1:8000"
        onClose={() => {}}
      />,
    );

    expect(screen.getByTestId('deploy-policy-openai')).toBeDefined();
    expect(screen.getByTestId('deploy-policy-anthropic')).toBeDefined();
  });

  it('does not show a deployment key before deploying', () => {
    mockFetchSequence({});
    render(
      <DeployModal
        pipeline={PIPELINE}
        backendToken="tok"
        API_BASE="http://127.0.0.1:8000"
        onClose={() => {}}
      />,
    );

    expect(screen.queryByTestId('deploy-key-value')).toBeNull();
  });

  it('shows the key exactly once, right after a successful deploy', async () => {
    mockFetchSequence({
      '/deployments': {
        deployment_id: 'dep-123',
        key: 'kv_shown_once_abc123',
        base_url: 'http://127.0.0.1:8000/v1',
        warning: 'shown once',
      },
    });

    render(
      <DeployModal
        pipeline={PIPELINE}
        backendToken="tok"
        API_BASE="http://127.0.0.1:8000"
        onClose={() => {}}
      />,
    );

    fireEvent.click(screen.getByTestId('deploy-submit'));

    const keyField = await screen.findByTestId('deploy-key-value');
    expect((keyField as HTMLInputElement).value).toBe('kv_shown_once_abc123');
    expect(screen.getByText(/shown only once/i)).toBeDefined();
  });

  it('copy button copies the key to the clipboard', async () => {
    mockFetchSequence({
      '/deployments': {
        deployment_id: 'dep-123',
        key: 'kv_copyme',
        base_url: 'http://127.0.0.1:8000/v1',
      },
    });

    render(
      <DeployModal
        pipeline={PIPELINE}
        backendToken="tok"
        API_BASE="http://127.0.0.1:8000"
        onClose={() => {}}
      />,
    );

    fireEvent.click(screen.getByTestId('deploy-submit'));
    await screen.findByTestId('deploy-key-value');

    fireEvent.click(screen.getByTestId('deploy-key-value-copy'));

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('kv_copyme');
  });

  it('LAN toggle requires an explicit confirmation before it takes effect', () => {
    mockFetchSequence({});
    render(
      <DeployModal
        pipeline={PIPELINE}
        backendToken="tok"
        API_BASE="http://127.0.0.1:8000"
        onClose={() => {}}
      />,
    );

    const lanCheckbox = screen.getByTestId('deploy-lan-toggle') as HTMLInputElement;
    expect(lanCheckbox.checked).toBe(false);

    fireEvent.click(lanCheckbox);

    // Checking the box does NOT immediately enable it — a confirmation
    // dialog naming the risk must appear first.
    expect(screen.getByTestId('deploy-lan-confirm')).toBeDefined();
    expect(lanCheckbox.checked).toBe(false);
  });

  it('canceling the LAN confirmation leaves LAN access off', () => {
    mockFetchSequence({});
    render(
      <DeployModal
        pipeline={PIPELINE}
        backendToken="tok"
        API_BASE="http://127.0.0.1:8000"
        onClose={() => {}}
      />,
    );

    fireEvent.click(screen.getByTestId('deploy-lan-toggle'));
    fireEvent.click(screen.getByTestId('deploy-lan-confirm-cancel'));

    expect(screen.queryByTestId('deploy-lan-confirm')).toBeNull();
    expect((screen.getByTestId('deploy-lan-toggle') as HTMLInputElement).checked).toBe(false);
  });

  it('accepting the LAN confirmation enables it', () => {
    mockFetchSequence({});
    render(
      <DeployModal
        pipeline={PIPELINE}
        backendToken="tok"
        API_BASE="http://127.0.0.1:8000"
        onClose={() => {}}
      />,
    );

    fireEvent.click(screen.getByTestId('deploy-lan-toggle'));
    fireEvent.click(screen.getByTestId('deploy-lan-confirm-accept'));

    expect(screen.queryByTestId('deploy-lan-confirm')).toBeNull();
    expect((screen.getByTestId('deploy-lan-toggle') as HTMLInputElement).checked).toBe(true);
  });

  it('deploy request carries the confirmed expose_lan flag', async () => {
    mockFetchSequence({
      '/deployments': {
        deployment_id: 'dep-123',
        key: 'kv_x',
        base_url: 'http://127.0.0.1:8000/v1',
      },
    });

    render(
      <DeployModal
        pipeline={PIPELINE}
        backendToken="tok"
        API_BASE="http://127.0.0.1:8000"
        onClose={() => {}}
      />,
    );

    fireEvent.click(screen.getByTestId('deploy-lan-toggle'));
    fireEvent.click(screen.getByTestId('deploy-lan-confirm-accept'));
    fireEvent.click(screen.getByTestId('deploy-submit'));

    await screen.findByTestId('deploy-key-value');

    const call = (global.fetch as ReturnType<typeof vi.fn>).mock.calls.find(
      (c: unknown[]) => typeof c[0] === 'string' && (c[0] as string).endsWith('/deployments'),
    );
    const body = JSON.parse((call![1] as RequestInit).body as string);
    expect(body.expose_lan).toBe(true);
  });

  it('disables Deploy when the pipeline has no access node', () => {
    mockFetchSequence({});
    const noGate: Pipeline = {
      ...PIPELINE,
      nodes: PIPELINE.nodes.filter((n) => n.type !== 'access'),
    };

    render(
      <DeployModal
        pipeline={noGate}
        backendToken="tok"
        API_BASE="http://127.0.0.1:8000"
        onClose={() => {}}
      />,
    );

    expect(screen.getByTestId('deploy-submit')).toHaveProperty('disabled', true);
    expect(screen.getByText(/cannot be deployed/i)).toBeDefined();
  });

  it('surfaces a deploy error from the backend', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'Access Required: add an access node.' }),
    }) as unknown as typeof fetch;

    render(
      <DeployModal
        pipeline={PIPELINE}
        backendToken="tok"
        API_BASE="http://127.0.0.1:8000"
        onClose={() => {}}
      />,
    );

    fireEvent.click(screen.getByTestId('deploy-submit'));

    expect(await screen.findByText(/Access Required/)).toBeDefined();
  });
});

describe('DeployModal — manage mode', () => {
  it('skips the create form and shows live status for an existing deployment', async () => {
    mockFetchSequence({
      '/deployments': {
        deployments: [
          {
            id: 'dep-existing',
            name: 'Existing',
            expose_lan: false,
            rate_limit_per_minute: 60,
            chat_input_node: 'in',
            chat_output_node: 'out',
            created_at: 1000,
            request_count: 7,
            error_count: 1,
            last_request_at: 2000,
          },
        ],
      },
    });

    render(
      <DeployModal
        pipeline={PIPELINE}
        existingDeploymentId="dep-existing"
        backendToken="tok"
        API_BASE="http://127.0.0.1:8000"
        onClose={() => {}}
      />,
    );

    expect(screen.queryByTestId('deploy-name')).toBeNull();
    expect(screen.queryByTestId('deploy-key-value')).toBeNull();

    const statusRow = await screen.findByTestId('deploy-status-row');
    expect(statusRow.textContent).toContain('7 requests served');
    expect(statusRow.textContent).toContain('1 errors');
  });

  it('rotate-key reveals a fresh one-time key', async () => {
    mockFetchSequence({
      '/rotate-key': { deployment_id: 'dep-existing', key: 'kv_freshly_rotated' },
      '/deployments': { deployments: [] },
    });

    render(
      <DeployModal
        pipeline={PIPELINE}
        existingDeploymentId="dep-existing"
        backendToken="tok"
        API_BASE="http://127.0.0.1:8000"
        onClose={() => {}}
      />,
    );

    fireEvent.click(screen.getByTestId('deploy-rotate'));

    const keyField = await screen.findByTestId('deploy-key-value');
    expect((keyField as HTMLInputElement).value).toBe('kv_freshly_rotated');
  });

  it('undeploy calls DELETE and closes the modal', async () => {
    const onClose = vi.fn();
    mockFetchSequence({ '/deployments': { deployments: [] } });

    render(
      <DeployModal
        pipeline={PIPELINE}
        existingDeploymentId="dep-existing"
        backendToken="tok"
        API_BASE="http://127.0.0.1:8000"
        onClose={onClose}
      />,
    );

    fireEvent.click(screen.getByTestId('deploy-undeploy'));

    await vi.waitFor(() => expect(onClose).toHaveBeenCalled());

    const deleteCall = (global.fetch as ReturnType<typeof vi.fn>).mock.calls.find(
      (call: unknown[]) => (call[1] as RequestInit | undefined)?.method === 'DELETE',
    );
    expect(deleteCall).toBeDefined();
  });
});
