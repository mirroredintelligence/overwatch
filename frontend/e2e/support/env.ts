// Values shared by playwright.config.ts and the support files. Plain constants,
// so the config loads nothing heavy.
export const BACKEND_PORT = 4010;

// 32 bytes, base64. For the browser tests only; the dev server gets the same value.
export const E2E_SESSION_SECRET = Buffer.alloc(32, 9).toString('base64');
