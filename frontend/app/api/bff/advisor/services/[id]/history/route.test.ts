// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = 'https://app.test/api/bff/advisor/services/s-virtual-ward/history';
const ctx = { params: Promise.resolve({ id: 's-virtual-ward' }) };

const ANSWER = {
  unitLabel: 'beds free',
  established: 10,
  since: '2026-11-05T14:00:00Z',
  until: '2026-11-06T14:00:00Z',
  staleAfterSeconds: 7200,
  points: [{ at: '2026-11-06T09:00:00Z', available: 4, overBy: null, status: 'accepting' }],
};

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/advisor/services/[id]/history', () => {
  it('answers 401 with no session', async () => {
    expect((await GET(await leadRequest(URL_, null), ctx)).status).toBe(401);
  });

  it('answers 403 to a role that may not read it', async () => {
    expect((await GET(await leadRequest(URL_, 'reporter'), ctx)).status).toBe(403);
  });

  it('reads the history from the back end root for an advisor and passes it on, checked', async () => {
    let auth: string | null = null;
    server.use(
      http.get(`${ROOT}/clinical/services/s-virtual-ward/history`, ({ request }) => {
        auth = request.headers.get('authorization');
        return HttpResponse.json(ANSWER);
      }),
    );
    const response = await GET(await leadRequest(URL_, 'advisor'), ctx);
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('private, no-store');
    expect(auth).toMatch(/^Bearer /);
    expect(await response.json()).toEqual(ANSWER);
  });

  it('is an error, not a drawn guess, when the answer is not the shape the chart knows', async () => {
    server.use(http.get(`${ROOT}/clinical/services/s-virtual-ward/history`, () => HttpResponse.json({ points: 'no' })));
    const response = await GET(await leadRequest(URL_, 'advisor'), ctx);
    expect(response.status).toBeGreaterThanOrEqual(500);
  });

  it('answers 404 when the back end does not know the service', async () => {
    server.use(http.get(`${ROOT}/clinical/services/s-virtual-ward/history`, () => HttpResponse.json({}, { status: 404 })));
    expect((await GET(await leadRequest(URL_, 'advisor'), ctx)).status).toBe(404);
  });
});
