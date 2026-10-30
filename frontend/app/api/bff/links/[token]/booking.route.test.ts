// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LINK_CSRF_COOKIE } from '@/lib/links/csrf';
import { BACKEND_ROOT, BOOKING_CHANGE_TOKEN, csrfFor, LINK, TENANT_HOST } from '@/test/fixtures/links';
import { cookieWrites, cookiesMock, lastWrite, requestWithCookies, resetCookieWrites } from '@/test/cookies';
import { resetLinkRequests, seenBackendRequests, seenBffPosts } from '@/test/msw/handlers/links';
import { GET, POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The booking purposes through the same BFF route as the capacity page (L02, W19).
const url = (token: string) => `https://${TENANT_HOST}/api/bff/links/${token}`;
const ctx = (token: string) => ({ params: Promise.resolve({ token }) });

function post(token: string, body: unknown, header: string | null) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json', Host: TENANT_HOST };
  if (header !== null) headers['X-CSRF-Token'] = header;
  return requestWithCookies(url(token), { [LINK_CSRF_COOKIE]: csrfFor(token) }, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetLinkRequests();
  resetCookieWrites();
  cookiesMock.mockClear();
});

describe('GET /api/bff/links/[token] for a booking request', () => {
  it('answers the booking view with its CSRF token and sets the cookie for this link only', async () => {
    const response = await GET(requestWithCookies(url(LINK.booking), {}), ctx(LINK.booking));
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({
      purpose: 'booking-request',
      reference: '4821',
      serviceName: 'UCR West',
      coordinationPhone: '0300 123 4567',
      csrfToken: csrfFor(LINK.booking),
    });
    expect(lastWrite(LINK_CSRF_COOKIE)).toMatchObject({ value: csrfFor(LINK.booking), options: { path: `/api/bff/links/${LINK.booking}` } });
  });

  it('answers a closed booking with 410 and the same word as any closed link, so the page does not say which it was', async () => {
    const response = await GET(requestWithCookies(url(LINK.bookingDeclined), {}), ctx(LINK.bookingDeclined));
    expect(response.status).toBe(410);
    expect(await response.json()).toEqual({ state: 'expired' });
    expect(cookieWrites).toHaveLength(0);
  });
});

describe('POST /api/bff/links/[token] for a booking answer', () => {
  it('forwards the decline reason to the back end and nothing else it is sent', async () => {
    const response = await POST(
      post(LINK.booking, { action: 'decline', reason: 'outside-criteria', tenantId: 'tenant-b' }, csrfFor(LINK.booking)),
      ctx(LINK.booking),
    );
    expect(response.status).toBe(200);
    expect(seenBackendRequests.at(-1)?.body).toEqual({ action: 'decline', reason: 'outside-criteria' });
    expect(await response.json()).toEqual({ bookingStatus: 'declined' });
  });

  it('returns the change token of a confirmed booking', async () => {
    const response = await POST(post(LINK.booking, { action: 'confirm' }, csrfFor(LINK.booking)), ctx(LINK.booking));
    expect(await response.json()).toEqual({ bookingStatus: 'confirmed', changeToken: BOOKING_CHANGE_TOKEN });
  });

  it('refuses a booking answer without the CSRF header and posts nothing to the back end', async () => {
    const response = await POST(post(LINK.booking, { action: 'confirm' }, null), ctx(LINK.booking));
    expect(response.status).toBe(403);
    expect(seenBffPosts).toHaveLength(0);
    expect(seenBackendRequests.filter((r) => r.method === 'POST')).toHaveLength(0);
  });
});
