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
  it('has a cookie of its own', () => {
    expect(OPERATOR_CSRF_COOKIE).not.toBe(CSRF_COOKIE);
  });

  it('verifies for the session it was made for and for no other account, host or nonce', () => {
    const token = operatorCsrfTokenFor(SUBJECT, NONCE);
    expect(verifyOperatorCsrfToken(SUBJECT, token)).toBe(true);
    expect(verifyOperatorCsrfToken({ ...SUBJECT, sub: 'ops-other' }, token)).toBe(false);
    expect(verifyOperatorCsrfToken({ ...SUBJECT, host: 'other.example.test' }, token)).toBe(false);
    expect(verifyOperatorCsrfToken(SUBJECT, `${'M'.repeat(43)}.${token.split('.')[1]}`)).toBe(false);
    expect(verifyOperatorCsrfToken(SUBJECT, 'x')).toBe(false);
    expect(verifyOperatorCsrfToken(SUBJECT, undefined)).toBe(false);
  });

  it('is not the token a tenant session is issued, even for the same subject and host', () => {
    const tenantToken = csrfTokenFor({ tenantId: 'trust-a', host: SUBJECT.host, sub: SUBJECT.sub }, NONCE);
    expect(verifyOperatorCsrfToken(SUBJECT, tenantToken)).toBe(false);
    expect(operatorCsrfTokenFor(SUBJECT, NONCE)).not.toBe(tenantToken);
  });

  it('is checked from the header and the operator cookie together', () => {
    const token = operatorCsrfTokenFor(SUBJECT, NONCE);
    const request = (header: string | null, cookie: string | null) =>
      new Request('https://console.example.test/x', {
        method: 'POST',
        headers: { ...(header === null ? {} : { 'X-CSRF-Token': header }), ...(cookie === null ? {} : { Cookie: `${OPERATOR_CSRF_COOKIE}=${cookie}` }) },
      });
    expect(checkOperatorCsrf(request(token, token), SUBJECT)).toBe(true);
    expect(checkOperatorCsrf(request(token, null), SUBJECT)).toBe(false);
    expect(checkOperatorCsrf(request(null, token), SUBJECT)).toBe(false);
    expect(checkOperatorCsrf(request(token, operatorCsrfTokenFor(SUBJECT, 'M'.repeat(43))), SUBJECT)).toBe(false);
    // The tenant cookie name does not count.
    const wrongName = new Request('https://console.example.test/x', { method: 'POST', headers: { 'X-CSRF-Token': token, Cookie: `${CSRF_COOKIE}=${token}` } });
    expect(checkOperatorCsrf(wrongName, SUBJECT)).toBe(false);
  });

  it('is a fault, never a pass, when the secret is missing', () => {
    vi.stubEnv('SESSION_SECRET', '');
    expect(() => verifyOperatorCsrfToken(SUBJECT, 'x')).toThrow('SESSION_SECRET');
  });
});
