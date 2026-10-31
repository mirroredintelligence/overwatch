// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { RECORDED_ANSWER } from '@/test/fixtures/links';
import { SecretConfigurationError, SecretNotFoundError } from './errors';

// The web tier takes its secrets from the vault (DEC-1304): every reader of `session-secret` awaits
// `getSecret`, reads nothing else, and a missing or unreadable secret is a fault (a thrown error, so a
// 5xx at the BFF seam), never "no session", "no match", "no cookie" or a pass. The vault is replaced
// here; the secret module has its own tests (secrets.test.ts).

const vault = vi.hoisted(() => ({ read: vi.fn<(name: string) => Promise<string>>() }));

vi.mock('@/lib/secrets', async (original) => ({
  ...(await original<typeof import('@/lib/secrets')>()),
  getSecret: (name: string) => vault.read(name),
  vaultConfigured: () => true,
}));
vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

import { checkCsrf, csrfTokenFor, verifyCsrfToken } from '@/lib/auth/csrf';
import { sealTransaction, unsealTransaction } from '@/lib/auth/flow';
import { sealSession, unsealSession, type Session } from '@/lib/auth/session';
import { sealThanks, unsealThanks } from '@/lib/links/thanks';
import { checkRenewCsrf, renewCsrfFor } from '@/lib/links/csrf';
import { checkOperatorCsrf, operatorCsrfTokenFor, verifyOperatorCsrfToken } from '@/lib/operator/csrf';
import { sealOperatorSession, unsealOperatorSession } from '@/lib/operator/session';
import { sealPending, unsealPending } from '@/lib/register/pending';
import { rememberPairing, pairingFrom } from '@/lib/screens/cookies';
import { requestWithCookies } from '@/test/cookies';
import { TENANTS } from '@/test/tenants';

const FUTURE = new Date(Date.now() + 3_600_000).toISOString();
const SESSION: Session = {
  role: 'advisor', services: [], tenantId: TENANTS.A.id, host: TENANTS.A.host, sub: 'user-1', backendToken: 'backend-token-sample', expiresAt: FUTURE,
};
const NONCE = 'N'.repeat(43);
const SUBJECT = { tenantId: TENANTS.A.id, host: TENANTS.A.host, sub: 'user-1' };
const OPERATOR_SUBJECT = { host: 'ops.example.test', sub: 'acct-1' };
const OPERATOR = { role: 'platform-operator' as const, host: 'ops.example.test', accountRef: 'acct-1', backendToken: 'op-token', expiresAt: FUTURE };
const LINK_TOKEN = 'LinkTokenAbcdefghijklmnopq';

beforeEach(() => {
  vault.read.mockReset();
  vault.read.mockImplementation(async (name) => {
    if (name === 'session-secret') return TEST_SESSION_SECRET;
    throw new SecretNotFoundError(name);
  });
});

describe('every reader of the session secret', () => {
  it('reads session-secret from the vault and nothing else', async () => {
    const operator = await sealOperatorSession(OPERATOR);
    const token = await csrfTokenFor(SUBJECT, NONCE);
    const sealed = await sealSession(SESSION);
    await unsealSession(sealed);
    await unsealOperatorSession(operator);
    await verifyCsrfToken(SUBJECT, token);
    await sealTransaction({ state: 's', nonce: 'n', verifier: 'v', next: '/', host: 'h' } as never, new Date());
    await sealThanks(RECORDED_ANSWER);
    await sealPending({ deviceId: 'D'.repeat(22), inviteToken: undefined });
    await renewCsrfFor(LINK_TOKEN);
    await operatorCsrfTokenFor(OPERATOR_SUBJECT, NONCE);
    const names = new Set(vault.read.mock.calls.map(([name]) => name));
    expect([...names]).toEqual(['session-secret']);
  });

  it('seals and unseals a session with the vault value', async () => {
    const sealed = await sealSession(SESSION);
    expect(await unsealSession(sealed)).toMatchObject({ sub: 'user-1' });
  });

  it('picks up a rotated secret: a session sealed with the old value is no session', async () => {
    const sealed = await sealSession(SESSION);
    vault.read.mockImplementation(async () => Buffer.alloc(32, 9).toString('base64'));
    expect(await unsealSession(sealed)).toBeNull();
  });
});

describe('a secret the vault cannot give is a fault, never a quiet "no"', () => {
  const missing = () => vault.read.mockImplementation(async (name) => { throw new SecretNotFoundError(name); });
  const unreadable = () => vault.read.mockImplementation(async (name) => { throw new SecretConfigurationError(`The secret ${name} could not be read.`); });
  const malformed = () => vault.read.mockImplementation(async () => 'too-short');

  const cases: [string, () => Promise<unknown>][] = [
    ['sealSession', () => sealSession(SESSION)],
    ['unsealSession (with a cookie)', () => unsealSession('anything')],
    ['unsealSession (with none)', () => unsealSession('')],
    ['csrfTokenFor', () => csrfTokenFor(SUBJECT, NONCE)],
    ['verifyCsrfToken', () => verifyCsrfToken(SUBJECT, 'x')],
    ['checkCsrf', () => checkCsrf(requestWithCookies('https://app.test/x', {}), SUBJECT)],
    ['sealTransaction', () => sealTransaction({} as never, new Date())],
    ['unsealTransaction (with a cookie)', () => unsealTransaction('anything', new Date())],
    ['unsealTransaction (with none)', () => unsealTransaction('', new Date())],
    ['sealThanks', () => sealThanks(RECORDED_ANSWER)],
    ['unsealThanks', () => unsealThanks('anything')],
    ['sealPending', () => sealPending({ deviceId: 'D'.repeat(22), inviteToken: undefined })],
    ['unsealPending', () => unsealPending('anything')],
    ['renewCsrfFor', () => renewCsrfFor(LINK_TOKEN)],
    ['checkRenewCsrf', () => checkRenewCsrf(requestWithCookies(`https://app.test/api/bff/links/${LINK_TOKEN}/renew`, {}, { method: 'POST', headers: { 'X-CSRF-Token': 'x' } }), LINK_TOKEN)],
    ['sealOperatorSession', () => sealOperatorSession(OPERATOR)],
    ['unsealOperatorSession', () => unsealOperatorSession('anything')],
    ['operatorCsrfTokenFor', () => operatorCsrfTokenFor(OPERATOR_SUBJECT, NONCE)],
    ['verifyOperatorCsrfToken', () => verifyOperatorCsrfToken(OPERATOR_SUBJECT, 'x')],
    ['checkOperatorCsrf', () => checkOperatorCsrf(requestWithCookies('https://ops.test/x', {}), OPERATOR_SUBJECT)],
    ['rememberPairing', () => rememberPairing({ pairingId: 'p-1', screenSecret: 'secret-value' })],
    ['pairingFrom', () => pairingFrom(requestWithCookies('https://app.test/x', { diucs_pairing: 'anything' }))],
  ];

  describe.each([['missing', missing], ['unreadable', unreadable], ['malformed', malformed]] as const)('when the secret is %s', (_kind, arrange) => {
    it.each(cases)('%s throws', async (_name, call) => {
      arrange();
      await expect(call()).rejects.toThrow();
    });
  });

  it('keeps the value of a malformed secret out of the message', async () => {
    malformed();
    const error = await sealSession(SESSION).catch((e: unknown) => e);
    expect((error as Error).message).not.toContain('too-short');
    expect((error as Error).message).toMatch(/session-secret/);
  });
});
