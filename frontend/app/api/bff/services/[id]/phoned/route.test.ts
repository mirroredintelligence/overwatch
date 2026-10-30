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
const PHONED_URL = `${BACKEND_BASE}/HealthcareService/svc-ucr-west/$advisor-phoned`;
type Seen = { body: unknown; key: string | null; token: string | null };
const seen: Seen[] = [];

function session(role: Role): Session {
  return {
    role,
    services: [],
    sub: 'advisor-1',
    backendToken: 'token-for-advisor',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

async function post(role: Role | null, body: unknown, key: string | null = 'key-0000001'): Promise<Response> {
  const cookies: Record<string, string> = { [CSRF_COOKIE]: CSRF };
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  const headers: Record<string, string> = { [CSRF_HEADER]: CSRF, 'Content-Type': 'application/json' };
  if (key !== null) headers['Idempotency-Key'] = key;
  return POST(
    requestWithCookies('https://app.test/api/bff/services/svc-ucr-west/phoned', cookies, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    }),
    { params: Promise.resolve({ id: 'svc-ucr-west' }) },
  );
}

beforeEach(() => {
  seen.length = 0;
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  server.use(
    http.post(PHONED_URL, async ({ request }) => {
      seen.push({
        body: await request.clone().json(),
        key: request.headers.get('idempotency-key'),
        token: request.headers.get('authorization'),
      });
      return HttpResponse.json({ resourceType: 'Observation', id: 'obs-1', valueInteger: 1 }, { status: 201 });
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('POST /api/bff/services/[id]/phoned (W14)', () => {
  it('sends the answer to $advisor-phoned as Parameters, with the case, the status and the value', async () => {
    const response = await post('advisor', { caseRef: '4821', said: 'limited', value: 1 });

    expect(response.status).toBe(201);
    expect(seen).toHaveLength(1);
    expect(seen[0].body).toEqual({
      resourceType: 'Parameters',
      parameter: [
        { name: 'case', valueReference: { reference: 'ServiceRequest/4821' } },
        { name: 'status', valueCode: 'limited' },
        { name: 'value', valueInteger: 1 },
      ],
    });
    expect(seen[0].key).toBe('key-0000001');
    expect(seen[0].token).toBe('Bearer token-for-advisor');
  });

  it('a not-accepting answer is sent with the value 0', async () => {
    await post('advisor', { caseRef: '4821', said: 'not-accepting', value: 7 });

    expect(seen[0].body).toMatchObject({ parameter: expect.arrayContaining([{ name: 'value', valueInteger: 0 }]) });
  });

  it('answers 403 for a reporter and calls nothing', async () => {
    expect((await post('reporter', { caseRef: '4821', said: 'limited', value: 1 })).status).toBe(403);
    expect(seen).toHaveLength(0);
  });

  it.each([
    ['an answer that is not one of the three', { caseRef: '4821', said: 'maybe', value: 1 }],
    ['a value that is not a whole number', { caseRef: '4821', said: 'limited', value: 1.5 }],
    ['a negative value', { caseRef: '4821', said: 'limited', value: -1 }],
    ['a value that is not a number', { caseRef: '4821', said: 'limited', value: 'two' }],
    ['no case', { said: 'limited', value: 1 }],
    ['a case that is not a case id', { caseRef: 'x y', said: 'limited', value: 1 }],
  ])('refuses %s with 400 and calls nothing', async (_label, body) => {
    expect((await post('advisor', body)).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('refuses a missing Idempotency-Key with 400', async () => {
    expect((await post('advisor', { caseRef: '4821', said: 'limited', value: 1 }, null)).status).toBe(400);
    expect(seen).toHaveLength(0);
  });
});
