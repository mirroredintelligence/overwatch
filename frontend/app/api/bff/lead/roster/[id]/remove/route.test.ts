// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { POST } from './route';

// Taking a duty manager off a roster through the BFF (DEC-1341).

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = 'https://app.test/api/bff/lead/roster/role-1/remove';
const ctx = { params: Promise.resolve({ id: 'role-1' }) };

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/lead/roster/[id]/remove', () => {
  it('answers 403 without the CSRF header and to an advisor', async () => {
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST' }), ctx)).status).toBe(403);
    expect((await POST(await leadRequest(URL_, 'advisor', { method: 'POST', csrf: true }), ctx)).status).toBe(403);
  });

  it('asks the back end to delete the roster place and answers that it was removed', async () => {
    let method: string | null = null;
    server.use(
      http.delete(`${ROOT}/lead/roster/role-1`, ({ request }) => {
        method = request.method;
        return HttpResponse.json({ removed: true });
      }),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true }), ctx);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ removed: true });
    expect(method).toBe('DELETE');
  });

  it('passes on a 404 when the back end does not know the place', async () => {
    server.use(http.delete(`${ROOT}/lead/roster/role-1`, () => HttpResponse.json({}, { status: 404 })));
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true }), ctx)).status).toBe(404);
  });
});
