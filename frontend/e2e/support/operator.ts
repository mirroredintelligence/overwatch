import { hkdfSync } from 'node:crypto';
import type { BrowserContext } from '@playwright/test';
import { EncryptJWT } from 'jose';
import { E2E_SESSION_SECRET } from './env';

// Seals an OPERATOR session cookie the way lib/operator/session.ts does: dir + A256GCM with a key derived from
// the session secret for this one purpose (so a tenant's session is no operator's), the claims it reads and
// no tenant. It does not import that module: Playwright cannot load it (it imports `next/headers`). If the
// sealed format changes, these tests fail at the first console page, which is the signal to change this too.

const OPERATOR_COOKIE = 'diucs_operator';

function key(): Uint8Array {
  const secret = new Uint8Array(Buffer.from(E2E_SESSION_SECRET, 'base64'));
  return new Uint8Array(hkdfSync('sha256', secret, 'diucs-operator-session', 'operator-session-v1', 32));
}

export async function signInOperator(context: BrowserContext, baseURL: string, role: 'platform-operator' | 'support', backendToken = 'e2e-operator-token') {
  const expiresAt = new Date(Date.now() + 3_600_000);
  const value = await new EncryptJWT({
    kind: 'operator',
    role,
    host: new URL(baseURL).host,
    accountRef: 'ops-e2e00000000000000000000000000001',
    backendToken,
    expiresAt: expiresAt.toISOString(),
  })
    .setProtectedHeader({ alg: 'dir', enc: 'A256GCM' })
    .setIssuedAt()
    .setExpirationTime(Math.floor(expiresAt.getTime() / 1000))
    .encrypt(key());
  await context.addCookies([{ name: OPERATOR_COOKIE, value, url: baseURL, httpOnly: true, sameSite: 'Strict' }]);
}
