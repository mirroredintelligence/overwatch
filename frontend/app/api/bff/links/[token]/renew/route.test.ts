// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND_ROOT, LINK, TENANT_HOST } from '@/test/fixtures/links';
import { renewCsrfFor } from '@/lib/links/csrf';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { cookiesMock, requestWithCookies, resetCookieWrites } from '@/test/cookies';
import { resetLinkRequests, seenBackendRequests } from '@/test/msw/handlers/links';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const url = (token: string) => `https://${TENANT_HOST}/api/bff/links/${token}/renew`;
const ctx = (token: string) => ({ params: Promise.resolve({ token }) });

const renew = (token: string, header: string | null = renewCsrfFor(token), init: RequestInit = {}) =>
  requestWithCookies(url(token), {}, {
    method: 'POST',
    ...init,
    headers: { ...(init.headers as Record<string, string> | undefined), ...(header === null ? {} : { 'X-CSRF-Token': header }) },
  });

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  resetLinkRequests();
  resetCookieWrites();
  cookiesMock.mockClear();
});

describe('POST /api/bff/links/[token]/renew', () => {
  it('asks for a new link for an expired link, with no session and the renewal CSRF token, and answers accepted', async () => {
    const response = await POST(renew(LINK.expired), ctx(LINK.expired));
    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({ state: 'accepted' });
    const sent = seenBackendRequests.find((r) => r.method === 'POST');
    expect(sent?.host).toBe(TENANT_HOST);
  });

  it('passes a rate limit through with Retry-After, so the page can say to wait', async () => {
    const response = await POST(renew(LINK.limited), ctx(LINK.limited));
    expect(response.status).toBe(429);
    expect(response.headers.get('Retry-After')).toBe('600');
  });

  it('never sends a body to the back end, so nothing the caller sends can name a tenant', async () => {
    await POST(
      renew(LINK.expired, renewCsrfFor(LINK.expired), { body: JSON.stringify({ tenantId: 'x' }), headers: { 'Content-Type': 'application/json' } }),
      ctx(LINK.expired),
    );
    expect(seenBackendRequests.find((r) => r.method === 'POST')?.body).toBeUndefined();
  });
});

// KI-178: a renewal sends a text, so it is checked as an answer is.
describe('the CSRF check of a renewal', () => {
  it.each([
    ['no header', null],
    ['an empty header', ''],
    ['the token of another link', renewCsrfFor(LINK.used)],
    ['a guess', 'f'.repeat(64)],
    ['the token that answers a capacity link', 'csrf-ExpiredLinkTokenAbcdefgh'],
  ])('refuses %s with 403, before calling the back end', async (_name, header) => {
    const response = await POST(renew(LINK.expired, header), ctx(LINK.expired));
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ state: 'forbidden' });
    expect(seenBackendRequests).toHaveLength(0);
  });

  it('refuses a renewal when there is no secret to check it with', async () => {
    vi.stubEnv('SESSION_SECRET', '');
    const response = await POST(renew(LINK.expired, 'a'.repeat(64)), ctx(LINK.expired));
    expect(response.status).toBe(403);
    expect(seenBackendRequests).toHaveLength(0);
  });

  it('still answers 202 for a token that cannot be a link, with no back end call', async () => {
    const response = await POST(renew('x', null), ctx('not.a.link/../token'));
    expect(response.status).toBe(202);
    expect(seenBackendRequests).toHaveLength(0);
  });
});
