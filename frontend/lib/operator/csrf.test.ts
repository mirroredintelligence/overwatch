// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, csrfTokenFor } from '@/lib/auth/csrf';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { checkOperatorCsrf, OPERATOR_CSRF_COOKIE, operatorCsrfTokenFor, verifyOperatorCsrfToken } from './csrf';

// The operator console's double-submit CSRF token: bound to the operator's session (account, host), made
// with a key of its own, in a cookie of its own, so a token of a tenant session is no operator token.

const NONCE = 'N'.repeat(43);
const SUBJECT = { host: 'console.example.test', sub: 'ops-0123456789abcdef0123456789abcdef' };

beforeEach(() => vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET));
afterEach(() => vi.unstubAllEnvs());

describe('the operator CSRF token', () => {
  it('has a cookie of its own', async () => {
    expect(OPERATOR_CSRF_COOKIE).not.toBe(CSRF_COOKIE);
  });

  it('verifies for the session it was made for and for no other account, host or nonce', async () => {
    const token = await operatorCsrfTokenFor(SUBJECT, NONCE);
    expect(await verifyOperatorCsrfToken(SUBJECT, token)).toBe(true);
    expect(await verifyOperatorCsrfToken({ ...SUBJECT, sub: 'ops-other' }, token)).toBe(false);
    expect(await verifyOperatorCsrfToken({ ...SUBJECT, host: 'other.example.test' }, token)).toBe(false);
    expect(await verifyOperatorCsrfToken(SUBJECT, `${'M'.repeat(43)}.${token.split('.')[1]}`)).toBe(false);
    expect(await verifyOperatorCsrfToken(SUBJECT, 'x')).toBe(false);
    expect(await verifyOperatorCsrfToken(SUBJECT, undefined)).toBe(false);
  });

  it('is not the token a tenant session is issued, even for the same subject and host', async () => {
    const tenantToken = await csrfTokenFor({ tenantId: 'trust-a', host: SUBJECT.host, sub: SUBJECT.sub }, NONCE);
    expect(await verifyOperatorCsrfToken(SUBJECT, tenantToken)).toBe(false);
    expect(await operatorCsrfTokenFor(SUBJECT, NONCE)).not.toBe(tenantToken);
  });

  it('is checked from the header and the operator cookie together', async () => {
    const token = await operatorCsrfTokenFor(SUBJECT, NONCE);
    const request = (header: string | null, cookie: string | null) =>
      new Request('https://console.example.test/x', {
        method: 'POST',
        headers: { ...(header === null ? {} : { 'X-CSRF-Token': header }), ...(cookie === null ? {} : { Cookie: `${OPERATOR_CSRF_COOKIE}=${cookie}` }) },
      });
    expect(await checkOperatorCsrf(request(token, token), SUBJECT)).toBe(true);
    expect(await checkOperatorCsrf(request(token, null), SUBJECT)).toBe(false);
    expect(await checkOperatorCsrf(request(null, token), SUBJECT)).toBe(false);
    expect(await checkOperatorCsrf(request(token, await operatorCsrfTokenFor(SUBJECT, 'M'.repeat(43))), SUBJECT)).toBe(false);
    // The tenant cookie name does not count.
    const wrongName = new Request('https://console.example.test/x', { method: 'POST', headers: { 'X-CSRF-Token': token, Cookie: `${CSRF_COOKIE}=${token}` } });
    expect(await checkOperatorCsrf(wrongName, SUBJECT)).toBe(false);
  });

  it('is a fault, never a pass, when the secret is missing', async () => {
    vi.stubEnv('SESSION_SECRET', '');
    await expect(verifyOperatorCsrfToken(SUBJECT, 'x')).rejects.toThrow('SESSION_SECRET');
  });
});
