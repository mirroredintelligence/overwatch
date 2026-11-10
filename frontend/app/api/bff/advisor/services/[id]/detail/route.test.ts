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
const URL_ = 'https://app.test/api/bff/advisor/services/svc-a/detail';
const ctx = { params: Promise.resolve({ id: 'svc-a' }) };

const ANSWER = {
  serviceId: 'svc-a',
  name: 'Ward A',
  category: 'inpatient-beds',
  status: 'limited',
  unitLabel: 'beds',
  established: 10,
  effectiveAvailable: 2,
  overBy: null,
  lastFigure: 2,
  reportedAt: '2026-10-30T06:30:00Z',
  nextDueAt: '2026-10-30T08:30:00Z',
  cadence: 'every-2-hrs',
  overdue: false,
  staleWarning: false,
  dataAgeSeconds: 1800,
  phone: '01305 000000',
  openingHours: [{ days: [0, 1, 2, 3, 4, 5, 6], allDay: true, start: null, end: null }],
  accepts: ['frailty'],
  excludes: [],
  ageMin: 18,
  ageMax: null,
  districts: ['DT4'],
};

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/advisor/services/[id]/detail', () => {
  it('answers 401 with no session', async () => {
    expect((await GET(await leadRequest(URL_, null), ctx)).status).toBe(401);
  });

  it.each(['reporter', 'lead', 'clinical', 'exec'] as const)('answers 403 to the %s role', async (role) => {
    expect((await GET(await leadRequest(URL_, role), ctx)).status).toBe(403);
  });

  it.each(['advisor', 'advisor-v2', 'analytics-user'] as const)(
    'reads the detail from the back end root for the %s role and passes it on, checked',
    async (role) => {
      let auth: string | null = null;
      server.use(
        http.get(`${ROOT}/clinical/services/svc-a/detail`, ({ request }) => {
          auth = request.headers.get('authorization');
          return HttpResponse.json(ANSWER);
        }),
      );
      const response = await GET(await leadRequest(URL_, role), ctx);
      expect(response.status).toBe(200);
      expect(response.headers.get('cache-control')).toBe('private, no-store');
      expect(auth).toMatch(/^Bearer /);
      expect(await response.json()).toEqual(ANSWER);
    },
  );

  it('is an error, not a drawn guess, when the answer is not the shape the page knows', async () => {
    server.use(http.get(`${ROOT}/clinical/services/svc-a/detail`, () => HttpResponse.json({ name: 1 })));
    expect((await GET(await leadRequest(URL_, 'advisor'), ctx)).status).toBeGreaterThanOrEqual(500);
  });

  it('answers 404 when the back end does not know the service', async () => {
    server.use(http.get(`${ROOT}/clinical/services/svc-a/detail`, () => HttpResponse.json({}, { status: 404 })));
    expect((await GET(await leadRequest(URL_, 'advisor'), ctx)).status).toBe(404);
  });
});
