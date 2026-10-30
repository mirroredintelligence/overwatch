// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const URL_ = 'https://app.test/api/bff/lead/people/remove';
const KEY = 'remove-key-0001';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

const req = (role: 'lead' | 'advisor', body: unknown, key: string | null = KEY) =>
  leadRequest(URL_, role, { method: 'POST', csrf: true, key, body });

describe('POST /api/bff/lead/people/remove', () => {
  it('answers 403 to an advisor, and 403 with no CSRF header', async () => {
    expect((await POST(await req('advisor', { person: 'role-42', reason: 'lost-phone' }))).status).toBe(403);
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', key: KEY, body: { person: 'role-42', reason: 'lost-phone' } }))).status).toBe(403);
  });

  it('answers 400 for a reason the back end does not know, a person that is not a role id, and no key', async () => {
    expect((await POST(await req('lead', { person: 'role-42', reason: 'bored' }))).status).toBe(400);
    expect((await POST(await req('lead', { person: '07700 900456', reason: 'lost-phone' }))).status).toBe(400);
    expect((await POST(await req('lead', { person: 'role-42', reason: 'lost-phone' }, null))).status).toBe(400);
  });

  it('removes the role at the back end with the key, and answers the counts the back end gives', async () => {
    let sent: { body: unknown; key: string | null; path: string } | undefined;
    server.use(
      http.post(`${BACKEND_BASE}/PractitionerRole/role-42/$remove`, async ({ request }) => {
        sent = { body: await request.json(), key: request.headers.get('idempotency-key'), path: new URL(request.url).pathname };
        return HttpResponse.json({
          resourceType: 'Parameters',
          parameter: [
            { name: 'rolesEnded', valueInteger: 1 },
            { name: 'devicesRevoked', valueInteger: 2 },
            { name: 'servicesWithoutReporter', valueInteger: 0 },
          ],
        });
      }),
    );
    const response = await POST(await req('lead', { person: 'role-42', reason: 'lost-phone' }));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ rolesEnded: 1, devicesRevoked: 2, servicesWithoutReporter: 0 });
    expect(sent?.key).toBe(KEY);
    expect(sent?.body).toEqual({ resourceType: 'Parameters', parameter: [{ name: 'reason', valueCode: 'lost-phone' }] });
  });
});
