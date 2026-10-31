// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER, csrfTokenFor } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { CASE_CLOSED } from '@/test/fixtures/backend-shapes';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

// The CSRF token issued to the sample session: bound to its person, tenant and host (TEN-046).
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const CSRF = await csrfTokenFor({ tenantId: 'trust-a', host: 'app.test', sub: 'advisor-1' }, 'N'.repeat(43));
const CLOSE_URL = `${BACKEND_BASE}/ServiceRequest/4821/$close`;
const seen: { body: unknown; key: string | null }[] = [];

function session(role: Role): Session {
  return {
    role,
    tenantId: 'trust-a',
    host: 'app.test',
    services: [],
    sub: 'advisor-1',
    backendToken: 'token-for-advisor',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

async function post(role: Role | null, body: unknown, csrf: string | null = CSRF): Promise<Response> {
  const cookies: Record<string, string> = { [CSRF_COOKIE]: CSRF };
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  const headers: Record<string, string> = { 'Content-Type': 'application/json', 'Idempotency-Key': 'key-0000003' };
  if (csrf !== null) headers[CSRF_HEADER] = csrf;
  return POST(
    requestWithCookies('https://app.test/api/bff/cases/4821/outcome', cookies, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    }),
    { params: Promise.resolve({ ref: '4821' }) },
  );
}

beforeEach(() => {
  seen.length = 0;
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  server.use(
    http.post(CLOSE_URL, async ({ request }) => {
      seen.push({ body: await request.clone().json(), key: request.headers.get('idempotency-key') });
      return HttpResponse.json(CASE_CLOSED);
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('POST /api/bff/cases/[ref]/outcome (W15)', () => {
  it('closes the case at the back end with the outcome as Parameters, and answers the close time the back end recorded (DEC-781)', async () => {
    const response = await post('advisor', {
      outcome: 'accepted-and-booked',
      destinationServiceId: 'svc-ucr-west',
      bestFitNotUsed: 'data-too-old',
    });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ closedAt: '2026-10-30T14:09:00Z' });
    expect(seen[0].body).toEqual({
      resourceType: 'Parameters',
      parameter: [
        { name: 'outcome', valueCode: 'accepted-and-booked' },
        { name: 'bestFitNotUsed', valueCode: 'data-too-old' },
        { name: 'destination', valueReference: { reference: 'HealthcareService/svc-ucr-west' } },
      ],
    });
    expect(seen[0].key).toBe('key-0000003');
  });

  it('answers 502 and not a made-up time when the back end answers a case that is not closed', async () => {
    server.use(http.post(CLOSE_URL, () => HttpResponse.json({ ...CASE_CLOSED, status: 'active' })));

    expect((await post('advisor', { outcome: 'declined' })).status).toBe(502);
  });

  it.each(['accepted-and-booked', 'redirected'])('refuses %s with no destination service, as the back end does, before any call', async (outcome) => {
    expect((await post('advisor', { outcome })).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it.each(['no-service-fits', 'out-of-area', 'declined', 'caller-cancelled'])(
    'accepts %s with no destination, and refuses one: the back end takes none for this outcome',
    async (outcome) => {
      expect((await post('advisor', { outcome })).status).toBe(200);
      expect((await post('advisor', { outcome, destinationServiceId: 'svc-ucr-west' })).status).toBe(400);
      expect(seen).toHaveLength(1);
    },
  );

  it('sends a redirect with its destination', async () => {
    await post('advisor', { outcome: 'redirected', destinationServiceId: 'svc-ucr-west' });

    expect(seen[0].body).toMatchObject({
      parameter: expect.arrayContaining([{ name: 'destination', valueReference: { reference: 'HealthcareService/svc-ucr-west' } }]),
    });
  });

  it('refuses an outcome or a reason that is not on the list, before any call', async () => {
    expect((await post('advisor', { outcome: 'deleted' })).status).toBe(400);
    expect((await post('advisor', { outcome: 'declined', bestFitNotUsed: 'bored' })).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('refuses a reporter, a lead and a request without CSRF', async () => {
    expect((await post('reporter', { outcome: 'declined' })).status).toBe(403);
    expect((await post('lead', { outcome: 'declined' })).status).toBe(403);
    expect((await post('advisor', { outcome: 'declined' }, null)).status).toBe(403);
    expect(seen).toHaveLength(0);
  });
});
