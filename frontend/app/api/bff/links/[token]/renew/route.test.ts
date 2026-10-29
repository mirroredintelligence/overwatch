// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND_ROOT, LINK, TENANT_HOST } from '@/test/fixtures/links';
import { cookiesMock, requestWithCookies, resetCookieWrites } from '@/test/cookies';
import { resetLinkRequests, seenBackendRequests } from '@/test/msw/handlers/links';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const url = (token: string) => `https://${TENANT_HOST}/api/bff/links/${token}/renew`;
const ctx = (token: string) => ({ params: Promise.resolve({ token }) });

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetLinkRequests();
  resetCookieWrites();
  cookiesMock.mockClear();
});

describe('POST /api/bff/links/[token]/renew', () => {
  it('asks for a new link for an expired link, with no session and no CSRF cookie, and answers accepted', async () => {
    const response = await POST(requestWithCookies(url(LINK.expired), {}, { method: 'POST' }), ctx(LINK.expired));
    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({ state: 'accepted' });
    const sent = seenBackendRequests.find((r) => r.method === 'POST');
    expect(sent?.host).toBe(TENANT_HOST);
  });

  it('passes a rate limit through with Retry-After, so the page can say to wait', async () => {
    const response = await POST(requestWithCookies(url(LINK.limited), {}, { method: 'POST' }), ctx(LINK.limited));
    expect(response.status).toBe(429);
    expect(response.headers.get('Retry-After')).toBe('600');
  });

  it('never sends a body to the back end, so nothing the caller sends can name a tenant', async () => {
    await POST(
      requestWithCookies(url(LINK.expired), {}, { method: 'POST', body: JSON.stringify({ tenantId: 'x' }), headers: { 'Content-Type': 'application/json' } }),
      ctx(LINK.expired),
    );
    expect(seenBackendRequests.find((r) => r.method === 'POST')?.body).toBeUndefined();
  });
});
