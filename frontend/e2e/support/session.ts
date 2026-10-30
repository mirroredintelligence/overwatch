import type { BrowserContext } from '@playwright/test';
import { EncryptJWT } from 'jose';
import { E2E_SESSION_SECRET, E2E_TENANT } from './env';

// Seals a BFF session cookie the way lib/auth/session.ts does (dir + A256GCM,
// the claims it reads). It does not import that module: Playwright cannot load
// it, because it imports `next/headers`. If the sealed format changes, these
// tests fail at sign-in, which is the signal to change this file too.

const SESSION_COOKIE = 'diucs_session';

export async function signIn(context: BrowserContext, baseURL: string, role: string, backendToken: string) {
  const expiresAt = new Date(Date.now() + 3_600_000);
  const value = await new EncryptJWT({
    role,
    tenantId: E2E_TENANT.id,
    host: new URL(baseURL).host,
    services: [],
    sub: 'e2e-screen',
    backendToken,
    expiresAt: expiresAt.toISOString(),
  })
    .setProtectedHeader({ alg: 'dir', enc: 'A256GCM' })
    .setIssuedAt()
    .setExpirationTime(Math.floor(expiresAt.getTime() / 1000))
    .encrypt(new Uint8Array(Buffer.from(E2E_SESSION_SECRET, 'base64')));
  await context.addCookies([{ name: SESSION_COOKIE, value, url: baseURL, httpOnly: true, sameSite: 'Strict' }]);
}
