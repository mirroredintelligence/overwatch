import {
  BACKEND_JWT_SECRET,
  CLIENT_ID,
  CLIENT_SECRET,
  DIRECTORY_A,
  DIRECTORY_B,
  DIRECTORY_PLATFORM,
  TENANT_A,
  TENANT_B,
  TENANT_PLATFORM,
} from '../../test/oidc/constants';

// Values shared by playwright.config.ts and the support files. Plain constants,
// so the config loads nothing heavy.
export const BACKEND_PORT = 4010;

// 32 bytes, base64. For the browser tests only; the dev server gets the same value.
export const E2E_SESSION_SECRET = Buffer.alloc(32, 9).toString('base64');

// The fake Entra provider for the staff sign-in tests (e2e/support/oidc.ts). It runs on 127.0.0.1
// and the site on localhost, so the browser sees them as two different sites, as it does for the
// real Microsoft login pages.
export const ENTRA_PORT = 4011;
export const ENTRA_HOST = `http://127.0.0.1:${ENTRA_PORT}`;
export const SITE_URL = 'http://localhost:3000';

// What the dev server is given for the staff sign-in. Two directories bound to two tenants, and the
// operator's own. Relative import: the config loads this file before the path aliases are known.
export const ENTRA_ENV = {
  ENTRA_CLIENT_ID: CLIENT_ID,
  ENTRA_CLIENT_SECRET: CLIENT_SECRET,
  ENTRA_AUTHORITY_HOST: ENTRA_HOST,
  DIUCS_PUBLIC_URL: SITE_URL,
  DIUCS_ENTRA_BINDINGS: JSON.stringify([
    { directoryId: DIRECTORY_A, tenantId: TENANT_A },
    { directoryId: DIRECTORY_B, tenantId: TENANT_B },
    { directoryId: DIRECTORY_PLATFORM, tenantId: TENANT_PLATFORM, platform: true },
  ]),
  BACKEND_JWT_SECRET,
  SESSION_SECRET: E2E_SESSION_SECRET,
};
