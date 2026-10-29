import { defineConfig, devices } from '@playwright/test';
import { BACKEND_PORT, ENTRA_ENV } from './e2e/support/env';

const PORT = 3000;
// The synthetic checks (O09) run against a deployed test environment, or the compose stack, named by
// SYNTHETIC_BASE_URL. When it is set, no dev server and no stand-in back end start here.
const SYNTHETIC_BASE_URL = process.env.SYNTHETIC_BASE_URL;
const SYNTHETIC = /@synthetic/;

export default defineConfig({
  testDir: './e2e',
  globalSetup: SYNTHETIC_BASE_URL ? undefined : './e2e/global-setup.ts',
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
      // Normal runs skip the synthetic checks: they need a deployed target, not the stand-in.
      name: 'chromium',
      grepInvert: SYNTHETIC,
      use: { ...devices['Desktop Chrome'] },
    },
    // Present only with a target, so a plain `pnpm e2e` never runs the synthetic checks.
    ...(SYNTHETIC_BASE_URL
      ? [
          {
            name: 'synthetic',
            grep: SYNTHETIC,
            use: { ...devices['Desktop Chrome'], baseURL: SYNTHETIC_BASE_URL },
          },
        ]
      : []),
  ],
  webServer: SYNTHETIC_BASE_URL
    ? undefined
    : {
        command: 'pnpm dev',
        url: `http://localhost:${PORT}`,
        reuseExistingServer: !process.env.CI,
        // The page reads the board from a stand-in back end that global-setup starts.
        env: {
          DIUCS_FHIR_BASE_URL: `http://127.0.0.1:${BACKEND_PORT}/fhir`,
          // The staff sign-in talks to the fake Entra provider that global-setup starts (W09),
          // and the session secret the browser tests seal their cookies with.
          ...ENTRA_ENV,
        },
      },
});
