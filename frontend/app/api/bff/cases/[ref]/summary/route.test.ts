// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { SUMMARY_NO_DESTINATION, SUMMARY_WITH_DESTINATION } from '@/test/fixtures/backend-shapes';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const SUMMARY_URL = `${BACKEND_BASE}/ServiceRequest/4821/$summary`;
const seen: { destination: string | null; token: string | null }[] = [];

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

async function get(role: Role | null, query = ''): Promise<Response> {
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  return GET(requestWithCookies(`https://app.test/api/bff/cases/4821/summary${query}`, cookies), {
    params: Promise.resolve({ ref: '4821' }),
  });
}

beforeEach(() => {
  seen.length = 0;
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  server.use(
    http.get(SUMMARY_URL, ({ request }) => {
      const destination = new URL(request.url).searchParams.get('destination');
      seen.push({ destination, token: request.headers.get('authorization') });
      return HttpResponse.json(destination === null ? SUMMARY_NO_DESTINATION : SUMMARY_WITH_DESTINATION);
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('GET /api/bff/cases/[ref]/summary (W15, H-322)', () => {
  it('asks the back end to build the summary for the open case, with the session token, and answers the display strings', async () => {
    const response = await get('advisor');

    expect(response.status).toBe(200);
    expect(seen).toEqual([{ destination: null, token: 'Bearer token-for-advisor' }]);
    expect(await response.json()).toMatchObject({
      reference: '4821',
      referrer: 'Ambulance crew',
      postcode: 'DT4',
      destination: 'No destination chosen yet',
      booked: 'No destination chosen yet',
      dataAge: 'No destination chosen yet',
    });
  });

  it('names the destination service the advisor chose, and answers its name, booking and data age', async () => {
    const response = await get('advisor', '?destination=svc-1');

    expect(seen[0]?.destination).toBe('svc-1');
    expect(await response.json()).toMatchObject({ destination: 'UCR West', booked: 'Confirmed 14:03', dataAge: '9 min ago' });
  });

  it('refuses a destination that cannot be a service id, before any call', async () => {
    expect((await get('advisor', '?destination=a%20b')).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('answers 409 closed when the back end says the case is closed: the summary is built only while a case is open', async () => {
    server.use(http.get(SUMMARY_URL, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'conflict' }] }, { status: 409 })));
    const response = await get('advisor');

    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({ code: 'closed' });
  });

  it('answers 502 when the back end answers something that is not a summary', async () => {
    server.use(http.get(SUMMARY_URL, () => HttpResponse.json({ resourceType: 'Bundle' })));

    expect((await get('advisor')).status).toBe(502);
  });

  it('answers 403 for a reporter and reads nothing', async () => {
    expect((await get('reporter')).status).toBe(403);
    expect(seen).toHaveLength(0);
  });

  it('is never cached', async () => {
    expect((await get('advisor')).headers.get('cache-control')).toBe('private, no-store');
  });
});
