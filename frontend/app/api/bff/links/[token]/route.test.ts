// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LINK_CSRF_COOKIE } from '@/lib/links/csrf';
import { BACKEND_ROOT, csrfFor, LINK, RECORDED_ANSWER, TENANT_HOST } from '@/test/fixtures/links';
import { cookieWrites, cookiesMock, lastWrite, requestWithCookies, resetCookieWrites } from '@/test/cookies';
import { resetLinkRequests, seenBackendRequests } from '@/test/msw/handlers/links';
import { server } from '@/test/msw/server';
import { GET, POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The link page's own API. No session: the token is the only thing that identifies the link.
const url = (token: string) => `https://${TENANT_HOST}/api/bff/links/${token}`;
const ctx = (token: string) => ({ params: Promise.resolve({ token }) });

function post(token: string, body: unknown, cookie: string | null, header: string | null) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json', Host: TENANT_HOST };
  if (header !== null) headers['X-CSRF-Token'] = header;
  const cookies = cookie === null ? {} : { [LINK_CSRF_COOKIE]: cookie };
  return requestWithCookies(url(token), cookies, {
    method: 'POST',
    headers,
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

beforeEach(() => {
  resetLinkRequests();
  resetCookieWrites();
  cookiesMock.mockClear();
});

describe('GET /api/bff/links/[token]', () => {
  it('answers without a session and sets the CSRF cookie for this link only', async () => {
    const response = await GET(requestWithCookies(url(LINK.recorded), {}), ctx(LINK.recorded));
    expect(response.status).toBe(200);
    const body = (await response.json()) as Record<string, unknown>;
    expect(body).toMatchObject({ state: 'ok', serviceName: 'UCR West', recordedValue: 3, csrfToken: csrfFor(LINK.recorded) });
    expect(lastWrite(LINK_CSRF_COOKIE)).toMatchObject({
      value: csrfFor(LINK.recorded),
      options: { httpOnly: true, sameSite: 'strict', path: `/api/bff/links/${LINK.recorded}` },
    });
    expect(response.headers.get('Cache-Control')).toBe('no-store');
  });

  it('sends the request’s host to the back end, and nothing a caller says about a tenant', async () => {
    await GET(requestWithCookies(url(LINK.recorded), {}), ctx(LINK.recorded));
    const last = seenBackendRequests.at(-1);
    expect(last?.host).toBe(TENANT_HOST);
  });

  it('answers an expired or used link with 410 and its state word only, and sets no cookie', async () => {
    const response = await GET(requestWithCookies(url(LINK.expired), {}), ctx(LINK.expired));
    expect(response.status).toBe(410);
    expect(await response.json()).toEqual({ state: 'expired' });
    expect(cookieWrites).toHaveLength(0);
  });

  it('answers a token that cannot be a link as gone, without calling the back end', async () => {
    const bad = 'not.a.link/../token';
    const response = await GET(requestWithCookies(url('x'), {}), ctx(bad));
    expect(response.status).toBe(410);
    expect(seenBackendRequests).toHaveLength(0);
  });

  it('answers a back end that cannot be reached with 503 and a fixed state, not a message', async () => {
    server.use(http.get(`${BACKEND_ROOT}/links/:token`, () => HttpResponse.error()));
    const response = await GET(requestWithCookies(url(LINK.recorded), {}), ctx(LINK.recorded));
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ state: 'unavailable' });
  });
});

describe('POST /api/bff/links/[token]', () => {
  it('refuses a post with no X-CSRF-Token header, before calling the back end', async () => {
    const response = await POST(post(LINK.recorded, { action: 'confirm' }, csrfFor(LINK.recorded), null), ctx(LINK.recorded));
    expect(response.status).toBe(403);
    expect(seenBackendRequests.filter((r) => r.method === 'POST')).toHaveLength(0);
  });

  it('refuses a header that is not the cookie for this link', async () => {
    const response = await POST(
      post(LINK.recorded, { action: 'confirm' }, csrfFor(LINK.recorded), 'wrong'),
      ctx(LINK.recorded),
    );
    expect(response.status).toBe(403);
    expect(seenBackendRequests.filter((r) => r.method === 'POST')).toHaveLength(0);
  });

  it('forwards a confirm with the header when the header matches the cookie', async () => {
    const token = csrfFor(LINK.recorded);
    const response = await POST(post(LINK.recorded, { action: 'confirm' }, token, token), ctx(LINK.recorded));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(RECORDED_ANSWER);
    const sent = seenBackendRequests.find((r) => r.method === 'POST');
    expect(sent?.body).toEqual({ action: 'confirm' });
    expect(sent?.host).toBe(TENANT_HOST);
  });

  it('forwards only the answer fields, so a tenant named in the body never reaches the back end', async () => {
    const token = csrfFor(LINK.recorded);
    await POST(
      post(LINK.recorded, { action: 'number', value: 4, tenantId: 'tenant-b', confirmOutOfRange: false, extra: 1 }, token, token),
      ctx(LINK.recorded),
    );
    expect(seenBackendRequests.find((r) => r.method === 'POST')?.body).toEqual({
      action: 'number',
      value: 4,
      confirmOutOfRange: false,
    });
  });

  it('refuses a body that is not a JSON object, without calling the back end', async () => {
    const token = csrfFor(LINK.recorded);
    const response = await POST(post(LINK.recorded, '{not json', token, token), ctx(LINK.recorded));
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ state: 'invalid' });
    expect(seenBackendRequests.filter((r) => r.method === 'POST')).toHaveLength(0);
  });

  it('passes the out-of-range answer through with the usual range, and the send-number answer with its reason', async () => {
    const token = csrfFor(LINK.recorded);
    const out = await POST(post(LINK.recorded, { action: 'number', value: 9 }, token, token), ctx(LINK.recorded));
    expect(out.status).toBe(422);
    expect(await out.json()).toEqual({ state: 'out-of-range', usualMin: 0, usualMax: 8 });

    const stale = await POST(post(LINK.stale, { action: 'confirm' }, csrfFor(LINK.stale), csrfFor(LINK.stale)), ctx(LINK.stale));
    expect(stale.status).toBe(409);
    expect(await stale.json()).toEqual({ state: 'send-number', reason: 'stale', message: 'Please send the number' });
  });

  it('passes a rate limit through with Retry-After', async () => {
    const token = csrfFor(LINK.limited);
    const response = await POST(post(LINK.limited, { action: 'confirm' }, token, token), ctx(LINK.limited));
    expect(response.status).toBe(429);
    expect(response.headers.get('Retry-After')).toBe('600');
    expect(await response.json()).toEqual({ state: 'rate-limited' });
  });
});
