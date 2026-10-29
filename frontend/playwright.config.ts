import { defineConfig, devices } from '@playwright/test';
import { BACKEND_PORT, ENTRA_ENV } from './e2e/support/env';

const PORT = 3000;

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'pnpm dev',
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    // The page reads the board from a stand-in back end that global-setup starts.
    env: {
      DIUCS_FHIR_BASE_URL: `http://127.0.0.1:${BACKEND_PORT}/fhir`,
      // The staff sign-in talks to the fake Entra provider that global-setup starts (W09).
      ...ENTRA_ENV,
    },
  },
});
