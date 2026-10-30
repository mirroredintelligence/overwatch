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
const DECLINED_URL = `${BACKEND_BASE}/HealthcareService/svc-ucr-west/$declined`;
const seen: { body: unknown; token: string | null }[] = [];

function session(role: Role): Session {
  return {
    role,
    services: [],
    sub: 'advisor-1',
    backendToken: 'token-for-advisor',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

async function post(role: Role | null, body: unknown): Promise<Response> {
  const cookies: Record<string, string> = { [CSRF_COOKIE]: CSRF };
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  return POST(
    requestWithCookies('https://app.test/api/bff/services/svc-ucr-west/declined', cookies, {
      method: 'POST',
      headers: { [CSRF_HEADER]: CSRF, 'Content-Type': 'application/json', 'Idempotency-Key': 'key-0000002' },
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
    http.post(DECLINED_URL, async ({ request }) => {
      seen.push({ body: await request.clone().json(), token: request.headers.get('authorization') });
      return HttpResponse.json({ resourceType: 'Parameters', parameter: [] }, { status: 201 });
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('POST /api/bff/services/[id]/declined (W14)', () => {
  it('sends the reason to $declined with the case', async () => {
    const response = await post('advisor', { caseRef: '4821', reason: 'outside-criteria' });

    expect(response.status).toBe(201);
    expect(seen[0].body).toEqual({
      resourceType: 'Parameters',
      parameter: [
        { name: 'case', valueReference: { reference: 'ServiceRequest/4821' } },
        { name: 'reason', valueCode: 'outside-criteria' },
      ],
    });
    expect(seen[0].token).toBe('Bearer token-for-advisor');
  });

  it.each(['full', 'outside-criteria', 'staffing-or-transport', 'other'])('accepts the reason %s', async (reason) => {
    expect((await post('advisor', { caseRef: '4821', reason })).status).toBe(201);
  });

  it('refuses a reason outside the four, and a reporter', async () => {
    expect((await post('advisor', { caseRef: '4821', reason: 'busy' })).status).toBe(400);
    expect((await post('reporter', { caseRef: '4821', reason: 'full' })).status).toBe(403);
    expect(seen).toHaveLength(0);
  });
});
