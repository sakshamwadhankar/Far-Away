import { defineConfig, devices } from '@playwright/test';
import path from 'path';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    trace: 'on-first-retry',
    baseURL: 'http://localhost:5173',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      command: 'npm run dev',
      url: 'http://localhost:5173',
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000,
    },
    {
      // Start the FastAPI backend. Plain-browser runs use the same fallback
      // credentials as src/hooks/useBackend.ts (port 8000, token 'test-token'),
      // so the session token must be set — auth fails closed without one.
      command: 'cd ../../backend && python -m uvicorn komvos.api.main:app --port 8000',
      url: 'http://127.0.0.1:8000/health',
      env: {
        KOMVOS_ALLOW_MOCK_ENDPOINT: '1',
        KOMVOS_SESSION_TOKEN: 'test-token',
        // Unpackaged dev parity (see src/main.ts): allows the Vite dev server
        // origin through CORS. Auth remains fail-closed — the session token
        // above is still required on every request.
        KOMVOS_DEV: '1'
      },
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000,
    }
  ],
});
