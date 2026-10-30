import { defineConfig, devices } from '@playwright/test';
import { BACKEND_PORT, ENTRA_ENV, PORT_CHOSEN, SITE_PORT } from './e2e/support/env';

// One port per run (e2e/support/env.ts), so two runs on a machine never share a dev server.
const PORT = SITE_PORT;
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
        command: `pnpm dev --port ${PORT}`,
        url: `http://localhost:${PORT}`,
        // A dev server is reused only on a port the person chose (DIUCS_E2E_PORT), never on the
        // port derived for this run, where another run's server could be.
        reuseExistingServer: PORT_CHOSEN && !process.env.CI,
        // The page reads the board from a stand-in back end that global-setup starts.
        env: {
          DIUCS_FHIR_BASE_URL: `http://127.0.0.1:${BACKEND_PORT}/fhir`,
          // The staff sign-in talks to the fake Entra provider that global-setup starts (W09),
          // and the session secret the browser tests seal their cookies with.
          ...ENTRA_ENV,
        },
      },
});
