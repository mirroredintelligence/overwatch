import { CLIENT_ID, CLIENT_SECRET } from '../../test/oidc/constants';

// Values shared by playwright.config.ts and the support files. Plain constants,
// so the config loads nothing heavy.
//
// The three ports of a run (the site, the stand-in back end and the fake Entra provider) follow from
// one base port, so that two e2e runs on one machine (two builders, a builder and a verifier) never
// share a dev server or a stand-in. DIUCS_E2E_PORT names the base; when it is not set the first
// module that loads this file derives one from its process id and writes it to the environment,
// where the browser-test workers inherit it. Three ports are taken from the base: the site, the
// stand-in back end and the fake Entra provider.
const FIRST_PORT = 20000;
const RUN_SLOTS = 3300;
const PORT_NAMED = Boolean(process.env.DIUCS_E2E_PORT);
if (!PORT_NAMED) {
  process.env.DIUCS_E2E_PORT = String(FIRST_PORT + (process.pid % RUN_SLOTS) * 3);
}
export const SITE_PORT = Number(process.env.DIUCS_E2E_PORT);
export const BACKEND_PORT = SITE_PORT + 1;
// True when the person who runs the tests named the port, so a dev server already on it may be
// reused. A port derived here is this run's alone and nothing may be on it.
export const PORT_CHOSEN = PORT_NAMED;

// 32 bytes, base64. For the browser tests only; the dev server gets the same value.
export const E2E_SESSION_SECRET = Buffer.alloc(32, 9).toString('base64');

// The fake Entra provider for the staff sign-in tests (e2e/support/oidc.ts). It runs on 127.0.0.1
// and the site on localhost, so the browser sees them as two different sites, as it does for the
// real Microsoft login pages.
export const ENTRA_PORT = SITE_PORT + 2;
export const ENTRA_HOST = `http://127.0.0.1:${ENTRA_PORT}`;
export const SITE_URL = `http://localhost:${SITE_PORT}`;

// What the dev server is given for the staff sign-in: the provider and the app registration. Which
// directory a tenant has bound, and who may sign in as what, is the stand-in back end's answer to
// POST /auth/token (e2e/support/exchange.ts), as it is the real back end's (TEN-043). Relative
// import: the config loads this file before the path aliases are known.
export const ENTRA_ENV = {
  ENTRA_CLIENT_ID: CLIENT_ID,
  ENTRA_CLIENT_SECRET: CLIENT_SECRET,
  ENTRA_AUTHORITY_HOST: ENTRA_HOST,
  DIUCS_PUBLIC_URL: SITE_URL,
  SESSION_SECRET: E2E_SESSION_SECRET,
};
