// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = 'https://app.test/api/bff/lead/reporters/number';
const KEY = 'change-number-key-0001';
const NEW_NUMBER = '07700 900456';

const POST_ = (body: unknown, role: 'lead' | 'advisor' = 'lead', key: string | null = KEY) =>
  leadRequest(URL_, role, { method: 'POST', csrf: true, key, body });

function postsFor(serviceId: string, roleId: string) {
  return http.get(`${ROOT}/lead/reporters`, ({ request }) => {
    const service = new URL(request.url).searchParams.get('service');
    const reporters = service === serviceId
      ? [{ serviceId, serviceName: 'UCR East', roleId, role: 'Duty manager', channel: 'text', numberEnding: '4821', coveredUntil: null }]
      : [];
    return HttpResponse.json({ reporters });
  });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/lead/reporters/number', () => {
  it('answers 403 to an advisor and 403 with no CSRF header', async () => {
    const body = { serviceId: 's-ucr-east', newNumber: NEW_NUMBER, until: 'this-week' };
    expect((await POST(await POST_(body, 'advisor'))).status).toBe(403);
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', key: KEY, body }))).status).toBe(403);
  });

  it('refuses a body that is not a valid change, a tenant field, and no key, and calls nothing', async () => {
    let called = false;
    server.use(http.get(`${ROOT}/lead/reporters`, () => { called = true; return HttpResponse.json({ reporters: [] }); }));
    expect((await POST(await POST_({ serviceId: 's-ucr-east', newNumber: '0123', until: 'this-week' }))).status).toBe(400);
    expect((await POST(await POST_({ serviceId: 's-ucr-east', newNumber: NEW_NUMBER, until: 'forever' }))).status).toBe(400);
    expect((await POST(await POST_({ serviceId: 's-ucr-east', newNumber: NEW_NUMBER, until: 'today', tenantId: 'x' }))).status).toBe(400);
    expect((await POST(await POST_({ serviceId: 's-ucr-east', newNumber: NEW_NUMBER, until: 'today' }, 'lead', null))).status).toBe(400);
    expect(called).toBe(false);
  });

  it('finds the post of the service, changes its number with the key, and answers the last four digits and the cover end', async () => {
    let changed: { body: unknown; key: string | null; path: string } | undefined;
    server.use(
      postsFor('s-ucr-east', 'role-ucr-east'),
      http.post(`${BACKEND_BASE}/PractitionerRole/role-ucr-east/$change-number`, async ({ request }) => {
        changed = { body: await request.json(), key: request.headers.get('idempotency-key'), path: new URL(request.url).pathname };
        return HttpResponse.json({
          resourceType: 'Parameters',
          parameter: [
            { name: 'numberEnding', valueString: '0456' },
            { name: 'coverUntil', valueDateTime: '2026-11-06T23:59:59Z' },
          ],
        });
      }),
    );
    const response = await POST(await POST_({ serviceId: 's-ucr-east', newNumber: NEW_NUMBER, until: 'this-week' }));
    expect(response.status).toBe(200);
    const answer = await response.text();
    expect(JSON.parse(answer)).toEqual({ numberEnding: '0456', coverUntil: '2026-11-06T23:59:59Z' });
    expect(answer).not.toContain('900456');
    expect(changed?.key).toBe(KEY);
    expect(changed?.body).toEqual({
      resourceType: 'Parameters',
      parameter: [
        { name: 'mobile', valueString: '07700900456' },
        { name: 'duration', valueCode: 'this-week' },
      ],
    });
  });

  it('answers 404 for a service with no reporter post, and changes nothing', async () => {
    let changed = false;
    server.use(
      postsFor('s-other', 'role-x'),
      http.post(`${BACKEND_BASE}/PractitionerRole/role-x/$change-number`, () => { changed = true; return HttpResponse.json({}); }),
    );
    const response = await POST(await POST_({ serviceId: 's-ucr-east', newNumber: NEW_NUMBER, until: 'today' }));
    expect(response.status).toBe(404);
    expect(changed).toBe(false);
  });
});
