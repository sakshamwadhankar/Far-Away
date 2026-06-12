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
      // Start the FastAPI backend
      command: 'cd ../../backend && .venv\\Scripts\\python.exe -m uvicorn neuralflow.api.main:app --port 8000',
      url: 'http://127.0.0.1:8000/health',
      env: {
        NEURALFLOW_ALLOW_MOCK_ENDPOINT: '1'
      },
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000,
    }
  ],
});
