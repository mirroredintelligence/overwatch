// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const CSRF = 'csrf-token-for-tests-only-0000000000000000000';
const CLOSE_URL = `${BACKEND_BASE}/ServiceRequest/4821/$close`;
const seen: { body: unknown; key: string | null }[] = [];

function session(role: Role): Session {
  return {
    role,
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
      return HttpResponse.json({ resourceType: 'ServiceRequest', id: '4821', status: 'completed' });
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('POST /api/bff/cases/[ref]/outcome (W15)', () => {
  it('closes the case at the back end with the outcome as Parameters, and answers when it was closed', async () => {
    const response = await post('advisor', { outcome: 'accepted-and-booked', bestFitNotUsed: 'data-too-old' });

    expect(response.status).toBe(200);
    expect(typeof ((await response.json()) as { closedAt: unknown }).closedAt).toBe('string');
    expect(seen[0].body).toEqual({
      resourceType: 'Parameters',
      parameter: [
        { name: 'outcome', valueCode: 'accepted-and-booked' },
        { name: 'bestFitNotUsed', valueCode: 'data-too-old' },
      ],
    });
    expect(seen[0].key).toBe('key-0000003');
  });

  it('a destination is sent as a reference to the service', async () => {
    await post('advisor', { outcome: 'redirected', destinationServiceId: 'svc-ucr-west' });

    expect(seen[0].body).toMatchObject({
      parameter: expect.arrayContaining([{ name: 'destination', valueReference: { reference: 'HealthcareService/svc-ucr-west' } }]),
    });
  });

  it.each(['no-service-fits', 'out-of-area', 'declined', 'caller-cancelled', 'redirected'])(
    'the outcome %s is accepted',
    async (outcome) => {
      expect((await post('advisor', { outcome })).status).toBe(200);
    },
  );

  it('refuses an outcome or a reason that is not on the list, before any call', async () => {
    expect((await post('advisor', { outcome: 'deleted' })).status).toBe(400);
    expect((await post('advisor', { outcome: 'declined', bestFitNotUsed: 'bored' })).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('refuses a reporter, and a request without CSRF', async () => {
    expect((await post('reporter', { outcome: 'declined' })).status).toBe(403);
    expect((await post('advisor', { outcome: 'declined' }, null)).status).toBe(403);
    expect(seen).toHaveLength(0);
  });
});
